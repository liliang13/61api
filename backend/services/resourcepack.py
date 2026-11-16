#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资源包业务:发放给用户、注册赠送、商品校验与统计。计费扣减见 services/billing。"""
from datetime import datetime, timedelta

from extensions import db
from models import ResourcePackDef, Setting, UserResourcePack


def grant_pack_to_user(user, pack_def, *, granted_type="admin_grant", order_no="",
                       valid_days=None, pack_name=None) -> UserResourcePack:
    """给用户发一个 tokens 资源包实例;valid_days 覆盖定义有效期,0/None=按定义。"""
    days = pack_def.valid_days if valid_days is None else valid_days
    expires = datetime.now() + timedelta(days=days) if days and days > 0 else None
    instance = UserResourcePack(
        user_id=user.id, pack_id=pack_def.id,
        pack_name=(pack_name or pack_def.name)[:64],
        model=pack_def.model, total_tokens=pack_def.tokens,
        granted_type=granted_type, order_no=order_no, status=1, expires_at=expires)
    db.session.add(instance)
    return instance


def grant_register_gift(user) -> UserResourcePack | None:
    """注册/建号赠送资源包;未配置或商品停用时静默跳过,不阻断开户。"""
    pack_id = Setting.get("register_gift_pack_id", 0)
    if not pack_id:
        return None
    pack_def = db.session.get(ResourcePackDef, pack_id)
    if not pack_def or pack_def.status != 1:
        return None
    return grant_pack_to_user(user, pack_def, granted_type="register_gift")


def validate_pack_fields(data, *, partial=False, current=None) -> str:
    """创建/编辑入参校验;返回错误文案,'' 表示通过。"""
    name = data.get("name")
    if not partial or name is not None:
        if not str(name or "").strip():
            return "资源包名称不能为空"
    model = data.get("model")
    if not partial or model is not None:
        if not str(model or "").strip():
            return "必须绑定模型"
    if "tokens_wan" in data or not partial:
        try:
            wan = float(data.get("tokens_wan"))
        except (TypeError, ValueError, OverflowError):
            return "tokens 数量无效"
        if wan <= 0 or wan > 100_000_000:
            return "tokens 数量需在 0.01 万 - 1 亿万之间"
    if "valid_days" in data or not partial:
        try:
            days = int(data.get("valid_days", 365))
        except (TypeError, ValueError, OverflowError):
            return "有效期必须是天数"
        if days < 0:
            return "有效期不能为负数"
    return ""
