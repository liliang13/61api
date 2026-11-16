#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公开接口:站点信息、模型目录(无需登录)。"""
from flask import Blueprint

from extensions import ok
from models import ApiKey, ModelItem, Setting, User

bp = Blueprint("public", __name__, url_prefix="/api/public")

SAFE_SETTING_KEYS = ("site_name", "announcement", "discount_note",
                     "hero_stats", "topup_packages", "kefu_qr_url")


@bp.get("/site-info")
def site_info():
    from config import (DEPLOYMENT_MODE, FEATURE_INVITE, FEATURE_INVOICE,
                        FEATURE_PAYMENTS, FEATURE_PUBLIC_SIGNUP, FEATURE_REDEEM,
                        FEATURE_SMS, IS_PRIVATE, SITE_NAME, SMS_MODE)
    keys = ("site_name", "announcement", "kefu_qr_url") if IS_PRIVATE else SAFE_SETTING_KEYS
    data = {k: Setting.get(k) for k in keys}
    data.setdefault("site_name", SITE_NAME)
    data["sms_dev"] = SMS_MODE == "dev"
    data["deployment_mode"] = DEPLOYMENT_MODE
    data["private"] = IS_PRIVATE
    data["features"] = {
        "public_signup": FEATURE_PUBLIC_SIGNUP,
        "sms": FEATURE_SMS,
        "payments": FEATURE_PAYMENTS,
        "invite": FEATURE_INVITE,
        "redeem": FEATURE_REDEEM,
        "invoice": FEATURE_INVOICE,
    }
    data["model_count"] = ModelItem.query.filter_by(status=1).count()
    if not IS_PRIVATE:
        data["user_count"] = User.query.count()
        data["key_count"] = ApiKey.query.count()
    return ok(data)


@bp.get("/models")
def models():
    items = (ModelItem.query.filter_by(status=1)
             .order_by(ModelItem.sort.asc(), ModelItem.id.asc()).all())
    # vendor 存的是上游渠道商名(基元律动/tokenriver 等),不向用户暴露;
    # 前端的厂商筛选按 display_name 品牌前缀推导,不需要本字段
    return ok([{k: v for k, v in m.to_dict().items() if k != "vendor"} for m in items])


@bp.get("/announcement")
def announcement():
    """控制台顶部公告横幅;enabled 需开关打开且文案非空。"""
    text = (Setting.get("announcement") or "").strip()
    enabled = bool(Setting.get("announcement_enabled", True)) and bool(text)
    return ok({
        "enabled": enabled,
        "text": text,
        "link": (Setting.get("announcement_link") or "").strip(),
        "updated_at": Setting.get("announcement_updated_at") or "",
    })
