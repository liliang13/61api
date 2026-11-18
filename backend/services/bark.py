#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""站长 Bark 推送:新用户注册、订单支付成功等运营事件推到手机。

配置走环境变量(BARK_SERVER_URL / BARK_DEVICE_KEY),未配置时静默停用。
发送在守护线程里执行,失败只记日志,绝不阻塞注册/支付回调主链路。
"""
import threading

import requests
from flask import current_app

from config import BARK_DEVICE_KEY, BARK_SERVER_URL

_TIMEOUT = 8


def enabled() -> bool:
    return bool(BARK_SERVER_URL) and bool(BARK_DEVICE_KEY)


def _post(title: str, body: str) -> None:
    url = BARK_SERVER_URL.rstrip("/") + "/push"
    resp = requests.post(
        url,
        json={"device_key": BARK_DEVICE_KEY, "title": title,
              "body": body, "group": "61api"},
        timeout=_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"Bark HTTP {resp.status_code} {resp.text[:120]}")


def send(title: str, body: str) -> None:
    """异步推送,任何异常只记日志。"""
    if not enabled():
        return

    def _worker():
        try:
            _post(title, body)
        except Exception:
            try:
                current_app.logger.exception("Bark 推送失败: %s", title)
            except Exception:
                pass

    threading.Thread(target=_worker, daemon=True).start()


def user_registered(phone: str, ip: str = "") -> None:
    ip_part = f"(IP {ip})" if ip else ""
    send("61API 新用户注册", f"{phone} 注册加入{ip_part}")


def order_paid(username: str, amount_fen: int, package_id: str, order_no: str) -> None:
    send("61API 收到订单付款",
         f"{username} 支付 ¥{amount_fen / 100:.2f}(套餐 {package_id},单号 {order_no})")
