# Hermes 附图策划代理部署说明

## 定位与边界

Hermes 是附图生成工作台的对话式策划与操作代理，不是图片 Provider。正式调用链为：

```text
Browser -> Frontend -> FastAPI -> hermes:8642 -> NewAPI reasoning model
                                  |
                                  -> Business Tool Registry
                                     -> Planning / Generation / Edit services
                                     -> JobBatch / TaskGroup / Celery / image provider
```

浏览器不直连 Hermes。图片仍由现有 Worker、Provider Resolver 和 `gpt-image-2` 完成，Hermes 不使用自己的图片工具。

## 固定版本与镜像

- Hermes Agent：`v0.20.5`
- 官方 release tag：`v2026.8.19`
- Compose image：`nousresearch/hermes-agent:v2026.8.19`
- 首次部署后应记录本机 image ID 和 registry digest；升级时不得直接改容器内 `/opt/hermes`。

## 持久化目录

Windows 部署机使用：

```text
C:/data/hermes-agent -> /opt/data
```

Linux 部署机可把 `HERMES_DATA_DIR` 改为 `/data/hermes-agent`。目录保存 `.env`、`config.yaml`、profiles、sessions、skills、logs 等 Hermes 状态。业务 Project、Plan、Prompt、GeneratedOutput、HermesConversation、HermesProposal 和 ToolAudit 仍保存在应用 MySQL 中。

同一时间只允许一个 Gateway 以写模式挂载同一个数据目录。

## 首次初始化

1. 创建独立数据目录，并限制为部署管理员可读写。
2. 在该目录运行官方 setup，跳过 Telegram、Discord 等无关平台。
3. 创建独立 Profile `image_operator`。
4. 将 NewAPI Key 放入 `/opt/data/.env` 对应的宿主机文件，不写入仓库。
5. 在 Profile 的 `config.yaml` 中通过 `key_env` 引用密钥。

当前验证配置的非敏感部分：

```yaml
model:
  default: gpt-5.5
  provider: newapi
  base_url: http://43.128.213.34:3000/v1
  context_length: 128000
  max_tokens: 4096

providers:
  newapi:
    api: http://43.128.213.34:3000/v1
    key_env: HERMES_NEWAPI_KEY
    transport: chat_completions
    default_model: gpt-5.5

agent:
  max_turns: 8
  run_budget_seconds: 120
  gateway_timeout: 180
  api_max_retries: 2
  disabled_toolsets:
    - terminal
    - file
    - browser
    - web

platform_toolsets:
  cli: []
  api_server: []

tool_loop_guardrails:
  hard_stop_enabled: true

memory:
  memory_enabled: false
  user_profile_enabled: false

plugins:
  enabled: []
```

实际 Profile 禁用的不止上例四项，而是当前版本已知的全部 Hermes 原生叶级 toolset。应用业务动作只通过 FastAPI 中的 Business Tool Registry 执行。

## 应用环境变量

真实值写入仓库根目录已忽略的 `.env` 或部署 Secret 管理器：

```env
HERMES_ENABLED=true
HERMES_BASE_URL=http://hermes:8642
HERMES_API_KEY=<独立强随机 API Server Key>
HERMES_MODEL=hermes-agent
HERMES_PROFILE=image_operator
HERMES_TIMEOUT_SECONDS=180
HERMES_DATA_DIR=C:/data/hermes-agent
HERMES_HOST_PORT=8642
COMPOSE_PROFILES=hermes
```

`HERMES_MODEL=hermes-agent` 是 API Server 对应用暴露的代理模型名；Hermes 内部实际推理模型是 `gpt-5.5`，两者不能混用。

## 网络与安全

- 容器内 API Server 监听 `0.0.0.0:8642`，供同一 Compose network 的 backend 访问。
- 宿主机调试端口只绑定 `127.0.0.1:8642`，不会暴露给局域网。
- 前端不保存或发送 Hermes/NewAPI Key。
- `API_SERVER_KEY`、NewAPI Key、JWT、数据库和对象存储凭据不得复用。
- 不挂载 Docker socket、SSH 私钥、数据库凭据或 MinIO 管理凭据。
- 不设置浏览器 CORS `*`。

## 启动、停止与日志

```bash
docker compose --profile hermes up -d hermes
docker compose --profile hermes up -d --no-deps backend
docker compose --profile hermes ps
docker compose logs --tail=200 hermes backend
```

停止或重启：

```bash
docker compose stop hermes
docker compose start hermes
docker compose restart hermes
```

Hermes 不应成为 backend 的硬启动依赖。Sidecar 停止时，助手显示暂时不可用，手工策划、生成、审核和素材功能继续可用。

## 健康与独立验证

健康检查使用官方 `GET /health`。认证接口使用 Bearer `API_SERVER_KEY`：

```bash
curl http://127.0.0.1:8642/health
curl -H "Authorization: Bearer <HERMES_API_KEY>" http://127.0.0.1:8642/v1/models
```

`/v1/models` 应包含 `hermes-agent`。`POST /v1/chat/completions` 应返回 OpenAI-compatible `choices[].message.content`，并在响应头返回 `X-Hermes-Session-Id`。生产验收还应从 backend 容器访问 `http://hermes:8642`，不能只测试宿主机回环地址。

## 故障排查

- `provider unavailable`：先从 Hermes 容器检查 NewAPI 地址、模型 alias 和认证；容器内 `localhost` 只代表 Hermes 自身。
- `403 request blocked`：检查中转渠道是否拦截较长 Agent system prompt；文本模型连通不等于完整 Hermes prompt 可用。
- `profile missing`：确认 `image_operator` Profile 位于挂载目录并由 Gateway 启动。
- `model not found`：区分 API Server 模型名 `hermes-agent` 与底层推理模型 alias。
- API Server 的“local unsandboxed terminal”通用警告：必须同时核验当前 Profile 已禁用全部原生工具，并确认请求 payload 中 `tools` 为空。
- 对话可用但 Proposal 不出现：检查返回 JSON、Business Tool 白名单和高成本动作显式意图校验。

## 升级与回滚

升级：

1. 备份 `HERMES_DATA_DIR`。
2. 记录当前镜像 ID/digest 和 `docker compose ps`。
3. 修改为明确的新版本 tag，pull 后先做 `/health`、`/v1/models`、会话连续性测试。
4. recreate 单个 Hermes 容器，再做 backend 和 Proposal 回归。

紧急回滚：

1. 设置 `HERMES_ENABLED=false`。
2. recreate backend。
3. `docker compose stop hermes`。

这样只关闭助手，不影响原工作台。恢复时重新设置 `HERMES_ENABLED=true` 并启动 Sidecar；MySQL 中的聊天和审计记录、`HERMES_DATA_DIR` 中的 Session 都不会因容器替换而丢失。

## Secret 轮换

1. 在 Secret 管理位置生成新的独立 `HERMES_API_KEY`。
2. 同步更新 Hermes API Server 和 backend 环境变量。
3. recreate Hermes 与 backend。
4. 验证旧 Key 返回 401、新 Key 正常；日志和 Git diff 中不得出现完整 Key。
