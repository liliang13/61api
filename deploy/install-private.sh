#!/usr/bin/env bash
# 61API 私有化一键安装(单机 Docker Compose)
# 用法:在项目根目录执行 bash deploy/install-private.sh
set -euo pipefail

cd "$(dirname "$0")"
ENV_FILE="61api.env"

rand_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

if [ ! -f "$ENV_FILE" ]; then
  cp env.private.example "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  secret="$(rand_hex)"
  pepper="$(rand_hex)"
  admin_pwd="A$(rand_hex | cut -c1-15)1"
  sed -i "s/REPLACE_WITH_OPENSSL_RAND_HEX_32/${secret}/" "$ENV_FILE"
  sed -i "s/REPLACE_WITH_ANOTHER_OPENSSL_RAND_HEX_32/${pepper}/" "$ENV_FILE"
  sed -i "s/REPLACE_WITH_STRONG_ADMIN_PASSWORD/${admin_pwd}/" "$ENV_FILE"
  echo "已生成 deploy/${ENV_FILE}"
  echo "管理员账号: admin"
  echo "管理员初始密码: ${admin_pwd}"
  echo "请登录后立即修改密码,并妥善保存该文件(权限 600)。"
else
  echo "检测到 deploy/${ENV_FILE},沿用现有配置。"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "未检测到 docker,请先安装 Docker Engine 与 Compose 插件。" >&2
  exit 1
fi

docker compose -f docker-compose.private.yml up -d --build
echo
echo "启动完成。健康检查:"
echo "  curl http://127.0.0.1:8300/health"
echo "  curl http://127.0.0.1:8300/ready"
echo "首次启动会自动建库并创建默认组织;随后在管理后台配置渠道、导入模型、开通用户。"
