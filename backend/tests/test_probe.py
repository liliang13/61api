import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture()
def app_ctx(tmp_path):
    """每个用例一个独立临时库。

    不从 sys.modules 弹模块(test_protocol 等文件在模块级持有实例引用,
    中途弹换会导致实例族错位);统一使用当前 sys.modules 里的 extensions/models,
    用例内再 import 时拿到的也是同一族模块。
    """
    import extensions
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="probe-test-secret",
        SQLALCHEMY_DATABASE_URI="sqlite:///" + (tmp_path / "probe.db").as_posix(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    extensions.db.init_app(app)
    with app.app_context():
        import models  # noqa: F401 -- 表元数据必须先于 create_all 注册
        extensions.db.create_all()
        yield app
        extensions.db.session.remove()
        extensions.db.drop_all()


def _mk_channel(db, **kw):
    import models
    ch = models.Channel(name=kw.pop("name", "ch"),
                        type=kw.pop("type", "openai"),
                        base_url=kw.pop("base_url", "https://up.example"),
                        api_key=kw.pop("api_key", "sk-x"),
                        models=kw.pop("models", '["m1"]'), **kw)
    db.session.add(ch)
    db.session.commit()
    return ch


def _fail(latency=10, error="HTTP 401"):
    return {"ok": False, "latency_ms": latency, "model": "m1", "error": error}


def _ok(latency=5):
    return {"ok": True, "latency_ms": latency, "model": "m1", "error": ""}


def test_probe_disables_channel_after_fail_threshold(app_ctx, monkeypatch):
    import models
    from extensions import db
    from services import probe
    ch = _mk_channel(db)
    monkeypatch.setattr(probe, "probe_once", lambda c: _fail())
    probe.probe_channel(ch)
    probe.probe_channel(ch)
    assert ch.status == 1 and ch.auto_disabled == 0
    probe.probe_channel(ch)                       # 默认阈值 3
    assert ch.status == 0 and ch.auto_disabled == 1
    kinds = [e.kind for e in models.ChannelEvent.query.filter_by(channel_id=ch.id).all()]
    assert kinds.count("probe_fail") == 3 and "auto_disable" in kinds
    assert ch.last_test_ok == 0 and ch.fail_streak == 3


def test_probe_recovers_auto_disabled_channel_after_two_successes(app_ctx, monkeypatch):
    import models
    from extensions import db
    from services import probe
    ch = _mk_channel(db)
    monkeypatch.setattr(probe, "probe_once", lambda c: _fail())
    for _ in range(3):
        probe.probe_channel(ch)
    monkeypatch.setattr(probe, "probe_once", lambda c: _ok())
    probe.probe_channel(ch)
    assert ch.status == 0 and ch.auto_disabled == 1   # 第一次成功只累计
    probe.probe_channel(ch)
    assert ch.status == 1 and ch.auto_disabled == 0 and ch.recover_streak == 0
    kinds = [e.kind for e in models.ChannelEvent.query.filter_by(channel_id=ch.id).all()]
    assert "auto_recover" in kinds


def test_probe_all_skips_manually_disabled_channels(app_ctx, monkeypatch):
    from extensions import db
    from services import probe
    enabled = _mk_channel(db, name="on")
    manual = _mk_channel(db, name="off", status=0)
    seen = []

    def fake(channel):
        seen.append(channel.id)
        return _ok()

    monkeypatch.setattr(probe, "probe_once", fake)
    probe.probe_all()
    assert enabled.id in seen and manual.id not in seen
    assert manual.last_test_ok is None               # 未被探活,不留测试结果


def test_disable_threshold_from_settings(app_ctx, monkeypatch):
    from extensions import db
    from services import probe
    ch = _mk_channel(db)
    import models
    models.Setting.put("probe_disable_threshold", 1)
    db.session.commit()
    monkeypatch.setattr(probe, "probe_once", lambda c: _fail())
    probe.probe_channel(ch)
    assert ch.status == 0 and ch.auto_disabled == 1


def test_probe_all_prunes_old_events(app_ctx, monkeypatch):
    import datetime as dt
    import models
    from extensions import db
    from services import probe
    ch = _mk_channel(db)
    old = models.ChannelEvent(channel_id=ch.id, kind="probe_ok", message="old",
                              created_at=dt.datetime.now() - dt.timedelta(days=20))
    db.session.add(old)
    db.session.commit()
    old_id = old.id
    db.session.expunge(old)
    monkeypatch.setattr(probe, "probe_once", lambda c: _ok())
    probe.probe_all()
    assert models.ChannelEvent.query.filter_by(id=old_id).first() is None


# ---------------- relay 错误分类 ----------------

def test_400_model_not_found_is_retry():
    from services.relay import _classify_upstream_error
    resp = SimpleNamespace(status_code=400,
                           text='{"error":{"message":"Invalid model: foo","type":"invalid_request_error"}}')
    phase, detail = _classify_upstream_error(resp)
    assert phase == "retry" and "Invalid model" in detail


def test_400_context_length_is_reject():
    from services.relay import _classify_upstream_error
    resp = SimpleNamespace(status_code=400,
                           text="This model's maximum context length is 8192 tokens")
    assert _classify_upstream_error(resp)[0] == "reject"


def test_retry_statuses_still_retry_with_body():
    from services.relay import _classify_upstream_error
    resp = SimpleNamespace(status_code=429, text="rate limited")
    phase, detail = _classify_upstream_error(resp)
    assert phase == "retry" and "429" in detail


def test_404_is_reject():
    from services.relay import _classify_upstream_error
    resp = SimpleNamespace(status_code=404, text="not found")
    assert _classify_upstream_error(resp)[0] == "reject"


def test_log_failover_writes_event(app_ctx):
    import models
    from extensions import db
    from services.relay import _log_failover
    ch = _mk_channel(db)
    _log_failover(ch.id, "req-abc", "upstream 502: bad gateway")
    ev = models.ChannelEvent.query.filter_by(channel_id=ch.id, kind="failover").one()
    assert ev.request_id == "req-abc" and "502" in ev.message


# ---------------- notify ----------------

def test_notify_payload_shapes():
    from services.notify import _payload
    assert _payload("wecom", "hi") == {"msgtype": "text", "text": {"content": "hi"}}
    assert _payload("dingtalk", "hi") == {"msgtype": "text", "text": {"content": "hi"}}
    assert _payload("feishu", "hi") == {"msg_type": "text", "content": {"text": "hi"}}


def test_notify_disabled_by_default(app_ctx):
    from services import notify
    assert notify.enabled() is False
    assert notify.send_text("x") is False


def test_notify_enabled_requires_url(app_ctx):
    import models
    from extensions import db
    from services import notify
    models.Setting.put("notify_enabled", True)
    models.Setting.put("notify_webhook_url", "not-a-url")
    db.session.commit()
    assert notify.enabled() is False
    models.Setting.put("notify_webhook_url", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x")
    db.session.commit()
    assert notify.enabled() is True


# ---------------- 渠道余额(词元之河 origin/user/balance 约定) ----------------

class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_fetch_balance_uses_origin_and_parses(app_ctx, monkeypatch):
    import services.network
    from extensions import db
    from services import probe
    monkeypatch.setattr(services.network, "validate_upstream_url", lambda url: url)
    ch = _mk_channel(db, base_url="https://api.tokenriver.cn/v1")
    seen = {}

    def fake_get(url, **kw):
        seen["url"] = url
        seen["auth"] = kw["headers"]["Authorization"]
        return _FakeResp(200, {"is_active": True, "balance": 123.45,
                               "total": 181.1, "used": 57.65, "currency": "CNY"})

    monkeypatch.setattr(probe.requests, "get", fake_get)
    info = probe.fetch_balance(ch)
    # /v1 后缀必须去掉:余额接口挂在站点根路径
    assert seen["url"] == "https://api.tokenriver.cn/user/balance"
    assert seen["auth"] == "Bearer sk-x"
    assert info == {"balance": 123.45, "total": 181.1, "used": 57.65,
                    "currency": "CNY", "is_active": True}


def test_fetch_balance_unsupported_upstream(app_ctx, monkeypatch):
    import services.network
    from extensions import db
    from services import probe
    monkeypatch.setattr(services.network, "validate_upstream_url", lambda url: url)
    ch = _mk_channel(db, base_url="https://api.deepseek.com")
    monkeypatch.setattr(probe.requests, "get",
                        lambda url, **kw: _FakeResp(404, {"error": "Not Found"}))
    with pytest.raises(ValueError, match="不支持余额查询"):
        probe.fetch_balance(ch)


def test_fetch_balance_non_json_response(app_ctx, monkeypatch):
    import services.network
    from extensions import db
    from services import probe
    monkeypatch.setattr(services.network, "validate_upstream_url", lambda url: url)
    ch = _mk_channel(db)
    monkeypatch.setattr(probe.requests, "get",
                        lambda url, **kw: _FakeResp(200, ValueError("no json")))
    with pytest.raises(ValueError):
        probe.fetch_balance(ch)
