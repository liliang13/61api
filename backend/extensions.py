#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask 扩展与通用工具:数据库、JWT、鉴权装饰器、统一响应。"""
import functools
import hashlib
import hmac
import ipaddress
import time
from datetime import datetime, timedelta

import jwt
from flask import g, jsonify, request
from sqlalchemy import text

from config import (API_KEY_PEPPER, JWT_TTL, SECRET_KEY, SESSION_COOKIE_NAME,
                    SESSION_COOKIE_SAMESITE, SESSION_COOKIE_SECURE,
                    TRUSTED_PROXY_IPS)

try:
    from flask_sqlalchemy import SQLAlchemy
    db = SQLAlchemy()
except Exception:  # pragma: no cover
    raise

JWT_ALG = "HS256"


def hash_api_key(raw) -> str:
    """返回 API 密钥的带服务端 pepper 的 HMAC-SHA256 十六进制摘要。"""
    if not isinstance(raw, str) or not raw:
        raise ValueError("API key 不能为空")
    return hmac.new(API_KEY_PEPPER.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()


def make_token(user) -> str:
    payload = {"uid": user.id, "role": user.role, "tv": user.token_version or 0,
               "exp": int(time.time()) + JWT_TTL}
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALG)


def decode_token(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALG])
    except Exception:
        return None


def current_payload():
    """优先解析 HttpOnly 会话 Cookie，兼容 Authorization Bearer。"""
    if hasattr(g, "auth_payload"):
        return g.auth_payload
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
    g.auth_payload = decode_token(token) if token else None
    return g.auth_payload


def current_uid():
    payload = current_payload()
    return payload.get("uid") if payload else None


def set_session_cookie(response, user):
    response.set_cookie(
        SESSION_COOKIE_NAME, make_token(user), max_age=JWT_TTL,
        httponly=True, secure=SESSION_COOKIE_SECURE,
        samesite=SESSION_COOKIE_SAMESITE, path="/")
    return response


def clear_session_cookie(response):
    response.set_cookie(
        SESSION_COOKIE_NAME, "", max_age=0, expires=0,
        httponly=True, secure=SESSION_COOKIE_SECURE,
        samesite=SESSION_COOKIE_SAMESITE, path="/")
    return response


def csrf_protect():
    """全局 before_request 钩子：Cookie 会话的 /api 写请求要求同源 AJAX 头。"""
    if (request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}
            or not (request.path == "/api" or request.path.startswith("/api/"))
            or not request.cookies.get(SESSION_COOKIE_NAME)):
        return None
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return err("CSRF 校验失败", 403)
    return None


def csrf_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        failure = csrf_protect()
        return failure if failure is not None else fn(*args, **kwargs)
    return wrapper


def auth_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        payload = current_payload()
        uid = payload.get("uid") if payload else None
        if not uid:
            return jsonify(ok=False, error="未登录或登录已过期"), 401
        from models import Tenant, User
        user = db.session.get(User, uid)
        if not user or user.status != 1:
            return jsonify(ok=False, error="账号不可用"), 401
        if (payload.get("tv") or 0) != (user.token_version or 0):
            return jsonify(ok=False, error="登录状态已失效,请重新登录"), 401
        g.user = user
        g.tenant = db.session.get(Tenant, user.tenant_id) if user.tenant_id else None
        return fn(*args, **kwargs)
    return wrapper


def current_tenant():
    return getattr(g, "tenant", None)


def admin_required(fn):
    @functools.wraps(fn)
    @auth_required
    def wrapper(*args, **kwargs):
        if g.user.role != "admin":
            return jsonify(ok=False, error="需要管理员权限"), 403
        return fn(*args, **kwargs)
    return wrapper


def _trusted_proxy(remote_addr):
    try:
        remote = ipaddress.ip_address(remote_addr or "")
    except ValueError:
        return False
    for trusted in TRUSTED_PROXY_IPS:
        try:
            if "/" in trusted:
                if remote in ipaddress.ip_network(trusted, strict=False):
                    return True
            elif remote == ipaddress.ip_address(trusted):
                return True
        except ValueError:
            continue
    return False


def client_ip():
    """仅当直连对端属于可信代理时，才采用代理提供的客户端地址。"""
    remote = request.remote_addr or ""
    if not _trusted_proxy(remote):
        return remote
    forwarded = request.headers.get("X-Forwarded-For", "")
    candidate = forwarded.split(",", 1)[0].strip() if forwarded else request.headers.get("X-Real-IP", "").strip()
    try:
        return str(ipaddress.ip_address(candidate)) if candidate else remote
    except ValueError:
        return remote


def check_rate_limit(scope, identity, limit, window_seconds) -> bool:
    """原子记录并检查固定窗口内次数；达到 limit 后的请求返回 False。"""
    if limit <= 0 or window_seconds <= 0:
        return False
    key = f"{scope}:{identity}"
    if len(key.encode("utf-8")) > 80:
        key = f"{scope}:{hashlib.sha256(str(identity).encode('utf-8')).hexdigest()}"[:80]
    now = datetime.now()
    cutoff = now - timedelta(seconds=window_seconds)
    try:
        result = db.session.execute(text(
            "INSERT INTO auth_throttle (key, created_at) "
            "SELECT :key, :now WHERE (SELECT COUNT(*) FROM auth_throttle "
            "WHERE key = :key AND created_at > :cutoff) < :limit"
        ), {"key": key, "now": now, "cutoff": cutoff, "limit": limit})
        db.session.commit()
        return result.rowcount == 1
    except Exception:
        db.session.rollback()
        raise


def ok(data=None, **extra):
    body = {"ok": True, "data": data}
    body.update(extra)
    return jsonify(body)


def err(message, status=400):
    return jsonify(ok=False, error=message), status


def page_args(default_size=20, max_size=100):
    try:
        page = max(1, int(request.args.get("page", 1)))
        size = min(max_size, max(1, int(request.args.get("page_size", default_size))))
    except ValueError:
        page, size = 1, default_size
    return page, size
