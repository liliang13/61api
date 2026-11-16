import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

import extensions
from extensions import check_rate_limit, csrf_protect, db, hash_api_key, make_token
from models import AuthThrottle, SmsRecord, User


BACKEND_DIR = Path(__file__).resolve().parents[1]
AJAX = {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture()
def app(tmp_path):
    database = tmp_path / "auth-test.db"
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="test-only-secret",
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database.as_posix()}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    from api.auth import bp
    app.register_blueprint(bp)
    app.before_request(csrf_protect)
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()
    assert database.parent == tmp_path


@pytest.fixture()
def client(app):
    return app.test_client()


def create_user(phone="13800000000", password="oldpass", username=None):
    user = User(phone=phone, username=username or phone, uid=str(100000 + User.query.count()),
                password_hash=generate_password_hash(password), invite_code=f"INV{phone}",
                token_version=0, status=1)
    db.session.add(user)
    db.session.commit()
    return user


def add_sms_code(phone, purpose, code="123456"):
    db.session.add(SmsRecord(phone=phone, purpose=purpose, code=code,
                             expires_at=datetime.now() + timedelta(minutes=5)))
    db.session.commit()


def test_password_login_sets_cookie_without_token_and_supports_bearer(client, app):
    with app.app_context():
        user = create_user()
        bearer = make_token(user)
    response = client.post("/api/auth/login", json={"phone": "13800000000", "password": "oldpass"})
    assert response.status_code == 200
    assert "token" not in response.get_json()["data"]
    cookie = response.headers["Set-Cookie"]
    assert "61api_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert client.get("/api/auth/me").status_code == 200
    client.get("/api/auth/me")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {bearer}"}).status_code == 200


def test_secure_cookie_flag(client, app, monkeypatch):
    monkeypatch.setattr(extensions, "SESSION_COOKIE_SECURE", True)
    with app.app_context():
        create_user()
    response = client.post("/api/auth/login", base_url="https://localhost",
                           json={"phone": "13800000000", "password": "oldpass"})
    assert response.status_code == 200
    assert "Secure" in response.headers["Set-Cookie"]


def test_cookie_takes_precedence_and_logout_clears_it(client, app):
    with app.app_context():
        first = create_user()
        second = create_user(phone="13900000000")
        second_token = make_token(second)
        first_id = first.id
    client.post("/api/auth/login", json={"phone": "13800000000", "password": "oldpass"})
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {second_token}"})
    assert response.get_json()["data"]["id"] == first_id
    response = client.post("/api/auth/logout", headers=AJAX)
    assert response.status_code == 200
    assert "Max-Age=0" in response.headers["Set-Cookie"]
    assert client.get("/api/auth/me").status_code == 401


def test_cookie_write_requires_csrf_header(client, app):
    with app.app_context():
        create_user()
    client.post("/api/auth/login", json={"phone": "13800000000", "password": "oldpass"})
    assert client.post("/api/auth/password", json={}).status_code == 403
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers=AJAX).status_code == 200


def test_password_policy_change_revokes_old_token_and_disable_blocks(client, app):
    with app.app_context():
        user = create_user()
        old_token = make_token(user)
        user_id = user.id
    client.post("/api/auth/login", json={"phone": "13800000000", "password": "oldpass"})
    weak = client.post("/api/auth/password", headers=AJAX,
                       json={"old_password": "oldpass", "new_password": "short1"})
    assert weak.status_code == 400
    changed = client.post("/api/auth/password", headers=AJAX,
                          json={"old_password": "oldpass", "new_password": "newpassword123"})
    assert changed.status_code == 200
    assert "61api_session=" in changed.headers["Set-Cookie"]
    assert client.get("/api/auth/me").status_code == 200
    with app.app_context():
        new_token = make_token(db.session.get(User, user_id))
    client.post("/api/auth/logout", headers=AJAX)
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401
    with app.app_context():
        user = db.session.get(User, user_id)
        user.status = 0
        db.session.commit()
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"}).status_code == 401


def test_register_and_sms_login_set_cookie_and_code_is_single_use(client, app):
    with app.app_context():
        add_sms_code("13800000000", "register")
    response = client.post("/api/auth/register", json={
        "phone": "13800000000", "password": "password123", "code": "123456"})
    assert response.status_code == 200
    assert "token" not in response.get_json()["data"]
    assert "61api_session=" in response.headers["Set-Cookie"]
    client.post("/api/auth/logout", headers=AJAX)
    with app.app_context():
        add_sms_code("13800000000", "login")
    assert client.post("/api/auth/sms/login", json={
        "phone": "13800000000", "code": "123456"}).status_code == 200
    client.post("/api/auth/logout", headers=AJAX)
    with app.app_context():
        add_sms_code("13800000000", "reset", "654321")
    assert client.post("/api/auth/password/reset", json={
        "phone": "13800000000", "code": "654321", "new_password": "password123"}).status_code == 200
    assert client.post("/api/auth/password/reset", json={
        "phone": "13800000000", "code": "654321", "new_password": "password456"}).status_code == 400


def test_register_invite_accepts_uid_and_legacy_code(client, app):
    with app.app_context():
        inviter = create_user(phone="13600000000")
        inviter_id, inviter_uid, inviter_code = inviter.id, inviter.uid, inviter.invite_code
        add_sms_code("13800000000", "register")
        add_sms_code("13900000000", "register")
    assert client.post("/api/auth/register", headers=AJAX, environ_base={"REMOTE_ADDR": "203.0.113.10"}, json={
        "phone": "13800000000", "password": "password123", "code": "123456",
        "invite_code": inviter_uid}).status_code == 200
    assert client.post("/api/auth/register", headers=AJAX, environ_base={"REMOTE_ADDR": "203.0.113.11"}, json={
        "phone": "13900000000", "password": "password123", "code": "123456",
        "invite_code": inviter_code.lower()}).status_code == 200
    with app.app_context():
        by_uid = User.query.filter_by(phone="13800000000").first()
        by_code = User.query.filter_by(phone="13900000000").first()
        assert by_uid.invited_by == inviter_id
        assert by_code.invited_by == inviter_id


def test_login_ip_and_account_rate_limits_are_recorded(client, app):
    with app.app_context():
        create_user()
    for _ in range(5):
        assert client.post("/api/auth/login", json={
            "phone": "13800000000", "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={
        "phone": "13800000000", "password": "oldpass"}).status_code == 429
    with app.app_context():
        assert AuthThrottle.query.filter_by(key="login:ip:127.0.0.1").count() == 6
        assert AuthThrottle.query.filter_by(key="login:account:13800000000").count() == 5


def test_atomic_rate_limit_and_sms_failure_limit(app):
    with app.app_context():
        assert [check_rate_limit("test", "one", 3, 60) for _ in range(4)] == [True, True, True, False]
        add_sms_code("13800000000", "login")
        from services.sms import verify_code
        assert not verify_code("13800000000", "login", "000000")
        assert verify_code("13800000000", "login", "123456")
        assert not verify_code("13800000000", "login", "123456")
        for _ in range(4):
            assert not verify_code("13800000000", "login", "bad")
        assert AuthThrottle.query.filter(AuthThrottle.key.like("sms:verify:%")).count() == 5


def test_sms_phone_and_ip_send_limits(app, monkeypatch):
    from services import sms
    monkeypatch.setattr(sms, "SMS_MODE", "dev")
    monkeypatch.setattr(sms, "SMS_SEND_IP_LIMIT", 2)
    with app.app_context():
        assert sms.send_code("13800000000", "login", "10.0.0.2")[0]
        assert not sms.send_code("13800000000", "login", "10.0.0.3")[0]
        assert sms.send_code("13900000000", "login", "10.0.0.2")[0]
        assert not sms.send_code("13700000000", "login", "10.0.0.2")[0]


def test_proxy_headers_only_trusted_for_configured_proxy(monkeypatch):
    monkeypatch.setattr(extensions, "TRUSTED_PROXY_IPS", ("10.0.0.1", "192.168.0.0/24"))
    app = Flask(__name__)
    with app.test_request_context("/", environ_overrides={"REMOTE_ADDR": "8.8.8.8"},
                                  headers={"X-Real-IP": "1.2.3.4"}):
        assert extensions.client_ip() == "8.8.8.8"
    with app.test_request_context("/", environ_overrides={"REMOTE_ADDR": "10.0.0.1"},
                                  headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.1"}):
        assert extensions.client_ip() == "1.2.3.4"


def test_api_key_hash_and_captcha_fail_closed(monkeypatch):
    assert hash_api_key("sk-test") == hash_api_key("sk-test")
    assert hash_api_key("sk-test") != hash_api_key("sk-other")
    assert len(hash_api_key("sk-test")) == 64
    monkeypatch.setenv("ALIYUN_CAPTCHA_ACCESS_KEY_ID", "test-ak")
    monkeypatch.setenv("ALIYUN_CAPTCHA_ACCESS_KEY_SECRET", "test-sk")
    from services import aliyun_captcha

    def fail(*args, **kwargs):
        raise aliyun_captcha.requests.Timeout("captcha_verify_param=secret")

    monkeypatch.setattr(aliyun_captcha.requests, "post", fail)
    assert not aliyun_captcha.verify_captcha("sensitive-captcha-value")


def test_production_config_fail_fast_and_database_override(tmp_path):
    database = tmp_path / "override.db"
    valid = {
        "APP_ENV": "production",
        "61API_SECRET_KEY": "a" * 32,
        "ADMIN_PASSWORD": "not-the-default-password",
        "SMS_MODE": "aliyun",
        "ALIYUN_SMS_ACCESS_KEY_ID": "sms-ak",
        "ALIYUN_SMS_ACCESS_KEY_SECRET": "sms-sk",
        "ALIYUN_SMS_SIGN_NAME": "61API",
        "ALIYUN_SMS_TEMPLATE_CODE": "SMS_1234567888",
        "PAYKIT_MODE": "alipay",
        "API_KEY_PEPPER": "b" * 32,
        "DATABASE_URL": f"sqlite:///{database.as_posix()}",
    }
    env = os.environ.copy()
    env.update(valid)
    code = "import config; assert config.SQLALCHEMY_DATABASE_URI.startswith('sqlite:///'); print(config.IS_PRODUCTION)"
    result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND_DIR, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.strip() == "True"
    for key, value in (("61API_SECRET_KEY", "short"), ("ADMIN_PASSWORD", "admin123456"),
                       ("SMS_MODE", "dev"), ("PAYKIT_MODE", "sandbox"), ("API_KEY_PEPPER", "short")):
        bad_env = env.copy()
        bad_env[key] = value
        result = subprocess.run([sys.executable, "-c", "import config"], cwd=BACKEND_DIR, env=bad_env,
                                capture_output=True, text=True)
        assert result.returncode != 0, key
        assert "RuntimeError" in result.stderr
    # SMS_MODE=aliyun 但短信凭据/签名/模板缺一项 → 生产启动即失败
    incomplete = env.copy()
    incomplete.pop("ALIYUN_SMS_TEMPLATE_CODE")
    result = subprocess.run([sys.executable, "-c", "import config"], cwd=BACKEND_DIR, env=incomplete,
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "SMS_MODE=aliyun" in result.stderr


def test_uid_is_random_not_sequential(app):
    from models import gen_unique_uid
    with app.app_context():
        uids = {gen_unique_uid() for _ in range(20)}
        assert len(uids) == 20                      # 查重不冲突
        vals = sorted(int(u) for u in uids)
        for v in vals:
            assert 100000 <= v <= 999999
        assert vals != list(range(100001, 100021))  # 不是旧的 100001 起连续递增模式


def test_register_records_agreement_audit(app, client, monkeypatch):
    """注册成功即留「同意服务条款/隐私政策」审计日志。"""
    from models import AuditLog
    from services import sms as sms_module
    monkeypatch.setattr(sms_module, "SMS_MODE", "dev")
    from services import aliyun_captcha
    monkeypatch.setattr(aliyun_captcha, "verify_captcha", lambda cvp: bool(cvp))
    client.post("/api/auth/sms/send", json={"phone": "13700000009", "purpose": "register",
                                            "captcha_verify_param": "ok"},
                headers=AJAX)
    with app.app_context():
        rec = (SmsRecord.query.filter_by(phone="13700000009", purpose="register", used=0)
               .order_by(SmsRecord.id.desc()).first())
        code = rec.code
    resp = client.post("/api/auth/register", json={
        "phone": "13700000009", "password": "Passw0rd123", "code": code}, headers=AJAX)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    with app.app_context():
        log = AuditLog.query.filter_by(action="user.agreement_agreed").one()
        assert log.actor_name == "13700000009"
        assert "服务条款" in log.detail and "隐私政策" in log.detail
