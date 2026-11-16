#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渠道异常通知:状态跃迁(自动禁用/自动恢复)推送到 IM 群机器人 webhook。

支持企业微信 / 钉钉 / 飞书三种文本机器人,配置存站点设置。
发送失败只记日志,绝不影响探活与请求主链路。
"""
import requests
from flask import current_app

from models import Setting

WEBHOOK_TYPES = ("wecom", "dingtalk", "feishu")
TEST_TEXT = "【61API】渠道通知测试:看到这条消息说明 webhook 配置已生效。"


def _payload(kind: str, text: str) -> dict:
    if kind == "feishu":
        return {"msg_type": "text", "content": {"text": text}}
    if kind == "dingtalk":
        return {"msgtype": "text", "text": {"content": text}}
    return {"msgtype": "text", "text": {"content": text}}   # wecom


def enabled() -> bool:
    url = (Setting.get("notify_webhook_url") or "").strip()
    return bool(Setting.get("notify_enabled", False)) and url.startswith(("http://", "https://"))


def send_text(text: str) -> bool:
    if not enabled():
        return False
    kind = Setting.get("notify_webhook_type", "wecom")
    if kind not in WEBHOOK_TYPES:
        kind = "wecom"
    url = (Setting.get("notify_webhook_url") or "").strip()
    try:
        resp = requests.post(url, json=_payload(kind, text), timeout=10)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} {resp.text[:120]}")
        return True
    except Exception:
        try:
            current_app.logger.exception("渠道通知发送失败")
        except Exception:
            pass
        return False


def channel_transition(channel, *, recovered: bool, detail: str = "") -> bool:
    verb = "已自动恢复上线" if recovered else "已自动禁用"
    return send_text(f"【61API】渠道「{channel.name}」{verb}{(':' + detail) if detail else ''}")


def send_test() -> bool:
    return send_text(TEST_TEXT)
