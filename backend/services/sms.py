#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""短信验证码:dev 模式自产自验(不花钱),aliyun 模式走阿里云短信(SendSms)。

阿里云无服务端验证码校验接口,统一本地生成、本地比对:发送前生成 6 位码存
SmsRecord,SendSms 只负责投递;校验用常数时间比对并原子作废。 ACS3-HMAC-SHA256
签名与 services/aliyun_captcha 同一套 V3 协议,纯标准库 + requests 直调。
"""
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests
from sqlalchemy import text

from config import (ALIYUN_SMS_ACCESS_KEY_ID, ALIYUN_SMS_ACCESS_KEY_SECRET,
                    ALIYUN_SMS_SIGN_NAME, ALIYUN_SMS_TEMPLATE_CODE, SMS_MODE,
                    SMS_SEND_IP_LIMIT, SMS_SEND_IP_WINDOW_SECONDS,
                    SMS_SEND_PHONE_WINDOW_SECONDS, SMS_VERIFY_LIMIT,
                    SMS_VERIFY_WINDOW_SECONDS)
from extensions import check_rate_limit, db
from models import SmsRecord

ENDPOINT = "dysmsapi.aliyuncs.com"
API_VERSION = "2017-05-25"
CODE_TTL_MINUTES = 5


def _now():
    return datetime.now()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_hex(key: bytes, msg: str) -> str:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()


def _signed_headers(ak: str, sk: str, action: str, body: bytes) -> dict:
    """ACS3-HMAC-SHA256 请求签名(RPC API:POST /,参数在 form body)。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = uuid.uuid4().hex
    payload_hash = _sha256_hex(body)
    headers = {
        "host": ENDPOINT,
        "x-acs-action": action,
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


def send_sms(phone: str, template_param: dict) -> tuple[bool, str]:
    """调用阿里云 SendSms;返回 (ok, 错误说明)。Code=OK 才视为成功。"""
    params = {
        "PhoneNumbers": phone,
        "SignName": ALIYUN_SMS_SIGN_NAME,
        "TemplateCode": ALIYUN_SMS_TEMPLATE_CODE,
        "TemplateParam": json.dumps(template_param, ensure_ascii=False),
    }
    body = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
    body_bytes = body.encode("utf-8")
    headers = _signed_headers(ALIYUN_SMS_ACCESS_KEY_ID, ALIYUN_SMS_ACCESS_KEY_SECRET,
                              "SendSms", body_bytes)
    headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"
    try:
        resp = requests.post(f"https://{ENDPOINT}/", data=body_bytes,
                             headers=headers, timeout=(3, 6))
        data = resp.json()
    except (requests.RequestException, ValueError):
        return False, "短信服务暂时不可用,请稍后再试"
    if not isinstance(data, dict) or data.get("Code") != "OK":
        detail = (data or {}).get("Message") if isinstance(data, dict) else ""
        return False, (detail or "短信发送失败,请稍后再试")[:80]
    return True, ""


def send_code(phone: str, purpose: str = "login", ip: str = ""):
    """发送验证码。返回 (ok, info);dev 模式 info 里带 code 供前端直填。"""
    if not check_rate_limit("sms:phone", phone, 1, SMS_SEND_PHONE_WINDOW_SECONDS):
        return False, "发送太频繁,请 60 秒后再试"
    if ip and not check_rate_limit("sms:ip", ip, SMS_SEND_IP_LIMIT, SMS_SEND_IP_WINDOW_SECONDS):
        return False, "当前网络发送太频繁,请稍后再试"
    if SMS_MODE == "off":
        return False, "短信服务未开启,请联系管理员"

    code = f"{secrets.randbelow(1000000):06d}"
    if SMS_MODE == "aliyun":
        okr, err_msg = send_sms(phone, {"code": code})
        if not okr:
            return False, err_msg

    db.session.add(SmsRecord(phone=phone, purpose=purpose, code=code,
                             expires_at=_now() + timedelta(minutes=CODE_TTL_MINUTES)))
    db.session.commit()
    return True, {"dev_code": code} if SMS_MODE == "dev" else {}


def _consume_code(record_id) -> bool:
    result = db.session.execute(text(
        "UPDATE sms_records SET used = 1 "
        "WHERE id = :id AND used = 0 AND expires_at > :now"
    ), {"id": record_id, "now": _now()})
    db.session.commit()
    return result.rowcount == 1


def verify_code(phone: str, purpose: str, code: str) -> bool:
    if not check_rate_limit("sms:verify", f"{phone}:{purpose}",
                            SMS_VERIFY_LIMIT, SMS_VERIFY_WINDOW_SECONDS):
        return False
    rec = (SmsRecord.query.filter_by(phone=phone, purpose=purpose, used=0)
           .order_by(SmsRecord.id.desc()).first())
    if not rec or not rec.expires_at or _now() > rec.expires_at or not code:
        return False
    if not secrets.compare_digest(rec.code or "", code):
        return False
    return _consume_code(rec.id)
