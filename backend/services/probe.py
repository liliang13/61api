#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渠道探活:发一条 1 token 极小请求,结果落库并驱动自动禁用/恢复状态机。

状态机(以 DB 为准,跨进程/跨 worker 共享,由 systemd timer 周期调用):
- status=1 渠道:连续失败 fail_streak 达阈值(设置 probe_disable_threshold,默认 3)
  → status=0 + auto_disabled=1,发禁用通知
- auto_disabled=1 渠道:继续探活,连续成功 RECOVER_STREAK 次 → status=1 + auto_disabled=0,
  发恢复通知
- 人为停用(status=0 且 auto_disabled=0)不探活、不自动恢复
"""
from datetime import datetime, timedelta

import requests

from extensions import db
from models import Channel, ChannelEvent, Setting
from services import notify

RECOVER_STREAK = 2
PROBE_TIMEOUT = 20
DEFAULT_DISABLE_THRESHOLD = 3
EVENT_RETENTION_DAYS = 14
UA = "61API-Probe/1.0"


def _pick_model(channel) -> str:
    from models import ModelItem
    names = channel.model_list()
    if "*" not in names:
        return names[0]
    first = ModelItem.query.filter_by(status=1).order_by(
        ModelItem.sort.asc(), ModelItem.id.asc()).first()
    return first.name if first else "deepseek-flash"


def probe_once(channel) -> dict:
    """对单渠道发极小探测请求,返回 {ok, latency_ms, model, error}。不写库。"""
    if channel.type == "mock":
        return {"ok": True, "latency_ms": 0, "model": "-", "error": ""}
    from services.network import validate_upstream_url
    model = _pick_model(channel)
    upstream_name = channel.upstream_model_of(model)
    start = datetime.now()
    try:
        url = validate_upstream_url(channel.base_url) + "/chat/completions"
        with requests.post(url, json={"model": upstream_name,
                                      "messages": [{"role": "user", "content": "hi"}],
                                      "max_tokens": 1, "stream": False},
                           headers={"Authorization": f"Bearer {channel.api_key}",
                                    "Content-Type": "application/json", "User-Agent": UA},
                           timeout=PROBE_TIMEOUT, allow_redirects=False) as resp:
            latency = int((datetime.now() - start).total_seconds() * 1000)
            if resp.status_code == 200:
                return {"ok": True, "latency_ms": latency, "model": model, "error": ""}
            try:
                body = (resp.text or "").strip().replace("\n", " ")[:200]
            except Exception:
                body = ""
            return {"ok": False, "latency_ms": latency, "model": model,
                    "error": f"HTTP {resp.status_code}" + (f": {body}" if body else "")}
    except Exception as exc:
        latency = int((datetime.now() - start).total_seconds() * 1000)
        return {"ok": False, "latency_ms": latency, "model": model, "error": f"connect: {exc}"}


def _record_event(channel, kind, message, latency_ms=None):
    db.session.add(ChannelEvent(channel_id=channel.id, kind=kind, latency_ms=latency_ms,
                                message=(message or "")[:500]))


def probe_channel(channel) -> dict:
    """探活单渠道并落库(结果 + 连败/连成计数 + 状态跃迁与通知)。"""
    result = probe_once(channel)
    channel.last_test_at = datetime.now()
    channel.last_test_ok = 1 if result["ok"] else 0
    channel.last_test_latency_ms = result["latency_ms"]
    channel.last_test_error = "" if result["ok"] else result["error"][:500]
    recovered = False
    disabled = False
    if result["ok"]:
        channel.fail_streak = 0
        _record_event(channel, "probe_ok",
                      f"探活成功 {result['model']} {result['latency_ms']}ms", result["latency_ms"])
        if channel.auto_disabled == 1:
            channel.recover_streak = (channel.recover_streak or 0) + 1
            if channel.recover_streak >= RECOVER_STREAK:
                channel.auto_disabled = 0
                channel.status = 1
                channel.recover_streak = 0
                _record_event(channel, "auto_recover",
                              f"连续 {RECOVER_STREAK} 次探活成功,自动恢复上线")
                recovered = True
        else:
            channel.recover_streak = 0
    else:
        channel.fail_streak = (channel.fail_streak or 0) + 1
        channel.recover_streak = 0
        _record_event(channel, "probe_fail", f"探活失败: {result['error']}", result["latency_ms"])
        threshold = Setting.get("probe_disable_threshold", DEFAULT_DISABLE_THRESHOLD, int) \
            or DEFAULT_DISABLE_THRESHOLD
        if channel.status == 1 and channel.fail_streak >= threshold:
            channel.status = 0
            channel.auto_disabled = 1
            _record_event(channel, "auto_disable",
                          f"连续 {channel.fail_streak} 次探活失败(阈值 {threshold}),自动禁用")
            disabled = True
    db.session.commit()
    if recovered:
        notify.channel_transition(channel, recovered=True,
                                  detail=f"连续 {RECOVER_STREAK} 次探活成功")
    if disabled:
        notify.channel_transition(channel, recovered=False,
                                  detail=f"连续 {channel.fail_streak} 次探活失败,最后错误 {result['error'][:120]}")
    return result


def probe_targets(channel_id=None):
    q = Channel.query.filter(db.or_(Channel.status == 1, Channel.auto_disabled == 1))
    if channel_id:
        q = q.filter(Channel.id == channel_id)
    return q.order_by(Channel.id).all()


def probe_all(channel_id=None) -> list:
    """定时探活入口:探活全部目标渠道并清理过期事件。"""
    results = [dict(probe_channel(c), channel=c.name, channel_id=c.id)
               for c in probe_targets(channel_id)]
    cutoff = datetime.now() - timedelta(days=EVENT_RETENTION_DAYS)
    ChannelEvent.query.filter(ChannelEvent.created_at < cutoff).delete(synchronize_session=False)
    db.session.commit()
    return results


def fetch_balance(channel) -> dict:
    """查询上游账户余额(TokenRiver 等中转的 origin/user/balance 约定,单位人民币元)。

    上游密钥即渠道 api_key;失败抛 ValueError(文案可直接展示给管理员)。
    """
    from urllib.parse import urlparse
    from services.network import validate_upstream_url
    parts = urlparse(channel.base_url or "")
    if not parts.scheme or not parts.netloc:
        raise ValueError("渠道 Base URL 无效")
    origin = validate_upstream_url(f"{parts.scheme}://{parts.netloc}")
    try:
        with requests.get(origin + "/user/balance",
                          headers={"Authorization": f"Bearer {channel.api_key or ''}",
                                   "Accept": "application/json"},
                          timeout=(5, 15), allow_redirects=False) as resp:
            status = resp.status_code
            try:
                data = resp.json()
            except Exception:
                data = None
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"上游无响应: {exc}") from exc
    if not isinstance(data, dict) or "balance" not in data:
        detail = data.get("error") if isinstance(data, dict) else ""
        suffix = f" {detail}" if detail else ""
        raise ValueError(f"该上游不支持余额查询或响应异常(HTTP {status}{suffix})")
    try:
        return {"balance": round(float(data["balance"]), 2),
                "total": round(float(data.get("total") or 0), 2),
                "used": round(float(data.get("used") or 0), 2),
                "currency": data.get("currency") or "CNY",
                "is_active": bool(data.get("is_active", True))}
    except (TypeError, ValueError):
        raise ValueError("余额响应数值无法解析")
