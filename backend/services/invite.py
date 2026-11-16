#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""邀请奖励防作弊与延迟发放。

规则(全部满足才建"待发放"记录):
  1. 邀请人最近登录 IP != 被邀请人注册 IP(防自邀自刷)
  2. 同一注册 IP 只认可第一个被邀请人(防 IP 农场批量注册)
  3. 拒绝虚拟运营商号段(162/165/167/170/171,接码平台常用)
  4. 单邀请人单日有效邀请数上限(默认 10)
发放:被邀请人累计充值 >= invite_min_topup_yuan(默认 ¥10)时,由支付成功钩子触发发放。
"""
from datetime import datetime, timedelta

from extensions import db
from models import InviteReward, Setting, TopupOrder, User

VIRTUAL_PREFIXES = ("162", "165", "167", "170", "171")
DAILY_LIMIT_DEFAULT = 10
MIN_TOPUP_DEFAULT = 10.0


def _cfg(key, default):
    return float(Setting.get(key, default))


def review_invite(inviter, new_user) -> bool:
    """注册时审核邀请关系。通过建待发放记录;拒绝建无效记录(留审计)。"""
    ip = new_user.register_ip or ""
    if inviter.last_login_ip and inviter.last_login_ip == ip:
        db.session.add(InviteReward(from_uid=inviter.id, to_uid=new_user.id, status=2,
                                    reason="注册 IP 与邀请人登录 IP 相同"))
        return False
    if ip:
        dup = (InviteReward.query
               .join(User, User.id == InviteReward.to_uid)
               .filter(User.register_ip == ip, InviteReward.status.in_((0, 1)),
                       User.id != new_user.id).count())
        if dup:
            db.session.add(InviteReward(from_uid=inviter.id, to_uid=new_user.id, status=2,
                                        reason="同 IP 已存在其他受邀账号"))
            return False
    if new_user.phone and new_user.phone[:3] in VIRTUAL_PREFIXES and             Setting.get("invite_block_virtual", True):
        db.session.add(InviteReward(from_uid=inviter.id, to_uid=new_user.id, status=2,
                                    reason="虚拟运营商号段不参与奖励"))
        return False
    limit = int(_cfg("invite_daily_limit", DAILY_LIMIT_DEFAULT))
    day_ago = datetime.now() - timedelta(days=1)
    used = InviteReward.query.filter(
        InviteReward.from_uid == inviter.id,
        InviteReward.status.in_((0, 1)),
        InviteReward.created_at > day_ago).count()
    if used >= limit:
        db.session.add(InviteReward(from_uid=inviter.id, to_uid=new_user.id, status=2,
                                    reason="邀请人单日邀请已达上限(" + str(limit) + ")"))
        return False

    from services.billing import yuan_to_quota
    bonus = yuan_to_quota(float(Setting.get("invite_bonus_cny", 1.0)))
    db.session.add(InviteReward(from_uid=inviter.id, to_uid=new_user.id, quota=bonus,
                                status=0, reason="待被邀请人累计充值达标"))
    return True


def _paid_total(user_id):
    return (db.session.query(db.func.coalesce(db.func.sum(TopupOrder.amount), 0))
            .filter(TopupOrder.user_id == user_id, TopupOrder.status == "paid")
            .scalar() or 0)


def grant_pending_for(user_id, commit=True):
    """累计充值达标后以条件更新发放奖励,重复或并发调用不会重复加款。"""
    threshold = _cfg("invite_min_topup_yuan", MIN_TOPUP_DEFAULT)
    paid_total = _paid_total(user_id)
    if paid_total < threshold * 100:
        return
    pending = InviteReward.query.filter_by(to_uid=user_id, status=0).all()
    now = datetime.now()
    for r in pending:
        changed = (db.session.query(InviteReward)
                   .filter(InviteReward.id == r.id, InviteReward.status == 0)
                   .update({"status": 1, "paid_at": now,
                            "reason": "被邀请人累计充值达标(¥%.2f)" % (paid_total / 100)},
                           synchronize_session=False))
        if not changed:
            continue
        credited = (db.session.query(User).filter(User.id == r.from_uid)
                    .update({"quota": db.func.coalesce(User.quota, 0) + r.quota},
                            synchronize_session=False))
        if credited != 1:
            raise RuntimeError("邀请人不存在")
    if commit:
        db.session.commit()


def revoke_ineligible_for(user_id):
    """退款使累计充值低于门槛时回收已发奖励;调用方负责提交事务。"""
    threshold = _cfg("invite_min_topup_yuan", MIN_TOPUP_DEFAULT)
    if _paid_total(user_id) >= threshold * 100:
        return
    from sqlalchemy import case
    rewards = InviteReward.query.filter_by(to_uid=user_id, status=1).all()
    for r in rewards:
        changed = (db.session.query(InviteReward)
                   .filter(InviteReward.id == r.id, InviteReward.status == 1)
                   .update({"status": 2,
                            "reason": "充值退款后未达邀请奖励门槛,奖励已回收"},
                           synchronize_session=False))
        if not changed:
            continue
        quota = db.func.coalesce(User.quota, 0)
        debited = (db.session.query(User).filter(User.id == r.from_uid)
                   .update({"quota": case((quota >= r.quota, quota - r.quota), else_=0)},
                           synchronize_session=False))
        if debited != 1:
            raise RuntimeError("邀请人不存在")
