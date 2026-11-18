#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""认证接口:手机号+验证码+密码注册;手机号+密码 或 手机号+验证码 登录。"""
import random
import re
import time
from datetime import datetime, timedelta

import jwt
from flask import Blueprint, g, request
from werkzeug.security import check_password_hash, generate_password_hash

from config import (FEATURE_PUBLIC_SIGNUP, FEATURE_SMS, SECRET_KEY,
                    LOGIN_ACCOUNT_LIMIT, LOGIN_ACCOUNT_WINDOW_SECONDS,
                    LOGIN_IP_LIMIT, LOGIN_IP_WINDOW_SECONDS)
from extensions import (auth_required, check_rate_limit, clear_session_cookie,
                        client_ip, db, err, ok, set_session_cookie)
from models import AuthThrottle, Setting, Tenant, User, gen_unique_uid
from services import audit
from services.billing import yuan_to_quota
from services.sms import send_code, verify_code

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
PHONE_CHANGE_SCOPE = "phone_change"
PHONE_CHANGE_TICKET_TTL = 600  # 换绑票据 10 分钟


def _phone_change_ticket() -> str:
    """第一步(验证旧手机号)通过后签发的短期换绑票据,绑定用户与有效期。"""
    return jwt.encode({"uid": g.user.id, "scope": PHONE_CHANGE_SCOPE,
                       "exp": int(time.time()) + PHONE_CHANGE_TICKET_TTL},
                      SECRET_KEY, algorithm="HS256")


def _phone_change_ticket_valid(ticket) -> bool:
    if not isinstance(ticket, str) or not ticket:
        return False
    try:
        payload = jwt.decode(ticket, SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return False
    return payload.get("scope") == PHONE_CHANGE_SCOPE and payload.get("uid") == g.user.id


def _password_valid(password):
    return (len(password) >= 10 and re.search(r"[A-Za-z]", password) is not None
            and re.search(r"\d", password) is not None)


def _gen_invite_code():
    while True:
        code = "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=8))
        if not User.query.filter_by(invite_code=code).first():
            return code


def _grant_invite_bonus(new_user, invite_ref):
    if not invite_ref:
        return
    ref = str(invite_ref).strip()
    # 邀请链接后缀为邀请人 UID(纯数字);旧链接的随机邀请码仍兼容
    inviter = User.query.filter_by(uid=ref).first() if ref.isdigit() else None
    if inviter is None:
        inviter = User.query.filter_by(invite_code=ref.upper()).first()
    if not inviter or inviter.id == new_user.id:
        return
    from services.invite import review_invite
    if review_invite(inviter, new_user):
        new_user.invited_by = inviter.id


def _login_response(user):
    user.last_login_at = datetime.now()
    user.last_login_ip = client_ip()
    AuthThrottle.query.filter(AuthThrottle.key == f"login:account:{user.phone or user.username}").delete()
    db.session.commit()
    audit.record("auth.login", target_type="user", target_id=user.id, actor=user)
    return set_session_cookie(ok({"user": user.to_dict()}), user)


def _login_blocked(identity):
    ip = client_ip()
    if not check_rate_limit("login:ip", ip, LOGIN_IP_LIMIT, LOGIN_IP_WINDOW_SECONDS):
        return err("尝试过于频繁,请稍后再试", 429)
    cutoff = datetime.now() - timedelta(seconds=LOGIN_ACCOUNT_WINDOW_SECONDS)
    failures = AuthThrottle.query.filter(
        AuthThrottle.key == f"login:account:{identity}",
        AuthThrottle.created_at > cutoff).count()
    if failures >= LOGIN_ACCOUNT_LIMIT:
        return err("失败次数过多,该账号已被临时锁定,请稍后再试", 429)
    return None


def _login_failed(identity):
    if not check_rate_limit("login:account", identity,
                            LOGIN_ACCOUNT_LIMIT, LOGIN_ACCOUNT_WINDOW_SECONDS):
        return err("失败次数过多,该账号已被临时锁定,请稍后再试", 429)
    return None


@bp.post("/register")
def register():
    if not FEATURE_PUBLIC_SIGNUP:
        return err("私有化部署不开放自助注册,请联系管理员开通账号", 403)
    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip()
    password = data.get("password") or ""
    if not PHONE_RE.match(phone):
        return err("手机号格式不正确")
    if not _password_valid(password):
        return err("密码至少 10 位且必须包含字母和数字")
    if User.query.filter_by(phone=phone).first():
        return err("该手机号已注册,请直接登录")
    if not verify_code(phone, "register", code=data.get("code") or ""):
        return err("验证码错误或已过期")

    user = User(phone=phone, username=phone,
                password_hash=generate_password_hash(password),
                invite_code=_gen_invite_code())
    tenant = Tenant.query.order_by(Tenant.id).first()
    user.tenant_id = tenant.id if tenant else None
    bonus_cny = float(Setting.get("new_user_bonus_cny", 0))
    user.quota = yuan_to_quota(bonus_cny)
    db.session.add(user)
    db.session.flush()
    user.uid = gen_unique_uid()
    user.register_ip = client_ip()
    _grant_invite_bonus(user, data.get("invite_code"))
    from services.resourcepack import grant_register_gift
    grant_register_gift(user)  # 注册赠送资源包(站点设置里配置;未配置则跳过)
    user.last_login_at = datetime.now()
    user.last_login_ip = client_ip()
    # 注册即视为同意《服务条款》与《隐私政策》,留审计日志
    audit.record("user.agreement_agreed", target_type="user", target_id=user.id,
                 detail={"agreements": ["服务条款", "隐私政策"], "via": "register"},
                 actor=user, commit=False)
    db.session.commit()
    from services.bark import user_registered
    user_registered(user.phone, user.register_ip or "")
    return set_session_cookie(ok({"user": user.to_dict()}), user)


@bp.post("/sms/send")
def sms_send():
    if not FEATURE_SMS:
        return err("私有化部署已关闭短信服务,请联系管理员", 403)
    from services.aliyun_captcha import verify_captcha
    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip()
    purpose = data.get("purpose") or "login"
    cvp = data.get("captcha_verify_param") or ""
    if purpose not in ("register", "login", "reset"):
        return err("不支持的验证码用途")
    if not PHONE_RE.match(phone):
        return err("手机号格式不正确")
    if not cvp or not verify_captcha(cvp):
        return err("人机验证未通过,请重试", 428)
    if purpose == "register" and User.query.filter_by(phone=phone).first():
        return err("该手机号已注册,请直接登录")
    if purpose in ("login", "reset") and not User.query.filter_by(phone=phone).first():
        return err("该手机号未注册")
    okr, info = send_code(phone, purpose, client_ip())
    if not okr:
        return err(info if isinstance(info, str) else "发送失败")
    return ok(info)


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    identity = (data.get("phone") or data.get("username") or "").strip()
    password = data.get("password") or ""
    blocked = _login_blocked(identity)
    if blocked:
        return blocked
    user = User.query.filter_by(phone=identity).first()
    if not user:
        user = User.query.filter_by(username=identity).first()
    if not user or not user.password_hash or not check_password_hash(user.password_hash, password):
        limited = _login_failed(identity)
        if limited:
            return limited
        audit.record("auth.login_failed", target_type="user", target_id=identity,
                     detail={"reason": "bad_password"})
        return err("手机号或密码错误", 401)
    if user.status != 1:
        audit.record("auth.login_failed", target_type="user", target_id=user.id,
                     detail={"reason": "disabled"}, actor=user)
        return err("账号已被禁用", 403)
    return _login_response(user)


@bp.post("/sms/login")
def sms_login():
    if not FEATURE_SMS:
        return err("私有化部署已关闭短信服务,请使用用户名密码登录", 403)
    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip()
    if not PHONE_RE.match(phone):
        return err("手机号格式不正确")
    blocked = _login_blocked(phone)
    if blocked:
        return blocked
    if not verify_code(phone, "login", data.get("code") or ""):
        limited = _login_failed(phone)
        if limited:
            return limited
        return err("验证码错误或已过期")
    user = User.query.filter_by(phone=phone).first()
    if not user:
        return err("该手机号未注册,请先注册", 404)
    if user.status != 1:
        return err("账号已被禁用", 403)
    return _login_response(user)


@bp.post("/logout")
def logout():
    return clear_session_cookie(ok())


@bp.post("/password/reset")
def reset_password():
    if not FEATURE_SMS:
        return err("私有化部署不开放自助重置,请联系管理员重置密码", 403)
    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip()
    new_pwd = data.get("new_password") or ""
    if not PHONE_RE.match(phone):
        return err("手机号格式不正确")
    if not _password_valid(new_pwd):
        return err("新密码至少 10 位且必须包含字母和数字")
    user = User.query.filter_by(phone=phone).first()
    if not user:
        return err("该手机号未注册", 404)
    if not verify_code(phone, "reset", data.get("code") or ""):
        return err("验证码错误或已过期")
    user.password_hash = generate_password_hash(new_pwd)
    user.token_version = (user.token_version or 0) + 1
    db.session.commit()
    audit.record("auth.password_reset", target_type="user", target_id=user.id,
                 detail={"via": "sms"}, actor=user)
    return ok()


@bp.get("/me")
@auth_required
def me():
    return ok(g.user.to_dict())


@bp.post("/password")
@auth_required
def change_password():
    data = request.get_json(silent=True) or {}
    old, new = data.get("old_password") or "", data.get("new_password") or ""
    if not _password_valid(new):
        return err("新密码至少 10 位且必须包含字母和数字")
    if g.user.password_hash and not check_password_hash(g.user.password_hash, old):
        return err("原密码错误")
    g.user.password_hash = generate_password_hash(new)
    g.user.token_version = (g.user.token_version or 0) + 1
    db.session.commit()
    audit.record("auth.password_change", target_type="user", target_id=g.user.id)
    return set_session_cookie(ok(), g.user)


@bp.post("/phone/change/send-old")
@auth_required
def phone_change_send_old():
    """换绑第一步:向当前绑定手机号发送验证码。"""
    if not FEATURE_SMS:
        return err("私有化部署已关闭短信服务", 403)
    if not g.user.phone:
        return err("当前账号未绑定手机号,无需验证旧号")
    okr, info = send_code(g.user.phone, "change_old", client_ip())
    if not okr:
        return err(info if isinstance(info, str) else "发送失败")
    return ok(info)


@bp.post("/phone/change/verify-old")
@auth_required
def phone_change_verify_old():
    """换绑第一步校验:验证旧手机号验证码,通过后签发 10 分钟换绑票据。"""
    if not FEATURE_SMS:
        return err("私有化部署已关闭短信服务", 403)
    if not g.user.phone:
        return err("当前账号未绑定手机号,无需验证旧号")
    data = request.get_json(silent=True) or {}
    if not verify_code(g.user.phone, "change_old", (data.get("code") or "").strip()):
        return err("验证码错误或已过期")
    return ok({"ticket": _phone_change_ticket()})


@bp.post("/phone/bind/send")
@auth_required
def bind_phone_send():
    """向新手机号发送绑定验证码;已绑定手机号的账号必须先通过旧号验证(持票据)。"""
    if not FEATURE_SMS:
        return err("私有化部署已关闭短信服务", 403)
    from services.aliyun_captcha import verify_captcha
    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip()
    cvp = data.get("captcha_verify_param") or ""
    if g.user.phone and not _phone_change_ticket_valid(data.get("ticket")):
        return err("请先验证当前手机号", 428)
    if not PHONE_RE.match(phone):
        return err("手机号格式不正确")
    if not cvp or not verify_captcha(cvp):
        return err("人机验证未通过,请重试", 428)
    if User.query.filter_by(phone=phone).first():
        return err("该手机号已被其他账号绑定")
    okr, info = send_code(phone, "bind", client_ip())
    if not okr:
        return err(info if isinstance(info, str) else "发送失败")
    return ok(info)


@bp.post("/phone/bind")
@auth_required
def bind_phone():
    if not FEATURE_SMS:
        return err("私有化部署已关闭短信服务", 403)
    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip()
    code = (data.get("code") or "").strip()
    if g.user.phone and not _phone_change_ticket_valid(data.get("ticket")):
        return err("请先验证当前手机号", 428)
    if not PHONE_RE.match(phone):
        return err("手机号格式不正确")
    if User.query.filter_by(phone=phone).first():
        return err("该手机号已被其他账号绑定")
    if not verify_code(phone, "bind", code):
        return err("验证码错误或已过期")
    g.user.phone = phone
    db.session.commit()
    audit.record("user.phone_change", target_type="user", target_id=g.user.id,
                 detail={"via": "sms_change_flow"})
    return ok()
