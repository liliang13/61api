#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paykit 支付接线:组装 PaymentService + 到账权益钩子。"""
import math
import os
import re
import sys
from datetime import datetime

import config
from config import PAYKIT_PATH, SITE_NAME, BASE_DIR

PAYKIT_OK = False
_PAYKIT_ERR = ""


def _import_paykit():
    """兼容旧包名 paykit 与新包名 xiaoningpay。

    PAYKIT_PATH 指向的目录若与包名同名但无 __init__.py,会被误认成空命名空间
    包,因此必须校验 PaymentService 属性才算找到真模块。
    """
    import importlib
    for name in ("paykit", "xiaoningpay"):
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        if hasattr(mod, "PaymentService"):
            return mod
    return None


if PAYKIT_PATH:
    for _p in (PAYKIT_PATH, os.path.dirname(os.path.abspath(PAYKIT_PATH))):
        if _p and _p not in sys.path:
            sys.path.insert(0, _p)
    _paykit_mod = _import_paykit()
    if _paykit_mod is not None:
        paykit = _paykit_mod
        PAYKIT_OK = True
    else:
        paykit = None
        _PAYKIT_ERR = "未找到 paykit/xiaoningpay 支付模块"
else:
    paykit = None

DEFAULT_PACKAGES = [
    {"id": "p10", "name": "入门包 ¥10", "price": 1000, "bonus_pct": 0},
    {"id": "p50", "name": "标准包 ¥50", "price": 5000, "bonus_pct": 5},
    {"id": "p100", "name": "进阶包 ¥100", "price": 10000, "bonus_pct": 10},
    {"id": "p500", "name": "企业包 ¥500", "price": 50000, "bonus_pct": 15},
]


def validate_packages(pkg_defs):
    if not isinstance(pkg_defs, list) or not pkg_defs:
        raise ValueError("充值套餐配置无效")
    packages = {}
    for item in pkg_defs:
        if not isinstance(item, dict):
            raise ValueError("充值套餐配置无效")
        raw_id = item.get("id")
        package_id = raw_id.strip() if isinstance(raw_id, str) else ""
        if not package_id or package_id in packages:
            raise ValueError("套餐 ID 不能为空或重复")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", package_id):
            raise ValueError("套餐 ID 仅限字母、数字、下划线和中划线")
        if re.fullmatch(r"rp\d+", package_id):
            raise ValueError("套餐 ID 不能使用 rp+数字(资源包保留前缀)")
        raw_price = item.get("price")
        try:
            price = int(raw_price)
            bonus_pct = float(item.get("bonus_pct", 0))
        except (TypeError, ValueError, OverflowError):
            raise ValueError("套餐价格或赠送比例无效")
        if (isinstance(raw_price, bool) or price <= 0 or
                (price != raw_price and str(price) != str(raw_price))):
            raise ValueError("套餐价格必须为正整数(分)")
        if not math.isfinite(bonus_pct) or bonus_pct < 0:
            raise ValueError("套餐赠送比例无效")
        packages[package_id] = {
            "name": str(item.get("name") or package_id),
            "price": price,
            "type": "credits",
            "credits": compute_credits(price, bonus_pct),
            "bonus_pct": bonus_pct,
        }
    return packages


def load_resource_pack_packages():
    """把「在售」(启用且 price>0)的资源包定义转成 paykit 套餐;id 固定 rp<N>。

    镜像写入 TopupOrder 后,入账以镜像快照为准,不依赖本表(定义删除也已发放为准)。
    """
    from models import ResourcePackDef
    packages = {}
    for d in ResourcePackDef.query.filter_by(status=1).order_by(ResourcePackDef.sort.asc(),
                                                                ResourcePackDef.id.asc()).all():
        if (d.price or 0) <= 0:
            continue  # 未定价 = 仅赠送,不进入售卖
        packages[f"rp{d.id}"] = {
            "name": d.name, "price": d.price, "type": "resource_pack",
            "credits": d.tokens, "model": d.model, "valid_days": d.valid_days,
        }
    return packages


class QuotaEntitlements:
    """支付状态与本地订单原子同步;金额与资源包快照始终以本地订单镜像为准。"""

    def grant(self, order: dict, package: dict) -> None:
        from extensions import db
        from models import ResourcePackDef, TopupOrder, User
        from services.invite import grant_pending_for
        from services.resourcepack import grant_pack_to_user

        try:
            mirror = TopupOrder.query.filter_by(order_no=order["order_no"]).first()
            if mirror is None:
                raise RuntimeError("本地充值订单镜像缺失")
            if mirror.user_id != order.get("user_id"):
                raise RuntimeError("充值订单用户不匹配")
            changed = (db.session.query(TopupOrder)
                       .filter(TopupOrder.id == mirror.id, TopupOrder.status == "pending")
                       .update({"status": "paid",
                                "pay_method": order.get("pay_method") or mirror.pay_method,
                                "paid_at": datetime.now()}, synchronize_session=False))
            if changed:
                if (mirror.kind or "credits") == "resource_pack":
                    user = db.session.get(User, mirror.user_id)
                    if user is None:
                        raise RuntimeError("充值订单用户不存在")
                    pid = str(mirror.package_id or "")
                    def_id = int(pid[2:]) if pid.startswith("rp") and pid[2:].isdigit() else None
                    pack_def = db.session.get(ResourcePackDef, def_id) if def_id else None
                    if pack_def is not None:
                        grant_pack_to_user(user, pack_def, granted_type="purchase",
                                           order_no=mirror.order_no)
                    else:
                        # 定义已删除:入账以镜像快照字段为准
                        grant_pack_to_user(user, _PackSnapshot(mirror), granted_type="purchase",
                                           order_no=mirror.order_no)
                else:
                    credited = (db.session.query(User)
                                .filter(User.id == mirror.user_id)
                                .update({"quota": db.func.coalesce(User.quota, 0) + mirror.quota},
                                        synchronize_session=False))
                    if credited != 1:
                        raise RuntimeError("充值订单用户不存在")
            db.session.expire_all()
            if mirror.status == "paid":
                grant_pending_for(mirror.user_id, commit=False)
            db.session.commit()
            if changed:
                # 仅首笔入账时推送 Bark(渠道重发通知幂等,不重复打扰)
                from services.bark import order_paid
                _u = db.session.get(User, mirror.user_id)
                order_paid(_u.username if _u else f"uid{mirror.user_id}",
                           int(mirror.amount or 0), mirror.package_id or "-",
                           mirror.order_no)
        except Exception:
            db.session.rollback()
            raise

    def revoke(self, order: dict, package: dict) -> None:
        from extensions import db
        from models import TopupOrder, User, UserResourcePack
        from services.invite import revoke_ineligible_for

        try:
            mirror = TopupOrder.query.filter_by(order_no=order["order_no"]).first()
            if mirror is None:
                raise RuntimeError("本地充值订单镜像缺失")
            if mirror.user_id != order.get("user_id"):
                raise RuntimeError("充值订单用户不匹配")
            if mirror.status == "refunded":
                return
            if (mirror.kind or "credits") == "resource_pack":
                instance = UserResourcePack.query.filter_by(order_no=mirror.order_no).first()
                if instance is not None and (instance.used_tokens or 0) > 0:
                    raise RuntimeError("资源包 tokens 已有消耗,无法退款")
            changed = (db.session.query(TopupOrder)
                       .filter(TopupOrder.id == mirror.id, TopupOrder.status == "paid")
                       .update({"status": "refunded"}, synchronize_session=False))
            if not changed:
                raise RuntimeError("充值订单状态不可退款")
            if (mirror.kind or "credits") == "resource_pack":
                instance = UserResourcePack.query.filter_by(order_no=mirror.order_no).first()
                if instance is not None:
                    db.session.delete(instance)
            else:
                debited = (db.session.query(User)
                           .filter(User.id == mirror.user_id,
                                   db.func.coalesce(User.quota, 0) >= mirror.quota)
                           .update({"quota": User.quota - mirror.quota},
                                   synchronize_session=False))
                if debited != 1:
                    raise RuntimeError("充值额度已消费,无法退款")
            db.session.expire_all()
            revoke_ineligible_for(mirror.user_id)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    def balance_of(self, user_id: int):
        from extensions import db
        from models import User
        user = db.session.get(User, user_id)
        return user.quota if user else None


class _PackSnapshot:
    """定义已被删除时,用订单镜像字段兜底构造发放入参。"""

    def __init__(self, mirror):
        self.id = None
        self.name = (mirror.pack_model or "资源包")
        self.model = mirror.pack_model
        self.tokens = mirror.quota
        self.valid_days = mirror.pack_days or 0


def compute_credits(price_fen: int, bonus_pct: float) -> int:
    from services.billing import cny_to_quota
    return int(round(cny_to_quota(price_fen) * (1 + (bonus_pct or 0) / 100.0)))


if PAYKIT_OK:
    class TopupPaymentService(paykit.PaymentService):
        """支付账单商品名统一为「余额充值/资源包+金额」,不向渠道暴露套餐名与模型名。"""

        def _subject_of(self, order: dict) -> str:
            yuan = int(order["amount"]) / 100
            amount = f"{yuan:.2f}".rstrip("0").rstrip(".")
            kind = "资源包" if str(order.get("package_id") or "").startswith("rp") else "余额充值"
            subject = f"{kind}¥{amount}"
            return f"{self.settings.site_name}-{subject}" if self.settings.site_name else subject
else:
    TopupPaymentService = None


def build_payment_service(mode_override=None):
    """组装支付服务;生产环境不加载沙箱渠道。

    PAYKIT_MODE 决定主渠道(默认收银方式与查单渠道);另一渠道配置齐备时
    一并注册进 gateways,供下单 method 参数与退款按 pay_method 路由使用。
    """
    production = bool(getattr(config, "IS_PRODUCTION", False))
    mode = mode_override or config.PAYKIT_MODE
    if production and mode == "sandbox":
        return None
    if not PAYKIT_OK:
        return None
    from models import Setting
    packages = validate_packages(Setting.get("topup_packages", DEFAULT_PACKAGES))
    packages.update(load_resource_pack_packages())
    settings = paykit.PaySettings(
        site_name=SITE_NAME, packages=packages, mode=mode, sandbox_payee=SITE_NAME)
    store = paykit.SQLiteOrderStore((BASE_DIR / "data" / "paykit_orders.db").as_posix())
    gateways = {}
    if not production:
        gateways["sandbox"] = paykit.SandboxGateway(payee=SITE_NAME)
    if mode == "alipay":
        gateways["alipay"] = paykit.AlipayGateway(paykit.AlipaySettings.from_env())
        wechat = paykit.WechatSettings.from_env()
        if wechat.ready:
            gateways["wechat"] = paykit.WechatGateway(wechat, client_ip_provider=lambda: None)
    elif mode == "wechat":
        gateways["wechat"] = paykit.WechatGateway(
            paykit.WechatSettings.from_env(), client_ip_provider=lambda: None)
        alipay = paykit.AlipaySettings.from_env()
        if alipay.ready:
            gateways["alipay"] = paykit.AlipayGateway(alipay)
    elif mode != "sandbox":
        raise ValueError("支付模式无效")
    return TopupPaymentService(settings, store, gateways=gateways,
                               entitlements=QuotaEntitlements())
