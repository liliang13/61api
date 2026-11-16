#!/usr/bin/env python3
try:
    from gevent import monkey
    monkey.patch_all()
except ImportError:
    pass

import os

from flask import Flask, abort, jsonify, request, send_from_directory
from flask_cors import CORS

from config import (BASE_DIR, CORS_ORIGINS, FEATURE_PAYMENTS, IS_PRIVATE,
                    IS_PRODUCTION, MAX_CONTENT_LENGTH, SECRET_KEY,
                    SESSION_COOKIE_NAME, SESSION_COOKIE_SECURE,
                    SQLALCHEMY_DATABASE_URI)
from extensions import db

DIST_DIR = (BASE_DIR.parent / "frontend" / "dist").resolve()
SCHEMA_VERSION = 14


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.update(
        SECRET_KEY=SECRET_KEY,
        SQLALCHEMY_DATABASE_URI=SQLALCHEMY_DATABASE_URI,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JSON_AS_ASCII=False,
        MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
        SESSION_COOKIE_NAME=SESSION_COOKIE_NAME,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=SESSION_COOKIE_SECURE,
        SESSION_COOKIE_SAMESITE="Strict",
    )
    db.init_app(app)
    CORS(app, resources={
        r"/api/*": {"origins": CORS_ORIGINS, "supports_credentials": True},
        r"/v1/*": {"origins": "*"},
    })

    from api.admin import bp as admin_bp
    from api.auth import bp as auth_bp
    from api.gateway import bp as gateway_bp
    from api.public import bp as public_bp
    from api.user import bp as user_bp
    blueprints = [auth_bp, public_bp, user_bp, admin_bp, gateway_bp]
    if FEATURE_PAYMENTS:
        from api.topup import bp as topup_bp
        blueprints.insert(3, topup_bp)
    for bp in blueprints:
        app.register_blueprint(bp)

    from extensions import csrf_protect
    app.before_request(csrf_protect)

    @app.after_request
    def response_headers(response):
        # 除静态资源外一律 no-cache:页面入口防止旧版缓存,API 防止导航后拿到过期数据
        if not (request.path.startswith("/assets/") and response.status_code == 200):
            response.headers["Cache-Control"] = "no-cache"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
        if IS_PRODUCTION:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if IS_PRIVATE:
            csp = ("default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
                   "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                   "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
                   "frame-src 'none'; form-action 'self'")
        else:
            csp = ("default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
                   "script-src 'self' 'unsafe-inline' https://o.alicdn.com https://*.alicdn.com; "
                   "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://*.alicdn.com https://*.aliyuncs.com; "
                   "font-src 'self' data:; connect-src 'self' https://api.61api.cn https://*.alicdn.com https://*.aliyuncs.com; "
                   "frame-src https://*.alicdn.com; form-action 'self' https://*.alipay.com")
        response.headers.setdefault("Content-Security-Policy", csp)
        if request.path.startswith("/assets/"):
            response.cache_control.public = True
            response.cache_control.max_age = 31536000
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    from extensions import current_uid
    with app.app_context():
        from sqlalchemy import event

        @event.listens_for(db.engine, "connect")
        def _sqlite_pragma(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=10000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        if not IS_PRODUCTION:
            initialize_database()
        if FEATURE_PAYMENTS:
            from services.payments import PAYKIT_OK, build_payment_service
            if PAYKIT_OK and not os.getenv("61API_SKIP_PAYMENT"):
                from services import payments as _payments
                pay_svc = build_payment_service()
                app.register_blueprint(_payments.paykit.create_payment_blueprint(
                    pay_svc,
                    current_user_id=current_uid,
                    balance_provider=pay_svc.entitlements.balance_of,
                    pay_page_endpoint="topup.pay_page",
                ))
            elif not PAYKIT_OK:
                app.logger.warning("paykit 未接入，充值接口不可用")

    @app.get("/health")
    def health():
        return jsonify(ok=True, service="61api", time=datetime_now_str())

    @app.get("/ready")
    def ready():
        from sqlalchemy import inspect, text
        try:
            db.session.execute(text("SELECT 1"))
            tables = set(inspect(db.engine).get_table_names())
            required = {"users", "api_keys", "usage_logs", "topup_orders", "settings", "invoice_items",
                        "channel_events", "tenants", "audit_logs",
                        "resource_pack_defs", "user_resource_packs"}
            if required - tables:
                return jsonify(ok=False, error="数据库尚未迁移"), 503
            from models import Setting
            if Setting.get("schema_version", 0, int) != SCHEMA_VERSION:
                return jsonify(ok=False, error="数据库迁移版本不一致"), 503
            return jsonify(ok=True)
        except Exception:
            app.logger.exception("readiness check failed")
            return jsonify(ok=False, error="服务尚未就绪"), 503

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(ok=False, error="请求体过大"), 413

    if DIST_DIR.is_dir() and (DIST_DIR / "index.html").is_file():
        @app.get("/")
        @app.get("/<path:path>")
        def spa(path=""):
            if path.startswith(("api/", "v1/", "pay/")):
                abort(404)
            target = DIST_DIR / path
            if path and target.is_file():
                return send_from_directory(DIST_DIR, path)
            if path.startswith("assets/"):
                # 发布后旧 chunk 已被替换,缺失时返回 404(而非 index.html),
                # 避免浏览器拿 HTML 当模块脚本报 MIME 错误掩盖真实原因
                abort(404)
            resp = send_from_directory(DIST_DIR, "index.html")
            # 入口页必须每次重新验证:发布后旧缓存的 index.html 会引用已不存在的 chunk
            resp.headers["Cache-Control"] = "no-cache"
            return resp

    return app


def initialize_database():
    db.create_all()
    _migrate()
    db.create_all()  # 迁移中 DROP 的旧结构表按最新模型重建
    from seed import ensure_seed
    ensure_seed()
    from models import Setting
    Setting.put("schema_version", SCHEMA_VERSION)
    db.session.commit()


def _migrate():
    from sqlalchemy import text
    from extensions import hash_api_key
    from models import ApiKey, Tenant, UsageLog, User, gen_unique_uid

    with db.engine.begin() as conn:
        def columns(table):
            return [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))]

        def add_columns(table, definitions):
            existing = columns(table)
            for name, definition in definitions.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))

        add_columns("users", {
            "uid": "VARCHAR(32)", "register_ip": "VARCHAR(64) DEFAULT ''",
            "last_login_ip": "VARCHAR(64) DEFAULT ''", "token_version": "INTEGER DEFAULT 0",
            "tenant_id": "INTEGER",
        })
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_uid ON users (uid)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_tenant_id ON users (tenant_id)"))
        add_columns("usage_logs", {
            "input_rate": "FLOAT DEFAULT 0", "output_rate": "FLOAT DEFAULT 0",
            "input_cost": "FLOAT DEFAULT 0", "output_cost": "FLOAT DEFAULT 0",
            "cache_rate": "FLOAT DEFAULT 0", "cache_hit_tokens": "INTEGER DEFAULT 0",
            "key_name": "VARCHAR(64) DEFAULT ''", "request_id": "VARCHAR(64)",
            "reserved_quota": "BIGINT DEFAULT 0", "billing_source": "VARCHAR(12) DEFAULT 'upstream'",
            "tenant_id": "INTEGER",
        })
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_usage_logs_tenant_id ON usage_logs (tenant_id)"))
        add_columns("invite_rewards", {
            "status": "INTEGER DEFAULT 0", "reason": "VARCHAR(120) DEFAULT ''", "paid_at": "DATETIME",
        })
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_invite_rewards_to ON invite_rewards (to_uid)"))
        add_columns("models", {
            "cache_input_price": "FLOAT DEFAULT 0", "official_input": "FLOAT DEFAULT 0",
            "official_output": "FLOAT DEFAULT 0",
        })
        add_columns("api_keys", {"key_prefix": "VARCHAR(16) DEFAULT ''", "key_last4": "VARCHAR(4) DEFAULT ''",
                                 "tenant_id": "INTEGER"})
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_api_keys_tenant_id ON api_keys (tenant_id)"))
        add_columns("channels", {
            "last_test_at": "DATETIME", "last_test_ok": "INTEGER",
            "last_test_latency_ms": "INTEGER", "last_test_error": "TEXT DEFAULT ''",
            "fail_streak": "INTEGER DEFAULT 0", "recover_streak": "INTEGER DEFAULT 0",
            "auto_disabled": "INTEGER DEFAULT 0",
            "model_map": "TEXT DEFAULT '{}'",
            "last_balance_at": "DATETIME", "last_balance_info": "TEXT DEFAULT ''",
        })
        add_columns("invoice_items", {"active": "INTEGER DEFAULT 1"})
        add_columns("usage_logs", {
            "pack_id": "INTEGER", "pack_reserved": "BIGINT DEFAULT 0",
        })
        add_columns("topup_orders", {
            "kind": "VARCHAR(16) DEFAULT 'credits'", "pack_model": "VARCHAR(128) DEFAULT ''",
            "pack_days": "INTEGER DEFAULT 0",
        })
        # v10:按用户自定义并发上限(0=用全局默认 GATEWAY_MAX_CONCURRENT_PER_USER)
        add_columns("users", {"concurrency_limit": "INTEGER DEFAULT 0"})
        add_columns("invoices", {
            "file_name": "VARCHAR(255) DEFAULT ''", "file_size": "INTEGER DEFAULT 0",
            "file_uploaded_at": "DATETIME",
        })
        add_columns("ticket_messages", {
            "file_name": "VARCHAR(255) DEFAULT ''", "file_key": "VARCHAR(128) DEFAULT ''",
            "file_size": "INTEGER DEFAULT 0",
        })
        # v9:资源包在 tokens 计量(v8)基础上恢复可选售卖,price>0 上架、0=仅赠送
        add_columns("resource_pack_defs", {"price": "INTEGER DEFAULT 0"})
        # v7 曾以「¥ 面额/售价」结构建过资源包两表;改为 tokens 计量后结构不兼容。
        # 两表发放均为赠送性质,历史金额口径数据不可换算:空表直接重建,非空表拒绝自动迁移。
        for table in ("resource_pack_defs", "user_resource_packs"):
            cols = columns(table)
            if not cols:
                continue  # 表不存在,由 create_all 按新结构创建
            legacy_col = {"resource_pack_defs": "face_quota", "user_resource_packs": "total_quota"}[table]
            if legacy_col not in cols:
                continue  # 已是 tokens 结构
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            if count:
                raise RuntimeError(
                    f"{table} 存在 {count} 条旧金额口径数据,tokens 版无法自动换算,"
                    "请先导出/清理后再执行迁移")
            conn.execute(text(f"DROP TABLE {table}"))
        conn.execute(text("UPDATE invoice_items SET active=0 WHERE invoice_id IN (SELECT id FROM invoices WHERE status=2)"))
        duplicate = conn.execute(text(
            "SELECT order_no FROM invoice_items WHERE active=1 GROUP BY order_no HAVING COUNT(*)>1 LIMIT 1"
        )).first()
        if duplicate:
            raise RuntimeError(f"订单 {duplicate[0]} 存在重复有效开票记录，请先人工核对后再迁移")
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_invoice_items_invoice_order ON invoice_items (invoice_id, order_no)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_invoice_items_active_order ON invoice_items (order_no) WHERE active=1"))

    for user in User.query.filter(User.uid.is_(None)).all():
        user.uid = gen_unique_uid()
    tenant = Tenant.query.order_by(Tenant.id).first()
    if tenant is None:
        from config import PRIVATE_TENANT_NAME
        tenant = Tenant(name=PRIVATE_TENANT_NAME, slug="default", quota=-1,
                        note="初始化时自动创建")
        db.session.add(tenant)
        db.session.flush()
    User.query.filter(User.tenant_id.is_(None)).update(
        {"tenant_id": tenant.id}, synchronize_session=False)
    ApiKey.query.filter(ApiKey.tenant_id.is_(None)).update(
        {"tenant_id": tenant.id}, synchronize_session=False)
    UsageLog.query.filter(UsageLog.tenant_id.is_(None)).update(
        {"tenant_id": tenant.id}, synchronize_session=False)
    for key in ApiKey.query.all():
        if key.key and key.key.startswith("sk-"):
            raw = key.key
            key.key_prefix = raw[:8]
            key.key_last4 = raw[-4:]
            key.key = hash_api_key(raw)
    for log in UsageLog.query.filter(UsageLog.request_id.is_(None)).all():
        log.request_id = f"legacy-{log.id}"
    db.session.commit()
    with db.engine.begin() as conn:
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_usage_logs_request_id ON usage_logs (request_id)"))


def datetime_now_str():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("MG_PORT", "5000"))
    app.run(host=os.getenv("MG_HOST", "127.0.0.1"), port=port, threaded=True)
