import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
from flask import Flask
from sqlalchemy import event

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from extensions import db, hash_api_key, make_token
from models import (ApiKey, InviteReward, Invoice, InvoiceItem, RedemptionCode,
                    Setting, TopupOrder, User)


@pytest.fixture()
def app(tmp_path):
    from api.admin import bp as admin_bp
    from api.topup import bp as topup_bp
    from api.user import bp as user_bp

    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret",
        SQLALCHEMY_DATABASE_URI="sqlite:///" + (tmp_path / "payments-test.db").as_posix(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    app.register_blueprint(admin_bp)
    app.register_blueprint(topup_bp)
    app.register_blueprint(user_bp)
    with app.app_context():
        @event.listens_for(db.engine, "connect")
        def sqlite_options(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.close()

        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture()
def user(app):
    with app.app_context():
        row = User(username="payer", role="user", status=1, quota=50,
                   token_version=0, invite_code="PAYER001")
        db.session.add(row)
        db.session.commit()
        return row.id


def auth_headers(user_id, app):
    with app.app_context():
        row = db.session.get(User, user_id)
        return {"Authorization": "Bearer " + make_token(row)}


def test_grant_revoke_replays_use_snapshot_and_claw_back_invite(app, user):
    from services.payments import QuotaEntitlements

    with app.app_context():
        inviter = User(username="inviter", quota=500, status=1, token_version=0,
                       invite_code="INVITER1")
        db.session.add(inviter)
        db.session.flush()
        db.session.add(InviteReward(from_uid=inviter.id, to_uid=user, quota=250, status=0))
        db.session.add(TopupOrder(order_no="ORDER-1", user_id=user, amount=2000,
                                  quota=1000, status="pending"))
        db.session.commit()
        inviter_id = inviter.id

        hook = QuotaEntitlements()
        callback = {"order_no": "ORDER-1", "user_id": user, "credits": 999999,
                    "pay_method": "sandbox"}
        hook.grant(callback, {})
        assert db.session.get(User, user).quota == 1050
        assert db.session.get(User, inviter_id).quota == 750
        assert TopupOrder.query.filter_by(order_no="ORDER-1").one().status == "paid"

        hook.grant(callback, {})
        assert db.session.get(User, user).quota == 1050
        assert db.session.get(User, inviter_id).quota == 750

        hook.revoke(callback, {})
        assert db.session.get(User, user).quota == 50
        assert db.session.get(User, inviter_id).quota == 500
        reward = InviteReward.query.filter_by(to_uid=user).one()
        assert reward.status == 2
        assert TopupOrder.query.filter_by(order_no="ORDER-1").one().status == "refunded"

        hook.revoke(callback, {})
        assert db.session.get(User, user).quota == 50
        assert db.session.get(User, inviter_id).quota == 500

        with pytest.raises(RuntimeError, match="镜像缺失"):
            hook.grant({"order_no": "MISSING", "user_id": user, "credits": 10}, {})


def test_revoke_rejects_consumed_credit(app, user):
    from services.payments import QuotaEntitlements

    with app.app_context():
        payer = db.session.get(User, user)
        payer.quota = 0
        db.session.add(TopupOrder(order_no="CONSUMED", user_id=user, amount=1000,
                                  quota=500, status="paid"))
        db.session.commit()
        with pytest.raises(RuntimeError, match="已消费"):
            QuotaEntitlements().revoke(
                {"order_no": "CONSUMED", "user_id": user, "credits": 1}, {})
        assert TopupOrder.query.filter_by(order_no="CONSUMED").one().status == "paid"


def test_local_pending_mirror_commits_before_payment_and_methods(app, user, monkeypatch):
    from api import topup

    calls = []

    class FakeService:
        settings = SimpleNamespace(mode="sandbox", packages={
            "p10": {"name": "入门包", "price": 1000, "credits": 5000000},
        })
        gateways = {"sandbox": SimpleNamespace()}

        def create_order(self, user_id, package_id):
            calls.append("create")
            return {"order_no": "LOCAL-FIRST", "user_id": user_id, "amount": 1}

        def start_payment(self, order):
            mirror = TopupOrder.query.filter_by(order_no=order["order_no"]).one()
            assert mirror.status == "pending"
            assert mirror.amount == 1000
            calls.append("start")
            return {"pay_url": "https://pay.example/test"}

    monkeypatch.setattr(topup, "get_service", lambda: FakeService())
    client = app.test_client()
    response = client.get("/api/topup/packages", headers=auth_headers(user, app))
    assert response.status_code == 200
    assert response.get_json()["data"]["methods"] == ["sandbox"]

    response = client.post("/api/topup/create", json={"package_id": "p10", "method": "wechat"},
                           headers=auth_headers(user, app))
    assert response.status_code == 400
    response = client.post("/api/topup/create", json={"package_id": "p10"},
                           headers=auth_headers(user, app))
    assert response.status_code == 200
    assert response.get_json()["data"]["amount"] == 1000
    assert calls == ["create", "start"]


def test_production_disables_sandbox_service_and_endpoint(app, user, monkeypatch):
    import config
    from services import payments

    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    monkeypatch.setattr(payments, "PAYKIT_OK", True)
    assert payments.build_payment_service("sandbox") is None
    response = app.test_client().post("/api/topup/sandbox/confirm", json={"order_no": "X"},
                                     headers=auth_headers(user, app))
    assert response.status_code == 403


def test_validate_packages_allows_editable_ids_and_preserves_order():
    from services.payments import validate_packages

    pkgs = validate_packages([
        {"id": " p200 ", "name": "两百日", "price": 20000, "bonus_pct": 10},
        {"id": "p10", "name": "入门", "price": 1000, "bonus_pct": 0},
    ])
    assert list(pkgs) == ["p200", "p10"]  # 列表顺序即展示顺序;ID 去除首尾空格
    assert pkgs["p10"]["credits"] > 0
    for bad_id in ("", "带 空格", "特价@套餐"):
        with pytest.raises(ValueError, match="套餐 ID"):
            validate_packages([{"id": bad_id, "name": "x", "price": 100, "bonus_pct": 0}])
    assert validate_packages([{"id": "a" * 40, "name": "x", "price": 100, "bonus_pct": 0}])


def test_payment_subject_is_balance_topup_with_amount():
    from types import SimpleNamespace

    from services.payments import TopupPaymentService

    svc = TopupPaymentService(SimpleNamespace(site_name="61API"), store=None, gateways={})
    assert svc._subject_of({"amount": 1000, "package_id": "p10"}) == "61API-余额充值¥10"
    assert svc._subject_of({"amount": 1050, "package_id": "p10"}) == "61API-余额充值¥10.5"
    assert svc._subject_of({"amount": 999, "package_id": "p10"}) == "61API-余额充值¥9.99"
    bare = TopupPaymentService(SimpleNamespace(site_name=""), store=None, gateways={})
    assert bare._subject_of({"amount": 50000}) == "余额充值¥500"


def test_custom_amount_topup_validation(app, user, monkeypatch):
    from api import topup

    seen = {}

    class FakeService:
        settings = SimpleNamespace(mode="alipay", packages={})
        gateways = {"alipay": SimpleNamespace(), "wechat": SimpleNamespace()}

        def create_dynamic_order(self, user_id, amount, package_id="custom", credits=0):
            seen["amount"], seen["credits"] = amount, credits
            return {"order_no": "CUSTOM-1", "user_id": user_id, "amount": amount}

        def start_payment(self, order):
            return {"pay_url": "https://pay.example/x"}

    monkeypatch.setattr(topup, "get_service", lambda: FakeService())
    monkeypatch.setattr(topup, "check_rate_limit", lambda *a, **k: True)
    client = app.test_client()
    headers = auth_headers(user, app)

    response = client.post("/api/topup/create", json={
        "package_id": "custom", "method": "alipay", "amount_yuan": 30}, headers=headers)
    assert response.status_code == 200
    assert response.get_json()["data"]["amount"] == 3000
    assert seen == {"amount": 3000, "credits": 15_000_000}  # 自定义金额不享受套餐赠送
    with app.app_context():
        mirror = TopupOrder.query.filter_by(order_no="CUSTOM-1").one()
        assert (mirror.package_id, mirror.amount, mirror.quota, mirror.pay_method) == \
            ("custom", 3000, 15_000_000, "alipay")

    for bad in (None, "30", True, 0, -5, 10.999, 99999):
        resp = client.post("/api/topup/create", json={
            "package_id": "custom", "method": "alipay", "amount_yuan": bad}, headers=headers)
        assert resp.status_code == 400, f"amount_yuan={bad!r} 应被拒绝"


def test_topup_create_rate_limited(app, user, monkeypatch):
    from api import topup

    counter = {"n": 0}

    class FakeService:
        settings = SimpleNamespace(mode="alipay", packages={})
        gateways = {"alipay": SimpleNamespace()}

        def create_dynamic_order(self, user_id, amount, package_id="custom", credits=0):
            counter["n"] += 1
            return {"order_no": f"CUSTOM-{counter['n']}", "user_id": user_id, "amount": amount}

        def start_payment(self, order):
            return {"pay_url": "https://pay.example/x"}

    monkeypatch.setattr(topup, "get_service", lambda: FakeService())
    client = app.test_client()
    headers = auth_headers(user, app)
    for _ in range(5):
        assert client.post("/api/topup/create", json={
            "package_id": "custom", "method": "alipay", "amount_yuan": 5},
            headers=headers).status_code == 200
    assert client.post("/api/topup/create", json={
        "package_id": "custom", "method": "alipay", "amount_yuan": 5},
        headers=headers).status_code == 429
    with app.app_context():
        assert TopupOrder.query.count() == 5  # 被限流的请求不产生订单


def test_admin_custom_topup_range_validation(app, user):
    with app.app_context():
        admin = User(username="range-admin", role="admin", status=1, token_version=0,
                     invite_code="RANGEAD1")
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id
    client = app.test_client()
    headers = auth_headers(admin_id, app)
    assert client.put("/api/admin/settings", json={
        "custom_topup_min_yuan": 100, "custom_topup_max_yuan": 50}, headers=headers).status_code == 400
    assert client.put("/api/admin/settings", json={
        "custom_topup_min_yuan": 0}, headers=headers).status_code == 400
    assert client.put("/api/admin/settings", json={
        "custom_topup_min_yuan": 1, "custom_topup_max_yuan": 5000}, headers=headers).status_code == 200


def test_wechat_gateway_joins_alipay_when_env_ready(app, monkeypatch, tmp_path):
    import config
    from services import payments

    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    monkeypatch.setattr(payments, "PAYKIT_OK", True)
    monkeypatch.setattr(payments, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "PAYKIT_MODE", "alipay")
    monkeypatch.setenv("ALIPAY_APP_ID", "2021000test")
    monkeypatch.setenv("ALIPAY_APP_PRIVATE_KEY", "alipay-key")
    for key, value in {"WECHAT_MCH_ID": "1234567890", "WECHAT_APP_ID": "wx-test",
                       "WECHAT_API_V3_KEY": "k" * 32,
                       "WECHAT_MERCHANT_SERIAL_NO": "SERIAL",
                       "WECHAT_MERCHANT_PRIVATE_KEY": "pem"}.items():
        monkeypatch.setenv(key, value)
    with app.app_context():
        svc = payments.build_payment_service()
    assert svc is not None
    assert list(svc.gateways) == ["alipay", "wechat"]
    assert svc.settings.mode == "alipay"

    monkeypatch.delenv("WECHAT_MCH_ID")
    with app.app_context():
        svc = payments.build_payment_service()
    assert list(svc.gateways) == ["alipay"]


def test_create_selects_requested_gateway(app, user, monkeypatch):
    from api import topup

    seen = {}

    class FakeService:
        settings = SimpleNamespace(mode="alipay", packages={
            "p10": {"name": "入门包", "price": 1000, "credits": 5000000},
        })
        gateways = {"alipay": SimpleNamespace(), "wechat": SimpleNamespace()}

        def create_order(self, user_id, package_id):
            return {"order_no": "WX-1", "user_id": user_id, "amount": 1}

        def start_payment(self, order):
            seen["mode_at_start"] = self.settings.mode
            return {"qr_content": "weixin://wxpay/abc"}

    monkeypatch.setattr(topup, "get_service", lambda: FakeService())
    client = app.test_client()
    headers = auth_headers(user, app)
    methods = client.get("/api/topup/packages", headers=headers).get_json()["data"]["methods"]
    assert methods == ["alipay", "wechat"]

    response = client.post("/api/topup/create", json={"package_id": "p10", "method": "wechat"},
                           headers=headers)
    assert response.status_code == 200
    assert response.get_json()["data"]["method"] == "wechat"
    assert seen["mode_at_start"] == "wechat"
    with app.app_context():
        assert TopupOrder.query.filter_by(order_no="WX-1").one().pay_method == "wechat"
    assert client.post("/api/topup/create", json={"package_id": "p10", "method": "sandbox"},
                       headers=headers).status_code == 400


def invoice_payload(order_nos):
    return {"order_nos": order_nos, "title_type": "个人", "title": "测试用户",
            "email": "payer@example.com"}


def test_invoice_deduplicates_orders_and_replay_is_rejected(app, user):
    with app.app_context():
        db.session.add(TopupOrder(order_no="INVOICE-1", user_id=user, amount=1000,
                                  quota=100, status="paid"))
        db.session.commit()
    client = app.test_client()
    headers = auth_headers(user, app)
    response = client.post("/api/user/invoices", json=invoice_payload(["INVOICE-1", "INVOICE-1"]),
                           headers=headers)
    assert response.status_code == 200
    assert response.get_json()["data"]["amount"] == 1000
    assert len(response.get_json()["data"]["orders"]) == 1

    response = client.post("/api/user/invoices", json=invoice_payload(["INVOICE-1"]),
                           headers=headers)
    assert response.status_code == 400
    with app.app_context():
        assert Invoice.query.count() == 1
        assert InvoiceItem.query.count() == 1


def test_invoice_concurrent_requests_create_only_one(app, user):
    with app.app_context():
        db.session.add(TopupOrder(order_no="INVOICE-RACE", user_id=user, amount=1000,
                                  quota=100, status="paid"))
        db.session.commit()
    barrier = Barrier(2)
    headers = auth_headers(user, app)

    def create_invoice(_):
        barrier.wait()
        response = app.test_client().post(
            "/api/user/invoices", json=invoice_payload(["INVOICE-RACE"]), headers=headers)
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(create_invoice, [1, 2]))
    assert statuses == [200, 400]
    with app.app_context():
        assert Invoice.query.count() == 1
        assert InvoiceItem.query.count() == 1


def test_rejected_invoice_releases_only_active_amount(app, user):
    with app.app_context():
        admin = User(username="admin", role="admin", status=1, token_version=0,
                     invite_code="ADMIN001")
        db.session.add(admin)
        db.session.flush()
        db.session.add(TopupOrder(order_no="INVOICE-2", user_id=user, amount=1000,
                                  quota=100, status="paid"))
        db.session.commit()
        admin_id = admin.id
    headers = auth_headers(user, app)
    client = app.test_client()
    created = client.post("/api/user/invoices", json=invoice_payload(["INVOICE-2"]),
                          headers=headers).get_json()["data"]
    response = client.put(f"/api/admin/invoices/{created['id']}/reject", json={},
                          headers=auth_headers(admin_id, app))
    assert response.status_code == 200
    available = client.get("/api/user/invoices/available-orders", headers=headers)
    assert available.get_json()["data"][0]["invoicable_yuan"] == 10
    with app.app_context():
        assert InvoiceItem.query.one().active == 0


def test_redemption_concurrent_requests_credit_once(app, user):
    with app.app_context():
        other = User(username="other", quota=0, status=1, token_version=0,
                     invite_code="OTHER001")
        db.session.add(other)
        db.session.add(RedemptionCode(code="61-RACE", quota=700, status=1))
        db.session.commit()
        other_id = other.id
    barrier = Barrier(2)
    headers = {user: auth_headers(user, app), other_id: auth_headers(other_id, app)}

    def redeem(uid):
        barrier.wait()
        response = app.test_client().post("/api/user/redeem", json={"code": "61-RACE"},
                                          headers=headers[uid])
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(redeem, [user, other_id]))
    assert statuses == [200, 400]
    with app.app_context():
        db.session.expire_all()
        assert db.session.get(User, user).quota + db.session.get(User, other_id).quota == 750
        code = RedemptionCode.query.filter_by(code="61-RACE").one()
        assert code.status == 0
        assert code.used_by in (user, other_id)


def test_api_key_hash_and_invalid_limits(app, user):
    client = app.test_client()
    headers = auth_headers(user, app)
    created = client.post("/api/user/keys", json={"name": "secret", "limit_yuan": 2},
                          headers=headers)
    assert created.status_code == 200
    raw = created.get_json()["data"]["key"]
    with app.app_context():
        stored = ApiKey.query.one()
        assert stored.key == hash_api_key(raw)
        assert stored.key != raw
        assert stored.key_prefix == raw[:8]
        assert stored.key_last4 == raw[-4:]
        key_id = stored.id

    listed = client.get("/api/user/keys", headers=headers).get_json()["data"]
    assert "key" not in listed[0]
    assert raw not in listed[0]["key_masked"]
    assert client.put(f"/api/user/keys/{key_id}", json={"limit_yuan": "nan"},
                      headers=headers).status_code == 400
    assert client.post("/api/user/keys", json={"limit_yuan": -1},
                       headers=headers).status_code == 400


def test_admin_quota_addition_and_invalid_number(app, user):
    with app.app_context():
        admin = User(username="quota-admin", role="admin", status=1, token_version=0,
                     invite_code="ADMIN002")
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id
    headers = auth_headers(admin_id, app)
    client = app.test_client()
    response = client.put(f"/api/admin/users/{user}", json={"quota_add_yuan": "1.5"},
                          headers=headers)
    assert response.status_code == 200
    assert response.get_json()["data"]["quota"] == 750050
    response = client.put(f"/api/admin/users/{user}", json={"quota_add_yuan": "not-a-number"},
                          headers=headers)
    assert response.status_code == 400
    with app.app_context():
        assert db.session.get(User, user).quota == 750050


# ---------------- 资源包(tokens 计量) ----------------

def _make_pack_def(app, **kw):
    from models import ResourcePackDef
    with app.app_context():
        d = ResourcePackDef(name=kw.get("name", "GLM 体验包"), model=kw.get("model", "glm-5.3"),
                            tokens=kw.get("tokens", 1_000_000), price=kw.get("price", 0),
                            valid_days=kw.get("valid_days", 30), status=1)
        db.session.add(d)
        db.session.commit()
        return d.id


def test_register_gift_pack(app, user):
    from models import Setting, UserResourcePack
    from services.resourcepack import grant_register_gift

    _make_pack_def(app)
    with app.app_context():
        receiver = db.session.get(User, user)
        assert grant_register_gift(receiver) is None  # 未配置不发放
        Setting.put("register_gift_pack_id", 1)
        db.session.commit()
        instance = grant_register_gift(receiver)
        assert instance is not None and instance.granted_type == "register_gift"
        assert instance.total_tokens == 1_000_000
        receiver.quota = 0  # 余额为 0 也不影响赠送
        db.session.commit()
        # 停用后不再发放
        from models import ResourcePackDef
        db.session.get(ResourcePackDef, 1).status = 0
        db.session.commit()
        assert grant_register_gift(receiver) is None
        assert UserResourcePack.query.filter_by(granted_type="register_gift").count() == 1


def test_admin_resource_pack_crud_grant_and_list(app, user):
    def_id = _make_pack_def(app)
    with app.app_context():
        from models import ModelItem, Tenant
        db.session.add(ModelItem(name="glm-5.3", input_price=1.0, output_price=8.0, status=1))
        db.session.add(Tenant(name="默认组织", slug="default", quota=-1))
        admin = User(username="pack-admin", role="admin", status=1, token_version=0,
                     invite_code="PACKADM1")
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id
    client = app.test_client()
    admin_headers = auth_headers(admin_id, app)
    user_headers = auth_headers(user, app)

    # 创建:模型不存在被拒
    bad = client.post("/api/admin/resource-packs", json={
        "name": "X", "model": "no-such-model", "tokens_wan": 100}, headers=admin_headers)
    assert bad.status_code == 400
    created = client.post("/api/admin/resource-packs", json={
        "name": "GPT 包", "model": "glm-5.3", "tokens_wan": 50, "valid_days": 90,
        "price_yuan": 39.9}, headers=admin_headers)
    assert created.status_code == 200
    data = created.get_json()["data"]
    assert data["tokens"] == 500_000
    assert data["price"] == 3990 and data["price_yuan"] == 39.9
    # 售价留空 = 仅赠送
    free = client.post("/api/admin/resource-packs", json={
        "name": "纯赠送包", "model": "glm-5.3", "tokens_wan": 10}, headers=admin_headers)
    assert free.get_json()["data"]["price"] == 0
    new_id = data["id"]

    # 手动发放(按 username)+ 列表可见
    granted = client.post(f"/api/admin/resource-packs/{def_id}/grant",
                          json={"username": "payer"}, headers=admin_headers)
    assert granted.status_code == 200
    assert granted.get_json()["data"]["state"] == "active"
    assert granted.get_json()["data"]["total_tokens"] == 1_000_000
    listed = client.get("/api/admin/resource-pack-grants", headers=admin_headers).get_json()["data"]
    assert listed["total"] == 1
    assert listed["items"][0]["pack_name"] == "GLM 体验包"
    assert listed["items"][0]["state"] == "active"

    # 状态筛选与用户视角
    assert client.get("/api/admin/resource-pack-grants?state=expired",
                      headers=admin_headers).get_json()["data"]["total"] == 0
    mine = client.get("/api/user/resource-packs", headers=user_headers).get_json()["data"]
    assert len(mine) == 1 and mine[0]["remaining_tokens"] == 1_000_000

    # 作废
    gid = listed["items"][0]["id"]
    assert client.put(f"/api/admin/resource-pack-grants/{gid}/disable",
                      json={}, headers=admin_headers).status_code == 200
    listed = client.get("/api/admin/resource-pack-grants?state=disabled",
                        headers=admin_headers).get_json()["data"]
    assert listed["total"] == 1

    # 有持有者 → 删除被拒;停用后不出现在可选范围(定义统计正确)
    assert client.delete(f"/api/admin/resource-packs/{def_id}",
                         headers=admin_headers).status_code == 400
    stats = client.get("/api/admin/resource-packs", headers=admin_headers).get_json()["data"]
    by_id = {d["id"]: d for d in stats}
    assert by_id[def_id]["granted_count"] == 1
    assert by_id[def_id]["used_tokens"] == 0


def test_register_gift_setting_validation_and_admin_create_grants(app, user):
    with app.app_context():
        from models import ResourcePackDef, Tenant
        db.session.add(ResourcePackDef(name="新人包", model="glm-5.3",
                                       tokens=2_500_000, valid_days=30, status=1))
        db.session.add(Tenant(name="默认组织", slug="default", quota=-1))
        admin = User(username="gift-admin", role="admin", status=1, token_version=0,
                     invite_code="GIFTADM1")
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id
    headers = auth_headers(admin_id, app)
    client = app.test_client()
    assert client.put("/api/admin/settings", json={"register_gift_pack_id": 999},
                      headers=headers).status_code == 400
    assert client.put("/api/admin/settings", json={"register_gift_pack_id": 1},
                      headers=headers).status_code == 200

    # 管理员建号视同注册,自动获得赠送包
    response = client.post("/api/admin/users", json={
        "username": "fresh-user", "password": "freshuser123", "tenant_id": 1}, headers=headers)
    assert response.status_code == 200
    with app.app_context():
        from models import UserResourcePack
        instance = UserResourcePack.query.one()
        assert instance.granted_type == "register_gift"
        assert instance.pack_name == "新人包"
        assert instance.total_tokens == 2_500_000


# ---------------- 资源包购买(tokens) ----------------

class FakePackService:
    settings = SimpleNamespace(mode="sandbox", packages={})
    gateways = {"sandbox": SimpleNamespace()}

    def create_order(self, user_id, package_id):
        return {"order_no": "RPT-1", "user_id": user_id, "amount": 4000,
                "package_id": package_id}

    def start_payment(self, order):
        return {"pay_url": "https://pay.example/rp"}


def test_resource_pack_purchase_orders_mirror_and_grants(app, user, monkeypatch):
    from api import topup
    from models import UserResourcePack
    from services.payments import QuotaEntitlements

    def_id = _make_pack_def(app, tokens=5_000_000)
    with app.app_context():
        from models import ModelItem, ResourcePackDef
        db.session.add(ModelItem(name="glm-5.3", input_price=1.0, output_price=8.0, status=1))
        db.session.get(ResourcePackDef, def_id).price = 4000  # ¥40 售卖
        db.session.commit()
    monkeypatch.setattr(topup, "get_service", lambda: FakePackService())
    monkeypatch.setattr(topup, "check_rate_limit", lambda *a, **k: True)
    client = app.test_client()
    headers = auth_headers(user, app)

    offers = client.get("/api/user/resource-pack-offers", headers=headers).get_json()["data"]
    assert offers["items"][0]["id"] == f"rp{def_id}"
    assert offers["items"][0]["tokens"] == 5_000_000

    response = client.post("/api/topup/create", json={"package_id": f"rp{def_id}"},
                           headers=headers)
    assert response.status_code == 200
    assert response.get_json()["data"]["quota"] == 5_000_000
    with app.app_context():
        mirror = TopupOrder.query.filter_by(order_no="RPT-1").one()
        assert (mirror.kind, mirror.amount, mirror.quota, mirror.pack_model,
                mirror.pack_days) == ("resource_pack", 4000, 5_000_000, "glm-5.3", 30)
        balance_before = db.session.get(User, user).quota

    hook = QuotaEntitlements()
    with app.app_context():
        hook.grant({"order_no": "RPT-1", "user_id": user, "pay_method": "sandbox"}, {})
        instance = UserResourcePack.query.filter_by(order_no="RPT-1").one()
        assert instance.model == "glm-5.3"
        assert instance.total_tokens == 5_000_000
        assert instance.granted_type == "purchase"
        assert instance.expires_at is not None
        assert db.session.get(User, user).quota == balance_before  # 余额不动
        # 重复入账不重复发放
        hook.grant({"order_no": "RPT-1", "user_id": user}, {})
        assert UserResourcePack.query.count() == 1


def test_resource_pack_only_priced_and_active_are_buyable(app, user, monkeypatch):
    from api import topup
    from services.payments import load_resource_pack_packages

    priced = _make_pack_def(app, tokens=1_000_000)
    free = _make_pack_def(app, tokens=2_000_000)
    off = _make_pack_def(app, tokens=3_000_000)
    with app.app_context():
        from models import ResourcePackDef
        db.session.get(ResourcePackDef, priced).price = 990      # 在售
        db.session.get(ResourcePackDef, off).status = 0          # 停用(即使有价)
        db.session.commit()
    with app.app_context():
        packages = load_resource_pack_packages()
        assert list(packages) == [f"rp{priced}"]
        assert packages[f"rp{priced}"]["credits"] == 1_000_000

    monkeypatch.setattr(topup, "get_service", lambda: FakePackService())
    monkeypatch.setattr(topup, "check_rate_limit", lambda *a, **k: True)
    client = app.test_client()
    headers = auth_headers(user, app)
    # 仅赠送包与停用包都拒绝下单
    for pid in (f"rp{free}", f"rp{off}", "rp99999"):
        resp = client.post("/api/topup/create", json={"package_id": pid}, headers=headers)
        assert resp.status_code == 400, pid
    with app.app_context():
        assert TopupOrder.query.count() == 0


def test_resource_pack_revoke_rules(app, user):
    from models import UserResourcePack
    from services.payments import QuotaEntitlements

    _make_pack_def(app, tokens=5_000_000)
    with app.app_context():
        db.session.add(TopupOrder(order_no="RPT-R", user_id=user, package_id="rp1",
                                  kind="resource_pack", amount=4000, quota=5_000_000,
                                  pack_model="glm-5.3", pack_days=30, status="pending"))
        db.session.commit()
    hook = QuotaEntitlements()
    with app.app_context():
        hook.grant({"order_no": "RPT-R", "user_id": user}, {})
        instance = UserResourcePack.query.filter_by(order_no="RPT-R").one()
        instance.used_tokens = 100  # 已有消耗
        db.session.commit()
        with pytest.raises(RuntimeError, match="资源包 tokens 已有消耗"):
            hook.revoke({"order_no": "RPT-R", "user_id": user}, {})
        assert TopupOrder.query.filter_by(order_no="RPT-R").one().status == "paid"
        instance.used_tokens = 0
        db.session.commit()
        hook.revoke({"order_no": "RPT-R", "user_id": user}, {})
        assert UserResourcePack.query.count() == 0
        assert TopupOrder.query.filter_by(order_no="RPT-R").one().status == "refunded"
        assert db.session.get(User, user).quota == 50  # 余额始终未动


def test_payment_subject_distinguishes_resource_pack():
    from types import SimpleNamespace

    from services.payments import TopupPaymentService

    svc = TopupPaymentService(SimpleNamespace(site_name="61API"), store=None, gateways={})
    assert svc._subject_of({"amount": 4000, "package_id": "rp3"}) == "61API-资源包¥40"
    assert svc._subject_of({"amount": 1000, "package_id": "p10"}) == "61API-余额充值¥10"


def test_admin_user_concurrency_limit_update(app, user):
    with app.app_context():
        admin = User(username="conc-admin", role="admin", status=1, token_version=0,
                     invite_code="CONCADM1")
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id
    headers = auth_headers(admin_id, app)
    client = app.test_client()
    assert client.put(f"/api/admin/users/{user}", json={"concurrency_limit": 16},
                      headers=headers).status_code == 200
    with app.app_context():
        assert db.session.get(User, user).concurrency_limit == 16
    # 非法值被拒
    for bad in (300, -1, "abc"):
        resp = client.put(f"/api/admin/users/{user}", json={"concurrency_limit": bad},
                          headers=headers)
        assert resp.status_code == 400, bad
    # 0 恢复全局默认
    assert client.put(f"/api/admin/users/{user}", json={"concurrency_limit": 0},
                      headers=headers).status_code == 200
    with app.app_context():
        assert db.session.get(User, user).concurrency_limit == 0


def test_topup_create_records_agreement_audit(app, user, monkeypatch):
    """创建充值订单即留「同意充值协议」审计日志。"""
    from models import AuditLog
    from api import topup

    class FakeService:
        settings = SimpleNamespace(mode="alipay", packages={})
        gateways = {"alipay": SimpleNamespace()}

        def create_dynamic_order(self, user_id, amount, package_id="custom", credits=0):
            return {"order_no": "AGR-1", "user_id": user_id, "amount": amount}

        def start_payment(self, order):
            return {"pay_url": "https://pay.example/x"}

    monkeypatch.setattr(topup, "get_service", lambda: FakeService())
    monkeypatch.setattr(topup, "check_rate_limit", lambda *a, **k: True)
    client = app.test_client()
    resp = client.post("/api/topup/create", json={
        "package_id": "custom", "method": "alipay", "amount_yuan": 5},
        headers=auth_headers(user, app))
    assert resp.status_code == 200
    with app.app_context():
        log = AuditLog.query.filter_by(action="recharge.agreement_agreed").one()
        assert "AGR-1" in log.detail
        assert "充值协议" in log.detail


def test_admin_grant_pack_by_uid(app, user):
    """发放支持按 UID 定位用户(兼容用户名/user_id)。"""
    with app.app_context():
        from models import ModelItem, ResourcePackDef, Tenant, User
        db.session.add(ModelItem(name="glm-5.3", input_price=1.0, output_price=8.0, status=1))
        db.session.add(ResourcePackDef(name="UID测试包", model="glm-5.3",
                                       tokens=1_000_000, valid_days=30, status=1))
        target = db.session.get(User, user)
        target.uid = "100002"
        admin = User(username="uid-admin", role="admin", status=1, token_version=0,
                     invite_code="UIDADM01")
        db.session.add(admin)
        db.session.commit()
        admin_id, uid_str = admin.id, target.uid
    client = app.test_client()
    headers = auth_headers(admin_id, app)

    # 按 UID 发放
    r = client.post("/api/admin/resource-packs/1/grant",
                    json={"username": uid_str}, headers=headers)
    assert r.status_code == 200
    d = r.get_json()["data"]
    assert d["user_id"] == user and d["granted_type"] == "admin_grant"

    # 按 user_id 发放
    r = client.post("/api/admin/resource-packs/1/grant",
                    json={"user_id": user}, headers=headers)
    assert r.status_code == 200

    # 不存在的 UID → 404
    r = client.post("/api/admin/resource-packs/1/grant",
                    json={"username": "999999"}, headers=headers)
    assert r.status_code == 404
    with app.app_context():
        from models import UserResourcePack
        assert UserResourcePack.query.filter_by(user_id=user).count() == 2


def test_special_vat_invoice_requires_confirmation(app, user):
    """申请增值税专用发票必须单独同意《专用发票抬头确认书》,并留审计。"""
    from models import AuditLog, TopupOrder
    with app.app_context():
        db.session.add(TopupOrder(order_no="INV-SP1", user_id=user, amount=2000,
                                  quota=1000, status="paid"))
        db.session.commit()
    client = app.test_client()
    headers = auth_headers(user, app)
    payload = {"order_nos": ["INV-SP1"], "inv_type": "增值税专用发票",
               "title_type": "企业", "title": "测试科技有限公司",
               "tax_no": "91130100MA0ABC1234", "email": "payer@example.com"}

    # 未同意确认书 → 400
    r = client.post("/api/user/invoices", json=payload, headers=headers)
    assert r.status_code == 400
    assert "专用发票抬头确认书" in r.get_json()["error"]

    # 同意确认书 → 成功并留审计
    ok_payload = dict(payload, special_confirmation=True)
    r = client.post("/api/user/invoices", json=ok_payload, headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    with app.app_context():
        log = AuditLog.query.filter_by(action="invoice.create").one()
        d = json.loads(log.detail)
        assert d["inv_type"] == "增值税专用发票"
        assert d["special_confirmation_confirmed"] is True

    # 普票不需要确认标记(回归)
    with app.app_context():
        db.session.add(TopupOrder(order_no="INV-SP2", user_id=user, amount=1000,
                                  quota=500, status="paid"))
        db.session.commit()
    r = client.post("/api/user/invoices", json={
        "order_nos": ["INV-SP2"], "inv_type": "电子普通发票",
        "title_type": "个人", "title": "测试个人", "email": "payer@example.com"},
        headers=headers)
    assert r.status_code == 200


def test_special_vat_invoice_rejects_personal_title(app, user):
    """专票仅支持企业抬头,个人抬头被拒。"""
    from models import TopupOrder
    with app.app_context():
        db.session.add(TopupOrder(order_no="INV-PER", user_id=user, amount=1000,
                                  quota=500, status="paid"))
        db.session.commit()
    client = app.test_client()
    r = client.post("/api/user/invoices", json={
        "order_nos": ["INV-PER"], "inv_type": "增值税专用发票", "special_confirmation": True,
        "title_type": "个人", "title": "张三", "email": "payer@example.com"},
        headers=auth_headers(user, app))
    assert r.status_code == 400
    assert "专用发票仅支持企业抬头" in r.get_json()["error"]
