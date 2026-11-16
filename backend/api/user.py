#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户控制台接口:数据看板 / API 密钥 / 用量日志 / 兑换码 / 邀请返佣 / 充值记录。"""
import math
import re
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, current_app, g, request
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

import extensions
from config import FEATURE_INVITE, FEATURE_INVOICE, FEATURE_PAYMENTS, FEATURE_REDEEM
from extensions import auth_required, db, err, ok, page_args
from models import (ApiKey, AuthThrottle, InviteReward, Invoice, InvoiceItem, ModelItem, Notice, NoticeRead, RedemptionCode, Tenant, Ticket, TicketMessage, TopupOrder, UsageLog, User, UserResourcePack)
from flask import send_file
from services import audit
from services import ticketfile
from services.billing import quota_to_yuan, yuan_to_quota


bp = Blueprint("user", __name__, url_prefix="/api/user")


@bp.get("/dashboard")
@auth_required
def dashboard():
    user = g.user
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    q_today = (db.session.query(func.count(UsageLog.id), func.coalesce(func.sum(UsageLog.prompt_tokens), 0),
                                func.coalesce(func.sum(UsageLog.completion_tokens), 0),
                                func.coalesce(func.sum(UsageLog.quota), 0))
               .filter(UsageLog.user_id == user.id, UsageLog.status != "held", UsageLog.created_at >= today).first())
    week_series = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        nxt = day + timedelta(days=1)
        row = (db.session.query(func.count(UsageLog.id), func.coalesce(func.sum(UsageLog.quota), 0))
               .filter(UsageLog.user_id == user.id, UsageLog.status != "held",
                       UsageLog.created_at >= day, UsageLog.created_at < nxt).first())
        week_series.append({"date": day.strftime("%m-%d"), "requests": row[0], "quota": int(row[1])})
    top_models = (db.session.query(UsageLog.model, func.count(UsageLog.id),
                                   func.coalesce(func.sum(UsageLog.quota), 0))
                  .filter(UsageLog.user_id == user.id, UsageLog.status != "held", UsageLog.created_at >= today - timedelta(days=7))
                  .group_by(UsageLog.model).order_by(func.sum(UsageLog.quota).desc()).limit(5).all())
    tenant = db.session.get(Tenant, user.tenant_id) if user.tenant_id else None
    return ok({
        "quota": user.quota, "used_quota": user.used_quota,
        "quota_yuan": quota_to_yuan(user.quota), "used_yuan": quota_to_yuan(user.used_quota),
        "tenant": ({"id": tenant.id, "name": tenant.name,
                    "quota": tenant.quota, "used_quota": tenant.used_quota,
                    "quota_yuan": quota_to_yuan(tenant.quota),
                    "used_yuan": quota_to_yuan(tenant.used_quota)} if tenant else None),
        "today": {"requests": q_today[0],
                  "tokens": int(q_today[1]) + int(q_today[2]),
                  "quota": int(q_today[3])},
        "week": week_series,
        "top_models": [{"model": m, "requests": c, "quota": int(q)} for m, c, q in top_models],
    })


# ---------------- API 密钥 ----------------

@bp.get("/keys")
@auth_required
def keys_list():
    rows = (ApiKey.query.filter_by(user_id=g.user.id)
            .order_by(ApiKey.id.desc()).all())
    return ok([k.to_dict() for k in rows])


def _key_quota_limit(value):
    if value in (None, ""):
        return -1
    if isinstance(value, bool):
        raise ValueError("限额无效")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("限额无效")
    return -1 if number == 0 else yuan_to_quota(number)


@bp.post("/keys")
@auth_required
def keys_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "默认密钥").strip()[:64]
    try:
        quota_limit = _key_quota_limit(data.get("limit_yuan"))
    except (TypeError, ValueError, OverflowError):
        return err("密钥限额无效", 400)
    raw = "sk-" + secrets.token_hex(20)
    key = ApiKey(user_id=g.user.id, tenant_id=g.user.tenant_id, name=name,
                 key=extensions.hash_api_key(raw),
                 key_prefix=raw[:8], key_last4=raw[-4:], quota_limit=quota_limit)
    db.session.add(key)
    db.session.commit()
    audit.record("key.create", target_type="api_key", target_id=key.id,
                 detail={"name": name, "quota_limit": quota_limit})
    d = key.to_dict()
    d["key"] = raw
    return ok(d)


@bp.put("/keys/<int:kid>")
@auth_required
def keys_update(kid):
    key = ApiKey.query.filter_by(id=kid, user_id=g.user.id).first()
    if not key:
        return err("密钥不存在", 404)
    data = request.get_json(silent=True) or {}
    if "name" in data:
        key.name = (data["name"] or key.name).strip()[:64]
    if "status" in data:
        key.status = 1 if data["status"] else 0
    if "limit_yuan" in data:
        try:
            key.quota_limit = _key_quota_limit(data["limit_yuan"])
        except (TypeError, ValueError, OverflowError):
            db.session.rollback()
            return err("密钥限额无效", 400)
    db.session.commit()
    audit.record("key.update", target_type="api_key", target_id=key.id,
                 detail={"name": key.name, "status": key.status, "quota_limit": key.quota_limit})
    return ok(key.to_dict())


@bp.delete("/keys/<int:kid>")
@auth_required
def keys_delete(kid):
    key = ApiKey.query.filter_by(id=kid, user_id=g.user.id).first()
    if not key:
        return err("密钥不存在", 404)
    key_id, key_name = key.id, key.name
    db.session.delete(key)
    db.session.commit()
    audit.record("key.delete", target_type="api_key", target_id=key_id,
                 detail={"name": key_name})
    return ok()


# ---------------- 用量日志 ----------------

@bp.get("/usage")
@auth_required
def usage():
    """用量明细:多维筛选(时间范围/模型/密钥/状态)+ 筛选范围汇总统计。"""
    page, size = page_args()
    model = request.args.get("model")
    key_id = request.args.get("key_id", type=int)
    status = request.args.get("status")
    conds = [UsageLog.user_id == g.user.id]
    if status:
        conds.append(UsageLog.status == status)
    else:
        conds.append(UsageLog.status != "held")
    start = request.args.get("start")
    end = request.args.get("end")
    days = request.args.get("days", type=int)
    if model:
        conds.append(UsageLog.model == model)
    if key_id:
        conds.append(UsageLog.key_id == key_id)
    if start:
        try:
            conds.append(UsageLog.created_at >= datetime.strptime(start, "%Y-%m-%d"))
        except ValueError:
            pass
    if end:
        try:
            conds.append(UsageLog.created_at < datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1))
        except ValueError:
            pass
    if not start and not end and days:
        conds.append(UsageLog.created_at >= datetime.now() - timedelta(days=days))

    total = UsageLog.query.filter(*conds).count()
    agg = (db.session.query(func.count(UsageLog.id),
                            func.coalesce(func.sum(UsageLog.prompt_tokens), 0),
                            func.coalesce(func.sum(UsageLog.completion_tokens), 0),
                            func.coalesce(func.sum(UsageLog.input_cost), 0),
                            func.coalesce(func.sum(UsageLog.output_cost), 0),
                            func.coalesce(func.sum(UsageLog.quota), 0))
           .filter(*conds).first())
    by_model = (db.session.query(UsageLog.model, func.count(UsageLog.id),
                                 func.coalesce(func.sum(UsageLog.prompt_tokens), 0),
                                 func.coalesce(func.sum(UsageLog.completion_tokens), 0),
                                 func.coalesce(func.sum(UsageLog.quota), 0))
                .filter(*conds).group_by(UsageLog.model)
                .order_by(func.sum(UsageLog.quota).desc()).limit(20).all())
    rows = (UsageLog.query.filter(*conds)
            .order_by(UsageLog.id.desc()).offset((page - 1) * size).limit(size).all())

    names = {k.id: k.name for k in ApiKey.query.filter_by(user_id=g.user.id).all()}
    items = []
    for r in rows:
        d = r.to_dict()
        d["key_display"] = d.get("key_name") or (names.get(r.key_id, "已删除密钥#" + str(r.key_id)) if r.key_id else "-")
        items.append(d)
    return ok({
        "total": total, "page": page, "page_size": size, "items": items,
        "summary": {"requests": agg[0], "prompt_tokens": int(agg[1]), "completion_tokens": int(agg[2]),
                    "input_cost": float(agg[3]), "output_cost": float(agg[4]),
                    "quota": int(agg[5]), "quota_yuan": quota_to_yuan(int(agg[5]))},
        "by_model": [{"model": m, "requests": c, "prompt_tokens": int(pt), "completion_tokens": int(ct),
                      "quota": int(qq), "quota_yuan": quota_to_yuan(int(qq))} for m, c, pt, ct, qq in by_model],
    })


# ---------------- 兑换码 ----------------

@bp.post("/redeem")
@auth_required
def redeem():
    if not FEATURE_REDEEM:
        return err("私有化部署未启用兑换码", 403)
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    # 防枚举:每用户每小时最多 10 次尝试(DB 计数,多 worker 安全)
    now = datetime.now()
    if AuthThrottle.query.filter(AuthThrottle.key == f"redeem:{g.user.id}",
                                 AuthThrottle.created_at > now - timedelta(hours=1)).count() >= 10:
        return err("尝试过于频繁,请稍后再试", 429)
    db.session.add(AuthThrottle(key=f"redeem:{g.user.id}"))
    db.session.commit()
    rec = RedemptionCode.query.filter_by(code=code).first()
    if not rec or rec.status != 1:
        return err("兑换码无效或已被使用")
    quota = rec.quota
    changed = (db.session.query(RedemptionCode)
               .filter(RedemptionCode.id == rec.id, RedemptionCode.status == 1)
               .update({"status": 0, "used_by": g.user.id, "used_at": datetime.now()},
                       synchronize_session=False))
    if not changed:
        db.session.rollback()
        return err("兑换码无效或已被使用")
    db.session.query(User).filter(User.id == g.user.id).update(
        {"quota": func.coalesce(User.quota, 0) + quota}, synchronize_session=False)
    db.session.commit()
    balance = db.session.query(User.quota).filter(User.id == g.user.id).scalar()
    return ok({"quota": quota, "yuan": quota_to_yuan(quota), "balance": balance})


# ---------------- 邀请返佣 ----------------

@bp.get("/invite")
@auth_required
def invite():
    if not FEATURE_INVITE:
        return err("私有化部署未启用邀请返佣", 403)
    from config import SITE_URL
    rewards = (InviteReward.query.filter_by(from_uid=g.user.id)
               .order_by(InviteReward.id.desc()).limit(50).all())
    total = db.session.query(func.coalesce(func.sum(InviteReward.quota), 0))\
        .filter_by(from_uid=g.user.id).scalar()
    invited = User.query.filter_by(invited_by=g.user.id).count()
    return ok({
        "invite_code": g.user.invite_code,
        "invite_link": f"{SITE_URL}/login?invite={g.user.uid}",
        "invited": invited, "total_quota": int(total or 0),
        "total_yuan": quota_to_yuan(int(total or 0)),
        "recent": [{"to_uid": r.to_uid, "quota": r.quota,
                    "created_at": r.created_at.strftime("%Y-%m-%d %H:%M")} for r in rewards],
    })


# ---------------- 充值记录 ----------------

@bp.get("/orders")
@auth_required
def my_orders():
    if not FEATURE_PAYMENTS:
        return err("私有化部署未启用在线充值", 403)
    rows = (TopupOrder.query.filter_by(user_id=g.user.id)
            .order_by(TopupOrder.id.desc()).limit(100).all())
    return ok([o.to_dict() for o in rows])


# ---------------- 模型价格(控制台内) ----------------

@bp.get("/model-prices")
@auth_required
def model_prices():
    items = (ModelItem.query.filter_by(status=1)
             .order_by(ModelItem.sort.asc(), ModelItem.id.asc()).all())
    # vendor 是渠道/上游供应商信息,不向用户暴露(管理后台仍可见)
    return ok([{k: v for k, v in m.to_dict().items() if k != "vendor"} for m in items])


# ---------------- 资源包 ----------------

@bp.get("/resource-packs")
@auth_required
def my_resource_packs():
    """我的资源包:现有实例、tokens 总量/剩余、使用量与到期时间。"""
    rows = (UserResourcePack.query.filter_by(user_id=g.user.id)
            .order_by(UserResourcePack.id.desc()).limit(200).all())
    return ok([p.to_dict() for p in rows])


@bp.get("/resource-pack-offers")
@auth_required
def resource_pack_offers():
    """可购买的资源包商品(启用且已定价),购买走 /api/topup/create。"""
    from services.payments import load_resource_pack_packages
    try:
        offers = load_resource_pack_packages()
    except Exception:
        current_app.logger.exception("加载资源包商品失败")
        return err("资源包商品暂不可用", 503)
    items = [{"id": pid, "name": p["name"], "model": p["model"],
              "price": p["price"], "price_yuan": round(p["price"] / 100, 2),
              "tokens": p["credits"], "valid_days": p["valid_days"]}
             for pid, p in offers.items()]
    return ok({"purchasable": bool(FEATURE_PAYMENTS), "items": items})

# ---------------- 发票管理 ----------------

TAX_NO_RE = re.compile(r"^[0-9A-HJ-NPQRTUWXY]{18}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _invoiced_of(order_no: str) -> int:
    """订单已被(待开具/已开具)发票占用的金额。"""
    return (db.session.query(db.func.coalesce(db.func.sum(InvoiceItem.amount), 0))
            .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .filter(InvoiceItem.order_no == order_no, InvoiceItem.active == 1,
                    Invoice.status.in_((0, 1))).scalar() or 0)


@bp.get("/invoices")
@auth_required
def invoices():
    if not FEATURE_INVOICE:
        return err("私有化部署未启用发票管理", 403)
    rows = (Invoice.query.filter_by(user_id=g.user.id)
            .order_by(Invoice.id.desc()).limit(100).all())
    return ok([i.to_dict() for i in rows])


@bp.get("/invoices/available-orders")
@auth_required
def invoice_available_orders():
    """可开票的已支付订单:已支付、未退款、剩余可开额度 > 0。"""
    if not FEATURE_INVOICE:
        return err("私有化部署未启用发票管理", 403)
    orders = (TopupOrder.query.filter_by(user_id=g.user.id, status="paid")
              .order_by(TopupOrder.id.desc()).limit(100).all())
    out = []
    for o in orders:
        left = o.amount - _invoiced_of(o.order_no)
        if left > 0:
            out.append({"order_no": o.order_no, "created_at": o.created_at.strftime("%Y-%m-%d") if o.created_at else "",
                        "amount": o.amount, "amount_yuan": o.amount / 100, "invoicable_yuan": left / 100})
    return ok(out)


@bp.post("/invoices")
@auth_required
def invoice_create():
    """提交开票申请;写事务内复查订单额度,防止并发重复占用。"""
    if not FEATURE_INVOICE:
        return err("私有化部署未启用发票管理", 403)
    data = request.get_json(silent=True) or {}
    order_nos = data.get("order_nos") or []
    inv_type = data.get("inv_type") or "电子普通发票"
    title_type = data.get("title_type") or "企业"
    title = (data.get("title") or "").strip()
    tax_no = (data.get("tax_no") or "").strip()
    email = (data.get("email") or "").strip()
    remark = (data.get("remark") or "").strip()[:200]

    if not isinstance(order_nos, list) or not order_nos:
        return err("请选择要开票的订单")
    if not all(isinstance(no, str) and no for no in order_nos):
        return err("订单号无效")
    order_nos = list(dict.fromkeys(order_nos))[:20]
    if inv_type not in ("电子普通发票", "增值税专用发票"):
        return err("发票类型不正确")
    if inv_type == "增值税专用发票" and data.get("special_confirmation") is not True:
        return err("申请专票需先阅读并同意《专用发票抬头确认书》")
    if title_type not in ("企业", "个人"):
        return err("抬头类型不正确")
    if inv_type == "增值税专用发票" and title_type != "企业":
        return err("专用发票仅支持企业抬头")
    if not title:
        return err("请填写发票抬头")
    if title_type == "企业" and not TAX_NO_RE.match(tax_no):
        return err("税号格式不正确(18 位统一社会信用代码)")
    if not EMAIL_RE.match(email):
        return err("请填写正确的接收邮箱")

    db.session.commit()
    try:
        if db.engine.dialect.name == "sqlite":
            db.session.execute(text("BEGIN IMMEDIATE"))
        total = 0
        picked = []
        for no in order_nos:
            o = (TopupOrder.query.with_for_update()
                 .filter_by(order_no=no, user_id=g.user.id, status="paid").first())
            if not o:
                db.session.rollback()
                return err("订单不存在或状态不可开票: " + no)
            left = o.amount - _invoiced_of(o.order_no)
            if left <= 0:
                db.session.rollback()
                return err("订单 %s 已全额开票" % no)
            total += left
            picked.append((o, left))
        if total < 100:
            db.session.rollback()
            return err("开票金额最低 ¥1")

        inv = Invoice(user_id=g.user.id, amount=total, inv_type=inv_type,
                      title_type=title_type, title=title,
                      tax_no=tax_no if title_type == "企业" else "",
                      email=email, remark=remark)
        db.session.add(inv)
        db.session.flush()
        for o, amt in picked:
            db.session.add(InvoiceItem(invoice_id=inv.id, order_no=o.order_no,
                                       user_id=g.user.id, amount=amt, active=1))
        db.session.commit()
        # 开票留痕:专票需用户单独同意《专用发票抬头确认书》
        audit.record("invoice.create", target_type="invoice", target_id=inv.id,
                     detail={"inv_type": inv_type, "amount_fen": total,
                             "title": title[:64], "tax_no": tax_no,
                             "special_confirmation_confirmed":
                                 inv_type == "增值税专用发票"},
                     actor=g.user)
        return ok(inv.to_dict())
    except IntegrityError:
        db.session.rollback()
        return err("订单已被其他发票占用,请刷新后重试", 409)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("创建发票失败")
        return err("开票申请失败,请稍后重试")


# ---------------- 发票文件下载 ----------------

INVOICE_FILE_DIR = None  # app.py 启动时确定(BASE_DIR/data/invoices)


def _invoice_file_path(invoice_id):
    from config import BASE_DIR
    return BASE_DIR / "data" / "invoices" / (str(invoice_id) + ".pdf")


@bp.get("/invoices/<int:iid>/file")
@auth_required
def download_invoice_file(iid):
    """下载自己的发票文件;仅本人的发票可下载,限流防批量拉取。"""
    if not extensions.check_rate_limit("inv-dl:" + str(g.user.id), "u" + str(g.user.id), 5, 60):
        return err("下载过于频繁,请稍后再试", 429)
    inv = Invoice.query.filter_by(id=iid, user_id=g.user.id).first()
    if not inv or not inv.file_name:
        return err("发票文件尚未上传", 404)
    path = _invoice_file_path(iid)
    if not path.exists():
        return err("发票文件丢失,请联系客服", 404)
    safe_name = (inv.invoice_no or ("invoice-" + str(iid))) + ".pdf"
    audit.record("invoice.file_download", target_type="invoice", target_id=iid,
                 detail={"file": inv.file_name[:80]}, actor=g.user)
    return send_file(path, as_attachment=True, download_name=safe_name,
                     mimetype="application/pdf")


# ---------------- 发票管理结束 ----------------


# ---------------- 站内消息 ----------------

@bp.get("/notices")
@auth_required
def notice_list():
    """当前用户消息列表(倒序分页,含已读标记)。"""
    page, size = page_args()
    base = Notice.query.filter_by(status=1)
    total = base.count()
    rows = (db.session.query(Notice, NoticeRead.id)
            .outerjoin(NoticeRead, db.and_(NoticeRead.notice_id == Notice.id,
                                           NoticeRead.user_id == g.user.id))
            .filter(Notice.status == 1)
            .order_by(Notice.id.desc())
            .offset((page - 1) * size).limit(size).all())
    items = [{"id": n.id, "title": n.title,
              "created_at": n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else None,
              "read": rid is not None} for n, rid in rows]
    return ok({"total": total, "page": page, "page_size": size, "items": items})


@bp.get("/notices/unread-count")
@auth_required
def notice_unread_count():
    """铃铛未读数。"""
    total = Notice.query.filter_by(status=1).count()
    read = (NoticeRead.query.join(Notice, Notice.id == NoticeRead.notice_id)
            .filter(NoticeRead.user_id == g.user.id, Notice.status == 1).count())
    return ok({"unread": max(0, total - read)})


@bp.post("/notices/read-all")
@auth_required
def notice_read_all():
    """全部已读。"""
    published = Notice.query.filter_by(status=1).all()
    read_ids = {r.notice_id for r in NoticeRead.query.filter_by(user_id=g.user.id).all()}
    now = datetime.now()
    for n in published:
        if n.id not in read_ids:
            db.session.add(NoticeRead(notice_id=n.id, user_id=g.user.id, read_at=now))
    db.session.commit()
    return ok()


@bp.get("/notices/<int:nid>")
@auth_required
def notice_detail(nid):
    """消息详情;打开即标记已读。"""
    n = Notice.query.filter_by(id=nid, status=1).first()
    if not n:
        return err("消息不存在", 404)
    if not NoticeRead.query.filter_by(notice_id=nid, user_id=g.user.id).first():
        db.session.add(NoticeRead(notice_id=nid, user_id=g.user.id, read_at=datetime.now()))
        db.session.commit()
    return ok({"id": n.id, "title": n.title, "body": n.body or "",
               "created_at": n.created_at.strftime("%Y-%m-%d %H:%M:%S") if n.created_at else None})


# ---------------- 工单 ----------------

TICKET_TITLE_MAX = 128
TICKET_CONTENT_MAX = 5000


def _ticket_preview(ticket_id):
    last = (TicketMessage.query.filter_by(ticket_id=ticket_id)
            .order_by(TicketMessage.id.desc()).first())
    if not last:
        return ""
    tag = "[我们] " if last.sender_role == "admin" else ""
    return tag + (last.content or "")[:60]


@bp.post("/tickets/attachment")
@auth_required
def upload_ticket_attachment():
    """上传工单图片附件(临时);返回 key,提交工单/回复时携带。"""
    f = request.files.get("file")
    if f is None or not f.filename:
        return err("请选择图片文件")
    try:
        data = f.read()
        meta = ticketfile.save_tmp(g.user.id, data,
                                   ticketfile.valid_image_name(f.filename))
    except ValueError as exc:
        return err(str(exc))
    return ok(meta)


@bp.get("/tickets")
@auth_required
def my_tickets():
    """我的工单列表。"""
    page, size = page_args()
    status = request.args.get("status")
    q = Ticket.query.filter_by(user_id=g.user.id)
    if status in ("open", "answered", "closed"):
        q = q.filter_by(status=status)
    total = q.count()
    rows = q.order_by(Ticket.updated_at.desc()).offset((page - 1) * size).limit(size).all()
    return ok({"total": total, "page": page, "page_size": size,
               "items": [t.to_dict(preview=_ticket_preview(t.id)) for t in rows]})


@bp.post("/tickets")
@auth_required
def create_ticket():
    """提交新工单。"""
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    content = (data.get("content") or "").strip()
    if not title:
        return err("标题不能为空")
    if not content:
        return err("内容不能为空")
    att = data.get("attachment") or {}
    t = Ticket(user_id=g.user.id, title=title[:TICKET_TITLE_MAX], status="open")
    db.session.add(t)
    db.session.flush()
    msg = TicketMessage(ticket_id=t.id, sender_role="user",
                        sender_id=g.user.id, sender_name=g.user.username or "",
                        content=content[:TICKET_CONTENT_MAX])
    if att.get("key"):
        db.session.add(msg)
        db.session.flush()  # 先拿 msg.id:正式文件按消息 ID 命名,同工单多图不冲突
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
    db.session.add(msg)
    db.session.commit()
    audit.record("ticket.create", target_type="ticket", target_id=t.id,
                 detail={"title": t.title[:64]})
    return ok(t.to_dict(preview=content[:60]))


def _own_ticket_or_404(tid):
    t = Ticket.query.filter_by(id=tid, user_id=g.user.id).first()
    return t


@bp.get("/tickets/<int:tid>")
@auth_required
def ticket_detail(tid):
    t = _own_ticket_or_404(tid)
    if not t:
        return err("工单不存在", 404)
    msgs = (TicketMessage.query.filter_by(ticket_id=tid)
            .order_by(TicketMessage.id.asc()).all())
    return ok(dict(t.to_dict(), messages=[m.to_dict() for m in msgs]))


@bp.post("/tickets/<int:tid>/reply")
@auth_required
def ticket_reply(tid):
    t = _own_ticket_or_404(tid)
    if not t:
        return err("工单不存在", 404)
    if t.status == "closed":
        return err("工单已关闭,如仍有问题请提交新工单")
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return err("回复内容不能为空")
    msg = TicketMessage(ticket_id=tid, sender_role="user",
                        sender_id=g.user.id, sender_name=g.user.username or "",
                        content=content[:TICKET_CONTENT_MAX])
    att = data.get("attachment") or {}
    if att.get("key"):
        db.session.add(msg)
        db.session.flush()  # 正式文件按消息 ID 命名
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
    t.status = "open"
    t.updated_at = datetime.now()
    db.session.commit()
    return ok(t.to_dict(preview=content[:60]))


@bp.post("/tickets/<int:tid>/close")
@auth_required
def ticket_close(tid):
    t = _own_ticket_or_404(tid)
    if not t:
        return err("工单不存在", 404)
    if t.status == "closed":
        return err("工单已是关闭状态")
    t.status = "closed"
    t.updated_at = datetime.now()
    db.session.commit()
    return ok(t.to_dict())


@bp.get("/tickets/<int:tid>/messages/<int:mid>/file")
@auth_required
def ticket_message_file(tid, mid):
    """工单消息附件图片(仅工单属主或管理员可看)。"""
    t = Ticket.query.get(tid)
    if not t:
        return err("工单不存在", 404)
    if g.user.role != "admin" and t.user_id != g.user.id:
        return err("工单不存在", 404)
    m = TicketMessage.query.filter_by(id=mid, ticket_id=tid).first()
    if not m or not m.file_key:
        return err("附件不存在", 404)
    from flask import send_file
    path, mime = ticketfile.open_final(m.file_key)
    if not path:
        return err("附件文件丢失", 404)
    return send_file(path, mimetype=mime, conditional=True)
