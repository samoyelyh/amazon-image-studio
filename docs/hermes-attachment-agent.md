# Hermes 附图策划代理部署说明

## 定位

Hermes 是附图生成工作台的对话式策划与操作代理，不是图片 Provider。所有策划、生成和图片编辑仍通过 Amazon Image Studio 的正式 Service、JobBatch、TaskGroup、Worker、Provider Resolver 和对象存储执行。

## 已验证的官方接口

本集成按 Hermes Agent v0.20.5（tag `v2026.8.19`）的官方 API Server 接入：

- `GET /health`
- `POST /v1/chat/completions`
- Bearer Token：Hermes `API_SERVER_KEY`
- 可选会话连续性：`X-Hermes-Session-Id`
- 默认模型名：`hermes-agent`

Hermes 作为独立 Sidecar/独立服务运行，FastAPI 是唯一调用方；浏览器不直接连接 Hermes。

## Hermes 侧建议配置

在隔离的 `image_operator` Profile 中启动 API Server。不要为该 Profile 启用 terminal、filesystem、browser、任意 HTTP 或基础设施管理工具。

```env
API_SERVER_ENABLED=true
API_SERVER_HOST=0.0.0.0
API_SERVER_PORT=8642
API_SERVER_KEY=<独立强随机密钥>
API_SERVER_MODEL_NAME=hermes-agent
```

启动命令由 Hermes 官方安装管理：

```text
hermes gateway
```

Hermes 自身还需要配置一个可用的推理模型 Provider。该 Provider 凭据属于 Hermes Sidecar，不应写入本项目仓库。

## Amazon Image Studio 配置

```env
HERMES_ENABLED=true
HERMES_BASE_URL=http://hermes:8642
HERMES_API_KEY=<与 API_SERVER_KEY 相同>
HERMES_MODEL=hermes-agent
HERMES_PROFILE=image_operator
HERMES_TIMEOUT_SECONDS=90
```

如果 Hermes 运行在宿主机而 FastAPI 运行在 Docker 中，`HERMES_BASE_URL` 应改为容器能够访问的宿主机地址。配置变更后重启 backend；不需要新增 Celery 队列或修改 Worker。

## 安全边界

- Hermes 只收到压缩后的项目上下文，不收到 Provider Key、对象存储凭据或内部图片 URL。
- Hermes 只可提出 Business Tool Registry 中的高层业务动作。
- 写操作默认形成 Proposal，用户确认后才执行。
- Apply 时重新校验用户权限、组织/用户/项目范围及工作台状态签名。
- 旧 Proposal 在 Theme、Model、Reference、Plan 等状态变化后会标记为 stale，不能覆盖新状态。
- Tool Audit 对常见密钥字段、Bearer Token 和 `sk-` 形式凭据做脱敏。
- Hermes 不可用时仅禁用助手输入，手工工作台保持可用。

## 当前范围

第一版实现 SUGGEST 模式，不实现 AUTO 模式、无限 Agent Loop、Hermes 直接 Provider 调用或 Hermes 自动修改生产 Skill。业务工具通过应用内注册表执行，而不是把数据库、Redis、Celery、MinIO 或通用 Shell 暴露给 Hermes。

## 健康检查

1. 在 Hermes 主机验证 `GET /health`。
2. 在 backend 容器内验证 `${HERMES_BASE_URL}/health` 可达。
3. 打开附图生成工作台的“助手”入口，状态应显示已连接。
4. 关闭 Hermes 后刷新，页面应显示助手不可用，但手工策划和生成仍可操作。
