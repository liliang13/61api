#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""61API 全局配置(全部可用环境变量覆盖)。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "data"
INSTANCE_DIR.mkdir(exist_ok=True)

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV in {"production", "prod"}


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# private=企业内网/私有化交付;public=原公开运营模式。私有化默认关闭所有对外运营能力。
DEPLOYMENT_MODE = os.getenv("DEPLOYMENT_MODE", "public").strip().lower()
IS_PRIVATE = DEPLOYMENT_MODE in {"private", "onprem", "on-premise", "on_premise"}
FEATURE_PUBLIC_SIGNUP = _env_bool("FEATURE_PUBLIC_SIGNUP", not IS_PRIVATE)
FEATURE_SMS = _env_bool("FEATURE_SMS", not IS_PRIVATE)
FEATURE_PAYMENTS = _env_bool("FEATURE_PAYMENTS", not IS_PRIVATE)
FEATURE_INVITE = _env_bool("FEATURE_INVITE", not IS_PRIVATE)
FEATURE_REDEEM = _env_bool("FEATURE_REDEEM", not IS_PRIVATE)
FEATURE_INVOICE = _env_bool("FEATURE_INVOICE", not IS_PRIVATE)
PRIVATE_TENANT_NAME = os.getenv("PRIVATE_TENANT_NAME", "默认组织")
DEFAULT_TENANT_QUOTA_YUAN = float(os.getenv("DEFAULT_TENANT_QUOTA_YUAN", "-1"))


DEFAULT_SECRET_KEY = "61api-dev-secret-change-me"
SECRET_KEY = (os.getenv("SECRET_KEY_61API") or os.getenv("61API_SECRET_KEY")
              or os.getenv("MODELGRID_SECRET_KEY") or DEFAULT_SECRET_KEY)
SQLALCHEMY_DATABASE_URI = os.getenv(
    "DATABASE_URL", "sqlite:///" + (INSTANCE_DIR / "61api.db").as_posix())
SQLALCHEMY_TRACK_MODIFICATIONS = False

SITE_NAME = os.getenv("SITE_NAME", "61API")
SITE_URL = os.getenv("SITE_URL", "http://127.0.0.1:5000")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = "admin123456"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)

SMS_MODE = os.getenv("SMS_MODE", "off" if IS_PRIVATE else "dev").strip().lower()
if SMS_MODE not in ("off", "dev", "aliyun"):
    SMS_MODE = "off"
ALIYUN_SMS_ACCESS_KEY_ID = os.getenv("ALIYUN_SMS_ACCESS_KEY_ID", "")
ALIYUN_SMS_ACCESS_KEY_SECRET = os.getenv("ALIYUN_SMS_ACCESS_KEY_SECRET", "")
ALIYUN_SMS_SIGN_NAME = os.getenv("ALIYUN_SMS_SIGN_NAME", "")
ALIYUN_SMS_TEMPLATE_CODE = os.getenv("ALIYUN_SMS_TEMPLATE_CODE", "")
SMS_VERIFY_LIMIT = int(os.getenv("SMS_VERIFY_LIMIT", "5"))
SMS_VERIFY_WINDOW_SECONDS = int(os.getenv("SMS_VERIFY_WINDOW_SECONDS", "300"))
SMS_SEND_IP_LIMIT = int(os.getenv("SMS_SEND_IP_LIMIT", "10"))
SMS_SEND_IP_WINDOW_SECONDS = int(os.getenv("SMS_SEND_IP_WINDOW_SECONDS", "3600"))
SMS_SEND_PHONE_WINDOW_SECONDS = int(os.getenv("SMS_SEND_PHONE_WINDOW_SECONDS", "60"))

# 站长 Bark 推送(新用户注册/订单支付提醒);留空即停用
BARK_SERVER_URL = os.getenv("BARK_SERVER_URL", "").strip()
BARK_DEVICE_KEY = os.getenv("BARK_DEVICE_KEY", "").strip()

PAYKIT_PATH = os.getenv("PAYKIT_PATH", "F:/paykit")
PAYKIT_MODE = os.getenv("PAYKIT_MODE", "off" if IS_PRIVATE else "sandbox").strip().lower()

DEFAULT_API_KEY_PEPPER = "61api-dev-api-key-pepper-change-me"
API_KEY_PEPPER = os.getenv("API_KEY_PEPPER", DEFAULT_API_KEY_PEPPER)
JWT_TTL = int(os.getenv("JWT_TTL_SECONDS", str(7 * 86400)))
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "61api_session")
SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", IS_PRODUCTION)
SESSION_COOKIE_SAMESITE = "Strict"

MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(2 * 1024 * 1024)))
DEFAULT_MAX_OUTPUT_TOKENS = int(os.getenv("DEFAULT_MAX_OUTPUT_TOKENS", "4096"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "32768"))
GATEWAY_RATE_LIMIT_PER_MINUTE = int(os.getenv("GATEWAY_RATE_LIMIT_PER_MINUTE", "60"))
GATEWAY_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("GATEWAY_RATE_LIMIT_WINDOW_SECONDS", "60"))
GATEWAY_MAX_CONCURRENT_PER_USER = int(os.getenv("GATEWAY_MAX_CONCURRENT_PER_USER", "4"))
LOGIN_IP_LIMIT = int(os.getenv("LOGIN_IP_LIMIT", "10"))
LOGIN_IP_WINDOW_SECONDS = int(os.getenv("LOGIN_IP_WINDOW_SECONDS", "300"))
LOGIN_ACCOUNT_LIMIT = int(os.getenv("LOGIN_ACCOUNT_LIMIT", "5"))
LOGIN_ACCOUNT_WINDOW_SECONDS = int(os.getenv("LOGIN_ACCOUNT_WINDOW_SECONDS", "900"))

TRUSTED_PROXY_IPS = tuple(
    item.strip() for item in os.getenv("TRUSTED_PROXY_IPS", "").split(",") if item.strip())
CORS_ORIGINS = [item.strip() for item in os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if item.strip()]

if IS_PRODUCTION:
    def _placeholder(value):
        return "REPLACE" in (value or "").upper()

    if _placeholder(SECRET_KEY) or SECRET_KEY == DEFAULT_SECRET_KEY or len(SECRET_KEY) < 32:
        raise RuntimeError("生产环境必须设置至少 32 字符的随机 JWT SECRET_KEY")
    if _placeholder(ADMIN_PASSWORD) or not ADMIN_PASSWORD or ADMIN_PASSWORD == DEFAULT_ADMIN_PASSWORD:
        raise RuntimeError("生产环境必须设置非默认 ADMIN_PASSWORD")
    if not IS_PRIVATE and SMS_MODE == "dev":
        raise RuntimeError("生产环境禁止使用 SMS_MODE=dev")
    if not IS_PRIVATE and PAYKIT_MODE == "sandbox":
        raise RuntimeError("生产环境禁止使用 PAYKIT_MODE=sandbox")
    if _placeholder(API_KEY_PEPPER) or API_KEY_PEPPER == DEFAULT_API_KEY_PEPPER or len(API_KEY_PEPPER) < 32:
        raise RuntimeError("生产环境必须设置至少 32 字符的随机 API_KEY_PEPPER")
    if SMS_MODE == "aliyun" and not all(
            (ALIYUN_SMS_ACCESS_KEY_ID, ALIYUN_SMS_ACCESS_KEY_SECRET,
             ALIYUN_SMS_SIGN_NAME, ALIYUN_SMS_TEMPLATE_CODE)):
        raise RuntimeError("生产环境 SMS_MODE=aliyun 必须配置 ALIYUN_SMS_ACCESS_KEY_ID/SECRET/"
                           "SIGN_NAME/TEMPLATE_CODE 四项")
