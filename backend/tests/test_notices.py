# -*- coding: utf-8 -*-
"""站内消息:管理发布 → 用户铃铛未读数/列表/详情已读/全部已读。"""
import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

from extensions import db
from models import Notice, NoticeRead, User

AJAX = {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture()
def app(tmp_path):
    app = Flask(__name__)
    app.config.update(
        TESTING=True, SECRET_KEY="test-only-secret",
        SQLALCHEMY_DATABASE_URI="sqlite:///" + (tmp_path / "notices.db").as_posix(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    from api.admin import bp as admin_bp
    from api.user import bp as user_bp
    app.register_blueprint(admin_bp)
    app.register_blueprint(user_bp)
    with app.app_context():
        db.create_all()
        admin = User(username="admin", role="admin", status=1, token_version=0, invite_code="NTCADM01")
        user = User(username="alice", role="user", status=1, token_version=0, invite_code="NTCUSR01")
        db.session.add_all([admin, user])
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


def test_notice_publish_list_detail_and_read_all(app, client):
    admin_t = _token(app, "admin")
    user_t = _token(app, "alice")

    # 发布两条
    assert _post(client, "/api/admin/notices", {"title": "公告一", "body": "第一条内容"}, admin_t).status_code == 200
    assert _post(client, "/api/admin/notices", {"title": "公告二", "body": "第二条内容"}, admin_t).status_code == 200
    # 标题/正文必填
    assert _post(client, "/api/admin/notices", {"title": "无正文", "body": ""}, admin_t).status_code == 400

    # 未读数 = 2
    r = client.get("/api/user/notices/unread-count", headers={"Authorization": "Bearer " + user_t})
    assert r.get_json()["data"]["unread"] == 2

    # 列表倒序 + 未读标记
    r = client.get("/api/user/notices", headers={"Authorization": "Bearer " + user_t})
    items = r.get_json()["data"]["items"]
    assert [i["title"] for i in items] == ["公告二", "公告一"]
    assert not any(i["read"] for i in items)

    # 详情自动置已读
    nid = items[0]["id"]
    r = client.get(f"/api/user/notices/{nid}", headers={"Authorization": "Bearer " + user_t})
    d = r.get_json()["data"]
    assert d["title"] == "公告二" and d["body"] == "第二条内容"
    with app.app_context():
        assert NoticeRead.query.filter_by(notice_id=nid).count() == 1

    # 全部已读 → 未读归零;重复调用幂等
    assert _post(client, "/api/user/notices/read-all", {}, user_t).status_code == 200
    r = client.get("/api/user/notices/unread-count", headers={"Authorization": "Bearer " + user_t})
    assert r.get_json()["data"]["unread"] == 0
    assert _post(client, "/api/user/notices/read-all", {}, user_t).status_code == 200

    # 无 token 不可见
    assert client.get("/api/user/notices/unread-count").status_code == 401


def test_notice_admin_edit_delete_and_user_visibility(app, client):
    admin_t = _token(app, "admin")
    user_t = _token(app, "alice")
    nid = _post(client, "/api/admin/notices", {"title": "待编辑", "body": "内容"}, admin_t)\
        .get_json()["data"]["id"]

    # 编辑标题与下架
    assert client.put(f"/api/admin/notices/{nid}", json={"title": "已编辑", "status": 0},
                      headers=AJAX | {"Authorization": "Bearer " + admin_t}).status_code == 200
    # 下架后用户列表不可见、未读数不含
    r = client.get("/api/user/notices", headers={"Authorization": "Bearer " + user_t})
    assert r.get_json()["data"]["total"] == 0
    assert client.get(f"/api/user/notices/{nid}",
                      headers={"Authorization": "Bearer " + user_t}).status_code == 404

    # 重新上架恢复可见;删除后消失且已读记录清理
    client.put(f"/api/admin/notices/{nid}", json={"status": 1},
               headers=AJAX | {"Authorization": "Bearer " + admin_t})
    client.get(f"/api/user/notices/{nid}", headers={"Authorization": "Bearer " + user_t})
    assert client.delete(f"/api/admin/notices/{nid}",
                         headers=AJAX | {"Authorization": "Bearer " + admin_t}).status_code == 200
    with app.app_context():
        assert Notice.query.count() == 0
        assert NoticeRead.query.count() == 0
    r = client.get("/api/user/notices", headers={"Authorization": "Bearer " + user_t})
    assert r.get_json()["data"]["total"] == 0
