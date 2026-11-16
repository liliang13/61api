import hashlib
import shutil
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask
from sqlalchemy import event


@pytest.fixture()
def env(tmp_path):
    source = Path(__file__).resolve().parents[1]
    copied = tmp_path / "backend"
    shutil.copytree(source, copied, ignore=shutil.ignore_patterns(
        "data", "tests", "__pycache__", "*.pyc", "app.py", "seed.py"))
    sys.path.insert(0, str(copied))
    project_modules = {name: module for name, module in list(sys.modules.items())
                       if name in {"config", "extensions", "models"}
                       or name.startswith(("api.", "services."))}
    for name in project_modules:
        sys.modules.pop(name, None)
    try:
        import extensions
        extensions.hash_api_key = lambda raw: hashlib.sha256(raw.encode()).hexdigest()
        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret",
            SQLALCHEMY_DATABASE_URI="sqlite:///" + (tmp_path / "billing.db").as_posix(),
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            DEFAULT_MAX_OUTPUT_TOKENS=8,
        )
        extensions.db.init_app(app)
        from api.gateway import bp as gateway_bp
        import api.gateway
        import services.network
        api.gateway.check_rate_limit = lambda *args, **kwargs: True
        services.network.validate_upstream_url = lambda url: url
        app.register_blueprint(gateway_bp)
        with app.app_context():
            event.listen(extensions.db.engine, "connect", _sqlite_options)
            extensions.db.create_all()
            import models
            user = models.User(username="billing", quota=100_000, used_quota=0, status=1,
                               token_version=0)
            extensions.db.session.add(user)
            extensions.db.session.flush()
            raw_key = "sk-test-key"
            key = models.ApiKey(user_id=user.id, name="test",
                                key=extensions.hash_api_key(raw_key),
                                key_prefix="sk-test", key_last4="-key",
                                quota_limit=-1, used_quota=0, status=1)
            item = models.ModelItem(name="test-model", input_price=1.0, output_price=1.0,
                                    cache_input_price=0.0, status=1)
            channel = models.Channel(name="mock", type="mock", models='["*"]', status=1)
            extensions.db.session.add_all([key, item, channel])
            extensions.db.session.commit()
            ids = (user.id, key.id, item.id, channel.id)
        yield SimpleNamespace(app=app, client=app.test_client(), db=extensions.db,
                              models=models, raw_key=raw_key, ids=ids,
                              billing=sys.modules["services.billing"], relay=sys.modules["services.relay"])
    finally:
        with app.app_context():
            extensions.db.session.remove()
            extensions.db.engine.dispose()
        sys.path.remove(str(copied))
        for name in list(sys.modules):
            if name in {"config", "extensions", "models"} or name.startswith(("api.", "services.")):
                sys.modules.pop(name, None)
        sys.modules.update(project_modules)


def _sqlite_options(dbapi_conn, _):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA busy_timeout=10000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def auth(env):
    return {"Authorization": "Bearer " + env.raw_key}


def chat_payload(**extra):
    body = {"model": "test-model", "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 1}
    body.update(extra)
    return body


def rows(env):
    user = env.db.session.get(env.models.User, env.ids[0])
    key = env.db.session.get(env.models.ApiKey, env.ids[1])
    logs = env.models.UsageLog.query.all()
    return user, key, logs


def test_key_limit_is_enforced_by_reservation(env):
    with env.app.app_context():
        key = env.db.session.get(env.models.ApiKey, env.ids[1])
        key.quota_limit = 1
        env.db.session.commit()
    response = env.client.post("/v1/chat/completions", json=chat_payload(), headers=auth(env))
    assert response.status_code == 402
    with env.app.app_context():
        user, key, logs = rows(env)
        assert user.quota == 100_000
        assert key.used_quota == 0
        assert logs == []


def test_nonstream_settles_actual_usage(env):
    response = env.client.post("/v1/chat/completions", json=chat_payload(), headers=auth(env))
    assert response.status_code == 200
    assert response.get_json()["usage"]["completion_tokens"] > 0
    with env.app.app_context():
        user, key, logs = rows(env)
        assert len(logs) == 1
        log = logs[0]
        assert log.status == "ok"
        assert log.request_id
        assert log.quota > 0
        assert log.reserved_quota >= log.quota
        assert user.quota == 100_000 - log.quota
        assert user.used_quota == log.quota
        assert key.used_quota == log.quota


def test_sse_settles_in_finally(env):
    response = env.client.post("/v1/chat/completions", json=chat_payload(stream=True),
                               headers=auth(env))
    assert response.status_code == 200
    assert b"data: [DONE]" in response.data
    with env.app.app_context():
        user, _, logs = rows(env)
        assert len(logs) == 1 and logs[0].status == "ok"
        assert logs[0].stream == 1
        assert user.used_quota == logs[0].quota


def test_interrupted_sse_still_settles(env):
    response = env.client.post("/v1/chat/completions", json=chat_payload(stream=True),
                               headers=auth(env))
    iterator = iter(response.response)
    next(iterator)
    response.close()
    with env.app.app_context():
        _, _, logs = rows(env)
        assert len(logs) == 1
        assert logs[0].status == "ok"
        assert logs[0].quota > 0


def test_concurrent_requests_cannot_overdraw(env):
    with env.app.app_context():
        user = env.db.session.get(env.models.User, env.ids[0])
        item = env.db.session.get(env.models.ModelItem, env.ids[2])
        user.quota = 500_000
        item.input_price = 0
        item.output_price = 1_000_000
        env.db.session.commit()
    barrier = threading.Barrier(3)
    statuses = []

    def call():
        client = env.app.test_client()
        barrier.wait()
        response = client.post("/v1/chat/completions", json=chat_payload(), headers=auth(env))
        statuses.append(response.status_code)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(20)
    assert sorted(statuses) == [200, 402]
    with env.app.app_context():
        user, key, logs = rows(env)
        assert user.quota == 0
        assert user.used_quota == 500_000
        assert key.used_quota == 500_000
        assert len(logs) == 1 and logs[0].status == "ok"


def test_settlement_failure_is_visible_and_retry_is_idempotent(env, monkeypatch):
    with env.app.app_context():
        user = env.db.session.get(env.models.User, env.ids[0])
        key = env.db.session.get(env.models.ApiKey, env.ids[1])
        item = env.db.session.get(env.models.ModelItem, env.ids[2])
        channel = env.db.session.get(env.models.Channel, env.ids[3])
        reservation = env.billing.reserve(user=user, api_key=key, channel=channel, item=item,
                                          prompt_tokens=10, completion_tokens=1)
        original_commit = env.billing.db.session.commit

        def fail_commit():
            raise RuntimeError("injected commit failure")

        monkeypatch.setattr(env.billing.db.session, "commit", fail_commit)
        with pytest.raises(env.billing.BillingError):
            env.billing.settle(reservation, channel=channel, item=item,
                               prompt_tokens=2, completion_tokens=1)
        monkeypatch.setattr(env.billing.db.session, "commit", original_commit)
        cost = env.billing.settle(reservation, channel=channel, item=item,
                                  prompt_tokens=2, completion_tokens=1)
        assert env.billing.settle(reservation, channel=channel, item=item,
                                  prompt_tokens=2, completion_tokens=1) == cost
        user, key, logs = rows(env)
        assert user.quota == 100_000 - cost
        assert user.used_quota == cost
        assert key.used_quota == cost
        assert len(logs) == 1 and logs[0].status == "ok"


def test_database_reserve_failure_prevents_upstream_call(env, monkeypatch):
    with env.app.app_context():
        channel = env.db.session.get(env.models.Channel, env.ids[3])
        channel.type = "openai"
        channel.base_url = "http://internal-upstream.invalid"
        env.db.session.commit()

    def fail_commit():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(env.billing.db.session, "commit", fail_commit)

    def unexpected(*args, **kwargs):
        raise AssertionError("upstream must not be called")

    monkeypatch.setattr(env.relay.requests, "post", unexpected)
    response = env.client.post("/v1/chat/completions", json=chat_payload(), headers=auth(env))
    assert response.status_code == 503


def test_upstream_error_closes_response_and_releases(env, monkeypatch):
    class Upstream:
        status_code = 500
        closed = False

        def close(self):
            self.closed = True

    upstream = Upstream()
    monkeypatch.setattr(env.relay.requests, "post", lambda *args, **kwargs: upstream)
    with env.app.app_context():
        channel = env.db.session.get(env.models.Channel, env.ids[3])
        channel.type = "openai"
        channel.base_url = "http://secret-internal.invalid"
        env.db.session.commit()
    response = env.client.post("/v1/chat/completions", json=chat_payload(), headers=auth(env))
    assert response.status_code == 502
    assert upstream.closed
    assert b"secret-internal" not in response.data
    with env.app.app_context():
        user, key, logs = rows(env)
        assert user.quota == 100_000 and user.used_quota == 0
        assert key.used_quota == 0
        assert len(logs) == 1 and logs[0].status == "error" and logs[0].quota == 0


def test_embeddings_and_malformed_chat_are_handled(env):
    embedding = env.client.post("/v1/embeddings",
                                json={"model": "test-model", "input": "hello"}, headers=auth(env))
    assert embedding.status_code == 200
    malformed = env.client.post("/v1/chat/completions",
                                json={"model": "test-model", "messages": ["bad"]}, headers=auth(env))
    assert malformed.status_code == 400
    bad_limit = env.client.post("/v1/chat/completions", json=chat_payload(max_tokens=True),
                                headers=auth(env))
    assert bad_limit.status_code == 400
    with env.app.app_context():
        assert env.models.UsageLog.query.count() == 1
        assert env.models.UsageLog.query.first().model == "test-model"


def test_active_reservations_enforce_user_concurrency_limit(env):
    with env.app.app_context():
        user = env.db.session.get(env.models.User, env.ids[0])
        key = env.db.session.get(env.models.ApiKey, env.ids[1])
        item = env.db.session.get(env.models.ModelItem, env.ids[2])
        channel = env.db.session.get(env.models.Channel, env.ids[3])
        reservations = [env.billing.reserve(user=user, api_key=key, channel=channel, item=item,
                                            prompt_tokens=1, completion_tokens=1)
                        for _ in range(4)]
        with pytest.raises(env.billing.BillingError) as failure:
            env.billing.reserve(user=user, api_key=key, channel=channel, item=item,
                                prompt_tokens=1, completion_tokens=1)
        assert failure.value.status == 429
        for reservation in reservations:
            env.billing.abort(reservation)
        assert env.models.UsageLog.query.filter_by(status="held").count() == 0


# ---------------- 资源包(tokens 计量) ----------------

def add_pack(env, **kw):
    """在测试库里直接发一个 tokens 资源包;默认绑定 test-model、100 万 tokens。"""
    from datetime import datetime, timedelta
    with env.app.app_context():
        pack = env.models.UserResourcePack(
            user_id=kw.get("user_id", env.ids[0]),
            pack_id=kw.get("pack_id", 1), pack_name=kw.get("pack_name", "测试资源包"),
            model=kw.get("model", "test-model"),
            total_tokens=kw.get("total_tokens", 1_000_000),
            used_tokens=kw.get("used_tokens", 0),
            granted_type=kw.get("granted_type", "admin_grant"), status=1,
            expires_at=kw.get("expires_at", datetime.now() + timedelta(days=30)))
        env.db.session.add(pack)
        env.db.session.commit()
        return pack.id


def pack_of(env, pack_id):
    return env.db.session.get(env.models.UserResourcePack, pack_id)


def test_pack_tokens_cover_request_and_balance_untouched(env):
    """包内 tokens 足够:调用不计费,余额分文不动,包按冻结量消耗。"""
    pack_id = add_pack(env)
    response = env.client.post("/v1/chat/completions", json=chat_payload(), headers=auth(env))
    assert response.status_code == 200
    with env.app.app_context():
        user, key, logs = rows(env)
        log = logs[0]
        assert user.quota == 100_000          # 余额未动
        assert user.used_quota == 0
        assert log.quota == 0                 # 余额实付为 0
        assert log.pack_id == pack_id
        assert log.pack_reserved > 0
        assert pack_of(env, pack_id).used_tokens == log.pack_reserved


def test_tokens_beyond_pack_billed_from_balance(env):
    """包内 tokens 抵扣,超出部分按模型价格从余额结算(单元级精确核算)。"""
    pack_id = add_pack(env, total_tokens=10)
    with env.app.app_context():
        user = env.db.session.get(env.models.User, env.ids[0])
        key = env.db.session.get(env.models.ApiKey, env.ids[1])
        item = env.db.session.get(env.models.ModelItem, env.ids[2])
        channel = env.db.session.get(env.models.Channel, env.ids[3])
        reservation = env.billing.reserve(user=user, api_key=key, channel=channel, item=item,
                                          prompt_tokens=60, completion_tokens=40)
        # 100 tokens × ¥1/1M = ¥0.0001 = 50 quota;包抵 10 tokens = 5 quota
        assert reservation.reserved_quota == 50
        assert reservation.pack_tokens == 10
        assert reservation.user_reserved == 45
        cost = env.billing.settle(reservation, channel=channel, item=item,
                                  prompt_tokens=60, completion_tokens=40)
        assert cost == 45
        user, key, logs = rows(env)
        log = logs[0]
        assert user.quota == 100_000 - 45
        assert user.used_quota == 45
        assert key.used_quota == 45           # 密钥净增按余额承担口径
        assert log.quota == 45
        assert log.pack_reserved == 10
        assert pack_of(env, pack_id).used_tokens == 10


def test_failed_request_releases_pack_tokens(env):
    with env.app.app_context():
        channel = env.db.session.get(env.models.Channel, env.ids[3])
        channel.type = "openai"
        channel.base_url = "http://secret-internal.invalid"
        env.db.session.commit()
    pack_id = add_pack(env)
    response = env.client.post("/v1/chat/completions", json=chat_payload(), headers=auth(env))
    assert response.status_code == 502
    with env.app.app_context():
        user, _, logs = rows(env)
        assert user.quota == 100_000
        assert pack_of(env, pack_id).used_tokens == 0
        assert logs[0].status == "error" and logs[0].quota == 0


def test_expired_pack_is_ignored(env):
    from datetime import datetime, timedelta
    add_pack(env, expires_at=datetime.now() - timedelta(days=1))
    response = env.client.post("/v1/chat/completions", json=chat_payload(), headers=auth(env))
    assert response.status_code == 200
    with env.app.app_context():
        user, _, logs = rows(env)
        assert logs[0].pack_id is None and logs[0].pack_reserved == 0
        assert user.quota == 100_000 - logs[0].quota
        assert logs[0].quota > 0


def test_other_model_pack_is_ignored(env):
    add_pack(env, model="other-model")
    response = env.client.post("/v1/chat/completions", json=chat_payload(), headers=auth(env))
    assert response.status_code == 200
    with env.app.app_context():
        logs = env.models.UsageLog.query.all()
        assert logs[0].pack_id is None


def test_zero_balance_with_live_pack_passes_guard(env):
    """余额为零但有可用资源包:网关放行,费用全部由 tokens 抵扣。"""
    add_pack(env)
    with env.app.app_context():
        user = env.db.session.get(env.models.User, env.ids[0])
        user.quota = 0
        env.db.session.commit()
    response = env.client.post("/v1/chat/completions", json=chat_payload(), headers=auth(env))
    assert response.status_code == 200
    with env.app.app_context():
        user, _, logs = rows(env)
        assert user.quota == 0
        assert logs[0].pack_id is not None and logs[0].quota == 0


def test_zero_balance_without_pack_still_blocked(env):
    add_pack(env, model="other-model")
    with env.app.app_context():
        user = env.db.session.get(env.models.User, env.ids[0])
        user.quota = 0
        env.db.session.commit()
    response = env.client.post("/v1/chat/completions", json=chat_payload(), headers=auth(env))
    assert response.status_code == 402


def test_expiring_first_is_consumed_first(env):
    """两个包时先用最快到期的。"""
    from datetime import datetime, timedelta
    soon = add_pack(env, total_tokens=300,
                    expires_at=datetime.now() + timedelta(days=1))
    later = add_pack(env, total_tokens=1_000_000,
                     expires_at=datetime.now() + timedelta(days=365))
    with env.app.app_context():
        user = env.db.session.get(env.models.User, env.ids[0])
        key = env.db.session.get(env.models.ApiKey, env.ids[1])
        item = env.db.session.get(env.models.ModelItem, env.ids[2])
        channel = env.db.session.get(env.models.Channel, env.ids[3])
        reservation = env.billing.reserve(user=user, api_key=key, channel=channel, item=item,
                                          prompt_tokens=1, completion_tokens=1)
        assert reservation.pack_id == soon
        env.billing.settle(reservation, channel=channel, item=item,
                           prompt_tokens=1, completion_tokens=1)
        assert pack_of(env, soon).used_tokens > 0
        assert pack_of(env, later).used_tokens == 0


def test_pack_snapshot_race_falls_back_to_balance(env):
    """快照后包被并发抢占:tokens 全部转余额计费,不出现负数。"""
    pack_id = add_pack(env, total_tokens=50)
    with env.app.app_context():
        user = env.db.session.get(env.models.User, env.ids[0])
        key = env.db.session.get(env.models.ApiKey, env.ids[1])
        item = env.db.session.get(env.models.ModelItem, env.ids[2])
        channel = env.db.session.get(env.models.Channel, env.ids[3])
        original = env.billing._pack_snapshot

        def racing_snapshot(uid, model, need):
            got = original(uid, model, need)
            pack = pack_of(env, pack_id)
            pack.used_tokens = pack.total_tokens
            env.db.session.commit()
            return got

        env.billing._pack_snapshot = racing_snapshot
        try:
            reservation = env.billing.reserve(user=user, api_key=key, channel=channel,
                                              item=item, prompt_tokens=1, completion_tokens=1)
            assert reservation.pack_id is None or reservation.pack_tokens == 0
        finally:
            env.billing._pack_snapshot = original
        env.billing.settle(reservation, channel=channel, item=item,
                           prompt_tokens=1, completion_tokens=1)
        user, _, logs = rows(env)
        assert user.quota == 100_000 - logs[0].quota
        assert user.used_quota == logs[0].quota


def test_key_limit_counts_full_reservation_with_pack(env):
    """密钥限额按全额费用预留硬顶,资源包抵扣不放松限额。"""
    add_pack(env)
    with env.app.app_context():
        key = env.db.session.get(env.models.ApiKey, env.ids[1])
        key.quota_limit = 1
        env.db.session.commit()
    response = env.client.post("/v1/chat/completions", json=chat_payload(), headers=auth(env))
    assert response.status_code == 402
    with env.app.app_context():
        user, key, logs = rows(env)
        assert user.quota == 100_000
        assert key.used_quota == 0
        assert logs == []


def test_per_user_concurrency_limit_overrides_global(env):
    """用户专属并发上限覆盖全局默认;0 恢复全局。"""
    with env.app.app_context():
        user = env.db.session.get(env.models.User, env.ids[0])
        user.concurrency_limit = 1
        env.db.session.commit()
        key = env.db.session.get(env.models.ApiKey, env.ids[1])
        item = env.db.session.get(env.models.ModelItem, env.ids[2])
        channel = env.db.session.get(env.models.Channel, env.ids[3])

        r1 = env.billing.reserve(user=user, api_key=key, channel=channel, item=item,
                                 prompt_tokens=1, completion_tokens=1)
        with pytest.raises(env.billing.BillingError) as err:
            env.billing.reserve(user=user, api_key=key, channel=channel, item=item,
                                prompt_tokens=1, completion_tokens=1)
        assert err.value.status == 429
        env.billing.abort(r1)

        # limit=0 恢复全局默认(4):4 个并发预留均可成功
        user.concurrency_limit = 0
        env.db.session.commit()
        rs = [env.billing.reserve(user=user, api_key=key, channel=channel, item=item,
                                  prompt_tokens=1, completion_tokens=1)
              for _ in range(4)]
        assert len(rs) == 4
        for r in rs:
            env.billing.abort(r)
