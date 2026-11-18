#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""管理后台接口:统计 / 用户 / 渠道 / 模型定价 / 订单 / 兑换码 / 用量 / 站点设置。"""
import json
import math
import re
import secrets
from datetime import datetime, timedelta

import requests as http
from flask import Blueprint, current_app, g, request, send_file
from sqlalchemy import func
from werkzeug.security import generate_password_hash

from config import (FEATURE_INVOICE, FEATURE_INVITE, FEATURE_PAYMENTS,
                    FEATURE_REDEEM)
from extensions import admin_required, db, err, ok, page_args
from models import (Invoice, InvoiceItem, InviteReward, ApiKey, AuditLog, Channel, ChannelEvent,
                    ModelItem, Notice, NoticeRead, RedemptionCode, ResourcePackDef, Setting,
                    Ticket, TicketMessage, Tenant, TopupOrder, UsageLog, User, UserResourcePack,
                    gen_unique_uid)
from services import audit
from services import ticketfile
from services.billing import quota_to_yuan, yuan_to_quota
from services import breaker
from services.network import validate_upstream_url

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


@bp.get("/stats")
@admin_required
def stats():
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    q_today = (db.session.query(func.count(UsageLog.id),
                                func.coalesce(func.sum(UsageLog.prompt_tokens), 0),
                                func.coalesce(func.sum(UsageLog.completion_tokens), 0),
                                func.coalesce(func.sum(UsageLog.quota), 0))
               .filter(UsageLog.status != "held", UsageLog.created_at >= today).first())
    revenue = db.session.query(func.coalesce(func.sum(TopupOrder.amount), 0))\
        .filter(TopupOrder.status == "paid").scalar()
    users_total = User.query.filter(User.role != "admin").count()
    quota_held = db.session.query(func.coalesce(func.sum(User.quota), 0)).scalar()
    series = []
    for i in range(13, -1, -1):
        day = today - timedelta(days=i)
        nxt = day + timedelta(days=1)
        row = (db.session.query(func.count(UsageLog.id), func.coalesce(func.sum(UsageLog.quota), 0))
               .filter(UsageLog.status != "held", UsageLog.created_at >= day, UsageLog.created_at < nxt).first())
        series.append({"date": day.strftime("%m-%d"), "requests": row[0], "quota": int(row[1])})
    recent = UsageLog.query.order_by(UsageLog.id.desc()).limit(10).all()
    _chans = {c.id: c.name for c in Channel.query.all()}
    _tenants = {t.id: t.name for t in Tenant.query.all()}
    _recent = [dict(r.to_dict(),
                    channel_name=_chans.get(r.channel_id, "#" + str(r.channel_id) if r.channel_id else "-"),
                    tenant_name=_tenants.get(r.tenant_id, "-"))
               for r in recent]
    # 财务口径:余额区分「已开票锁定」与「净退款敞口」
    # 每用户有效开票额(active 发票项,含待开具/已开具,不含已拒绝)
    invoiced_by_user = dict(db.session.query(
        InvoiceItem.user_id, func.coalesce(func.sum(InvoiceItem.amount), 0))
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .filter(InvoiceItem.active == 1, Invoice.status.in_((0, 1)))
        .group_by(InvoiceItem.user_id).all())
    balances = dict(db.session.query(User.id, func.coalesce(User.quota, 0)).all())
    invoiced_locked = sum(min(int(balances.get(uid, 0)), int(inv))
                          for uid, inv in invoiced_by_user.items())
    total_balance = int(quota_held or 0)

    return ok({
        "users": users_total, "keys": ApiKey.query.count(),
        "tenants": Tenant.query.count(),
        "channels": Channel.query.count(),
        "models": ModelItem.query.filter_by(status=1).count(),
        "quota_held_yuan": quota_to_yuan(total_balance),
        "invoiced_locked_yuan": quota_to_yuan(invoiced_locked),
        "exposed_yuan": quota_to_yuan(max(0, total_balance - invoiced_locked)),
        "revenue_yuan": round(int(revenue or 0) / 100, 2),
        "today": {"requests": q_today[0],
                  "tokens": int(q_today[1]) + int(q_today[2]), "quota": int(q_today[3])},
        "series": series,
        "recent_logs": _recent,
    })


# ---------------- 用户管理 ----------------

def _password_valid(password):
    return (len(password) >= 10 and re.search(r"[A-Za-z]", password) is not None
            and re.search(r"\d", password) is not None)


def _unique_invite_code():
    while True:
        code = secrets.token_hex(4).upper()
        if not User.query.filter_by(invite_code=code).first():
            return code


@bp.get("/users")
@admin_required
def users():
    page, size = page_args()
    q = User.query
    tenant_id = request.args.get("tenant_id", type=int)
    if tenant_id:
        q = q.filter(User.tenant_id == tenant_id)
    kw = (request.args.get("search") or "").strip()
    if kw:
        q = q.filter((User.username.contains(kw)) | (User.phone.contains(kw)) | (User.uid.contains(kw)) |
                     (User.id == int(kw) if kw.isdigit() else False))
    total = q.count()
    rows = q.order_by(User.id.desc()).offset((page - 1) * size).limit(size).all()
    tenant_names = {t.id: t.name for t in Tenant.query.all()}
    return ok({"total": total, "page": page, "page_size": size,
               "items": [dict(u.to_dict(), tenant_name=tenant_names.get(u.tenant_id, ""))
                         for u in rows]})


@bp.post("/users")
@admin_required
def user_create():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not re.match(r"^[A-Za-z0-9_.-]{3,64}$", username):
        return err("用户名需为 3-64 位字母、数字、下划线、点或短横线")
    if not _password_valid(password):
        return err("密码至少 10 位且必须包含字母和数字")
    if User.query.filter_by(username=username).first():
        return err("用户名已存在")
    tenant = db.session.get(Tenant, data.get("tenant_id")) if data.get("tenant_id") else None
    if tenant is None:
        return err("请选择所属组织")
    role = data.get("role") or "user"
    if role not in ("user", "admin"):
        return err("角色不正确")
    try:
        quota = max(0, yuan_to_quota(float(data.get("quota_yuan") or 0)))
        phone = (data.get("phone") or "").strip()
    except (TypeError, ValueError, OverflowError):
        return err("额度数值无效")
    if phone and not re.match(r"^1[3-9]\d{9}$", phone):
        return err("手机号格式不正确")
    if phone and User.query.filter_by(phone=phone).first():
        return err("手机号已存在")
    user = User(username=username, phone=phone or None, tenant_id=tenant.id, role=role,
                password_hash=generate_password_hash(password), quota=quota,
                invite_code=_unique_invite_code(), status=1)
    db.session.add(user)
    db.session.flush()
    user.uid = gen_unique_uid()
    from services.resourcepack import grant_register_gift
    gift = grant_register_gift(user)  # 建号视同注册,同样享受资源包赠送
    db.session.commit()
    audit.record("user.create", target_type="user", target_id=user.id,
                 detail={"username": username, "tenant_id": tenant.id, "role": role,
                         "quota_yuan": quota_to_yuan(quota),
                         "gift_pack": gift.pack_name if gift else None})
    return ok(dict(user.to_dict(), tenant_name=tenant.name))


def _quota_value(value):
    if isinstance(value, bool):
        raise ValueError("数值无效")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("数值无效")
    return yuan_to_quota(number)


@bp.put("/users/<int:uid>")
@admin_required
def user_update(uid):
    user = db.session.get(User, uid)
    if not user:
        return err("用户不存在", 404)
    data = request.get_json(silent=True) or {}
    try:
        delta = (_quota_value(data["quota_add_yuan"])
                 if data.get("quota_add_yuan") not in (None, "") else None)
        quota_set = (_quota_value(data["quota_set_yuan"])
                     if data.get("quota_set_yuan") not in (None, "") else None)
    except (TypeError, ValueError, OverflowError):
        return err("额度数值无效", 400)
    if quota_set is not None and quota_set < 0:
        return err("额度不能为负数", 400)
    if "status" in data:
        if user.deleted_at:
            return err("已注销账户不可变更状态(软删除保留中)")
        user.status = 1 if data["status"] else 0
    if "role" in data and data["role"] in ("user", "admin"):
        user.role = data["role"]
    if "concurrency_limit" in data:
        try:
            cl = int(data["concurrency_limit"] or 0)
        except (TypeError, ValueError, OverflowError):
            return err("并发限制无效", 400)
        if not (0 <= cl <= 256):
            return err("并发限制需在 0-256 之间(0=使用全局默认)", 400)
        user.concurrency_limit = cl
    if "tenant_id" in data:
        tenant = db.session.get(Tenant, data["tenant_id"])
        if tenant is None:
            db.session.rollback()
            return err("组织不存在", 400)
        user.tenant_id = tenant.id
        # 密钥归属跟随用户迁移;历史用量仍保留原组织,便于对账
        ApiKey.query.filter_by(user_id=user.id).update(
            {"tenant_id": tenant.id}, synchronize_session=False)
    if delta is not None:
        conditions = [User.id == uid]
        if delta < 0:
            conditions.append(func.coalesce(User.quota, 0) >= -delta)
        changed = (db.session.query(User).filter(*conditions)
                   .update({"quota": func.coalesce(User.quota, 0) + delta},
                           synchronize_session=False))
        if not changed:
            db.session.rollback()
            return err("用户余额不足", 400)
    if quota_set is not None:
        user.quota = quota_set
    db.session.commit()
    audit.record("user.update", target_type="user", target_id=user.id,
                 detail={"fields": sorted(data.keys()), "role": user.role,
                         "status": user.status, "tenant_id": user.tenant_id,
                         "concurrency_limit": user.concurrency_limit or 0})
    return ok(user.to_dict())


@bp.post("/users/<int:uid>/password")
@admin_required
def user_reset_password(uid):
    user = db.session.get(User, uid)
    if not user:
        return err("用户不存在", 404)
    data = request.get_json(silent=True) or {}
    password = data.get("password") or ""
    if not _password_valid(password):
        return err("密码至少 10 位且必须包含字母和数字")
    user.password_hash = generate_password_hash(password)
    user.token_version = (user.token_version or 0) + 1
    db.session.commit()
    audit.record("user.password_reset", target_type="user", target_id=user.id,
                 detail={"username": user.username})
    return ok()


# ---------------- 组织管理 ----------------

@bp.get("/tenants")
@admin_required
def tenants():
    rows = Tenant.query.order_by(Tenant.id.asc()).all()
    user_counts = dict(db.session.query(User.tenant_id, func.count(User.id))
                       .filter(User.role != "admin").group_by(User.tenant_id).all())
    usage = dict(db.session.query(UsageLog.tenant_id, func.coalesce(func.sum(UsageLog.quota), 0))
                 .filter(UsageLog.status != "held").group_by(UsageLog.tenant_id).all())
    return ok([dict(t.to_dict(),
                    user_count=user_counts.get(t.id, 0),
                    usage_quota=int(usage.get(t.id, 0)),
                    usage_yuan=quota_to_yuan(int(usage.get(t.id, 0))))
               for t in rows])


@bp.post("/tenants")
@admin_required
def tenant_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    slug = (data.get("slug") or "").strip().lower()
    if not name:
        return err("组织名称不能为空")
    if not re.match(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$", slug):
        return err("标识需为 3-64 位小写字母、数字或短横线")
    if Tenant.query.filter_by(slug=slug).first():
        return err("组织标识已存在")
    try:
        quota = float(data.get("quota_yuan", -1))
    except (TypeError, ValueError, OverflowError):
        return err("额度数值无效")
    if not math.isfinite(quota) or quota < -1:
        return err("额度数值无效")
    tenant = Tenant(name=name, slug=slug,
                    quota=-1 if quota < 0 else yuan_to_quota(quota),
                    note=(data.get("note") or "").strip()[:200])
    db.session.add(tenant)
    db.session.commit()
    audit.record("tenant.create", target_type="tenant", target_id=tenant.id,
                 detail={"name": name, "slug": slug, "quota_yuan": quota})
    return ok(tenant.to_dict())


@bp.put("/tenants/<int:tid>")
@admin_required
def tenant_update(tid):
    tenant = db.session.get(Tenant, tid)
    if not tenant:
        return err("组织不存在", 404)
    data = request.get_json(silent=True) or {}
    if "name" in data and (data["name"] or "").strip():
        tenant.name = data["name"].strip()[:128]
    if "status" in data:
        tenant.status = 1 if data["status"] else 0
    if "note" in data:
        tenant.note = (data["note"] or "").strip()[:200]
    if "quota_set_yuan" in data and data["quota_set_yuan"] not in (None, ""):
        try:
            value = float(data["quota_set_yuan"])
        except (TypeError, ValueError, OverflowError):
            return err("额度数值无效")
        if not math.isfinite(value) or value < -1:
            return err("额度数值无效")
        tenant.quota = -1 if value < 0 else yuan_to_quota(value)
    db.session.commit()
    audit.record("tenant.update", target_type="tenant", target_id=tenant.id,
                 detail={"fields": sorted(data.keys()), "status": tenant.status})
    return ok(tenant.to_dict())


# ---------------- 审计日志 ----------------

@bp.get("/audit")
@admin_required
def audit_list():
    page, size = page_args()
    q = AuditLog.query
    if request.args.get("tenant_id", type=int):
        q = q.filter(AuditLog.tenant_id == request.args.get("tenant_id", type=int))
    if request.args.get("action"):
        q = q.filter(AuditLog.action == request.args.get("action"))
    if request.args.get("actor_id", type=int):
        q = q.filter(AuditLog.actor_id == request.args.get("actor_id", type=int))
    kw = (request.args.get("search") or "").strip()
    if kw:
        q = q.filter((AuditLog.actor_name.contains(kw)) | (AuditLog.detail.contains(kw)) |
                     (AuditLog.target_id.contains(kw)))
    total = q.count()
    rows = q.order_by(AuditLog.id.desc()).offset((page - 1) * size).limit(size).all()
    return ok({"total": total, "page": page, "page_size": size,
               "items": [r.to_dict() for r in rows]})



# ---------------- 渠道管理 ----------------

@bp.get("/channels")
@admin_required
def channels():
    rows = Channel.query.order_by(Channel.priority.asc(), Channel.id.asc()).all()
    bs = breaker.all_status()
    now = datetime.now().timestamp()
    out = []
    for c in rows:
        d = c.to_dict(secret=True)
        b = bs.get(str(c.id)) or {}
        open_until = b.get("open_until", 0)
        d["circuit_open"] = open_until > now
        d["circuit_left"] = max(0, int(open_until - now))
        d["recent_fails"] = b.get("fails", 0)
        d["last_err"] = b.get("last_err", "")
        out.append(d)
    return ok(out)


@bp.get("/channels/overview")
@admin_required
def channels_overview():
    """渠道状态总览:探活字段 + 24h 调用聚合 + 熔断态 + 最近事件。"""
    rows = Channel.query.order_by(Channel.priority.asc(), Channel.id.asc()).all()
    since = datetime.now() - timedelta(hours=24)
    usage = (db.session.query(UsageLog.channel_id, func.count(UsageLog.id),
                              func.coalesce(func.sum(UsageLog.quota), 0),
                              func.coalesce(func.sum(db.case((UsageLog.status == "ok", 1), else_=0)), 0))
             .filter(UsageLog.status != "held", UsageLog.created_at >= since)
             .group_by(UsageLog.channel_id).all())
    agg = {cid: {"requests": n, "quota": int(q), "ok": int(o)} for cid, n, q, o in usage}
    bs = breaker.all_status()
    now_ts = datetime.now().timestamp()
    events = {}
    for ev in ChannelEvent.query.order_by(ChannelEvent.id.desc()).limit(400).all():
        events.setdefault(ev.channel_id, []).append(ev.to_dict())
    items = []
    for c in rows:
        d = c.to_dict(secret=True)
        b = bs.get(str(c.id)) or {}
        open_until = b.get("open_until", 0)
        d["circuit_open"] = open_until > now_ts
        d["circuit_left"] = max(0, int(open_until - now_ts))
        d["recent_fails"] = b.get("fails", 0)
        d["last_err"] = b.get("last_err", "")
        a = agg.get(c.id, {"requests": 0, "quota": 0, "ok": 0})
        d["usage_24h"] = {"requests": a["requests"], "quota": a["quota"],
                          "quota_yuan": quota_to_yuan(a["quota"]),
                          "ok_rate": round(a["ok"] / a["requests"], 4) if a["requests"] else None}
        d["events"] = events.get(c.id, [])[:20]
        items.append(d)
    return ok({
        "items": items,
        "summary": {
            "total": len(items),
            "enabled": sum(1 for c in items if c["status"] == 1),
            "circuit_open": sum(1 for c in items if c["circuit_open"]),
            "auto_disabled": sum(1 for c in items if c["auto_disabled"] == 1),
            "untested": sum(1 for c in items if c["last_test_ok"] is None and c["type"] != "mock"),
        },
    })


def _clean_model_map(raw):
    """model_map 入参清洗:仅保留非空的 str→str 条目;非对象返回 None。"""
    if not isinstance(raw, dict):
        return None
    out = {}
    for k, v in raw.items():
        key, value = str(k).strip(), str(v).strip()
        if key and value:
            out[key] = value
    return out


@bp.post("/channels")
@admin_required
def channel_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return err("渠道名称不能为空")
    channel_type = data.get("type") or "openai"
    if channel_type not in ("openai", "mock"):
        return err("渠道类型不正确")
    base_url = (data.get("base_url") or "").strip()
    if channel_type == "openai":
        from services.network import validate_upstream_url
        try:
            base_url = validate_upstream_url(base_url)
        except ValueError as exc:
            return err(str(exc))
    raw_map = data.get("model_map")
    if raw_map and not isinstance(raw_map, dict):
        return err("模型映射必须是对象")
    try:
        priority = int(data.get("priority") or 0)
        weight = int(data.get("weight") or 1)
    except (TypeError, ValueError, OverflowError):
        return err("优先级和权重必须是整数")
    if not 1 <= weight <= 1000:
        return err("权重必须在 1 到 1000 之间")
    ch = Channel(name=name, type=channel_type, base_url=base_url,
                 api_key=(data.get("api_key") or "").strip(),
                 models=json.dumps(data.get("models") or ["*"], ensure_ascii=False),
                 model_map=json.dumps(_clean_model_map(raw_map) or {}, ensure_ascii=False),
                 priority=priority, weight=weight, status=1 if data.get("status", 1) else 0)
    db.session.add(ch)
    db.session.commit()
    audit.record("channel.create", target_type="channel", target_id=ch.id,
                 detail={"name": ch.name, "type": ch.type, "base_url": ch.base_url})
    return ok(ch.to_dict(secret=True))


@bp.put("/channels/<int:cid>")
@admin_required
def channel_update(cid):
    ch = db.session.get(Channel, cid)
    if not ch:
        return err("渠道不存在", 404)
    data = request.get_json(silent=True) or {}
    for f in ("name", "base_url"):
        if f in data:
            setattr(ch, f, (data[f] or "").strip())
    if "type" in data:
        ch.type = data["type"] or "openai"
    if ch.type not in ("openai", "mock"):
        return err("渠道类型不正确")
    if ch.type == "openai":
        from services.network import validate_upstream_url
        try:
            ch.base_url = validate_upstream_url(ch.base_url)
        except ValueError as exc:
            return err(str(exc))
    _k = data.get("api_key")
    if isinstance(_k, str) and _k.strip() and not _k.strip().endswith("..."):
        ch.api_key = _k.strip()
    if "models" in data:
        ch.models = json.dumps(data["models"] or ["*"], ensure_ascii=False)
    if "model_map" in data:
        raw_map = data.get("model_map")
        if raw_map and not isinstance(raw_map, dict):
            return err("模型映射必须是对象")
        ch.model_map = json.dumps(_clean_model_map(raw_map) or {}, ensure_ascii=False)
    try:
        if "priority" in data:
            ch.priority = int(data["priority"] or 0)
        if "weight" in data:
            ch.weight = int(data["weight"] or 1)
    except (TypeError, ValueError, OverflowError):
        return err("优先级和权重必须是整数")
    if not 1 <= ch.weight <= 1000:
        return err("权重必须在 1 到 1000 之间")
    if "status" in data:
        ch.status = 1 if data["status"] else 0
        if ch.status == 1:
            # 人工启用视为对自动禁用的裁决:清掉状态机计数,避免立刻被再次禁用
            ch.auto_disabled = 0
            ch.fail_streak = 0
            ch.recover_streak = 0
    db.session.commit()
    audit.record("channel.update", target_type="channel", target_id=ch.id,
                 detail={"name": ch.name, "status": ch.status, "fields": sorted(data.keys())})
    return ok(ch.to_dict(secret=True))


@bp.delete("/channels/<int:cid>")
@admin_required
def channel_delete(cid):
    ch = db.session.get(Channel, cid)
    if not ch:
        return err("渠道不存在", 404)
    channel_name = ch.name
    db.session.delete(ch)
    db.session.commit()
    audit.record("channel.delete", target_type="channel", target_id=cid,
                 detail={"name": channel_name})
    return ok()


@bp.post("/channels/<int:cid>/promote")
@admin_required
def channel_promote(cid):
    """设为主用:该渠道优先级置为全局最小,同模型流量优先走它。"""
    ch = db.session.get(Channel, cid)
    if not ch:
        return err("渠道不存在", 404)
    min_prio = db.session.query(db.func.min(Channel.priority)).scalar() or 0
    ch.priority = min_prio - 1
    db.session.commit()
    return ok({"priority": ch.priority})


# 模型 id → 市面常见显示名的品牌映射(自动美化上架显示名)
BRAND_MAP = {
    "deepseek": "DeepSeek", "glm": "GLM", "qwen": "Qwen", "gpt": "GPT",
    "o1": "o1", "o3": "o3", "o4": "o4", "claude": "Claude", "gemini": "Gemini",
    "kimi": "Kimi", "moonshot": "Moonshot", "minimax": "MiniMax", "ernie": "ERNIE",
    "hunyuan": "Hunyuan", "doubao": "Doubao", "llama": "Llama", "yi": "Yi",
    "baichuan": "Baichuan", "grok": "Grok", "mistral": "Mistral",
}


def auto_tags(model_id: str, m: dict) -> list:
    """根据上游能力字段与命名习惯自动生成中文标签。"""
    tags = []
    if m.get("supports_reasoning"):
        tags.append("推理")
    if m.get("supports_vision"):
        tags.append("多模态")
    if m.get("supports_tools"):
        tags.append("工具调用")
    ctx = m.get("context_length") or 0
    try:
        ctx = int(ctx)
    except (TypeError, ValueError):
        ctx = 0
    if ctx >= 900_000:
        tags.append("1M 上下文")
    elif ctx >= 240_000:
        tags.append("256K 上下文")
    elif ctx >= 120_000:
        tags.append("128K 上下文")
    low = model_id.lower()
    if "embed" in low:
        return ["向量"]
    # 命名启发只看型号段(跳过品牌段,避免 MiniMax 的 max、Codex 的 code 等误判)
    tail = "-".join(low.split("-")[1:])
    if any(k in tail for k in ("coder", "code", "coding")):
        tags.append("编码")
    if any(k in tail for k in ("flash", "turbo", "mini", "air", "lite")):
        tags.append("性价比")
    if any(k in tail for k in ("-pro", "pro-", "max", "ultra")):
        tags.append("旗舰")
    if "agent" in tail:
        tags.append("Agent")
    # 去重保序,最多 5 个
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:5]


def pretty_display_name(model_id: str) -> str:
    """glm-5.1 → GLM-5.1;deepseek-v4.1-flash → DeepSeek-V4.1-Flash;qwen3-coder-plus → Qwen3-Coder-Plus。

    规则:品牌映射表定品牌;版本段(v4.1/k2/m2)字母大写;纯字母段首字母大写;
    特例:OpenAI o 系后的 mini 保持小写(市面写法 o4-mini)。
    """
    parts = model_id.split("-")
    out = [BRAND_MAP.get(parts[0].lower(), parts[0].capitalize())]
    for prev, p in zip(out, parts[1:]):
        if p.isdigit() or ("." in p and p.replace(".", "").isdigit()):
            out.append(p)                                    # 纯数字/版本号 4.1 / 1017
        elif re.fullmatch(r"[a-z]\d+(?:\.\d+)?", p):
            out.append(p[0].upper() + p[1:])                 # v4.1→V4.1 / k2→K2 / m2→M2
        elif p.isalpha() and len(p) <= 4 and p.lower() == "mini" and prev.lower() in ("o1", "o3", "o4"):
            out.append("mini")                               # o4-mini 市面小写
        else:
            out.append(p.capitalize())                       # flash→Flash / pro→Pro / preview→Preview
    return "-".join(out)


@bp.post("/channels/import-model")
@admin_required
def channel_import_model():
    """把上游拉取到的模型一键上架到定价目录(名称+定价,立即可售)。"""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    inp = float(data.get("input_price") or 0)
    outp = float(data.get("output_price") or 0)
    cch = float(data.get("cache_input_price") or 0)
    vendor = (data.get("vendor") or "").strip()[:32] or "其他"
    if not name:
        return err("缺少模型名")
    if ModelItem.query.filter_by(name=name).first():
        return err("该模型已在目录中")
    if inp <= 0 or outp < 0:
        return err("请填写有效定价(输入价需大于 0)")
    if cch < 0 or cch > inp:
        return err("缓存命中价需介于 0 与输入价之间")
    tags = data.get("tags")
    if not isinstance(tags, list) or not tags:
        tags = ["对话"]
    m = ModelItem(name=name, display_name=pretty_display_name(name), vendor=vendor,
                  tags=json.dumps([str(t)[:12] for t in tags[:5]], ensure_ascii=False),
                  input_price=inp, output_price=outp, cache_input_price=cch, sort=99, status=1)
    db.session.add(m)
    db.session.commit()
    return ok(m.to_dict())


def _price_of(m):
    """解析上游价格字段,兼容多种命名(人民币/百万 tokens)。"""
    inp = m.get("input_price_per_million") or (m.get("pricing") or {}).get("prompt")
    outp = m.get("output_price_per_million") or (m.get("pricing") or {}).get("completion")
    cch = m.get("cache_read_price_per_million") or (m.get("pricing") or {}).get("cache_read")
    eff = m.get("effective_pricing") or {}
    if inp is None and eff.get("prompt") is not None:
        inp = eff["prompt"]
    if outp is None and eff.get("completion") is not None:
        outp = eff["completion"]
    if cch is None and eff.get("cache_read") is not None:
        cch = eff["cache_read"]

    def _f(v):
        try:
            return round(float(v), 4) if v is not None else None
        except (TypeError, ValueError):
            return None
    return _f(inp), _f(outp), _f(cch)


# DeepSeek 官方无价格接口,内置公开价目兜底(¥/1M)
UPSTREAM_STATIC_PRICES = {
    "api.deepseek.com": {
        "deepseek-flash": (2.0, 8.0), "deepseek-chat": (2.0, 8.0),
        "deepseek-v4-pro": (4.0, 16.0), "deepseek-reasoner": (4.0, 16.0)}}


def _fetch_upstream_catalog(base_url: str, api_key: str, exclude_channel_id=None) -> list:
    """拉取上游 /models 并归一化:价格兜底、目录状态、其他渠道重叠。返回条目列表。"""
    url = validate_upstream_url(base_url) + "/models"
    with http.get(url, headers={"Authorization": f"Bearer {api_key or ''}"},
                  timeout=(5, 15), allow_redirects=False) as resp:
        data = resp.json()
    static_map = UPSTREAM_STATIC_PRICES.get(base_url.split("//")[-1].split("/")[0], {})
    catalog = {m.name: m for m in ModelItem.query.all()}
    overlap = {}
    others = Channel.query.filter(Channel.status == 1)
    if exclude_channel_id:
        others = others.filter(Channel.id != exclude_channel_id)
    for other in others.all():
        for name in other.model_list():
            if name != "*":
                overlap.setdefault(name, []).append(other.name)
    items = []
    rows = [m for m in (data.get("data") or []) if m.get("id")]
    for m in sorted(rows, key=lambda x: x["id"]):
        n = m["id"]
        inp, outp, cch = _price_of(m)
        if inp is None and n in static_map:
            inp, outp = static_map[n]
        cat = catalog.get(n)
        items.append({"name": n, "in_catalog": bool(cat and cat.status == 1),
                      "catalog_price": [cat.input_price, cat.output_price, cat.cache_input_price or 0] if cat else None,
                      "upstream_input": inp, "upstream_output": outp, "upstream_cache": cch,
                      "upstream_tags": auto_tags(n, m),
                      "currency": "CNY",
                      "other_channels": overlap.get(n, [])})
    return items


@bp.get("/channels/<int:cid>/upstream-models")
@admin_required
def channel_upstream_models(cid):
    """拉取上游真实模型列表(OpenAI /models 标准),供渠道配置勾选。"""
    ch = db.session.get(Channel, cid)
    if not ch:
        return err("渠道不存在", 404)
    if ch.type == "mock":
        return ok({"models": ["*"], "note": "mock 渠道承接全部模型"})
    try:
        items = _fetch_upstream_catalog(ch.base_url, ch.api_key, exclude_channel_id=cid)
    except Exception:
        current_app.logger.exception("upstream models fetch failed")
        return err("上游模型列表拉取失败", 502)
    return ok({"models": items, "total": len(items)})


@bp.post("/channels/probe-models")
@admin_required
def channel_probe_models():
    """免建渠道直接拉取上游模型列表(新建渠道向导第 2 步)。"""
    data = request.get_json(silent=True) or {}
    try:
        base_url = validate_upstream_url((data.get("base_url") or "").strip())
    except ValueError as exc:
        return err(str(exc))
    try:
        items = _fetch_upstream_catalog(base_url, (data.get("api_key") or "").strip())
    except Exception:
        current_app.logger.exception("upstream models probe failed")
        return err("上游模型列表拉取失败,请检查地址与密钥", 502)
    return ok({"models": items, "total": len(items)})


@bp.post("/channels/<int:cid>/test")
@admin_required
def channel_test(cid):
    """渠道连通性测试:与定时探活同一逻辑,结果落库并参与自动禁用/恢复状态机。"""
    ch = db.session.get(Channel, cid)
    if not ch:
        return err("渠道不存在", 404)
    from services.probe import probe_channel
    result = probe_channel(ch)
    return ok({"ok": result["ok"], "latency_ms": result["latency_ms"], "model": result["model"],
               "error": result["error"], "status": ch.status, "auto_disabled": bool(ch.auto_disabled)})


@bp.post("/channels/<int:cid>/balance")
@admin_required
def channel_balance(cid):
    """查询上游账户余额(origin/user/balance 约定,如词元之河),结果落库供渠道页展示。"""
    ch = db.session.get(Channel, cid)
    if not ch:
        return err("渠道不存在", 404)
    if ch.type == "mock":
        return err("mock 渠道没有余额")
    if not ch.api_key:
        return err("该渠道未配置 API Key")
    from services.probe import fetch_balance
    try:
        info = fetch_balance(ch)
    except ValueError as exc:
        return err(str(exc), 502)
    ch.last_balance_at = datetime.now()
    ch.last_balance_info = json.dumps(info, ensure_ascii=False)
    db.session.commit()
    return ok(info)


# ---------------- 模型定价 ----------------

@bp.get("/models")
@admin_required
def models():
    rows = ModelItem.query.order_by(ModelItem.sort.asc(), ModelItem.id.asc()).all()
    return ok([m.to_dict() for m in rows])


@bp.post("/models")
@admin_required
def model_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return err("模型名不能为空")
    if ModelItem.query.filter_by(name=name).first():
        return err("模型已存在")
    try:
        prices = [float(data.get(field) or 0) for field in
                  ("input_price", "output_price", "cache_input_price", "official_input", "official_output")]
        sort = int(data.get("sort") or 0)
    except (TypeError, ValueError, OverflowError):
        return err("模型定价和排序必须是有效数字")
    if any(not math.isfinite(value) or value < 0 for value in prices):
        return err("模型定价必须是非负有限数字")
    m = ModelItem(name=name, display_name=data.get("display_name") or name,
                  vendor=data.get("vendor") or "其他",
                  tags=json.dumps(data.get("tags") or [], ensure_ascii=False),
                  input_price=prices[0], output_price=prices[1], cache_input_price=prices[2],
                  official_input=prices[3], official_output=prices[4],
                  description=data.get("description") or "",
                  status=1 if data.get("status", 1) else 0, sort=sort)
    db.session.add(m)
    db.session.commit()
    audit.record("model.create", target_type="model", target_id=m.id,
                 detail={"name": m.name, "display_name": m.display_name})
    return ok(m.to_dict())


@bp.put("/models/<int:mid>")
@admin_required
def model_update(mid):
    m = db.session.get(ModelItem, mid)
    if not m:
        return err("模型不存在", 404)
    data = request.get_json(silent=True) or {}
    for f in ("display_name", "vendor", "description"):
        if f in data:
            setattr(m, f, data[f])
    if "tags" in data:
        m.tags = json.dumps(data["tags"] or [], ensure_ascii=False)
    try:
        for field in ("input_price", "output_price", "cache_input_price", "official_input", "official_output"):
            if field in data:
                value = float(data[field] or 0)
                if not math.isfinite(value) or value < 0:
                    return err("模型定价必须是非负有限数字")
                setattr(m, field, value)
        if "sort" in data:
            m.sort = int(data["sort"] or 0)
    except (TypeError, ValueError, OverflowError):
        return err("模型定价和排序必须是有效数字")
    if "status" in data:
        m.status = 1 if data["status"] else 0
    db.session.commit()
    audit.record("model.update", target_type="model", target_id=m.id,
                 detail={"name": m.name, "status": m.status, "fields": sorted(data.keys())})
    return ok(m.to_dict())


@bp.delete("/models/<int:mid>")
@admin_required
def model_delete(mid):
    m = db.session.get(ModelItem, mid)
    if not m:
        return err("模型不存在", 404)
    model_name = m.name
    db.session.delete(m)
    db.session.commit()
    audit.record("model.delete", target_type="model", target_id=mid,
                 detail={"name": model_name})
    return ok()


@bp.post("/models/reorder")
@admin_required
def models_reorder():
    """按提交的 id 顺序整体重排;首页价格表/模型页/网关 /v1/models 均按此顺序展示。"""
    data = request.get_json(silent=True) or {}
    ids = data.get("ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        return err("参数必须是模型 id 数组")
    if len(set(ids)) != len(ids):
        return err("id 不能重复")
    existing = {i for (i,) in ModelItem.query.with_entities(ModelItem.id).all()}
    missing = [i for i in ids if i not in existing]
    if missing:
        return err(f"模型不存在: {missing[:5]}")
    for index, mid in enumerate(ids):
        db.session.query(ModelItem).filter(ModelItem.id == mid)\
            .update({"sort": index}, synchronize_session=False)
    db.session.commit()
    return ok({"count": len(ids)})


# ---------------- 订单 ----------------

@bp.get("/orders")
@admin_required
def orders():
    if not FEATURE_PAYMENTS:
        return err("私有化部署未启用在线充值", 403)
    page, size = page_args()
    q = TopupOrder.query
    status = request.args.get("status")
    if status:
        q = q.filter(TopupOrder.status == status)
    total = q.count()
    rows = q.order_by(TopupOrder.id.desc()).offset((page - 1) * size).limit(size).all()
    return ok({"total": total, "page": page, "page_size": size,
               "items": [o.to_dict() for o in rows]})


@bp.post("/orders/<order_no>/refund")
@admin_required
def order_refund(order_no):
    if not FEATURE_PAYMENTS:
        return err("私有化部署未启用在线充值", 403)
    mirror = TopupOrder.query.filter_by(order_no=order_no).first()
    if not mirror:
        return err("订单不存在", 404)
    if mirror.status != "paid":
        return err("订单状态不可退款")
    used = (db.session.query(db.func.coalesce(db.func.sum(InvoiceItem.amount), 0))
            .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .filter(InvoiceItem.order_no == order_no, InvoiceItem.active == 1,
                    Invoice.status.in_((0, 1))).scalar() or 0)
    if used > 0:
        return err("该订单已申请开票(¥%.2f),开票后不可退款。如需退款请先在发票管理中拒绝该申请。" % (used / 100))
    if (mirror.kind or "credits") == "resource_pack":
        instance = UserResourcePack.query.filter_by(order_no=order_no).first()
        if instance is not None and (instance.used_tokens or 0) > 0:
            return err("资源包 tokens 已有消耗,无法退款")
    else:
        user = db.session.get(User, mirror.user_id)
        if not user or (user.quota or 0) < mirror.quota:
            return err("充值额度已消费,无法退款")
    from services.payments import build_payment_service
    method = mirror.pay_method if mirror.pay_method in ("alipay", "wechat", "sandbox") else "alipay"
    try:
        svc = build_payment_service(method)
        if not svc:
            return err("支付组件未就绪", 503)
        svc.refund_order(order_no, reason="管理员退款")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("充值订单退款失败: %s", order_no)
        return err("退款失败,请稍后重试")
    return ok()


# ---------------- 发票管理 ----------------

@bp.get("/invoices")
@admin_required
def admin_invoices():
    if not FEATURE_INVOICE:
        return err("私有化部署未启用发票管理", 403)
    page, size = page_args()
    q = Invoice.query
    status = request.args.get("status", type=int)
    if status is not None:
        q = q.filter(Invoice.status == status)
    total = q.count()
    rows = q.order_by(Invoice.id.desc()).offset((page - 1) * size).limit(size).all()
    items = []
    for i in rows:
        d = i.to_dict()
        u = db.session.get(User, i.user_id)
        d["username"] = u.username if u else "?"
        d["uid"] = u.uid if u else ""
        items.append(d)
    return ok({"total": total, "page": page, "page_size": size, "items": items})


@bp.put("/invoices/<int:iid>/issue")
@admin_required
def admin_invoice_issue(iid):
    """标记已开具(填写发票号)。"""
    if not FEATURE_INVOICE:
        return err("私有化部署未启用发票管理", 403)
    inv = db.session.get(Invoice, iid)
    if not inv:
        return err("记录不存在", 404)
    if inv.status == 1:
        return err("已开具过")
    data = request.get_json(silent=True) or {}
    no = (data.get("invoice_no") or "").strip()
    if not no:
        return err("请填写发票号码")
    inv.status = 1
    inv.invoice_no = no[:64]
    inv.issued_at = datetime.now()
    db.session.commit()
    return ok()


@bp.put("/invoices/<int:iid>/reject")
@admin_required
def admin_invoice_reject(iid):
    """拒绝开票(额度随即释放,用户可重新申请)。已开具的不可拒绝,需走红冲。"""
    if not FEATURE_INVOICE:
        return err("私有化部署未启用发票管理", 403)
    inv = db.session.get(Invoice, iid)
    if not inv:
        return err("记录不存在", 404)
    if inv.status == 1:
        return err("已开具的发票不可拒绝,请走红冲流程")
    data = request.get_json(silent=True) or {}
    inv.status = 2
    inv.reject_reason = (data.get("reason") or "信息有误")[:200]
    (db.session.query(InvoiceItem)
     .filter(InvoiceItem.invoice_id == inv.id, InvoiceItem.active == 1)
     .update({"active": 0}, synchronize_session=False))
    db.session.commit()
    return ok()


# ---------------- 邀请审计 ----------------


# ---------------- 兑换码 ----------------

@bp.get("/codes")
@admin_required
def codes():
    if not FEATURE_REDEEM:
        return err("私有化部署未启用兑换码", 403)
    page, size = page_args(20)
    q = RedemptionCode.query
    batch = request.args.get("batch")
    if batch:
        q = q.filter(RedemptionCode.batch == batch)
    total = q.count()
    rows = q.order_by(RedemptionCode.id.desc()).offset((page - 1) * size).limit(size).all()
    return ok({"total": total, "page": page, "page_size": size,
               "items": [c.to_dict() for c in rows]})


@bp.post("/codes/generate")
@admin_required
def codes_generate():
    if not FEATURE_REDEEM:
        return err("私有化部署未启用兑换码", 403)
    data = request.get_json(silent=True) or {}
    try:
        count = min(500, max(1, int(data.get("count") or 10)))
        yuan = float(data.get("yuan") or 1)
    except (TypeError, ValueError, OverflowError):
        return err("兑换码数量和金额必须是有效数字")
    if not math.isfinite(yuan) or yuan <= 0:
        return err("兑换金额必须大于 0")
    batch = (data.get("batch") or datetime.now().strftime("%Y%m%d%H%M%S"))[:32]
    made = []
    for _ in range(count):
        code = "61-" + secrets.token_hex(4).upper()
        while RedemptionCode.query.filter_by(code=code).first():
            code = "61-" + secrets.token_hex(4).upper()
        db.session.add(RedemptionCode(code=code, quota=yuan_to_quota(yuan), batch=batch))
        made.append(code)
    db.session.commit()
    return ok({"batch": batch, "count": count, "yuan": yuan, "codes": made})


# ---------------- 用量日志 ----------------

@bp.get("/logs")
@admin_required
def logs():
    page, size = page_args()
    conds = []
    model = request.args.get("model")
    if model:
        conds.append(UsageLog.model == model)
    uid = request.args.get("user_id", type=int)
    if uid:
        conds.append(UsageLog.user_id == uid)
    tid = request.args.get("tenant_id", type=int)
    if tid:
        conds.append(UsageLog.tenant_id == tid)
    total = UsageLog.query.filter(*conds).count()
    agg = (db.session.query(func.count(UsageLog.id),
                            func.coalesce(func.sum(UsageLog.prompt_tokens), 0),
                            func.coalesce(func.sum(UsageLog.completion_tokens), 0),
                            func.coalesce(func.sum(UsageLog.quota), 0))
           .filter(*conds).first())
    rows = (UsageLog.query.filter(*conds)
            .order_by(UsageLog.id.desc()).offset((page - 1) * size).limit(size).all())
    names = {k.id: k.name for k in ApiKey.query.all()}
    chans = {c.id: c.name for c in Channel.query.all()}
    tenants = {t.id: t.name for t in Tenant.query.all()}
    items = []
    for r in rows:
        d = r.to_dict()
        d["key_display"] = d.get("key_name") or (names.get(r.key_id, "#" + str(r.key_id)) if r.key_id else "-")
        d["channel_name"] = chans.get(r.channel_id, "#" + str(r.channel_id) if r.channel_id else "-")
        d["tenant_name"] = tenants.get(r.tenant_id, "-")
        items.append(d)
    by_channel = (db.session.query(UsageLog.channel_id, func.count(UsageLog.id),
                                    func.coalesce(func.sum(UsageLog.quota), 0))
                  .filter(*conds).group_by(UsageLog.channel_id)
                  .order_by(func.sum(UsageLog.quota).desc()).all())
    return ok({"total": total, "page": page, "page_size": size, "items": items,
               "summary": {"requests": agg[0], "prompt_tokens": int(agg[1]),
                           "completion_tokens": int(agg[2]), "quota": int(agg[3]),
                           "quota_yuan": quota_to_yuan(int(agg[3]))},
               "by_channel": [{"channel": chans.get(cid, "#" + str(cid) if cid else "-"),
                               "requests": c, "quota": int(q), "quota_yuan": quota_to_yuan(int(q))}
                              for cid, c, q in by_channel]})


# ---------------- 邀请审计 ----------------

@bp.get("/invites")
@admin_required
def invites():
    if not FEATURE_INVITE:
        return err("私有化部署未启用邀请返佣", 403)
    page, size = page_args()
    q = InviteReward.query
    status = request.args.get("status", type=int)
    if status is not None:
        q = q.filter(InviteReward.status == status)
    total = q.count()
    rows = q.order_by(InviteReward.id.desc()).offset((page - 1) * size).limit(size).all()
    items = []
    for r in rows:
        f_u = db.session.get(User, r.from_uid)
        t_u = db.session.get(User, r.to_uid)
        items.append({"id": r.id,
                      "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else None,
                      "from_uid": r.from_uid, "from_name": (f_u.username if f_u else "?"),
                      "from_uid_code": (f_u.uid if f_u else ""),
                      "to_uid": r.to_uid, "to_name": (t_u.username if t_u else "?"),
                      "to_uid_code": (t_u.uid if t_u else ""),
                      "quota_yuan": (r.quota or 0) / 500000, "status": r.status,
                      "reason": r.reason,
                      "paid_at": r.paid_at.strftime("%Y-%m-%d %H:%M") if r.paid_at else None})
    return ok({"total": total, "page": page, "page_size": size, "items": items})


@bp.put("/invites/<int:rid>/grant")
@admin_required
def invite_grant(rid):
    """人工发放;奖励状态条件和余额加法在同一事务中完成。"""
    if not FEATURE_INVITE:
        return err("私有化部署未启用邀请返佣", 403)
    r = db.session.get(InviteReward, rid)
    if not r:
        return err("记录不存在", 404)
    reason = ((r.reason or "") + " [人工发放]")[:120]
    changed = (db.session.query(InviteReward)
               .filter(InviteReward.id == rid, InviteReward.status != 1)
               .update({"status": 1, "paid_at": datetime.now(), "reason": reason},
                       synchronize_session=False))
    if not changed:
        db.session.rollback()
        return err("该奖励已发放")
    credited = (db.session.query(User).filter(User.id == r.from_uid)
                .update({"quota": func.coalesce(User.quota, 0) + (r.quota or 0)},
                        synchronize_session=False))
    if credited != 1:
        db.session.rollback()
        return err("邀请人不存在", 404)
    db.session.commit()
    return ok()


# ---------------- 资源包 ----------------

PACK_STATE_COND = {
    # 动态状态的 SQL 表达(state 与 UserResourcePack.state 属性保持一致)
    "active": (UserResourcePack.status == 1,
               UserResourcePack.total_tokens > func.coalesce(UserResourcePack.used_tokens, 0),
               (UserResourcePack.expires_at.is_(None)) | (UserResourcePack.expires_at > func.now())),
    "expired": (UserResourcePack.expires_at.isnot(None),
                UserResourcePack.expires_at <= func.now()),
    "exhausted": (UserResourcePack.status == 1,
                  UserResourcePack.total_tokens > 0,
                  func.coalesce(UserResourcePack.used_tokens, 0) >= UserResourcePack.total_tokens,
                  (UserResourcePack.expires_at.is_(None)) | (UserResourcePack.expires_at > func.now())),
    "disabled": (UserResourcePack.status == 0,),
}


@bp.get("/resource-packs")
@admin_required
def resource_packs():
    """资源包商品定义 + 发放统计。"""
    rows = ResourcePackDef.query.order_by(ResourcePackDef.sort.asc(), ResourcePackDef.id.asc()).all()
    stats = {r[0]: r for r in db.session.query(
        UserResourcePack.pack_id,
        func.count(UserResourcePack.id),
        func.coalesce(func.sum(UserResourcePack.total_tokens), 0),
        func.coalesce(func.sum(UserResourcePack.used_tokens), 0))
        .group_by(UserResourcePack.pack_id).all()}
    active = dict(db.session.query(UserResourcePack.pack_id, func.count(UserResourcePack.id))
                  .filter(UserResourcePack.status == 1).group_by(UserResourcePack.pack_id).all())
    return ok([dict(d.to_dict(),
                    granted_count=stats.get(d.id, (0, 0, 0, 0))[1],
                    active_count=active.get(d.id, 0),
                    granted_tokens=int(stats.get(d.id, (0, 0, 0, 0))[2]),
                    used_tokens=int(stats.get(d.id, (0, 0, 0, 0))[3]))
               for d in rows])


@bp.post("/resource-packs")
@admin_required
def resource_pack_create():
    data = request.get_json(silent=True) or {}
    err_msg = _validate_pack_payload(data)
    if err_msg:
        return err(err_msg)
    price_yuan = _pack_price_yuan(data)
    if price_yuan is None:
        return err("售价无效")
    model = str(data["model"]).strip()
    if not ModelItem.query.filter_by(name=model).first():
        return err("模型目录中不存在该模型,请先在模型定价中上架")
    d = ResourcePackDef(
        name=str(data["name"]).strip()[:64], model=model,
        tokens=int(round(float(data["tokens_wan"]) * 10_000)),
        price=round(price_yuan * 100),
        valid_days=max(0, int(data.get("valid_days", 365))),
        description=(data.get("description") or "").strip()[:200],
        status=1 if data.get("status", 1) else 0,
        sort=int(data.get("sort") or 0))
    db.session.add(d)
    db.session.commit()
    audit.record("pack.create", target_type="resource_pack", target_id=d.id,
                 detail={"name": d.name, "model": d.model, "tokens": d.tokens,
                         "price": d.price, "valid_days": d.valid_days})
    return ok(d.to_dict())


def _pack_price_yuan(data):
    """售价(元)选填:0/空 = 仅赠送;返回 None 表示非法。"""
    raw = data.get("price_yuan")
    if raw in (None, "", 0, "0"):
        return 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or value < 0 or value > 100_000:
        return None
    return value


def _validate_pack_payload(data, partial=False):
    from services.resourcepack import validate_pack_fields
    return validate_pack_fields(data, partial=partial)


@bp.put("/resource-packs/<int:pid>")
@admin_required
def resource_pack_update(pid):
    d = db.session.get(ResourcePackDef, pid)
    if not d:
        return err("资源包不存在", 404)
    data = request.get_json(silent=True) or {}
    err_msg = _validate_pack_payload(data, partial=True)
    if err_msg:
        return err(err_msg)
    if "name" in data:
        d.name = str(data["name"]).strip()[:64]
    if "model" in data:
        model = str(data["model"]).strip()
        if not ModelItem.query.filter_by(name=model).first():
            return err("模型目录中不存在该模型,请先在模型定价中上架")
        d.model = model
    if "tokens_wan" in data:
        d.tokens = int(round(float(data["tokens_wan"]) * 10_000))
    if "price_yuan" in data:
        price_yuan = _pack_price_yuan(data)
        if price_yuan is None:
            return err("售价无效")
        d.price = round(price_yuan * 100)
    if "valid_days" in data:
        d.valid_days = max(0, int(data["valid_days"]))
    if "description" in data:
        d.description = (data["description"] or "").strip()[:200]
    if "status" in data:
        d.status = 1 if data["status"] else 0
    if "sort" in data:
        d.sort = int(data["sort"] or 0)
    db.session.commit()
    audit.record("pack.update", target_type="resource_pack", target_id=d.id,
                 detail={"name": d.name, "status": d.status, "fields": sorted(data.keys())})
    return ok(d.to_dict())


@bp.delete("/resource-packs/<int:pid>")
@admin_required
def resource_pack_delete(pid):
    d = db.session.get(ResourcePackDef, pid)
    if not d:
        return err("资源包不存在", 404)
    if UserResourcePack.query.filter_by(pack_id=pid).count():
        return err("已有用户持有该资源包,请下架而非删除")
    name = d.name
    db.session.delete(d)
    db.session.commit()
    audit.record("pack.delete", target_type="resource_pack", target_id=pid, detail={"name": name})
    return ok()


@bp.get("/resource-pack-grants")
@admin_required
def resource_pack_grants():
    """用户持有明细:资源包管理主列表(现有/到期时间/使用量)。"""
    page, size = page_args()
    conds = []
    if request.args.get("user_id", type=int):
        conds.append(UserResourcePack.user_id == request.args.get("user_id", type=int))
    if request.args.get("pack_id", type=int):
        conds.append(UserResourcePack.pack_id == request.args.get("pack_id", type=int))
    state = request.args.get("state")
    if state in PACK_STATE_COND:
        conds.extend(PACK_STATE_COND[state])
    kw = (request.args.get("search") or "").strip()
    user_ids = None
    if kw:
        matched = User.query.filter((User.username.contains(kw)) | (User.uid.contains(kw))).all()
        user_ids = [u.id for u in matched] or [-1]
        conds.append(UserResourcePack.user_id.in_(user_ids))
    total = UserResourcePack.query.filter(*conds).count()
    rows = (UserResourcePack.query.filter(*conds)
            .order_by(UserResourcePack.id.desc()).offset((page - 1) * size).limit(size).all())
    users = {u.id: u for u in User.query.filter(
        User.id.in_({r.user_id for r in rows})).all()} if rows else {}
    items = []
    for r in rows:
        u = users.get(r.user_id)
        items.append(r.to_dict(username=u.username if u else f"#{r.user_id}")
                     | {"user_uid": u.uid if u else ""})
    return ok({"total": total, "page": page, "page_size": size, "items": items})


@bp.post("/resource-packs/<int:pid>/grant")
@admin_required
def resource_pack_grant(pid):
    """手动发放资源包给指定用户(可覆盖有效期天数)。"""
    d = db.session.get(ResourcePackDef, pid)
    if not d:
        return err("资源包不存在", 404)
    data = request.get_json(silent=True) or {}
    # 定位用户:user_id > username/uid(先按用户名精确匹配,纯数字再按 UID 兜底)
    user = db.session.get(User, data.get("user_id")) if data.get("user_id") else None
    if user is None:
        name_or_uid = (data.get("username") or "").strip()
        if name_or_uid:
            user = User.query.filter_by(username=name_or_uid).first()
            if user is None and name_or_uid.isdigit():
                user = User.query.filter_by(uid=name_or_uid).first()
    if not user:
        return err("用户不存在(检查用户名或 UID)", 404)
    valid_days = d.valid_days
    if data.get("valid_days") not in (None, ""):
        try:
            valid_days = max(0, int(data["valid_days"]))
        except (TypeError, ValueError, OverflowError):
            return err("有效期必须是天数")
    from services.resourcepack import grant_pack_to_user
    instance = grant_pack_to_user(user, d, granted_type="admin_grant", valid_days=valid_days)
    db.session.commit()
    audit.record("pack.grant", target_type="resource_pack", target_id=pid,
                 detail={"user_id": user.id, "username": user.username, "uid": user.uid,
                         "valid_days": valid_days})
    return ok(instance.to_dict(username=user.username))


@bp.put("/resource-pack-grants/<int:gid>/disable")
@admin_required
def resource_pack_disable(gid):
    """作废用户持有的资源包;已有调用预留结算/释放不受影响(按 id 回账)。"""
    instance = db.session.get(UserResourcePack, gid)
    if not instance:
        return err("记录不存在", 404)
    instance.status = 0
    db.session.commit()
    audit.record("pack.disable", target_type="resource_pack_instance", target_id=gid,
                 detail={"user_id": instance.user_id, "pack_id": instance.pack_id})
    return ok()


# ---------------- 工单支持 ----------------

@bp.get("/tickets")
@admin_required
def admin_tickets():
    """全部工单列表(可按状态筛选,带用户名与最后消息预览)。"""
    page, size = page_args()
    status = request.args.get("status")
    q = Ticket.query
    if status in ("open", "answered", "closed"):
        q = q.filter_by(status=status)
    total = q.count()
    rows = q.order_by(Ticket.updated_at.desc()).offset((page - 1) * size).limit(size).all()
    users = {u.id: u for u in User.query.filter(User.id.in_({t.user_id for t in rows})).all()} if rows else {}
    items = []
    for t in rows:
        u = users.get(t.user_id)
        d = t.to_dict(username=u.username if u else f"#{t.user_id}", preview="")
        d["preview"] = _admin_ticket_preview(t.id)
        items.append(d)
    return ok({"total": total, "page": page, "page_size": size, "items": items})


def _admin_ticket_preview(ticket_id):
    last = (TicketMessage.query.filter_by(ticket_id=ticket_id)
            .order_by(TicketMessage.id.desc()).first())
    if not last:
        return ""
    tag = "[用户] " if last.sender_role == "user" else "[我们] "
    return tag + (last.content or "")[:60]


@bp.get("/tickets/<int:tid>")
@admin_required
def admin_ticket_detail(tid):
    t = db.session.get(Ticket, tid)
    if not t:
        return err("工单不存在", 404)
    u = db.session.get(User, t.user_id)
    msgs = (TicketMessage.query.filter_by(ticket_id=tid)
            .order_by(TicketMessage.id.asc()).all())
    return ok(dict(t.to_dict(username=u.username if u else f"#{t.user_id}"),
                   messages=[m.to_dict() for m in msgs]))


@bp.post("/tickets/<int:tid>/reply")
@admin_required
def admin_ticket_reply(tid):
    t = db.session.get(Ticket, tid)
    if not t:
        return err("工单不存在", 404)
    if t.status == "closed":
        return err("工单已关闭,请先重新开启")
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return err("回复内容不能为空")
    msg = TicketMessage(ticket_id=tid, sender_role="admin",
                        sender_id=g.user.id, sender_name=g.user.username or "官方客服",
                        content=content[:5000])
    att = data.get("attachment") or {}
    if att.get("key"):
        db.session.add(msg)
        db.session.flush()  # 正式文件按消息 ID 命名,同工单多图不冲突
        try:
            path, ext, size = ticketfile.promote(str(att.get("key")), g.user.id, msg.id)
        except ValueError as exc:
            db.session.rollback()
            return err(str(exc))
        msg.file_key = "m{}.{}".format(msg.id, ext.lstrip("."))
        msg.file_name = ticketfile.valid_image_name(att.get("name") or "")
        msg.file_size = size
    else:
        db.session.add(msg)
    t.status = "answered"
    t.updated_at = datetime.now()
    db.session.commit()
    audit.record("ticket.reply", target_type="ticket", target_id=tid,
                 detail={"user_id": t.user_id})
    return ok(t.to_dict())


@bp.post("/tickets/<int:tid>/close")
@admin_required
def admin_ticket_close(tid):
    t = db.session.get(Ticket, tid)
    if not t:
        return err("工单不存在", 404)
    t.status = "closed"
    t.updated_at = datetime.now()
    db.session.commit()
    audit.record("ticket.close", target_type="ticket", target_id=tid)
    return ok(t.to_dict())


@bp.post("/tickets/<int:tid>/reopen")
@admin_required
def admin_ticket_reopen(tid):
    t = db.session.get(Ticket, tid)
    if not t:
        return err("工单不存在", 404)
    t.status = "open"
    t.updated_at = datetime.now()
    db.session.commit()
    audit.record("ticket.reopen", target_type="ticket", target_id=tid)
    return ok(t.to_dict())


# ---------------- 发票文件上传/下载 ----------------

INVOICE_FILE_MAX_BYTES = 10 * 1024 * 1024  # 10MB


def _invoice_dir():
    from config import BASE_DIR
    d = BASE_DIR / "data" / "invoices"
    d.mkdir(parents=True, exist_ok=True)
    return d


@bp.post("/invoices/<int:iid>/file")
@admin_required
def admin_upload_invoice_file(iid):
    """上传发票 PDF 文件(存服务器本机,按发票 ID 命名)。"""
    inv = db.session.get(Invoice, iid)
    if not inv:
        return err("发票申请不存在", 404)
    if inv.status == 2:
        return err("已拒绝的发票申请不能上传文件")
    f = request.files.get("file")
    if f is None or not f.filename:
        return err("请选择 PDF 文件")
    if not f.filename.lower().endswith(".pdf"):
        return err("仅支持 PDF 文件")
    data = f.read()
    if len(data) > INVOICE_FILE_MAX_BYTES:
        return err("文件超过 10MB 限制")
    if not data.startswith(b"%PDF-"):
        return err("文件内容不是有效的 PDF")
    d = _invoice_dir()
    path = d / (str(iid) + ".pdf")
    path.write_bytes(data)
    inv.file_name = f.filename[:255]
    inv.file_size = len(data)
    inv.file_uploaded_at = datetime.now()
    db.session.commit()
    audit.record("invoice.file_upload", target_type="invoice", target_id=iid,
                 detail={"file": inv.file_name[:80], "size": len(data),
                         "user_id": inv.user_id}, actor=g.user)
    return ok(inv.to_dict())


@bp.get("/invoices/<int:iid>/file")
@admin_required
def admin_download_invoice_file(iid):
    inv = db.session.get(Invoice, iid)
    if not inv or not inv.file_name:
        return err("发票文件尚未上传", 404)
    path = _invoice_dir() / (str(iid) + ".pdf")
    if not path.exists():
        return err("发票文件丢失,请联系管理员", 404)
    safe_name = (inv.invoice_no or ("invoice-" + str(iid))) + ".pdf"
    audit.record("invoice.file_download", target_type="invoice", target_id=iid,
                 detail={"file": inv.file_name[:80], "by": "admin"},
                 actor=g.user)
    return send_file(path, as_attachment=True, download_name=safe_name,
                     mimetype="application/pdf")


# ---------------- 站内消息 ----------------

@bp.get("/notices")
@admin_required
def admin_notices():
    """站内消息列表(含每条已读人数)。"""
    page, size = page_args()
    q = Notice.query
    total = q.count()
    rows = q.order_by(Notice.id.desc()).offset((page - 1) * size).limit(size).all()
    read_counts = dict(db.session.query(NoticeRead.notice_id, func.count(NoticeRead.id))
                       .group_by(NoticeRead.notice_id).all()) if rows else {}
    items = []
    for n in rows:
        d = n.to_dict()
        d["read_count"] = read_counts.get(n.id, 0)
        d["body_preview"] = (n.body or "")[:80]
        items.append(d)
    return ok({"total": total, "page": page, "page_size": size, "items": items})


@bp.post("/notices")
@admin_required
def admin_notice_create():
    """发布站内消息(面向全体用户)。"""
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    body = (data.get("body") or "").strip()
    if not title:
        return err("标题不能为空")
    if not body:
        return err("正文不能为空")
    n = Notice(title=title[:128], body=body[:20000], status=1)
    db.session.add(n)
    db.session.commit()
    audit.record("notice.create", target_type="notice", target_id=n.id,
                 detail={"title": title[:64]})
    return ok(n.to_dict())


@bp.put("/notices/<int:nid>")
@admin_required
def admin_notice_update(nid):
    n = db.session.get(Notice, nid)
    if not n:
        return err("消息不存在", 404)
    data = request.get_json(silent=True) or {}
    if "title" in data:
        if not (data["title"] or "").strip():
            return err("标题不能为空")
        n.title = data["title"].strip()[:128]
    if "body" in data:
        if not (data["body"] or "").strip():
            return err("正文不能为空")
        n.body = data["body"].strip()[:20000]
    if "status" in data:
        n.status = 1 if data["status"] else 0
    db.session.commit()
    audit.record("notice.update", target_type="notice", target_id=n.id,
                 detail={"title": n.title[:64], "status": n.status, "fields": sorted(data.keys())})
    return ok(n.to_dict())


@bp.delete("/notices/<int:nid>")
@admin_required
def admin_notice_delete(nid):
    n = db.session.get(Notice, nid)
    if not n:
        return err("消息不存在", 404)
    title = n.title
    NoticeRead.query.filter_by(notice_id=nid).delete(synchronize_session=False)
    db.session.delete(n)
    db.session.commit()
    audit.record("notice.delete", target_type="notice", target_id=nid, detail={"title": title[:64]})
    return ok()


# ---------------- 站点设置 ----------------

SETTING_KEYS = ("site_name", "announcement", "announcement_link", "announcement_enabled",
                "discount_note", "hero_stats", "custom_topup_enabled",
                "custom_topup_min_yuan", "custom_topup_max_yuan",
                "topup_packages", "invite_bonus_cny", "invite_min_topup_yuan",
                "new_user_bonus_cny", "register_gift_pack_id", "kefu_qr_url",
                "notify_enabled", "notify_webhook_type", "notify_webhook_url",
                "probe_disable_threshold")
NOTIFY_TYPES = ("wecom", "dingtalk", "feishu")


@bp.get("/settings")
@admin_required
def settings_get():
    return ok({k: Setting.get(k) for k in SETTING_KEYS})


@bp.put("/settings")
@admin_required
def settings_put():
    data = request.get_json(silent=True) or {}
    if not FEATURE_PAYMENTS:
        for key in ("topup_packages", "custom_topup_enabled", "custom_topup_min_yuan",
                    "custom_topup_max_yuan"):
            data.pop(key, None)
    if not FEATURE_INVITE:
        data.pop("invite_bonus_cny", None)
        data.pop("invite_min_topup_yuan", None)
    if "announcement_link" in data:
        link = str(data["announcement_link"] or "").strip()
        if link and not link.startswith(("http://", "https://")):
            return err("公告链接必须以 http(s):// 开头")
        data["announcement_link"] = link
    if "announcement_enabled" in data:
        data["announcement_enabled"] = bool(data["announcement_enabled"])
    if "custom_topup_enabled" in data:
        data["custom_topup_enabled"] = bool(data["custom_topup_enabled"])
    if "notify_enabled" in data:
        data["notify_enabled"] = bool(data["notify_enabled"])
    if "notify_webhook_type" in data:
        data["notify_webhook_type"] = data["notify_webhook_type"] or "wecom"
        if data["notify_webhook_type"] not in NOTIFY_TYPES:
            return err("通知类型不正确")
    if "notify_webhook_url" in data:
        url = str(data["notify_webhook_url"] or "").strip()
        if url and not url.startswith(("http://", "https://")):
            return err("webhook 地址必须以 http(s):// 开头")
        data["notify_webhook_url"] = url
    if "probe_disable_threshold" in data:
        try:
            data["probe_disable_threshold"] = min(10, max(1, int(data["probe_disable_threshold"] or 3)))
        except (TypeError, ValueError, OverflowError):
            return err("禁用阈值必须是 1 到 10 的整数")
    if "register_gift_pack_id" in data:
        gift_id = data["register_gift_pack_id"]
        if gift_id in ("", None, False, 0, "0"):
            data["register_gift_pack_id"] = 0
        else:
            try:
                gift_id = int(gift_id)
            except (TypeError, ValueError):
                return err("注册赠送资源包无效")
            if not db.session.get(ResourcePackDef, gift_id):
                return err("注册赠送的资源包不存在")
            data["register_gift_pack_id"] = gift_id
    try:
        if "topup_packages" in data:
            from services.payments import validate_packages
            validate_packages(data["topup_packages"])
        if "invite_min_topup_yuan" in data:
            threshold = float(data["invite_min_topup_yuan"])
            if not math.isfinite(threshold) or threshold < 0:
                raise ValueError("邀请门槛无效")
        for key in ("custom_topup_min_yuan", "custom_topup_max_yuan"):
            if key in data:
                value = float(data[key])
                if not math.isfinite(value) or value <= 0:
                    raise ValueError("自定义充值金额范围无效")
    except (TypeError, ValueError, OverflowError):
        return err("站点设置数值或套餐配置无效", 400)
    min_yuan = float(data.get("custom_topup_min_yuan",
                              Setting.get("custom_topup_min_yuan", 1)))
    max_yuan = float(data.get("custom_topup_max_yuan",
                              Setting.get("custom_topup_max_yuan", 5000)))
    if min_yuan > max_yuan:
        return err("自定义充值最低金额不能高于最高金额")
    changed = []
    for k, v in data.items():
        if k in SETTING_KEYS:
            Setting.put(k, v)
            changed.append(k)
    if any(k in changed for k in ("announcement", "announcement_link", "announcement_enabled")):
        # 版本号变化后,用户端已关闭的公告横幅会重新弹出
        Setting.put("announcement_updated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    db.session.commit()
    audit.record("settings.update", target_type="settings", detail={"changed": changed})
    return ok({"changed": changed})


@bp.post("/notify/test")
@admin_required
def notify_test():
    """发送一条测试通知,验证 webhook 配置。"""
    from services import notify
    if notify.send_test():
        return ok()
    return err("通知发送失败:请确认已开启通知、webhook 地址正确且机器人可用", 502)
