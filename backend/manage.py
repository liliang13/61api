#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

os.environ["61API_SKIP_PAYMENT"] = "1"

from app import app, initialize_database
from config import BASE_DIR
from extensions import db
from models import UsageLog, gen_unique_uid


def migrate():
    with app.app_context():
        initialize_database()
    print("数据库迁移完成")


def backup(target):
    destination = Path(target).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    final_dir = destination / stamp
    temp_dir = destination / ("." + stamp + ".tmp")
    if final_dir.exists() or temp_dir.exists():
        raise RuntimeError("备份目录已存在，请更换目标目录")
    temp_dir.mkdir(mode=0o700)
    with app.app_context():
        database_path = db.engine.url.database
    sources = {
        "61api.db": Path(database_path),
        "paykit_orders.db": BASE_DIR / "data" / "paykit_orders.db",
    }
    manifest = {"created_at": datetime.now().isoformat(), "databases": {}}
    try:
        for name, source in sources.items():
            if not source or not source.exists():
                if name == "paykit_orders.db":
                    continue
                raise RuntimeError(f"数据库不存在: {source}")
            output = temp_dir / name
            with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(output)) as dst:
                src.backup(dst)
            with closing(sqlite3.connect(output)) as check:
                result = check.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"{name} 备份完整性检查失败: {result}")
            os.chmod(output, 0o600)
            manifest["databases"][name] = {"integrity": result}
        manifest_path = temp_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(manifest_path, 0o600)
        temp_dir.rename(final_dir)
    except Exception:
        for path in temp_dir.glob("*"):
            path.unlink()
        temp_dir.rmdir()
        raise
    print(final_dir)


def check():
    from sqlalchemy import inspect, text
    required = {"users", "api_keys", "usage_logs", "topup_orders", "settings", "invoice_items",
                "channel_events", "tenants", "audit_logs",
                "resource_pack_defs", "user_resource_packs"}
    with app.app_context():
        db.session.execute(text("SELECT 1"))
        missing = sorted(required - set(inspect(db.engine).get_table_names()))
        from models import Setting
        version = Setting.get("schema_version", 0, int)
        held = UsageLog.query.filter_by(status="held").count()
    if missing:
        raise RuntimeError("缺少数据表: " + ", ".join(missing))
    if version != 14:
        raise RuntimeError(f"数据库迁移版本不一致: {version}")
    print(json.dumps({"ok": True, "schema_version": version, "held_reservations": held}, ensure_ascii=False))


def reservations(minutes):
    from models import ApiKey, User
    cutoff = datetime.now() - timedelta(minutes=minutes)
    with app.app_context():
        rows = (UsageLog.query.filter(UsageLog.status == "held", UsageLog.created_at < cutoff)
                .order_by(UsageLog.created_at).all())
        result = []
        for row in rows:
            user = db.session.get(User, row.user_id)
            key = db.session.get(ApiKey, row.key_id) if row.key_id else None
            result.append({"request_id": row.request_id, "user": user.username if user else row.user_id,
                           "key": key.key_prefix if key else None, "reserved_quota": row.reserved_quota,
                           "created_at": row.created_at.isoformat()})
    print(json.dumps(result, ensure_ascii=False, indent=2))


def probe(channel_id=None):
    from services.probe import probe_all
    with app.app_context():
        results = probe_all(channel_id)
    print(json.dumps(results, ensure_ascii=False, indent=2))


def init_private():
    """私有化首装:建表/迁移/种子数据,输出默认组织与管理员信息。"""
    with app.app_context():
        initialize_database()
        from models import Tenant, User
        tenant = Tenant.query.order_by(Tenant.id).first()
        admin = User.query.filter_by(role="admin").order_by(User.id).first()
        print(json.dumps({
            "ok": True,
            "tenant": tenant.to_dict() if tenant else None,
            "admin": {"id": admin.id, "username": admin.username, "uid": admin.uid} if admin else None,
        }, ensure_ascii=False, indent=2))


def create_tenant(name, slug, quota_yuan):
    with app.app_context():
        from models import Tenant
        from services.billing import yuan_to_quota
        if Tenant.query.filter_by(slug=slug).first():
            raise RuntimeError("组织标识已存在")
        tenant = Tenant(name=name, slug=slug,
                        quota=-1 if quota_yuan < 0 else yuan_to_quota(quota_yuan))
        db.session.add(tenant)
        db.session.commit()
        print(json.dumps(tenant.to_dict(), ensure_ascii=False, indent=2))


def create_user(username, password, tenant_id, role, quota_yuan):
    import re
    from werkzeug.security import generate_password_hash
    from models import Tenant, User
    from services.billing import yuan_to_quota
    if len(password) < 10 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise RuntimeError("密码至少 10 位且必须包含字母和数字")
    if role not in ("user", "admin"):
        raise RuntimeError("角色只能是 user 或 admin")
    with app.app_context():
        if User.query.filter_by(username=username).first():
            raise RuntimeError("用户名已存在")
        tenant = db.session.get(Tenant, tenant_id)
        if tenant is None:
            raise RuntimeError("组织不存在")
        user = User(username=username, tenant_id=tenant.id, role=role,
                    password_hash=generate_password_hash(password),
                    quota=yuan_to_quota(max(0, quota_yuan)),
                    invite_code=os.urandom(4).hex().upper(), status=1)
        db.session.add(user)
        db.session.flush()
        user.uid = gen_unique_uid()
        db.session.commit()
        print(json.dumps(dict(user.to_dict(), tenant_name=tenant.name),
                         ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="61API 发布与运维命令")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    backup_parser = sub.add_parser("backup")
    backup_parser.add_argument("--target", required=True)
    sub.add_parser("check")
    reservation_parser = sub.add_parser("reservations")
    reservation_parser.add_argument("--older-than-minutes", type=int, default=30)
    probe_parser = sub.add_parser("probe")
    probe_parser.add_argument("--channel", type=int, default=None)
    sub.add_parser("init-private")
    tenant_parser = sub.add_parser("create-tenant")
    tenant_parser.add_argument("--name", required=True)
    tenant_parser.add_argument("--slug", required=True)
    tenant_parser.add_argument("--quota-yuan", type=float, default=-1)
    user_parser = sub.add_parser("create-user")
    user_parser.add_argument("--username", required=True)
    user_parser.add_argument("--password", required=True)
    user_parser.add_argument("--tenant-id", type=int, required=True)
    user_parser.add_argument("--role", default="user")
    user_parser.add_argument("--quota-yuan", type=float, default=0)
    args = parser.parse_args()
    if args.command == "migrate":
        migrate()
    elif args.command == "backup":
        backup(args.target)
    elif args.command == "check":
        check()
    elif args.command == "reservations":
        reservations(max(1, args.older_than_minutes))
    elif args.command == "probe":
        probe(args.channel)
    elif args.command == "init-private":
        init_private()
    elif args.command == "create-tenant":
        create_tenant(args.name, args.slug, args.quota_yuan)
    elif args.command == "create-user":
        create_user(args.username, args.password, args.tenant_id, args.role, args.quota_yuan)


if __name__ == "__main__":
    main()
