# -*- coding: utf-8 -*-
"""两步换绑手机号:旧号验证 → 票据 → 新号验证码绑定。"""
import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

from extensions import db
from models import User

AJAX = {"X-Requested-With": "XMLHttpRequest"}
OLD_PHONE = "13800000000"
NEW_PHONE = "13900000001"


@pytest.fixture()
def app(tmp_path):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="test-only-secret",
        SQLALCHEMY_DATABASE_URI="sqlite:///" + (tmp_path / "phone-change.db").as_posix(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    from api.auth import bp
    app.register_blueprint(bp)
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def create_user(phone=OLD_PHONE):
    user = User(phone=phone, username=phone, uid="100001",
                password_hash=generate_password_hash("oldpass"), invite_code="PHCHG001",
                token_version=0, status=1)
    db.session.add(user)
    db.session.commit()
    return user


def _login(client):
    assert client.post("/api/auth/login", json={"phone": OLD_PHONE, "password": "oldpass"}).status_code == 200


def _latest_code(app, phone, purpose):
    with app.app_context():
        from models import SmsRecord
        rec = (SmsRecord.query.filter_by(phone=phone, purpose=purpose, used=0)
               .order_by(SmsRecord.id.desc()).first())
        return rec.code if rec else None


def test_phone_change_requires_old_phone_verification_first(app, client):
    """已绑定用户直接换绑(无票据)必须被拒。"""
    with app.app_context():
        create_user()
    _login(client)
    resp = client.post("/api/auth/phone/bind", json={"phone": NEW_PHONE, "code": "000000"},
                       headers=AJAX)
    assert resp.status_code == 428
    assert "请先验证当前手机号" in resp.get_json()["error"]
    resp = client.post("/api/auth/phone/bind/send", json={"phone": NEW_PHONE,
                                                          "captcha_verify_param": "x"},
                       headers=AJAX)
    assert resp.status_code == 428


def test_phone_change_two_step_flow(app, client, monkeypatch):
    from services import aliyun_captcha
    monkeypatch.setattr(aliyun_captcha, "verify_captcha", lambda cvp: bool(cvp))
    with app.app_context():
        create_user()
    _login(client)

    # 第一步:向旧手机号发码并校验
    resp = client.post("/api/auth/phone/change/send-old", headers=AJAX)
    assert resp.status_code == 200
    code = _latest_code(app, OLD_PHONE, "change_old")
    resp = client.post("/api/auth/phone/change/verify-old", json={"code": code}, headers=AJAX)
    assert resp.status_code == 200
    ticket = resp.get_json()["data"]["ticket"]
    assert ticket

    # 错误票据无法给新号发码
    assert client.post("/api/auth/phone/bind/send", json={
        "phone": NEW_PHONE, "captcha_verify_param": "x", "ticket": "bad"}, headers=AJAX).status_code == 428

    # 第二步:新号发码 + 绑定(携带票据)
    resp = client.post("/api/auth/phone/bind/send", json={
        "phone": NEW_PHONE, "captcha_verify_param": "ok", "ticket": ticket}, headers=AJAX)
    assert resp.status_code == 200
    bind_code = _latest_code(app, NEW_PHONE, "bind")
    resp = client.post("/api/auth/phone/bind", json={
        "phone": NEW_PHONE, "code": bind_code, "ticket": ticket}, headers=AJAX)
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(User, 1).phone == NEW_PHONE


def test_phone_change_wrong_old_code_rejected(app, client):
    with app.app_context():
        create_user()
    _login(client)
    client.post("/api/auth/phone/change/send-old", headers=AJAX)
    resp = client.post("/api/auth/phone/change/verify-old", json={"code": "000000"}, headers=AJAX)
    assert resp.status_code == 400
    assert "验证码错误" in resp.get_json()["error"]


def test_first_time_bind_without_old_phone_stays_one_step(app, client, monkeypatch):
    """从未绑定手机号的账号(私有化建号)无需旧号验证,直接绑定。"""
    from services import aliyun_captcha
    monkeypatch.setattr(aliyun_captcha, "verify_captcha", lambda cvp: bool(cvp))
    with app.app_context():
        u = create_user()
        u.phone = None
        db.session.commit()
    _login(client)
    resp = client.post("/api/auth/phone/bind/send", json={
        "phone": NEW_PHONE, "captcha_verify_param": "ok"}, headers=AJAX)
    assert resp.status_code == 200
    bind_code = _latest_code(app, NEW_PHONE, "bind")
    resp = client.post("/api/auth/phone/bind", json={
        "phone": NEW_PHONE, "code": bind_code}, headers=AJAX)
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(User, 1).phone == NEW_PHONE
