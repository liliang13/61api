#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""计费换算与原子额度预留/结算。额度单位: 500000 quota = ¥1。

资金顺序:模型绑定的资源包(最快到期先用)优先按 tokens 抵扣——包内 tokens 不计价,
超出部分按模型价格从余额扣费。组织额度按全额费用预留,是第二道闸。
"""
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, update

from extensions import db
from models import ApiKey, Tenant, UsageLog, User, UserResourcePack


class BillingError(RuntimeError):
    def __init__(self, message="计费服务不可用", *, status=503, code="billing_error"):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class Reservation:
    request_id: str
    user_id: int
    key_id: int | None
    reserved_quota: int           # 全额费用预留(含资源包将抵扣的部分)
    tenant_id: int | None = None
    pack_id: int | None = None    # 预留时冻结 tokens 的资源包实例
    pack_tokens: int = 0          # 资源包冻结的 tokens
    user_reserved: int = 0        # 余额侧冻结费用(reserved_quota - 包抵扣份额)


def yuan_to_quota(cny: float) -> int:
    return int(round(float(cny) * 500_000))


def quota_to_yuan(quota) -> float:
    return round((quota or 0) / 500_000, 6)


def compute_cost(model_item, prompt_tokens: int, completion_tokens: int,
                 cache_hit_tokens: int = 0) -> dict:
    """分项计费:输入(区分缓存命中/未命中)/输出(¥)+ 合计 quota(最低 1)。"""
    hit = min(max(0, cache_hit_tokens), prompt_tokens)
    miss = prompt_tokens - hit
    cache_price = (model_item.cache_input_price or 0)
    hit_fee = hit / 1_000_000.0 * cache_price if cache_price > 0 else hit / 1_000_000.0 * (model_item.input_price or 0)
    miss_fee = miss / 1_000_000.0 * (model_item.input_price or 0)
    input_cost = hit_fee + miss_fee
    output_cost = completion_tokens / 1_000_000.0 * (model_item.output_price or 0)
    return {
        "input_cost": round(input_cost, 8),
        "output_cost": round(output_cost, 8),
        "cache_cost": round(hit_fee, 8),
        "quota": max(1, yuan_to_quota(input_cost + output_cost)),
    }


def chat_cost_quota(model_item, prompt_tokens: int, completion_tokens: int) -> int:
    return compute_cost(model_item, prompt_tokens, completion_tokens)["quota"]


def estimate_tokens(text: str) -> int:
    """上游未返回 usage 时兜底估算。汉字约 1 token/字, ASCII 约 1 token/4 字符。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    other = len(text) - cjk
    return max(1, cjk + other // 4)


def conservative_tokens(value) -> int:
    """用于预留的输入上限,按 UTF-8 字节数避免常见估算低报。"""
    import json
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return max(1, len(text.encode("utf-8")))


def cny_to_quota(cny_fen: int) -> int:
    return yuan_to_quota(cny_fen / 100.0)


def _pack_live():
    """资源包可参与计费的实时条件(每次调用生成,避免固化 now)。"""
    return (
        UserResourcePack.status == 1,
        UserResourcePack.total_tokens > func.coalesce(UserResourcePack.used_tokens, 0),
        or_(UserResourcePack.expires_at.is_(None), UserResourcePack.expires_at > datetime.now()),
    )


def pack_available_tokens(user_id: int, model: str | None = None) -> int:
    """用户(可限定模型)全部有效资源包的剩余 tokens 合计。"""
    conds = [UserResourcePack.user_id == user_id, *_pack_live()]
    if model:
        conds.append(UserResourcePack.model == model)
    total = db.session.query(
        func.coalesce(func.sum(UserResourcePack.total_tokens - func.coalesce(UserResourcePack.used_tokens, 0)), 0)
    ).filter(*conds).scalar()
    return int(total or 0)


def user_has_pack_for(user_id: int, model: str | None = None) -> bool:
    """是否存在可用资源包;余额为零时网关凭它放行,实际额度仍由 reserve 把关。"""
    conds = [UserResourcePack.user_id == user_id, *_pack_live()]
    if model:
        conds.append(UserResourcePack.model == model)
    return db.session.query(UserResourcePack.id).filter(*conds).first() is not None


def _pack_snapshot(user_id: int, model: str, need: int):
    """挑一个该模型可用、最快到期的资源包,返回 (id, 冻结 tokens);没有则 (None, 0)。

    冻结量是读取时点的剩余上限,真实扣减由 reserve 里的原子 UPDATE 兜底校验。
    """
    if need <= 0:
        return None, 0
    row = (db.session.query(UserResourcePack.id,
                            UserResourcePack.total_tokens - func.coalesce(UserResourcePack.used_tokens, 0))
           .filter(UserResourcePack.user_id == user_id, UserResourcePack.model == model, *_pack_live())
           .order_by(UserResourcePack.expires_at.is_(None), UserResourcePack.expires_at.asc())
           .first())
    if row is None:
        return None, 0
    return row[0], min(max(0, int(row[1] or 0)), need)


def _pack_cost_share(full_cost: int, total_tokens: int, pack_tokens: int) -> int:
    """包内 tokens 按单价占比折算的抵扣费用(不超过全额费用)。"""
    if pack_tokens <= 0 or total_tokens <= 0:
        return 0
    return min(int(full_cost), int(full_cost) * int(pack_tokens) // int(total_tokens))


def reserve(*, user, api_key, channel, item, prompt_tokens, completion_tokens,
            stream=False, request_id=None, tenant=None) -> Reservation:
    """原子冻结本次调用的最大可能消耗; held 记录本身不计消费量。

    全额费用先做预留上限,再挑选资源包冻结其中一部分 tokens,
    余额只冻结「全额费用 - 包内 tokens 按单价折算」的差值;
    任一步失败统一 rollback,已执行的包冻结随之撤销。
    """
    full = compute_cost(item, prompt_tokens, completion_tokens)["quota"]
    tokens_reserved = max(1, int(prompt_tokens) + int(completion_tokens))
    pack_id, pack_tokens = _pack_snapshot(user.id, item.name, tokens_reserved)
    user_reserved = full - _pack_cost_share(full, tokens_reserved, pack_tokens)
    if tenant is None and getattr(user, "tenant_id", None):
        tenant = db.session.get(Tenant, user.tenant_id)
    reservation = Reservation(request_id or uuid.uuid4().hex, user.id,
                              api_key.id if api_key else None, full,
                              tenant.id if tenant else None,
                              pack_id if pack_tokens else None, pack_tokens,
                              user_reserved)
    try:
        if tenant is not None and tenant.status != 1:
            raise BillingError("所属组织已停用,请联系管理员", status=403,
                               code="tenant_disabled")
        if tenant is not None and (tenant.quota or 0) >= 0:
            result = db.session.execute(
                update(Tenant)
                .where(Tenant.id == tenant.id, Tenant.status == 1, Tenant.quota >= full)
                .values(quota=Tenant.quota - full)
            )
            if result.rowcount != 1:
                raise BillingError("组织额度不足,请联系管理员", status=402,
                                   code="insufficient_tenant_quota")
        if pack_tokens:
            result = db.session.execute(
                update(UserResourcePack)
                .where(UserResourcePack.id == pack_id, *_pack_live(),
                       UserResourcePack.total_tokens - func.coalesce(UserResourcePack.used_tokens, 0)
                       >= pack_tokens)
                .values(used_tokens=func.coalesce(UserResourcePack.used_tokens, 0) + pack_tokens)
            )
            if result.rowcount != 1:  # 并发下包余额被抢占:tokens 全部转余额计费
                reservation = Reservation(reservation.request_id, reservation.user_id,
                                          reservation.key_id, reservation.reserved_quota,
                                          reservation.tenant_id, None, 0, full)
                user_reserved = full
        if user_reserved > 0:
            result = db.session.execute(
                update(User).where(User.id == user.id, User.status == 1, User.quota >= user_reserved)
                .values(quota=User.quota - user_reserved)
            )
            if result.rowcount != 1:
                raise BillingError("余额不足,请先充值", status=402, code="insufficient_quota")
        from config import GATEWAY_MAX_CONCURRENT_PER_USER
        limit = (getattr(user, "concurrency_limit", 0) or 0) or GATEWAY_MAX_CONCURRENT_PER_USER
        active = UsageLog.query.filter_by(user_id=user.id, status="held").count()
        if active >= limit:
            raise BillingError("并发请求过多,请稍后重试", status=429, code="rate_limit_exceeded")
        if api_key is not None:
            condition = (ApiKey.id == api_key.id, ApiKey.user_id == user.id, ApiKey.status == 1)
            result = db.session.execute(
                update(ApiKey).where(*condition).where(
                    (ApiKey.quota_limit <= 0) | (ApiKey.quota_limit - ApiKey.used_quota >= full))
                .values(used_quota=func.coalesce(ApiKey.used_quota, 0) + full)
            )
            if result.rowcount != 1:
                raise BillingError("该密钥额度不足", status=402, code="insufficient_quota")
        db.session.add(UsageLog(
            request_id=reservation.request_id, reserved_quota=full,
            user_id=user.id, tenant_id=reservation.tenant_id, key_id=reservation.key_id,
            channel_id=channel.id if channel else None, model=item.name,
            prompt_tokens=0, completion_tokens=0, quota=0,
            stream=1 if stream else 0, status="held",
            input_rate=item.input_price or 0, output_rate=item.output_price or 0,
            cache_rate=item.cache_input_price or 0,
            key_name=api_key.name if api_key else "",
            pack_id=reservation.pack_id, pack_reserved=reservation.pack_tokens,
        ))
        db.session.commit()
        return reservation
    except BillingError:
        db.session.rollback()
        raise
    except Exception as exc:
        db.session.rollback()
        raise BillingError() from exc


def settle(reservation: Reservation, *, channel, item, prompt_tokens, completion_tokens,
           latency_ms=0, stream=False, status="ok", error_msg="", cache_hit=0,
           source="upstream") -> int:
    """将预留原子转为实际消耗;重复结算直接返回首次结果。

    实际 tokens 先被资源包消耗(以冻结量为上限),余额只承担折算后的费用差值;
    UsageLog.quota 记录余额实付(全包抵扣时为 0),失败/中止时两路全额退回。
    """
    billed = compute_cost(item, prompt_tokens, completion_tokens, cache_hit) if status == "ok" else {
        "input_cost": 0, "output_cost": 0, "cache_cost": 0, "quota": 0,
    }
    full_cost = billed["quota"]
    if full_cost > reservation.reserved_quota:
        error_msg = ((error_msg + "; ") if error_msg else "") + "actual cost exceeded reservation; capped"
        full_cost = reservation.reserved_quota
    actual_tokens = max(0, int(prompt_tokens) + int(completion_tokens))
    pack_used = min(reservation.pack_tokens, actual_tokens) if status == "ok" else 0
    pack_cost = _pack_cost_share(full_cost, actual_tokens, pack_used)
    # 保守预留下实际 tokens 不会超过预留;上游超发(如不遵守 max_tokens)时按余额预留封顶
    user_cost = min(full_cost - pack_cost, reservation.user_reserved)
    try:
        result = db.session.execute(
            update(UsageLog)
            .where(UsageLog.request_id == reservation.request_id, UsageLog.status == "held")
            .values(channel_id=channel.id if channel else None,
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                    quota=user_cost, stream=1 if stream else 0, latency_ms=latency_ms,
                    status=status, error_msg=(error_msg or "")[:500],
                    cache_hit_tokens=cache_hit, billing_source=source,
                    input_cost=billed["input_cost"], output_cost=billed["output_cost"])
        )
        if result.rowcount != 1:
            log = UsageLog.query.filter_by(request_id=reservation.request_id).first()
            if log is None:
                raise BillingError("计费预留记录不存在")
            db.session.rollback()
            return log.quota or 0
        db.session.execute(
            update(User).where(User.id == reservation.user_id)
            .values(quota=User.quota + (reservation.user_reserved - user_cost),
                    used_quota=func.coalesce(User.used_quota, 0) + user_cost)
        )
        if reservation.pack_id is not None:
            db.session.execute(
                update(UserResourcePack).where(UserResourcePack.id == reservation.pack_id)
                .values(used_tokens=func.coalesce(UserResourcePack.used_tokens, 0)
                        + pack_used - reservation.pack_tokens)
            )
        if reservation.tenant_id is not None:
            db.session.execute(
                update(Tenant).where(Tenant.id == reservation.tenant_id, Tenant.quota >= 0)
                .values(quota=Tenant.quota + (reservation.reserved_quota - full_cost))
            )
            db.session.execute(
                update(Tenant).where(Tenant.id == reservation.tenant_id)
                .values(used_quota=func.coalesce(Tenant.used_quota, 0) + full_cost)
            )
        if reservation.key_id is not None:
            db.session.execute(
                update(ApiKey).where(ApiKey.id == reservation.key_id)
                .values(used_quota=ApiKey.used_quota - (reservation.reserved_quota - user_cost),
                        last_used_at=datetime.now())
            )
        db.session.commit()
        return user_cost
    except BillingError:
        db.session.rollback()
        raise
    except Exception as exc:
        db.session.rollback()
        raise BillingError("计费结算失败") from exc


def abort(reservation: Reservation, *, error_msg="", status="aborted") -> None:
    """释放全部预留;已结算或已释放的调用保持幂等。"""
    try:
        result = db.session.execute(
            update(UsageLog)
            .where(UsageLog.request_id == reservation.request_id, UsageLog.status == "held")
            .values(status=status, quota=0, error_msg=(error_msg or "")[:500])
        )
        if result.rowcount != 1:
            log = UsageLog.query.filter_by(request_id=reservation.request_id).first()
            if log is None:
                raise BillingError("计费预留记录不存在")
            db.session.rollback()
            return
        db.session.execute(
            update(User).where(User.id == reservation.user_id)
            .values(quota=User.quota + (reservation.user_reserved or 0))
        )
        if reservation.pack_id is not None:
            db.session.execute(
                update(UserResourcePack).where(UserResourcePack.id == reservation.pack_id)
                .values(used_tokens=func.coalesce(UserResourcePack.used_tokens, 0)
                        - (reservation.pack_tokens or 0))
            )
        if reservation.tenant_id is not None:
            db.session.execute(
                update(Tenant).where(Tenant.id == reservation.tenant_id, Tenant.quota >= 0)
                .values(quota=Tenant.quota + reservation.reserved_quota)
            )
        if reservation.key_id is not None:
            db.session.execute(
                update(ApiKey).where(ApiKey.id == reservation.key_id)
                .values(used_quota=ApiKey.used_quota - reservation.reserved_quota)
            )
        db.session.commit()
    except BillingError:
        db.session.rollback()
        raise
    except Exception as exc:
        db.session.rollback()
        raise BillingError("释放计费预留失败") from exc
