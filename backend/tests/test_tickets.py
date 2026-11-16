# -*- coding: utf-8 -*-
"""工单系统:创建/对话/状态流转/权限/管理处理。"""
import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

from extensions import db
from models import Ticket, TicketMessage, User

AJAX = {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture()
def app(tmp_path):
    app = Flask(__name__)
    app.config.update(
        TESTING=True, SECRET_KEY="test-only-secret",
        SQLALCHEMY_DATABASE_URI="sqlite:///" + (tmp_path / "tickets.db").as_posix(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    from api.admin import bp as admin_bp
    from api.user import bp as user_bp
    app.register_blueprint(admin_bp)
    app.register_blueprint(user_bp)
    with app.app_context():
        db.create_all()
        db.session.add_all([
            User(username="alice", role="user", status=1, token_version=0, invite_code="TKTA001"),
            User(username="bob", role="user", status=1, token_version=0, invite_code="TKTB002"),
            User(username="admin", role="admin", status=1, token_version=0, invite_code="TKTADM0"),
        ])
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _token(app, username):
    from extensions import make_token
    with app.app_context():
        return make_token(User.query.filter_by(username=username).one())


def _post(client, url, payload, token):
    return client.post(url, json=payload, headers=AJAX | {"Authorization": "Bearer " + token})


def test_ticket_full_flow(app, client):
    alice_t = _token(app, "alice")
    admin_t = _token(app, "admin")

    # 创建
    resp = _post(client, "/api/user/tickets", {"title": "充值没到账", "content": "15:20 支付宝付了 10 元"}, alice_t)
    assert resp.status_code == 200
    tid = resp.get_json()["data"]["id"]
    assert resp.get_json()["data"]["status"] == "open"

    # 空内容被拒
    assert _post(client, "/api/user/tickets", {"title": "x", "content": ""}, alice_t).status_code == 400

    # alice 查看详情(自己的)
    r = client.get(f"/api/user/tickets/{tid}", headers=AJAX | {"Authorization": "Bearer " + alice_t})
    d = r.get_json()["data"]
    assert d["title"] == "充值没到账" and len(d["messages"]) == 1
    assert d["messages"][0]["sender_role"] == "user"

    # bob 看不到 alice 的工单
    bob_t = _token(app, "bob")
    assert client.get(f"/api/user/tickets/{tid}",
                      headers=AJAX | {"Authorization": "Bearer " + bob_t}).status_code == 404

    # 管理员回复 → answered
    r = _post(client, f"/api/admin/tickets/{tid}/reply", {"content": "已确认到账,请刷新余额"}, admin_t)
    assert r.status_code == 200
    assert r.get_json()["data"]["status"] == "answered"

    # alice 列表可见 answered;回复 → 回到 open
    r = client.get("/api/user/tickets", headers=AJAX | {"Authorization": "Bearer " + alice_t})
    assert r.get_json()["data"]["items"][0]["status"] == "answered"
    r = _post(client, f"/api/user/tickets/{tid}/reply", {"content": "看到了,谢谢"}, alice_t)
    assert r.get_json()["data"]["status"] == "open"

    # 用户关闭
    assert _post(client, f"/api/user/tickets/{tid}/close", {}, alice_t).status_code == 200
    # 关闭后不能回复
    assert _post(client, f"/api/user/tickets/{tid}/reply", {"content": "再问下"}, alice_t).status_code == 400
    # 管理员重开
    assert _post(client, f"/api/admin/tickets/{tid}/reopen", {}, admin_t).status_code == 200
    with app.app_context():
        assert Ticket.query.get(tid).status == "open"
        assert TicketMessage.query.filter_by(ticket_id=tid).count() == 3


def test_admin_ticket_list_filters_and_preview(app, client):
    alice_t = _token(app, "alice")
    admin_t = _token(app, "admin")
    tid = _post(client, "/api/user/tickets", {"title": "问题 A", "content": "内容 A"}, alice_t)\
        .get_json()["data"]["id"]
    _post(client, "/api/user/tickets", {"title": "问题 B", "content": "内容 B"}, alice_t)

    # 管理列表带用户名与预览
    r = client.get("/api/admin/tickets", headers=AJAX | {"Authorization": "Bearer " + admin_t})
    items = r.get_json()["data"]["items"]
    assert items[0]["username"] == "alice" and "[用户]" in items[0]["preview"]

    # 状态筛选
    _post(client, f"/api/admin/tickets/{tid}/reply", {"content": "答复"}, admin_t)
    r = client.get("/api/admin/tickets?status=open", headers=AJAX | {"Authorization": "Bearer " + admin_t})
    data = r.get_json()["data"]
    assert data["total"] == 1 and data["items"][0]["title"] == "问题 B"
    r = client.get("/api/admin/tickets?status=answered", headers=AJAX | {"Authorization": "Bearer " + admin_t})
    assert r.get_json()["data"]["total"] == 1

    # 管理员关闭
    assert _post(client, f"/api/admin/tickets/{tid}/close", {}, admin_t).status_code == 200
    with app.app_context():
        assert Ticket.query.get(tid).status == "closed"
