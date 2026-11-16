#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""管理操作审计写入。审计失败只记日志,不影响主业务。"""
import json

from flask import current_app, g, has_request_context

from extensions import client_ip, db
from models import AuditLog


def record(action, *, target_type="", target_id="", detail="", tenant_id=None,
           actor=None, commit=True):
    """写入一条审计记录。action 建议用 `模块.动作` 形式,如 user.create。"""
    try:
        if actor is None and has_request_context():
            actor = getattr(g, "user", None)
        if tenant_id is None and actor is not None:
            tenant_id = getattr(actor, "tenant_id", None)
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail, ensure_ascii=False, separators=(",", ":"))
        row = AuditLog(
            tenant_id=tenant_id,
            actor_id=getattr(actor, "id", None) if actor is not None else None,
            actor_name=(getattr(actor, "username", "") or "")[:64] if actor is not None else "",
            action=action[:64],
            target_type=(target_type or "")[:32],
            target_id=str(target_id or "")[:64],
            detail=(detail or "")[:4000],
            ip=client_ip() if has_request_context() else "",
        )
        db.session.add(row)
        if commit:
            db.session.commit()
        return row
    except Exception:  # pragma: no cover - 审计失败不应影响主流程
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.exception("audit record failed: %s", action)
        return None
