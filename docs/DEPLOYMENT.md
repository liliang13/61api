# 61API 生产部署手册

本文是完整的生产部署与运维手册:发布包构建、systemd + OpenResty 部署、数据库迁移与回滚、备份恢复演练、渠道探活。本地开发与功能介绍见 [README](../README.md)。

> **私有化交付版**:设置 `DEPLOYMENT_MODE=private` 后,公开注册、短信登录、在线充值、兑换码、邀请返佣、发票全部关闭,改为管理员开通账号 + 组织(租户)额度 + 审计日志,支持离线部署。私有部署的商业授权与交付服务请联系版权方(见 README「商业授权」)。

## 功能与部署概览

| 模块 | 能力 |
| --- | --- |
| 官网 | 首页、模型列表、文档中心、服务条款与隐私政策 |
| 网关 | OpenAI 兼容 `/v1/chat/completions`(普通与流式 SSE)、`/v1/embeddings`、`/v1/models`、`/v1/responses`;Anthropic 兼容 `/v1/messages`(tools/图片/真流式)与 `/v1/messages/count_tokens`;渠道按优先级和权重路由,失败不扣费 |
| 计量 | 按上游 usage 以人民币计费(500000 quota = ¥1),流式响应解析 usage,用量逐笔可查 |
| 账户 | 账号密码与手机验证码登录、改密、两步换绑手机 |
| 控制台 | 看板、API 密钥、用量日志、充值、资源包、兑换码、邀请返佣、工单(图片附件)、公告、账户设置 |
| 充值 | 可配置套餐、paykit 支付宝/微信收款、后台退款 |
| 运营 | 用户、租户、渠道(探活/熔断/通知)、模型定价与排序、订单、发票、兑换码、审计日志与站点设置 |

内置种子目录当前为 **2 款 DeepSeek 模型**;实际可用模型以数据库和 `/v1/models` 返回为准。内置 mock 渠道默认停用,接入真实上游后在管理后台按需启用。页面页脚的备案信息由运营方自行配置维护,变更主体或域名时应同步复核。

## 部署形态

目标是 Debian 12、systemd 与 OpenResty。示例配置在 `deploy/` 目录,复制后按实际证书路径调整:

- `deploy/61api.service.example`:gunicorn `gthread`,2 workers × 8 threads,仅监听 `127.0.0.1:8300`。
- `deploy/61api.cn.conf.example`:主站及控制台的反向代理,`/v1/` 关闭 SSE 缓冲。
- `deploy/api.61api.cn.conf.example`:API 子域仅开放 `/v1/`、`/health`、`/ready`,其余路径返回 404。
- `deploy/env.example`:生产环境变量占位,**不包含真实秘密**。
- `deploy/61api-probe.service.example` 与 `deploy/61api-probe.timer.example`:渠道定时探活(每 5 分钟),见下文「渠道探活与异常通知」。

应用统一设置安全响应头与 CSP;OpenResty 不再添加另一套安全头,避免重复或冲突。TLS 证书、DNS、支付异步通知地址(如 `https://your-domain.com/api/pay/alipay/notify`)需在实际平台配置。

### 1. 目录与环境

发布采用版本目录和 `current` 软链接;数据库与备份位于独立持久目录,不能随代码回滚被覆盖:

```text
/opt/61api/
├── current -> /opt/61api/releases/<RELEASE>
├── releases/<RELEASE>/{backend,frontend,deploy,.venv}
└── shared/
    ├── backend/data/       # 软链接到每个版本的 backend/data
    └── backups/
/etc/61api/61api.env        # 权限 0600,不进入发布包或 Git
```

```bash
sudo useradd --system --home /opt/61api --shell /usr/sbin/nologin 61api
sudo install -d -o 61api -g 61api /opt/61api/releases \
  /opt/61api/shared/backend/data /opt/61api/shared/backups
sudo install -d -m 700 /etc/61api
sudo cp deploy/env.example /etc/61api/61api.env
sudoedit /etc/61api/61api.env
sudo chmod 600 /etc/61api/61api.env
sudo cp deploy/61api.service.example /etc/systemd/system/61api.service
```

必须替换所有占位值:`APP_ENV=production`、`SMS_MODE`(生产接阿里云短信则设 `aliyun`)、`PAYKIT_MODE=alipay`,并设置强随机 `SECRET_KEY_61API`、独立的 `API_KEY_PEPPER` 和管理员密码。可用 `openssl rand -hex 32` 分别生成应用密钥;`API_KEY_PEPPER` 变更会使既有 API Key 失效,必须纳入稳定密钥管理。配置 `TRUSTED_PROXY_IPS=127.0.0.1` 和阿里云验证码凭据。按所安装 paykit 版本补充支付宝/微信配置,确认 `PAYKIT_PATH` 指向正确模块;真实密钥和证书只放在服务器受控位置。

`deploy/env.example` 是空白模板,不表示凭据已经轮换,也不表示短信或线上支付已经验收。

### 2. 构建发布包

在干净源码目录构建。发布包明确排除 `backend/data`、所有 `.env` 和所有 `node_modules`,防止数据库、秘密和本机依赖进入包内:

```bash
RELEASE="$(date +%Y%m%d%H%M%S)"
cd frontend
npm ci
npm run build          # 私有化部署:同源网关(/v1 由反向代理转发)
# npm run build:public # 61api.cn 公开运营:网关走 https://api.61api.cn(frontend/.env.public)
cd ..
tar \
  --exclude='backend/data' --exclude='backend/data/*' \
  --exclude='.env' --exclude='*/.env' \
  --exclude='node_modules' --exclude='*/node_modules' \
  --exclude='node_modules/*' --exclude='*/node_modules/*' \
  -czf "/tmp/61api-${RELEASE}.tar.gz" backend frontend/dist deploy
sha256sum "/tmp/61api-${RELEASE}.tar.gz" > "/tmp/61api-${RELEASE}.tar.gz.sha256"
tar -tzf "/tmp/61api-${RELEASE}.tar.gz"
```

上传前检查归档清单,确认没有上述排除项;上传后在服务器核对 SHA-256。不要把 `/opt/61api/shared`、`/etc/61api/61api.env` 或本机虚拟环境打入发布包。

### 3. 备份、发布与迁移

以下命令在服务器执行。先记录发布前备份命令输出的文件路径和校验信息,再切换版本;**不要只重启而不迁移**。首次部署尚无 `current` 时可跳过发布前 `reservations` 和备份步骤,此后每次发布都必须执行。

```bash
export RELEASE=替换为发布包时间戳
export APP=/opt/61api

# 发布前检查与一致性备份;记录输出的 BACKUP 路径。
cd "$APP/current/backend"
sudo -u 61api "$APP/current/.venv/bin/python" manage.py reservations
sudo -u 61api "$APP/current/.venv/bin/python" manage.py backup \
  --target "$APP/shared/backups"

# 解压并安装该版本的固定依赖。
sudo install -d "$APP/releases/$RELEASE"
sudo tar -xzf "/tmp/61api-${RELEASE}.tar.gz" -C "$APP/releases/$RELEASE"
sudo python3 -m venv "$APP/releases/$RELEASE/.venv"
sudo "$APP/releases/$RELEASE/.venv/bin/pip" install \
  -r "$APP/releases/$RELEASE/backend/requirements.txt"
sudo ln -s "$APP/shared/backend/data" "$APP/releases/$RELEASE/backend/data"

# 切换后由 systemd 的 ExecStartPre 显式执行 migrate、check,再启动 gunicorn。
sudo ln -sfn "$APP/releases/$RELEASE" "$APP/current"
sudo systemctl daemon-reload
sudo systemctl enable 61api
sudo systemctl restart 61api
```

`ExecStartPre` 的顺序固定为 `python manage.py migrate`、`python manage.py check`,两者任一失败都会阻止 `ExecStart`。不要删除这些步骤,也不要依赖应用启动时的隐式建表代替发布迁移。

### 4. 健康检查与验收

`/health` 用于进程存活检查,`/ready` 用于发布就绪检查;只有两者均成功才视为可接流量:

```bash
systemctl status 61api --no-pager
journalctl -u 61api -n 100 --no-pager
curl --fail --silent --show-error http://127.0.0.1:8300/health
curl --fail --silent --show-error http://127.0.0.1:8300/ready
curl --fail --silent --show-error https://your-domain.com/health
curl --fail --silent --show-error https://api.your-domain.com/ready
API_KEY=替换为控制台生成的测试密钥
curl --fail --silent --show-error -H "Authorization: Bearer ${API_KEY}" \
  https://api.your-domain.com/v1/models
cd /opt/61api/current/backend
sudo -u 61api /opt/61api/current/.venv/bin/python manage.py check
sudo -u 61api /opt/61api/current/.venv/bin/python manage.py reservations
```

另需确认 API 子域根路径与非开放路径返回 404,并实际验证 SSE 分段到达而非等待完整响应。短信、支付下单/异步通知/退款、管理后台和密钥调用应在上线验收中分别测试;本文不声明这些外部链路已经验证。

OpenResty 安装示例后先校验再加载:

```bash
sudo cp /opt/61api/current/deploy/61api.cn.conf.example /etc/nginx/conf.d/61api.cn.conf
sudo cp /opt/61api/current/deploy/api.61api.cn.conf.example /etc/nginx/conf.d/api.61api.cn.conf
sudo nginx -t
sudo systemctl reload openresty       # 使用 nginx 时改为 systemctl reload nginx
```

### 5. 备份策略

- 每次发布、迁移和重大配置变更前执行 `python manage.py backup --target DIR`。
- 日常备份写入 `/opt/61api/shared/backups`,再复制到独立机器或对象存储;同机备份不等于容灾。
- 保留策略应同时按时间和存储容量限制,备份文件设为仅服务账号与管理账号可读,异地副本加密。
- 备份记录需包含发布时间、代码版本、文件路径、大小、校验值和恢复结果;定期核对备份非空且可读取。
- 恢复会覆盖备份之后产生的数据。恢复前必须保存当前故障现场,并评估订单、余额和预订状态差异。

### 6. 渠道探活与异常通知

渠道健康状态以数据库为准,不依赖应用进程内存:

- `python manage.py probe` 探活全部「启用中」与「被自动禁用」的渠道:发 1 token 极小请求,结果写入渠道字段与 `channel_events` 事件时间线;同时清理 14 天前的旧事件。
- 连续失败达到阈值(管理后台「站点设置」中的禁用阈值,默认 3)自动禁用该渠道并推送通知;被自动禁用的渠道继续探活,连续 2 次成功自动恢复上线并推送通知。**人为停用**的渠道不参与探活,也不会自动恢复;管理后台手动启用渠道会清空状态机计数。
- 请求层面的失败切换(含上游「模型不存在」类 400 改走下一渠道)同样写入 `channel_events`,渠道管理页可按渠道查看事件时间线与 24h 调用成功率。

安装定时探活:

```bash
sudo cp deploy/61api-probe.service.example /etc/systemd/system/61api-probe.service
sudo cp deploy/61api-probe.timer.example /etc/systemd/system/61api-probe.timer
sudo systemctl daemon-reload
sudo systemctl enable --now 61api-probe.timer
```

异常通知在管理后台「站点设置」配置:选择企业微信 / 钉钉 / 飞书机器人类型、填入 webhook 地址、开启后点「发送测试通知」验证。通知只在自动禁用与自动恢复两个状态跃迁时推送;探活细节与失败切换记录看渠道管理页的时间线。

## 回滚与恢复

### 代码回滚

若新版本未通过 health/ready,先切回仍保留的旧版本:

```bash
export APP=/opt/61api
export PREVIOUS=/opt/61api/releases/替换为上一可用版本
sudo ln -sfn "$PREVIOUS" "$APP/current"
sudo systemctl restart 61api
curl --fail http://127.0.0.1:8300/health
curl --fail http://127.0.0.1:8300/ready
```

旧代码无法兼容已迁移数据库时,不得强行反复重启:停止服务,并使用该次发布前的备份恢复。回滚后再次执行 `python manage.py check` 与 `python manage.py reservations`。

### 从 SQLite 快照恢复

以下以备份命令输出的 `61api.db` 快照为例;若备份清单还包含 WAL、支付订单库或其他文件,必须按清单恢复同一备份点,不能只挑选主库。将 `BACKUP` 替换为实际输出路径:

```bash
export APP=/opt/61api
export BACKUP=/opt/61api/shared/backups/替换为实际备份文件.db
sudo systemctl stop 61api
sudo -u 61api cp -a "$APP/shared/backend/data" \
  "$APP/shared/backend/data.before-restore-$(date +%Y%m%d%H%M%S)"
sudo -u 61api install -m 600 "$BACKUP" "$APP/shared/backend/data/61api.db"
sudo -u 61api rm -f "$APP/shared/backend/data/61api.db-wal" \
  "$APP/shared/backend/data/61api.db-shm"
sudo ln -sfn /opt/61api/releases/替换为与备份兼容的版本 "$APP/current"
sudo systemctl start 61api
curl --fail http://127.0.0.1:8300/health
curl --fail http://127.0.0.1:8300/ready
cd "$APP/current/backend"
sudo -u 61api "$APP/current/.venv/bin/python" manage.py check
sudo -u 61api "$APP/current/.venv/bin/python" manage.py reservations
```

启动前迁移同样会执行,因此必须选择与备份兼容的代码版本。恢复后核对用户、订单、余额和用量,再决定是否开放流量。

### 恢复演练

至少每季度在隔离环境演练一次,不连接生产短信或支付回调:

1. 使用 `python manage.py backup --target DIR` 生成新备份,记录校验值并复制到隔离目录。
2. 在空白数据目录按上一节流程恢复,确认服务可启动且 health/ready 成功。
3. 执行 `python manage.py check`、`python manage.py reservations`,抽样核对用户、订单、余额、用量与关键页面。
4. 记录恢复点、实际 RPO/RTO、失败项和修复责任人;未完成恢复验证的备份不得视为可用。

## 上线检查清单

- [ ] 所有环境占位值已替换,默认管理员密码不再使用,秘密未进入 Git 或发布包。
- [ ] 发布前备份成功且异地副本可读,已完成隔离恢复演练。
- [ ] 显式迁移、check、health、ready 和 reservations 检查通过。
- [ ] API 子域路径限制、SSE、TLS 与 Flask 安全头/CSP 已验证。
- [ ] 真实上游、短信和支付链路已由运营人员单独验收;未验收项明确记录。
- [ ] 页脚备案信息、模型目录、价格和套餐与当前运营信息一致。
