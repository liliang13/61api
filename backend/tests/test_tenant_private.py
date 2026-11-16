import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

import api.auth as auth_api
from extensions import db
from models import ApiKey, AuditLog, Channel, ModelItem, Tenant, UsageLog, User
from services import audit
from services.billing import BillingError, abort, reserve, settle


@pytest.fixture()
def app(tmp_path):
    database = tmp_path / "tenant-test.db"
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="test-only-secret",
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database.as_posix()}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def make_tenant(quota=5_000_000):
    tenant = Tenant(name="研发中心", slug="rd", quota=quota, status=1)
    db.session.add(tenant)
    db.session.flush()
    return tenant


def make_user(tenant, quota=10_000_000):
    user = User(username="tester", tenant_id=tenant.id, role="user", status=1,
                quota=quota, password_hash=generate_password_hash("StrongPass123"),
                uid="100001", invite_code="TESTCODE")
    db.session.add(user)
    db.session.commit()
    return user


def make_model(input_price=1.0, output_price=1.0):
    item = ModelItem(name="unit-model", display_name="Unit", vendor="test",
                     input_price=input_price, output_price=output_price, status=1)
    db.session.add(item)
    db.session.commit()
    return item


def test_reserve_blocks_when_tenant_quota_is_low(app):
    with app.app_context():
        tenant = make_tenant(quota=500_000)   # ¥1
        user = make_user(tenant, quota=10_000_000)
        item = make_model()
        with pytest.raises(BillingError) as exc:
            reserve(user=user, api_key=None, channel=None, item=item,
                    prompt_tokens=2_000_000, completion_tokens=0)
        assert exc.value.code == "insufficient_tenant_quota"
        assert exc.value.status == 402
        db.session.expire_all()
        assert db.session.get(Tenant, tenant.id).quota == 500_000
        assert db.session.get(User, user.id).quota == 10_000_000
        assert UsageLog.query.count() == 0


def test_settle_refunds_tenant_and_user(app):
    with app.app_context():
        tenant = make_tenant(quota=5_000_000)  # ¥10
        user = make_user(tenant, quota=10_000_000)
        item = make_model()
        reservation = reserve(user=user, api_key=None, channel=None, item=item,
                              prompt_tokens=2_000_000, completion_tokens=0)
        db.session.expire_all()
        assert db.session.get(Tenant, tenant.id).quota == 4_000_000
        assert db.session.get(User, user.id).quota == 9_000_000

        cost = settle(reservation, channel=None, item=item,
                      prompt_tokens=1_000_000, completion_tokens=0)
        assert cost == 500_000
        db.session.expire_all()
        assert db.session.get(Tenant, tenant.id).quota == 4_500_000
        assert db.session.get(Tenant, tenant.id).used_quota == 500_000
        assert db.session.get(User, user.id).quota == 9_500_000
        assert db.session.get(User, user.id).used_quota == 500_000


def test_abort_refunds_tenant(app):
    with app.app_context():
        tenant = make_tenant(quota=5_000_000)
        user = make_user(tenant)
        item = make_model()
        reservation = reserve(user=user, api_key=None, channel=None, item=item,
                              prompt_tokens=1_000_000, completion_tokens=0)
        abort(reservation, error_msg="client closed")
        db.session.expire_all()
        assert db.session.get(Tenant, tenant.id).quota == 5_000_000
        assert db.session.get(User, user.id).quota == 10_000_000
        assert UsageLog.query.first().status == "aborted"


def test_private_mode_blocks_public_signup_and_sms(app, monkeypatch):
    from api.auth import bp
    app.register_blueprint(bp)
    monkeypatch.setattr(auth_api, "FEATURE_PUBLIC_SIGNUP", False)
    monkeypatch.setattr(auth_api, "FEATURE_SMS", False)
    client = app.test_client()
    r = client.post("/api/auth/register", json={
        "phone": "13800000000", "password": "StrongPass123", "code": "123456"})
    assert r.status_code == 403
    r = client.post("/api/auth/sms/send", json={"phone": "13800000000", "purpose": "login"})
    assert r.status_code == 403
    r = client.post("/api/auth/sms/login", json={"phone": "13800000000", "code": "123456"})
    assert r.status_code == 403


def test_audit_record_persists(app):
    with app.app_context():
        tenant = make_tenant()
        user = make_user(tenant)
        audit.record("test.action", target_type="user", target_id=user.id,
                     detail={"key": "value"}, actor=user)
        row = AuditLog.query.one()
        assert row.action == "test.action"
        assert row.tenant_id == tenant.id
        assert row.actor_name == "tester"
        assert '"value"' in row.detail
