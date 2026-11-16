#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""充值接口:套餐列表 → 创建订单 → 沙箱确认/渠道收银台。支付本体复用 paykit。

在售资源包(启用且已定价)以 rp<N> 为套餐 ID 走同一下单/收银台链路,
入账时按订单 kind 发放 tokens 资源包实例。
"""
import math
import re
from datetime import datetime

from flask import Blueprint, current_app, g, redirect, request

import config
from extensions import auth_required, check_rate_limit, db, err, ok
from models import ResourcePackDef, Setting, TopupOrder
from services import audit
from services.payments import DEFAULT_PACKAGES
from services import payments
from services.billing import quota_to_yuan

bp = Blueprint("topup", __name__, url_prefix="/api/topup")

_service = None


def get_service():
    """延迟组装并在套餐/汇率变化后自动重建(以 Setting 更新时间粗略判断)。"""
    global _service
    _service = payments.build_payment_service()
    return _service


def _custom_config():
    return {
        "enabled": bool(Setting.get("custom_topup_enabled", True)),
        "min_yuan": float(Setting.get("custom_topup_min_yuan", 1)),
        "max_yuan": float(Setting.get("custom_topup_max_yuan", 5000)),
    }


def _parse_custom_fen(raw):
    """自定义金额(元)→ 整数分;类型、精度、正负全部服务端裁决。"""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("自定义金额无效")
    amount = float(raw)
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("自定义金额必须是正数")
    fen = round(amount * 100)
    if abs(amount * 100 - fen) > 1e-6:
        raise ValueError("自定义金额最多支持两位小数")
    return fen


@bp.get("/packages")
@auth_required
def packages():
    try:
        svc = get_service()
        rate = float(Setting.get("usd_cny_rate", 7.3))
    except Exception:
        current_app.logger.exception("加载充值套餐失败")
        return err("充值套餐暂不可用", 503)
    if not svc:
        return ok({"paykit": False, "methods": [], "packages": []})
    out = []
    for pid, p in svc.settings.packages.items():
        if p.get("type") == "resource_pack":
            continue  # 资源包商品只在资源包页展示,充值页仅余额套餐
        bonus_pct = round(float(p.get("bonus_pct", 0) or 0), 2)
        out.append({"id": pid, "name": p["name"], "price": p["price"],
                    "price_yuan": round(p["price"] / 100, 2),
                    "credits": p["credits"], "credits_yuan": quota_to_yuan(p["credits"]),
                    "bonus_pct": bonus_pct, "rate": rate})
    return ok({"paykit": True, "mode": svc.settings.mode,
               "methods": list(svc.gateways.keys()), "packages": out,
               "custom": _custom_config()})


@bp.post("/create")
@auth_required
def create():
    data = request.get_json(silent=True) or {}
    package_id = data.get("package_id") or ""
    try:
        svc = get_service()
        if not svc:
            return err("支付组件未就绪", 503)
        method = data.get("method") or svc.settings.mode
        if method not in svc.gateways:
            return err("支付方式不可用")
        # 下单接口直连渠道,按用户限流防刷
        if not check_rate_limit("topup_create", f"uid:{g.user.id}", 5, 60):
            return err("创建订单过于频繁,请稍后再试", 429)
        if package_id == "custom":
            cfg = _custom_config()
            if not cfg["enabled"]:
                return err("自定义金额充值未开放")
            try:
                amount_fen = _parse_custom_fen(data.get("amount_yuan"))
            except ValueError as exc:
                return err(str(exc))
            if not (cfg["min_yuan"] * 100 <= amount_fen <= cfg["max_yuan"] * 100):
                return err(f"自定义金额需在 ¥{cfg['min_yuan']:g} - ¥{cfg['max_yuan']:g} 之间")
            quota = payments.compute_credits(amount_fen, 0)
            order = svc.create_dynamic_order(g.user.id, amount_fen,
                                             package_id="custom", credits=quota)
            mirror = TopupOrder(order_no=order["order_no"], user_id=g.user.id,
                                package_id="custom", amount=amount_fen,
                                quota=quota, pay_method=method, status="pending")
            resp_amount, resp_quota = amount_fen, quota
        elif re.fullmatch(r"rp\d+", package_id):
            d = db.session.get(ResourcePackDef, int(package_id[2:]))
            if not d or d.status != 1 or (d.price or 0) <= 0:
                return err("资源包不存在、已停用或未开放购买")
            order = svc.create_order(g.user.id, package_id)
            # 镜像写入 tokens/模型/有效期快照,入账以镜像为准(定义后续调整不影响已下单)
            mirror = TopupOrder(order_no=order["order_no"], user_id=g.user.id,
                                package_id=package_id, kind="resource_pack",
                                amount=d.price, quota=d.tokens,
                                pack_model=d.model, pack_days=d.valid_days,
                                pay_method=method, status="pending")
            resp_amount, resp_quota = d.price, d.tokens
        else:
            pkg = svc.settings.packages.get(package_id)
            if not pkg:
                return err("充值套餐不存在")
            order = svc.create_order(g.user.id, package_id)
            mirror = TopupOrder(order_no=order["order_no"], user_id=g.user.id,
                                package_id=package_id, amount=pkg["price"],
                                quota=pkg["credits"], pay_method=method, status="pending")
            resp_amount, resp_quota = pkg["price"], pkg["credits"]
        db.session.add(mirror)
        db.session.commit()
        # 点击创建订单即视为同意《充值协议》,留审计日志
        audit.record("recharge.agreement_agreed", target_type="user", target_id=g.user.id,
                     detail={"agreement": "充值协议", "order_no": order["order_no"],
                             "package_id": package_id, "amount_fen": resp_amount},
                     actor=g.user)
        svc.settings.mode = method
        pay = svc.start_payment(order)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("创建充值订单或发起支付失败")
        return err("支付发起失败,请稍后再试")
    return ok({"order_no": order["order_no"], "amount": resp_amount, "method": method,
               "quota": resp_quota, **pay})


@bp.post("/sandbox/confirm")
@auth_required
def sandbox_confirm():
    if getattr(config, "IS_PRODUCTION", False):
        return err("接口不可用", 403)
    data = request.get_json(silent=True) or {}
    order_no = data.get("order_no") or ""
    try:
        svc = get_service()
        if not svc:
            return err("支付组件未就绪", 503)
        order = svc.get_order(order_no)
        if not order or order["user_id"] != g.user.id:
            return err("订单不存在", 404)
        result = svc.confirm_sandbox(order_no, user_id=g.user.id)
    except Exception:
        current_app.logger.exception("沙箱支付确认失败")
        return err("支付确认失败,请稍后重试")
    return ok(result)


@bp.get("/pay-page/<order_no>")
def pay_page(order_no):
    """paykit 同步回跳落地:回前端充值页展示结果。"""
    return redirect(f"/console/topup?order={order_no}&done=1")
