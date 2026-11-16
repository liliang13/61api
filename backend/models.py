#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据模型。额度单位:quota(500000 quota = ¥1)。"""
import json
import secrets
from datetime import datetime

from extensions import db

QUOTA_PER_UNIT = 500_000  # ¥1


def gen_unique_uid() -> str:
    """随机分配 6 位对外 UID(100000-999999),查重保证唯一;不按注册顺序递增。"""
    while True:
        uid = str(100_000 + secrets.randbelow(900_000))
        if not User.query.filter_by(uid=uid).first():
            return uid


class Tenant(db.Model):
    """组织/部门。私有化部署下作为额度、用户与用量的隔离边界。"""
    __tablename__ = "tenants"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    slug = db.Column(db.String(64), unique=True, nullable=False)
    status = db.Column(db.Integer, default=1)            # 1 启用 0 停用
    quota = db.Column(db.BigInteger, default=-1)         # 剩余额度,-1=不限
    used_quota = db.Column(db.BigInteger, default=0)     # 累计消费
    note = db.Column(db.String(200), default="")
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "slug": self.slug,
            "status": self.status, "quota": self.quota, "used_quota": self.used_quota,
            "note": self.note or "",
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, index=True, default=1)  # 所属组织
    uid = db.Column(db.String(32), unique=True)         # 自动分配的对外 UID(随机 6 位,不按顺序)
    username = db.Column(db.String(64), unique=True)
    phone = db.Column(db.String(20), unique=True)
    email = db.Column(db.String(128))
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(16), default="user")      # user / admin
    token_version = db.Column(db.Integer, default=0)     # 改密/封禁时 +1,使旧 JWT 全部失效
    status = db.Column(db.Integer, default=1)            # 1 正常 0 禁用
    quota = db.Column(db.BigInteger, default=0)          # 剩余额度
    used_quota = db.Column(db.BigInteger, default=0)     # 累计消费
    invite_code = db.Column(db.String(16), unique=True)
    invited_by = db.Column(db.Integer)                   # 邀请人 user id
    created_at = db.Column(db.DateTime, default=datetime.now)
    last_login_at = db.Column(db.DateTime)
    register_ip = db.Column(db.String(64), default="")
    last_login_ip = db.Column(db.String(64), default="")
    concurrency_limit = db.Column(db.Integer, default=0)  # 单用户并发上限;0=用全局默认

    def to_dict(self):
        from services.geo import ip_location
        return {
            "id": self.id, "uid": self.uid, "token_version": self.token_version, "username": self.username, "phone": self.phone,
            "email": self.email, "role": self.role, "status": self.status, "tenant_id": self.tenant_id,
            "quota": self.quota, "used_quota": self.used_quota,
            "concurrency_limit": self.concurrency_limit or 0,
            "invite_code": self.invite_code, "invited_by": self.invited_by,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "last_login_at": self.last_login_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_login_at else None,
            "register_ip": self.register_ip or "",
            "last_login_ip": self.last_login_ip or "",
            "register_location": ip_location(self.register_ip),
            "last_login_location": ip_location(self.last_login_ip),
        }


class ApiKey(db.Model):
    __tablename__ = "api_keys"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, index=True, nullable=False)
    tenant_id = db.Column(db.Integer, index=True)
    name = db.Column(db.String(64), default="默认密钥")
    key = db.Column(db.String(64), unique=True, nullable=False)
    key_prefix = db.Column(db.String(16), default="")
    key_last4 = db.Column(db.String(4), default="")
    quota_limit = db.Column(db.BigInteger, default=-1)   # -1 不限
    used_quota = db.Column(db.BigInteger, default=0)
    status = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.now)
    last_used_at = db.Column(db.DateTime)

    def to_dict(self):
        """密钥只回脱敏形式(sk-前8位…后4位);完整明文仅在创建接口响应中出现一次。"""
        masked = ((self.key_prefix or self.key[:8]) + "••••••••" +
                  (self.key_last4 or self.key[-4:])) if self.key else ""
        return {
            "id": self.id, "name": self.name, "key_masked": masked,
            "quota_limit": self.quota_limit, "used_quota": self.used_quota,
            "status": self.status,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "last_used_at": self.last_used_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_used_at else None,
        }


class Channel(db.Model):
    """上游渠道。type: openai=标准 OpenAI 兼容上游 / mock=内置演示渠道。"""
    __tablename__ = "channels"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    type = db.Column(db.String(16), default="openai")
    base_url = db.Column(db.String(256), default="")
    api_key = db.Column(db.String(256), default="")
    models = db.Column(db.Text, default='["*"]')         # JSON 数组,"*" 表示全部模型
    model_map = db.Column(db.Text, default="{}")         # JSON:目录名 → 上游模型名(仅不同名时写)
    priority = db.Column(db.Integer, default=0)          # 数值小的优先
    weight = db.Column(db.Integer, default=1)
    status = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.now)
    # 探活状态(services/probe 维护):last_test_ok 为 NULL 表示从未测过
    last_test_at = db.Column(db.DateTime)
    last_test_ok = db.Column(db.Integer)
    last_test_latency_ms = db.Column(db.Integer)
    last_test_error = db.Column(db.Text, default="")
    fail_streak = db.Column(db.Integer, default=0)       # 连续探活失败次数
    recover_streak = db.Column(db.Integer, default=0)    # 自动禁用后连续探活成功次数
    auto_disabled = db.Column(db.Integer, default=0)     # 1=探活自动禁用(区别于人为停用)
    # 上游账户余额缓存(admin 手动查询落库,非实时):JSON {balance,total,used,currency,is_active}
    last_balance_at = db.Column(db.DateTime)
    last_balance_info = db.Column(db.Text, default="")

    def model_list(self):
        try:
            return json.loads(self.models or '["*"]')
        except Exception:
            return ["*"]

    def model_mapping(self):
        """目录名 → 上游模型名;只含改名映射,同名模型不出现在映射里。"""
        try:
            mapping = json.loads(self.model_map or "{}")
        except Exception:
            return {}
        if not isinstance(mapping, dict):
            return {}
        return {str(k): str(v) for k, v in mapping.items() if k and v}

    def upstream_model_of(self, catalog_name: str) -> str:
        return self.model_mapping().get(catalog_name, catalog_name)

    def balance_info(self):
        """最近一次余额查询的解析结果;从未查过或解析失败返回 None。"""
        try:
            data = json.loads(self.last_balance_info or "")
        except Exception:
            return None
        return data if isinstance(data, dict) and "balance" in data else None

    def to_dict(self, secret=False):
        d = {
            "id": self.id, "name": self.name, "type": self.type,
            "base_url": self.base_url, "models": self.model_list(),
            "model_map": self.model_mapping(),
            "priority": self.priority, "weight": self.weight,
            "status": self.status,
            "last_test_at": self.last_test_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_test_at else None,
            "last_test_ok": self.last_test_ok,
            "last_test_latency_ms": self.last_test_latency_ms,
            "last_test_error": self.last_test_error or "",
            "fail_streak": self.fail_streak or 0,
            "auto_disabled": self.auto_disabled or 0,
            "last_balance_at": self.last_balance_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_balance_at else None,
            "last_balance_info": self.balance_info(),
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }
        d["api_key"] = (self.api_key[:6] + "...") if (self.api_key and not secret) else self.api_key
        return d


class ChannelEvent(db.Model):
    """渠道事件:探活结果 / 自动禁用与恢复 / 请求失败切换留痕,支撑状态总览与时间线。"""
    __tablename__ = "channel_events"
    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, index=True, nullable=False)
    kind = db.Column(db.String(16), nullable=False)      # probe_ok/probe_fail/auto_disable/auto_recover/failover
    latency_ms = db.Column(db.Integer)
    message = db.Column(db.Text, default="")
    request_id = db.Column(db.String(64))                # failover 时关联 usage_logs.request_id
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)

    def to_dict(self):
        return {
            "id": self.id, "channel_id": self.channel_id, "kind": self.kind,
            "latency_ms": self.latency_ms, "message": self.message or "",
            "request_id": self.request_id,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class ModelItem(db.Model):
    """模型目录与定价。价格为用户实际支付价(¥ / 1M tokens);official_* 为官方原价,用于折扣展示。"""
    __tablename__ = "models"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)
    display_name = db.Column(db.String(128), default="")
    vendor = db.Column(db.String(64), default="其他")
    tags = db.Column(db.Text, default="[]")              # JSON 数组
    input_price = db.Column(db.Float, default=0.0)       # 售价 ¥/1M 输入(缓存未命中)
    output_price = db.Column(db.Float, default=0.0)      # 售价 ¥/1M 输出
    cache_input_price = db.Column(db.Float, default=0.0) # 缓存命中输入价 ¥/1M(0=不区分,按全价)
    official_input = db.Column(db.Float, default=0.0)    # 官方原价 ¥/1M 输入(0=不展示折扣)
    official_output = db.Column(db.Float, default=0.0)   # 官方原价 ¥/1M 输出
    description = db.Column(db.Text, default="")
    status = db.Column(db.Integer, default=1)
    sort = db.Column(db.Integer, default=0)

    def tag_list(self):
        try:
            return json.loads(self.tags or "[]")
        except Exception:
            return []

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "display_name": self.display_name or self.name,
            "vendor": self.vendor, "tags": self.tag_list(),
            "input_price": self.input_price, "output_price": self.output_price,
            "cache_input_price": self.cache_input_price or 0,
            "official_input": self.official_input, "official_output": self.official_output,
            "description": self.description, "status": self.status, "sort": self.sort,
        }


class UsageLog(db.Model):
    __tablename__ = "usage_logs"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(64), unique=True, nullable=False)
    reserved_quota = db.Column(db.BigInteger, default=0, server_default="0", nullable=False)
    user_id = db.Column(db.Integer, index=True)
    tenant_id = db.Column(db.Integer, index=True)
    key_id = db.Column(db.Integer)
    channel_id = db.Column(db.Integer)
    model = db.Column(db.String(128), index=True)
    prompt_tokens = db.Column(db.Integer, default=0)
    completion_tokens = db.Column(db.Integer, default=0)
    quota = db.Column(db.BigInteger, default=0)
    stream = db.Column(db.Integer, default=0)
    latency_ms = db.Column(db.Integer, default=0)
    status = db.Column(db.String(16), default="ok")      # held / ok / error / aborted / blocked
    error_msg = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)
    # 计费快照(调用时点单价,调价不影响历史复算):金额单位 ¥
    input_rate = db.Column(db.Float, default=0.0)        # 输入单价 ¥/1M
    output_rate = db.Column(db.Float, default=0.0)       # 输出单价 ¥/1M
    cache_rate = db.Column(db.Float, default=0.0)        # 缓存命中单价快照 ¥/1M
    cache_hit_tokens = db.Column(db.Integer, default=0)  # 缓存命中的输入 tokens
    billing_source = db.Column(db.String(12), default="upstream")  # upstream=精确 / estimated=估算
    input_cost = db.Column(db.Float, default=0.0)        # 输入费用
    output_cost = db.Column(db.Float, default=0.0)       # 输出费用
    key_name = db.Column(db.String(64), default="")      # 密钥名冗余(密钥删除后仍可显示)
    # 资源包抵扣:pack_id 为本次占用的持有实例;pack_reserved 为预留时冻结的包 tokens
    pack_id = db.Column(db.Integer)
    pack_reserved = db.Column(db.BigInteger, default=0, server_default="0", nullable=False)

    def to_dict(self):
        return {
            "id": self.id, "model": self.model,
            "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
            "quota": self.quota, "stream": bool(self.stream),
            "latency_ms": self.latency_ms, "status": self.status,
            "error_msg": self.error_msg,
            "input_rate": self.input_rate or 0, "output_rate": self.output_rate or 0,
            "cache_rate": self.cache_rate or 0, "cache_hit_tokens": self.cache_hit_tokens or 0,
            "billing_source": self.billing_source or "upstream",
            "input_cost": self.input_cost or 0, "output_cost": self.output_cost or 0,
            "key_name": self.key_name or "",
            "pack_id": self.pack_id, "pack_reserved": self.pack_reserved or 0,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class TopupOrder(db.Model):
    """本地订单镜像(paykit 存原始订单,这里冗余一份便于后台列表与统计)。

    kind=credits 为余额充值;kind=resource_pack 为资源包购买,pack_model/pack_days/quota
    为下单时点的资源包快照(入账以镜像为准,定义后续调整不影响历史订单)。
    """
    __tablename__ = "topup_orders"
    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(64), unique=True, nullable=False)
    user_id = db.Column(db.Integer, index=True)
    package_id = db.Column(db.String(64))
    kind = db.Column(db.String(16), default="credits", server_default="credits", nullable=False)
    amount = db.Column(db.Integer, default=0)            # CNY 分
    quota = db.Column(db.BigInteger, default=0)          # 到账额度(余额 quota 或资源包 tokens)
    pack_model = db.Column(db.String(128), default="")   # 资源包绑定模型(kind=resource_pack)
    pack_days = db.Column(db.Integer, default=0)         # 资源包有效天数快照(0=永久)
    status = db.Column(db.String(16), default="pending") # pending/paid/refunded
    pay_method = db.Column(db.String(32), default="")
    trade_no = db.Column(db.String(128), default="")
    created_at = db.Column(db.DateTime, default=datetime.now)
    paid_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            "id": self.id, "order_no": self.order_no, "user_id": self.user_id,
            "package_id": self.package_id, "kind": self.kind or "credits",
            "amount": self.amount, "quota": self.quota,
            "pack_model": self.pack_model or "", "pack_days": self.pack_days or 0,
            "status": self.status, "pay_method": self.pay_method, "trade_no": self.trade_no,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "paid_at": self.paid_at.strftime("%Y-%m-%d %H:%M:%S") if self.paid_at else None,
        }


class RedemptionCode(db.Model):
    __tablename__ = "redemption_codes"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), unique=True, nullable=False)
    quota = db.Column(db.BigInteger, default=0)
    status = db.Column(db.Integer, default=1)            # 1 未用 0 已用
    batch = db.Column(db.String(32), default="")
    used_by = db.Column(db.Integer)
    used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id, "code": self.code, "quota": self.quota, "status": self.status,
            "batch": self.batch, "used_by": self.used_by,
            "used_at": self.used_at.strftime("%Y-%m-%d %H:%M:%S") if self.used_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class ResourcePackDef(db.Model):
    """资源包商品定义:面向单个模型的 tokens 包,由管理后台维护。

    以 tokens 计量:调用绑定模型时直接消耗 tokens,不按价格计费,用尽后回落余额。
    price 为售价(分);>0 即上架售卖,0/空 = 仅赠送(注册赠送/管理员发放)。
    """
    __tablename__ = "resource_pack_defs"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    model = db.Column(db.String(128), index=True, nullable=False)  # 绑定的模型名(模型目录 name)
    tokens = db.Column(db.BigInteger, default=0)         # 包内 tokens 总量
    price = db.Column(db.Integer, default=0)             # 售价(分);0 = 仅赠送不可购买
    valid_days = db.Column(db.Integer, default=365)      # 自发放起有效天数;0=永久
    description = db.Column(db.String(200), default="")
    status = db.Column(db.Integer, default=1)            # 1 启用 0 停用(停用后不参与赠送/售卖)
    sort = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "model": self.model,
            "tokens": self.tokens,
            "price": self.price, "price_yuan": round((self.price or 0) / 100, 2),
            "valid_days": self.valid_days, "description": self.description or "",
            "status": self.status, "sort": self.sort,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class UserResourcePack(db.Model):
    """用户持有的资源包实例;网关计费时优先消耗 tokens,惰性过期(到期即不再参与)。"""
    __tablename__ = "user_resource_packs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, index=True, nullable=False)
    pack_id = db.Column(db.Integer, index=True)          # 来源商品定义 id
    pack_name = db.Column(db.String(64), default="")     # 冗余(定义删除后仍可显示)
    model = db.Column(db.String(128), index=True, nullable=False)
    total_tokens = db.Column(db.BigInteger, default=0)
    used_tokens = db.Column(db.BigInteger, default=0)
    granted_type = db.Column(db.String(16), default="admin_grant")  # register_gift/admin_grant
    order_no = db.Column(db.String(64), default="")      # 预留(当前无购买来源)
    status = db.Column(db.Integer, default=1)            # 1 有效 0 作废(管理员手动作废)
    created_at = db.Column(db.DateTime, default=datetime.now)
    expires_at = db.Column(db.DateTime)                  # NULL=永久

    @property
    def state(self):
        """动态状态:disabled/active/expired/exhausted。"""
        if self.status != 1:
            return "disabled"
        if self.expires_at is not None and self.expires_at <= datetime.now():
            return "expired"
        if (self.used_tokens or 0) >= (self.total_tokens or 0):
            return "exhausted"
        return "active"

    def to_dict(self, username=None):
        total = self.total_tokens or 0
        used = self.used_tokens or 0
        remaining = max(0, total - used)
        return {
            "id": self.id, "user_id": self.user_id, "username": username,
            "pack_id": self.pack_id, "pack_name": self.pack_name or f"资源包#{self.pack_id}",
            "model": self.model,
            "total_tokens": total, "used_tokens": used, "remaining_tokens": remaining,
            "granted_type": self.granted_type, "order_no": self.order_no or "",
            "status": self.status, "state": self.state,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "expires_at": self.expires_at.strftime("%Y-%m-%d %H:%M:%S") if self.expires_at else None,
        }


class InviteReward(db.Model):
    """邀请奖励。status: 0=待发放(被邀请人未达门槛) 1=已发放 2=无效(风控拒绝)。"""
    __tablename__ = "invite_rewards"
    id = db.Column(db.Integer, primary_key=True)
    from_uid = db.Column(db.Integer, index=True)
    to_uid = db.Column(db.Integer, index=True)
    quota = db.Column(db.BigInteger, default=0)
    status = db.Column(db.Integer, default=0)
    reason = db.Column(db.String(120), default="")   # 无效原因 / 发放触发说明
    created_at = db.Column(db.DateTime, default=datetime.now)
    paid_at = db.Column(db.DateTime)


class SmsRecord(db.Model):
    __tablename__ = "sms_records"
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), index=True)
    purpose = db.Column(db.String(32), default="login")
    code = db.Column(db.String(8), default="")           # dev 模式自产验证码
    msg_id = db.Column(db.String(64), default="")        # 历史遗留(原 jsms 模式),已不写入
    expires_at = db.Column(db.DateTime)
    used = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)


class Setting(db.Model):
    __tablename__ = "settings"
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, default="")

    @staticmethod
    def get(key, default=None, cast=None):
        row = db.session.get(Setting, key)
        if row is None or row.value == "":
            return default
        try:
            v = json.loads(row.value)
        except Exception:
            v = row.value
        return v if cast is None else cast(v)

    @staticmethod
    def put(key, value):
        row = db.session.get(Setting, key)
        if row is None:
            row = Setting(key=key)
            db.session.add(row)
        row.value = json.dumps(value, ensure_ascii=False)
        return row


class Captcha(db.Model):
    """滑块挑战(kind=1)与短信票据(kind=2),见 services/captcha 说明。"""
    __tablename__ = "captchas"
    id = db.Column(db.Integer, primary_key=True)
    cid = db.Column(db.String(64), unique=True)
    kind = db.Column(db.Integer, default=1)          # 1=滑块挑战 2=短信票据
    x = db.Column(db.Integer, default=0)             # 缺口真实 x(kind=1)
    tries = db.Column(db.Integer, default=0)
    used = db.Column(db.Integer, default=0)
    phone = db.Column(db.String(20), default="")
    ip = db.Column(db.String(64), default="")
    created_at = db.Column(db.DateTime, default=datetime.now)
    expires_at = db.Column(db.DateTime)


class AuthThrottle(db.Model):
    """认证相关频控计数(登录失败/兑换尝试),多 worker 下以 DB 为准。"""
    __tablename__ = "auth_throttle"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), index=True)
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)


class Invoice(db.Model):
    """发票申请。status: 0=待开具 1=已开具 2=已拒绝。金额单位:分。"""
    __tablename__ = "invoices"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, index=True)
    amount = db.Column(db.Integer, default=0)            # 开票金额(分)= 关联订单金额合计
    inv_type = db.Column(db.String(16), default="电子普通发票")
    title_type = db.Column(db.String(16), default="企业")  # 企业 / 个人
    title = db.Column(db.String(128), default="")
    tax_no = db.Column(db.String(32), default="")
    email = db.Column(db.String(128), default="")
    remark = db.Column(db.String(200), default="")
    status = db.Column(db.Integer, default=0)
    invoice_no = db.Column(db.String(64), default="")
    reject_reason = db.Column(db.String(200), default="")
    file_name = db.Column(db.String(255), default="")       # 发票文件原始文件名(展示用)
    file_size = db.Column(db.Integer, default=0)            # 发票文件大小(字节)
    file_uploaded_at = db.Column(db.DateTime)               # 管理员上传时间
    created_at = db.Column(db.DateTime, default=datetime.now)
    issued_at = db.Column(db.DateTime)

    def to_dict(self):
        items = InvoiceItem.query.filter_by(invoice_id=self.id).all()
        return {
            "id": self.id, "amount": self.amount, "amount_yuan": (self.amount or 0) / 100,
            "inv_type": self.inv_type, "title_type": self.title_type,
            "title": self.title, "tax_no": self.tax_no, "email": self.email,
            "remark": self.remark, "status": self.status,
            "invoice_no": self.invoice_no, "reject_reason": self.reject_reason,
            "file_name": self.file_name or "", "file_size": self.file_size or 0,
            "file_uploaded_at": self.file_uploaded_at.strftime("%Y-%m-%d %H:%M") if self.file_uploaded_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
            "issued_at": self.issued_at.strftime("%Y-%m-%d %H:%M") if self.issued_at else None,
            "orders": [{"order_no": i.order_no, "amount": i.amount, "amount_yuan": i.amount / 100} for i in items],
        }


class InvoiceItem(db.Model):
    """发票-充值订单关联:每单累计开票额度守恒。"""
    __tablename__ = "invoice_items"
    __table_args__ = (db.UniqueConstraint("invoice_id", "order_no", name="uq_invoice_item_order"),)
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, index=True)
    order_no = db.Column(db.String(64), index=True)
    user_id = db.Column(db.Integer, index=True)
    amount = db.Column(db.Integer, default=0)            # 本发票占用该订单的开票金额(分)
    active = db.Column(db.Integer, default=1, nullable=False)


class Notice(db.Model):
    """管理后台发布的站内消息(面向全体用户)。status: 1=已发布 0=已下架。"""
    __tablename__ = "notices"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), nullable=False)
    body = db.Column(db.Text, default="")
    status = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id, "title": self.title, "body": self.body or "",
            "status": self.status,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class NoticeRead(db.Model):
    """用户对站内消息的已读记录。"""
    __tablename__ = "notice_reads"
    __table_args__ = (db.UniqueConstraint("notice_id", "user_id", name="uq_notice_read"),)
    id = db.Column(db.Integer, primary_key=True)
    notice_id = db.Column(db.Integer, index=True, nullable=False)
    user_id = db.Column(db.Integer, index=True, nullable=False)
    read_at = db.Column(db.DateTime, default=datetime.now)


class Ticket(db.Model):
    """工单。status: open=待处理(用户新建/回复) answered=已回复(待用户查看) closed=已关闭。"""
    __tablename__ = "tickets"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, index=True, nullable=False)
    title = db.Column(db.String(128), nullable=False)
    status = db.Column(db.String(16), default="open", index=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, index=True)

    def to_dict(self, username=None, preview=None):
        return {
            "id": self.id, "user_id": self.user_id, "username": username,
            "title": self.title, "status": self.status,
            "preview": preview, "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M") if self.updated_at else None,
        }


class TicketMessage(db.Model):
    """工单对话消息。sender_role: user / admin。"""
    __tablename__ = "ticket_messages"
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, index=True, nullable=False)
    sender_role = db.Column(db.String(8), nullable=False)
    sender_id = db.Column(db.Integer)
    sender_name = db.Column(db.String(64), default="")
    content = db.Column(db.Text, nullable=False)
    file_name = db.Column(db.String(255), default="")   # 附件原始文件名(展示)
    file_key = db.Column(db.String(128), default="")    # 附件存储 key(服务端生成)
    file_size = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id, "ticket_id": self.ticket_id, "sender_role": self.sender_role,
            "sender_name": self.sender_name or "",
            "content": self.content or "",
            "file_name": self.file_name or "", "file_key": self.file_key or "",
            "file_size": self.file_size or 0,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
        }


class AuditLog(db.Model):
    """管理操作审计。私有化交付中用于追责与等保留痕。"""
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, index=True)
    actor_id = db.Column(db.Integer, index=True)
    actor_name = db.Column(db.String(64), default="")
    action = db.Column(db.String(64), index=True, nullable=False)
    target_type = db.Column(db.String(32), default="")
    target_id = db.Column(db.String(64), default="")
    detail = db.Column(db.Text, default="")
    ip = db.Column(db.String(64), default="")
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)

    def to_dict(self):
        return {
            "id": self.id, "tenant_id": self.tenant_id,
            "actor_id": self.actor_id, "actor_name": self.actor_name or "",
            "action": self.action, "target_type": self.target_type or "",
            "target_id": self.target_id or "", "detail": self.detail or "",
            "ip": self.ip or "",
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }

