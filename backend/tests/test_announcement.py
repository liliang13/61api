"""站内公告:公开端点展示逻辑 + 管理端保存与版本号。"""
import sys
import time
from pathlib import Path

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from extensions import db, make_token
from models import User


@pytest.fixture()
def app(tmp_path):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret",
        SQLALCHEMY_DATABASE_URI="sqlite:///" + (tmp_path / "announce-test.db").as_posix(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    from api.admin import bp as admin_bp
    from api.public import bp as public_bp
    app.register_blueprint(admin_bp)
    app.register_blueprint(public_bp)
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def admin_headers(app):
    with app.app_context():
        row = User(username="root", role="admin", status=1, token_version=0,
                   password_hash=generate_password_hash("password123"), invite_code="ADM1N001")
        db.session.add(row)
        db.session.commit()
        token = make_token(row)
    return {"Authorization": "Bearer " + token}


def test_announcement_public_endpoint_and_dismiss_version(app, admin_headers):
    client = app.test_client()
    # 无文案 → 不展示
    body = client.get("/api/public/announcement").get_json()["data"]
    assert body["enabled"] is False

    # 链接缺协议 → 拒绝保存
    saved = client.put("/api/admin/settings", json={
        "announcement": "系统维护通知", "announcement_link": "61api.cn/docs",
    }, headers=admin_headers)
    assert saved.status_code == 400

    saved = client.put("/api/admin/settings", json={
        "announcement": "系统维护通知",
        "announcement_link": "https://61api.cn/docs",
        "announcement_enabled": True,
    }, headers=admin_headers)
    assert saved.status_code == 200

    body = client.get("/api/public/announcement").get_json()["data"]
    assert body["enabled"] is True
    assert body["text"] == "系统维护通知"
    assert body["link"] == "https://61api.cn/docs"
    version = body["updated_at"]
    assert version

    # 保存无关字段 → 版本号不变;修改公告 → 版本号变化(用户端已关闭的横幅会重新弹出)
    client.put("/api/admin/settings", json={"site_name": "61API"}, headers=admin_headers)
    assert client.get("/api/public/announcement").get_json()["data"]["updated_at"] == version
    time.sleep(1.1)  # 时间戳精确到秒
    client.put("/api/admin/settings", json={"announcement": "新版本上线"}, headers=admin_headers)
    changed = client.get("/api/public/announcement").get_json()["data"]
    assert changed["updated_at"] != version
    assert changed["enabled"] is True

    # 关闭开关 → 不展示
    client.put("/api/admin/settings", json={"announcement_enabled": False}, headers=admin_headers)
    assert client.get("/api/public/announcement").get_json()["data"]["enabled"] is False
