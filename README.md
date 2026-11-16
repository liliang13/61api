# 61API · 开源大模型 API 网关与运营平台

[![License: PolyForm Noncommercial](https://img.shields.io/badge/License-PolyForm_NC_1.0.0-orange)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](./backend/requirements.txt)
[![Flask](https://img.shields.io/badge/Flask-3.x-green)](./backend)
[![Vue 3](https://img.shields.io/badge/Vue-3.x-brightgreen)](./frontend)

一套开箱即用的大模型 API 网关 + 用户控制台 + 管理后台:统一 OpenAI / Anthropic 双协议接入、多渠道路由与熔断、按量计费、充值与套餐、工单售后,自带站点前台。

- **在线演示**: [https://www.61api.cn](https://www.61api.cn)(文档中心 [https://www.61api.cn/docs](https://www.61api.cn/docs))
- **商业授权 / 私有部署**: 见下方 [商业授权](#商业授权--commercial-licensing)
- **生产部署手册**: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

## 功能特性

**网关协议**

- OpenAI 兼容:`/v1/chat/completions`(普通 + 流式 SSE)、`/v1/embeddings`、`/v1/responses`、`/v1/models`
- Anthropic 兼容:`/v1/messages`(system / tools / 图片 / 真流式)、`/v1/messages/count_tokens`
- 双认证:`x-api-key` 与 `Authorization: Bearer`;`/v1/messages` 全部错误为 Anthropic 格式,OpenAI SDK、Claude Code、Cline、LobeChat 等客户端直连可用

**渠道与路由**

- 渠道按 priority + weight 加权路由,失败自动切换下一渠道,失败尝试不扣费
- 渠道级模型映射:目录模型名 → 上游模型名,同名目录模型多渠道自动互为主备
- 上游「模型不存在」类 400 自动换渠道,其余 400 直接返回用户
- 定时探活(建议每 5 分钟):连败达阈值自动禁用并推送通知,连成自动恢复;事件时间线 + 24h 调用成功率
- 企微 / 钉钉 / 飞书机器人异常通知

**计量与计费**

- 按上游 usage tokens 以人民币计费,流式响应同样解析 usage,逐笔用量可查
- 资源包:预付费 tokens 包,可定价出售也可赠送;预留冻结 + 结算分流,支持指定模型专用包

**账户与运营**

- 充值套餐(赠送比例可配)、兑换码、邀请返佣、发票申请(开票信息收集)
- 支付宝 + 微信 Native 双渠道收单(经独立支付模块 paykit,可选)、后台退款
- 工单系统(图片附件,魔数校验)、公告、两步换绑手机号
- 管理后台:用户 / 租户、渠道、模型定价与排序、订单、发票、工单、兑换码、审计日志、站点设置

**私有部署模式**

- `DEPLOYMENT_MODE=private` 一键切换:关闭公开注册、短信登录、在线充值、兑换码、邀请、发票,改为管理员统一开通账号 + 组织(租户)额度 + 审计,可离线部署
- 适合企业内网网关、团队共享算力等场景

**安全**

- 统一安全响应头 + CSP,阿里云验证码 2.0(注册 / 找回密码防刷)
- API Key pepper 加密存储,生产环境启动强校验(弱密钥直接拒绝启动)

## 技术栈

| 端 | 技术 |
| --- | --- |
| 后端 | Python 3.11+ · Flask · SQLAlchemy · SQLite · gunicorn + gevent |
| 前端 | Vue 3 · Vite · Element Plus · Tailwind v4 · Pinia |
| 部署 | systemd · OpenResty/Nginx · Docker(可选) |

## 快速开始(本地开发)

后端:

```bash
cd backend
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
MG_PORT=8100 python app.py
```

前端:

```bash
cd frontend
npm ci
npm run dev                 # 本地开发
VITE_API_ORIGIN=https://api.example.com npm run build   # 独立 API 域名部署;单域名同源部署不设置该变量
```

默认管理员 `admin / admin123456`(仅首次建库生效),默认 `SMS_MODE=dev` 会把验证码回显在响应里 —— **这两个默认值不得用于生产**。

依赖安全检查与测试:

```bash
cd backend
pip-audit -r requirements.txt
python -m pytest            # 全量单元测试
```

## 支付模块(可选)

在线收款通过自研支付模块 **paykit** 接入(支付宝 RSA2 证书/公钥双模式、微信支付 v3 Native、Sandbox 沙箱网关)。paykit 独立发布、未随本项目开源;**不安装 paykit 时其余功能完全可用**,仅在线充值/资源包购买不可用,生产部署时通过 `PAYKIT_PATH` 指向该模块即可。

## API 接入示例

OpenAI 兼容(OpenAI SDK / Cline / LobeChat 等):

```python
from openai import OpenAI

client = OpenAI(api_key="sk-控制台生成", base_url="https://api.61api.cn/v1")
resp = client.chat.completions.create(
    model="deepseek-flash",
    messages=[{"role": "user", "content": "你好"}],
)
print(resp.choices[0].message.content)
```

Anthropic 兼容(Claude Code 等原生客户端直连):

```bash
export ANTHROPIC_BASE_URL=https://api.61api.cn
export ANTHROPIC_AUTH_TOKEN=sk-控制台生成
claude
```

## 生产部署

生产部署手册(发布包构建、systemd + OpenResty、迁移与回滚、备份恢复演练、渠道探活定时器)见 **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**;`deploy/` 目录含 systemd 单元、双域名 Nginx vhost 与环境变量模板。

要点:

- 敏感配置全部走环境变量(`SECRET_KEY_61API`、`API_KEY_PEPPER`、`ADMIN_PASSWORD` 等),生产模式启动时强校验,默认值直接拒绝启动
- 数据库为 SQLite(单文件,`backend/data/`),自带 `manage.py backup` 在线备份与 `manage.py migrate` 幂等迁移
- `/health` = 进程存活,`/ready` = 数据库就绪;探针用 ready,负载均衡用 health

## 商业授权 / Commercial Licensing

本项目源码基于 **[PolyForm Noncommercial 1.0.0](./LICENSE)** 许可证开放:

- ✅ **允许**(免费):个人学习、研究、测试评估、内部非商业使用、教学、修改与分发(须保持同一许可证)
- ❌ **禁止**(未经授权):任何商业用途,包括但不限于对外提供付费服务 / SaaS 化运营、转售、付费私有部署、将本项目或其衍生品用于商业产品

**商业授权与私有部署服务**(含私有模式交付、离线部署、定制开发、技术支持)由版权方提供,洽谈请联系:

> 📧 **contact@xiaoningkeji.com**

购买商业授权后,您将获得不受非商用条款约束的专属许可。已付费部分按商业合同执行,与本许可证互不影响。

## License

Copyright (c) 2026 河北小柠科技有限公司 (Hebei Xiaoning Technology Co., Ltd.). 本项目源码以 [PolyForm Noncommercial 1.0.0](./LICENSE) 许可,商用需另行获得商业授权。
