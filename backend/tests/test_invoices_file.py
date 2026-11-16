# -*- coding: utf-8 -*-
"""发票文件上传/下载:权限、校验、限流、审计。"""
import io

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

from extensions import db
from models import Invoice, TopupOrder, User

AJAX = {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture()
def app(tmp_path):
    app = Flask(__name__)
    app.config.update(
        TESTING=True, SECRET_KEY="test-only-secret",
        SQLALCHEMY_DATABASE_URI="sqlite:///" + (tmp_path / "invfile.db").as_posix(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    from api.admin import bp as admin_bp
    from api.user import bp as user_bp
    app.register_blueprint(admin_bp)
    app.register_blueprint(user_bp)
    import pathlib
    import api.admin as admin_mod
    import api.user as user_mod
    inv_dir = tmp_path / "invoices"
    user_mod._invoice_file_path = lambda iid: pathlib.Path(inv_dir) / (str(iid) + ".pdf")
    def _fake_invoice_dir():
        pathlib.Path(inv_dir).mkdir(parents=True, exist_ok=True)
        return pathlib.Path(inv_dir)
    admin_mod._invoice_dir = _fake_invoice_dir
    with app.app_context():
        db.create_all()
        db.session.add_all([
            User(username="alice", role="user", status=1, token_version=0, invite_code="IFA001"),
            User(username="bob", role="user", status=1, token_version=0, invite_code="IFB002"),
            User(username="file-admin", role="admin", status=1, token_version=0, invite_code="IFADM01"),
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


def _make_pdf(size=2048):
    return b"%PDF-1.7\n" + b"0" * (size - 12) + b"\n%%EOF\n"


def _create_special_invoice(app, client, user_t, order_no="FILE-1", amount=2000):
    with app.app_context():
        alice = User.query.filter_by(username="alice").one()
        db.session.add(TopupOrder(order_no=order_no, user_id=alice.id, amount=amount,
                                  quota=amount * 500, status="paid"))
        db.session.commit()
    r = client.post("/api/user/invoices", json={
        "order_nos": [order_no], "inv_type": "增值税专用发票", "special_confirmation": True,
        "title_type": "企业", "title": "测试科技有限公司",
        "tax_no": "91130100MA0ABC1234", "email": "payer@example.com"},
        headers={"Authorization": "Bearer " + user_t})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    return r.get_json()["data"]["id"]


def test_invoice_file_upload_download_flow(app, client):
    """管理员上传 PDF → 用户下载(留审计)→ 越权/未上传/非 PDF/超大全被拒。"""
    from models import AuditLog
    user_t = _token(app, "alice")
    bob_t = _token(app, "bob")
    admin_t = _token(app, "file-admin")
    UAJ = {"Authorization": "Bearer " + user_t}
    AAJ = {"Authorization": "Bearer " + admin_t}

    iid = _create_special_invoice(app, client, user_t)

    # 未上传时下载 → 404
    assert client.get(f"/api/user/invoices/{iid}/file", headers=UAJ).status_code == 404

    # 非 PDF 被拒(魔数校验)
    r = client.post(f"/api/admin/invoices/{iid}/file",
                    data={"file": (io.BytesIO(b"not a pdf"), "fake.pdf")},
                    headers={**AAJ, "Content-Type": "multipart/form-data"})
    assert r.status_code == 400
    assert "不是有效的 PDF" in r.get_json()["error"]

    # 超 10MB 被拒
    r = client.post(f"/api/admin/invoices/{iid}/file",
                    data={"file": (io.BytesIO(b"%PDF-1.7\n" + b"0" * (10 * 1024 * 1024 + 10)), "big.pdf")},
                          headers={**AAJ, "Content-Type": "multipart/form-data"})
    assert r.status_code == 400
    assert "10MB" in r.get_json()["error"]

    # 非 .pdf 后缀被拒
    r = client.post(f"/api/admin/invoices/{iid}/file",
                    data={"file": (io.BytesIO(_make_pdf()), "invoice.txt")},
                    headers={**AAJ, "Content-Type": "multipart/form-data"})
    assert r.status_code == 400

    # 正常上传(中文文件名)
    r = client.post(f"/api/admin/invoices/{iid}/file",
                    data={"file": (io.BytesIO(_make_pdf()), "发票-测试.pdf")},
                    headers={**AAJ, "Content-Type": "multipart/form-data"})
    assert r.status_code == 200
    d = r.get_json()["data"]
    assert d["file_name"] == "发票-测试.pdf" and d["file_size"] > 0

    # 用户下载(内容为 PDF + 审计)
    r = client.get(f"/api/user/invoices/{iid}/file", headers=UAJ)
    assert r.status_code == 200
    assert r.data.startswith(b"%PDF-")
    with app.app_context():
        all_actions = [a[0] for a in db.session.query(AuditLog.action).all()]
        print("AUDIT_ACTIONS:", all_actions)
        actions = [a for a in all_actions if a.startswith("invoice.file")]
        assert "invoice.file_upload" in actions
        assert "invoice.file_download" in actions

    # bob 下载他人发票 → 404(不泄露存在性)
    assert client.get(f"/api/user/invoices/{iid}/file",
                      headers={"Authorization": "Bearer " + bob_t}).status_code == 404


def test_invoice_download_rate_limited(app, client, tmp_path):
    """下载限流:每用户 20 次/分钟,超出 429。"""
    import pathlib
    from models import Invoice, TopupOrder
    user_t = _token(app, "alice")
    admin_t = _token(app, "file-admin")
    with app.app_context():
        alice = User.query.filter_by(username="alice").one()
        db.session.add(TopupOrder(order_no="RATE-1", user_id=alice.id, amount=1000,
                                  quota=500, status="paid"))
        inv = Invoice(user_id=alice.id, inv_type="电子普通发票", title_type="个人",
                      title="x", amount=1000, file_name="a.pdf", file_size=100)
        db.session.add(inv)
        db.session.commit()
        iid = inv.id
    import api.user as user_mod
    inv_dir = tmp_path / "invoices"
    inv_dir.mkdir(parents=True, exist_ok=True)
    user_mod._invoice_file_path = lambda x: inv_dir / (str(x) + ".pdf")
    (inv_dir / (str(iid) + ".pdf")).write_bytes(_make_pdf(100))
    UAH = {"Authorization": "Bearer " + user_t}
    client = app.test_client()
    for i in range(5):
        r = client.get(f"/api/user/invoices/{iid}/file", headers=UAH)
        assert r.status_code == 200, (i, r.get_data(as_text=True)[:80])
    r = client.get(f"/api/user/invoices/{iid}/file", headers=UAH)
    assert r.status_code == 429
    assert "下载过于频繁" in r.get_json()["error"]
