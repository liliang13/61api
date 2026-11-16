#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渠道熔断器(进程内内存态)。

连续失败 FAIL_THRESHOLD 次 → 熔断 OPEN_SECONDS 秒(期间该渠道不参与选路);
熔断到期后半开,放行请求探测,成功即恢复。多 worker 各自独立计数,最终效果一致。
"""
import threading
import time

_LOCK = threading.Lock()
_STATE: dict = {}          # channel_id -> {"fails": int, "open_until": float, "last_err": str}
FAIL_THRESHOLD = 3
OPEN_SECONDS = 60


def is_open(channel_id: int) -> bool:
    with _LOCK:
        s = _STATE.get(channel_id)
        return bool(s and s.get("open_until", 0) > time.time())


def open_until(channel_id: int) -> float:
    with _LOCK:
        s = _STATE.get(channel_id)
        return s.get("open_until", 0) if s else 0


def record_fail(channel_id: int, err: str):
    with _LOCK:
        s = _STATE.setdefault(channel_id, {"fails": 0, "open_until": 0, "last_err": ""})
        s["fails"] = s.get("fails", 0) + 1
        s["last_err"] = (err or "")[:200]
        if s["fails"] >= FAIL_THRESHOLD:
            s["open_until"] = time.time() + OPEN_SECONDS
            s["fails"] = 0  # 熔断结束重新计数


def record_success(channel_id: int):
    with _LOCK:
        _STATE.pop(channel_id, None)


def status_of(channel_id: int) -> dict:
    with _LOCK:
        s = _STATE.get(channel_id) or {}
        return {"fails": s.get("fails", 0), "last_err": s.get("last_err", ""),
                "open_until": s.get("open_until", 0)}


def all_status() -> dict:
    with _LOCK:
        return {cid: dict(v) for cid, v in _STATE.items()}
