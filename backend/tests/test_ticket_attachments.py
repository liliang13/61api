# -*- coding: utf-8 -*-
"""工单附件:上传安全校验、tmp→正式、属主访问控制。"""
import io
import os
import time

import pytest
from flask import Flask

from extensions import db
from models import TicketMessage, User

AJAX = {"X-Requested-With": "XMLHttpRequest"}

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


@pytest.fixture()
def app(tmp_path, monkeypatch):
    from api.admin import bp as admin_bp
    from api.user import bp as user_bp
    import services.ticketfile as tf
    monkeypatch.setattr(tf, "BASE", tmp_path / "tf")

    app = Flask(__name__)
    app.config.update(
        TESTING=True, SECRET_KEY="test-only-secret",
        SQLALCHEMY_DATABASE_URI="sqlite:///" + (tmp_path / "tickets.db").as_posix(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    app.register_blueprint(admin_bp)
    app.register_blueprint(user_bp)
    with app.app_context():
        db.create_all()
        db.session.add_all([
            User(username="alice", role="user", status=1, token_version=0, invite_code="TA001"),
            User(username="bob", role="user", status=1, token_version=0, invite_code="TB002"),
            User(username="admin", role="admin", status=1, token_version=0, invite_code="TADM01"),
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


def _mk_ticket(client, t, title="问题", **extra):
    r = client.post("/api/user/tickets", json={"title": title, "content": "内容", **extra},
                    headers=AJAX | {"Authorization": "Bearer " + t})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    return r.get_json()["data"]["id"]


def _upload(client, t, data, name="s.png"):
    # bytes 须包 BytesIO:werkzeug 3.1 + py3.14 下裸 bytes 会被当成普通表单字段
    return client.post("/api/user/tickets/attachment",
                       data={"file": (io.BytesIO(data), name)},
                       headers=AJAX | {"Authorization": "Bearer " + t})


def _detail(client, t, tid):
    r = client.get(f"/api/user/tickets/{tid}",
                   headers=AJAX | {"Authorization": "Bearer " + t})
    assert r.status_code == 200
    return r.get_json()["data"]


def test_attachment_upload_and_promote_flow(app, client):
    import services.ticketfile as tf
    t = _token(app, "alice")

    # 正常 PNG 上传 → 返回 tmp key
    r = _upload(client, t, PNG)
    assert r.status_code == 200, r.get_data(as_text=True)[:150]
    meta = r.get_json()["data"]
    assert meta["key"].startswith("u") and meta["key"].endswith(".tmp.png")
    assert meta["name"] == "s.png"

    # 创建工单带附件
    tid = _mk_ticket(client, t, "带图", attachment=meta)

    # 临时文件已被 promote(不复存在),正式文件 m{tid}.png 存在
    assert not (tf.BASE / "tmp" / meta["key"]).exists()
    detail = _detail(client, t, tid)
    msgs = detail["messages"]
    assert len(msgs) == 1 and msgs[0]["file_key"] == "m{}.png".format(tid)
    assert (tf.BASE / "msg" / msgs[0]["file_key"]).exists()
    assert msgs[0]["file_name"] == "s.png" and msgs[0]["file_size"] == len(PNG)

    # 无效 key 被拒(路径穿越/伪造/他人 tmp);空 key 视为无附件,不报错
    for bad in ("../../etc/passwd", "u999-x.tmp.png", "m1.png"):
        r = client.post("/api/user/tickets", json={
            "title": "x", "content": "y", "attachment": {"key": bad, "name": "a.png"}},
            headers=AJAX | {"Authorization": "Bearer " + t})
        assert r.status_code == 400, bad

    # 已用过的 key(promote 后消失)再引用 → 附件已失效
    r = client.post("/api/user/tickets", json={
        "title": "x", "content": "y", "attachment": meta},
        headers=AJAX | {"Authorization": "Bearer " + t})
    assert r.status_code == 400 and "失效" in r.get_json()["error"]

    # 属主查看消息附件图片
    mid = msgs[0]["id"]
    r = client.get(f"/api/user/tickets/{tid}/messages/{mid}/file",
                   headers={"Authorization": "Bearer " + t})
    assert r.status_code == 200 and r.data == PNG

    # 他人查看 → 404(不暴露存在性)
    b = _token(app, "bob")
    assert client.get(f"/api/user/tickets/{tid}/messages/{mid}/file",
                      headers={"Authorization": "Bearer " + b}).status_code == 404


def test_attachment_type_and_size_guards(app, client):
    t = _token(app, "alice")
    # 伪图片(扩展名 png,内容非图片魔数)→ 按内容拒绝
    r = _upload(client, t, b"hello world" * 10, "fake.png")
    assert r.status_code == 400 and "仅支持" in r.get_json()["error"]
    # SVG 被拒(可执行脚本载体,不在白名单)
    r = _upload(client, t, b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "x.svg")
    assert r.status_code == 400 and "仅支持" in r.get_json()["error"]
    # 超大被拒(>5MB)
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024 + 10)
    r = _upload(client, t, big, "big.png")
    assert r.status_code == 400 and "5MB" in r.get_json()["error"]
    # 未登录被拒
    c2 = app.test_client()
    r = c2.post("/api/user/tickets/attachment",
                data={"file": (io.BytesIO(PNG), "x.png")})
    assert r.status_code == 401
    # tmp 目录不应残留被拒文件
    import services.ticketfile as tf
    assert not (tf.BASE / "tmp").exists() or not any((tf.BASE / "tmp").iterdir())


def test_reply_with_attachment_and_admin_view(app, client):
    user_t = _token(app, "alice")
    admin_t = _token(app, "admin")
    tid = _mk_ticket(client, user_t)
    att = _upload(client, user_t, PNG, "r.png").get_json()["data"]

    # 用户回复带附件
    r = client.post(f"/api/user/tickets/{tid}/reply", json={
        "content": "补充截图", "attachment": att},
        headers=AJAX | {"Authorization": "Bearer " + user_t})
    assert r.status_code == 200

    # 管理员详情可见附件消息,并能查看图片(管理员走用户端图片接口放行)
    r = client.get(f"/api/admin/tickets/{tid}", headers=AJAX | {"Authorization": "Bearer " + admin_t})
    msgs = r.get_json()["data"]["messages"]
    with_att = [m for m in msgs if m.get("file_key")]
    assert len(with_att) == 1
    mid = with_att[0]["id"]
    r = client.get(f"/api/user/tickets/{tid}/messages/{mid}/file",
                   headers=AJAX | {"Authorization": "Bearer " + admin_t})
    assert r.status_code == 200

    # 管理员回复带附件
    a_att = _upload(client, admin_t, PNG, "a.png").get_json()["data"]
    r = client.post(f"/api/admin/tickets/{tid}/reply", json={
        "content": "这是处理截图", "attachment": a_att},
        headers=AJAX | {"Authorization": "Bearer " + admin_t})
    assert r.status_code == 200

    # 工单关闭后,用户再回复(带附件)被拒
    r = client.post(f"/api/user/tickets/{tid}/close", json={},
                    headers=AJAX | {"Authorization": "Bearer " + user_t})
    assert r.status_code == 200
    att2 = _upload(client, user_t, PNG, "b.png").get_json()["data"]
    r = client.post(f"/api/user/tickets/{tid}/reply", json={
        "content": "x", "attachment": att2},
        headers=AJAX | {"Authorization": "Bearer " + user_t})
    assert r.status_code == 400 and "关闭" in r.get_json()["error"]


def test_cleanup_tmp_removes_orphans(app, client):
    import time

    import services.ticketfile as tf
    t = _token(app, "alice")
    _upload(client, t, PNG, "old.png")
    tmp_dir = tf.BASE / "tmp"
    assert any(tmp_dir.iterdir())
    # 把 mtime 拨到 25 小时前 → 应被清理
    old = time.time() - 25 * 3600
    for f in tmp_dir.iterdir():
        os.utime(f, (old, old))
    n = tf.cleanup_tmp(24)
    assert n == 1 and not any(tmp_dir.iterdir())
    # 新文件不受影响
    _upload(client, t, PNG, "new.png")
    assert tf.cleanup_tmp(24) == 0 and any(tmp_dir.iterdir())
