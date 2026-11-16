#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阿里云验证码 2.0 服务端验签(VerifyIntelligentCaptcha,ACS3-HMAC-SHA256)。

文档: help.aliyun.com/zh/captcha/captcha2-0/user-guide/server-access
凭据从环境变量读取:
  ALIYUN_CAPTCHA_ACCESS_KEY_ID / ALIYUN_CAPTCHA_ACCESS_KEY_SECRET / ALIYUN_CAPTCHA_SCENE_ID
调用异常、非成功响应及明确验签失败均拒绝。
"""
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import requests

ENDPOINT = "captcha.cn-shanghai.aliyuncs.com"
API_VERSION = "2023-03-05"
ACTION = "VerifyIntelligentCaptcha"


def _creds():
    return (os.getenv("ALIYUN_CAPTCHA_ACCESS_KEY_ID", ""),
            os.getenv("ALIYUN_CAPTCHA_ACCESS_KEY_SECRET", ""),
            os.getenv("ALIYUN_CAPTCHA_SCENE_ID", ""))


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_hex(key: bytes, msg: str) -> str:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()


def _signed_headers(ak: str, sk: str, body: bytes) -> dict:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = uuid.uuid4().hex
    payload_hash = _sha256_hex(body)
    headers = {
        "host": ENDPOINT,
        "x-acs-action": ACTION,
        "x-acs-version": API_VERSION,
        "x-acs-date": now,
        "x-acs-signature-nonce": nonce,
        "x-acs-content-sha256": payload_hash,
    }
    signed = sorted(headers.keys())
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in signed)
    canonical_request = ("POST\n/\n\n" + canonical_headers + "\n"
                         + ";".join(signed) + "\n" + payload_hash)
    string_to_sign = "ACS3-HMAC-SHA256\n" + _sha256_hex(canonical_request.encode("utf-8"))
    signature = _hmac_hex(sk.encode("utf-8"), string_to_sign)
    headers["Authorization"] = (
        f"ACS3-HMAC-SHA256 Credential={ak}, "
        f"SignedHeaders={';'.join(signed)}, Signature={signature}")
    return headers


def verify_captcha(captcha_verify_param: str) -> bool:
    ak, sk, scene_id = _creds()
    if not isinstance(captcha_verify_param, str) or not (ak and sk and captcha_verify_param):
        return False
    body = ("CaptchaVerifyParam=" + quote(captcha_verify_param, safe="")
            + "&SceneId=" + quote(scene_id, safe=""))
    body_bytes = body.encode("utf-8")
    headers = _signed_headers(ak, sk, body_bytes)
    headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"
    try:
        resp = requests.post(f"https://{ENDPOINT}/", data=body_bytes,
                             headers=headers, timeout=(3, 6))
        if resp.status_code != 200:
            return False
        data = resp.json()
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    result = data.get("Result") or {}
    return isinstance(result, dict) and result.get("VerifyResult") is True
