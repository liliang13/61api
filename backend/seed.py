#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""种子数据:管理员、站点设置、内置演示渠道和模型目录。幂等且不删除业务数据。"""
import json

from werkzeug.security import generate_password_hash

from config import (ADMIN_PASSWORD, ADMIN_USERNAME, DEFAULT_TENANT_QUOTA_YUAN,
                    IS_PRIVATE, PRIVATE_TENANT_NAME, SITE_NAME)
from extensions import db
from models import ApiKey, Channel, ModelItem, Setting, Tenant, User

HERO_STATS = {"stat1": {"num": "2", "label": "DeepSeek 全系模型"},
              "stat2": {"num": "1:1", "label": "人民币充值直兑额度"},
              "stat3": {"num": "7×24", "label": "网关服务"}}

CATALOG_VERSION = 3  # v3: 补录官方原价(official_input/output)
OLD_RATE = 7.3  # 旧额度单位(500000=$1)→ 新单位(500000=¥1)的换算系数

# (name, display, vendor, tags, 售价输入¥, 售价输出¥, sort, 官方输入¥, 官方输出¥)
MODELS = [
    ("deepseek-flash", "DeepSeek-V4.1-Flash", "DeepSeek", ["对话", "性价比", "多模态", "1M 上下文"], 1.00, 4.00, 1, 2.00, 8.00),
    ("deepseek-v4-pro", "DeepSeek-V4-Pro", "DeepSeek", ["推理", "旗舰"], 2.00, 8.00, 2, 4.00, 16.00),
]


def ensure_seed():
    tenant = Tenant.query.order_by(Tenant.id).first()
    if tenant is None:
        quota = -1 if DEFAULT_TENANT_QUOTA_YUAN < 0 else int(DEFAULT_TENANT_QUOTA_YUAN * 500_000)
        tenant = Tenant(name=PRIVATE_TENANT_NAME, slug="default", quota=quota,
                        note="初始化时自动创建")
        db.session.add(tenant)
        db.session.flush()

    if User.query.count() == 0:
        admin = User(username=ADMIN_USERNAME, tenant_id=tenant.id,
                     password_hash=generate_password_hash(ADMIN_PASSWORD),
                     role="admin", quota=500_000 * (1000 if IS_PRIVATE else 10),
                     invite_code="ADMIN888")
        db.session.add(admin)

    # 兼容从公开版升级过来的老库:没有组织归属的用户统一挂到默认组织
    User.query.filter(User.tenant_id.is_(None)).update(
        {"tenant_id": tenant.id}, synchronize_session=False)

    defaults = {
        "site_name": SITE_NAME,
        "announcement": ("私有化部署版已就绪。所有模型调用走内网网关,"
                         "账号由管理员统一开通。" if IS_PRIVATE else
                         "全部模型以人民币计价,注册即送体验金;模型与价格持续上架中。"),
        "hero_stats": HERO_STATS,
    }
    if not IS_PRIVATE:
        from services.payments import DEFAULT_PACKAGES
        defaults.update({
            "discount_note": 0.5,
            "topup_packages": DEFAULT_PACKAGES,
            "invite_bonus_cny": 1.0,
            "new_user_bonus_cny": 0.5,
        })
    for k, v in defaults.items():
        if db.session.get(Setting, k) is None:
            Setting.put(k, v)
    # usd_cny_rate 已随人民币计价废弃
    old_rate = db.session.get(Setting, "usd_cny_rate")
    if old_rate is not None:
        db.session.delete(old_rate)

    if Channel.query.count() == 0:
        # 演示渠道默认停用:接真实上游后由管理后台按需启停,避免假数据兜底
        db.session.add(Channel(name="内置演示渠道(mock)", type="mock",
                               models='["*"]', priority=99, weight=1, status=0))

    _ensure_catalog()
    db.session.commit()


def _ensure_catalog():
    ver = Setting.get("catalog_version", 0)
    if ver == CATALOG_VERSION and ModelItem.query.count() > 0:
        return
    for name, disp, vendor, tags, inp, outp, sort, off_in, off_out in MODELS:
        item = ModelItem.query.filter_by(name=name).first()
        if item is None:
            item = ModelItem(name=name, input_price=inp, output_price=outp)
            db.session.add(item)
        item.display_name = disp
        item.vendor = vendor
        item.tags = json.dumps(tags, ensure_ascii=False)
        item.sort = sort
        item.official_input = off_in
        item.official_output = off_out
    if 0 < ver < 2:
        for u in User.query.all():
            u.quota = int(round((u.quota or 0) * OLD_RATE))
            u.used_quota = int(round((u.used_quota or 0) * OLD_RATE))
        for k in ApiKey.query.all():
            if k.quota_limit and k.quota_limit > 0:
                k.quota_limit = int(round(k.quota_limit * OLD_RATE))
            k.used_quota = int(round((k.used_quota or 0) * OLD_RATE))
        from models import UsageLog
        for log in UsageLog.query.all():
            log.quota = int(round((log.quota or 0) * OLD_RATE))
    Setting.put("catalog_version", CATALOG_VERSION)
