# Phase 6：统一任务系统与 API Key 资源池

## 范围与优先级

优先级：P0。依赖 Phase 3 的账号、团队、RBAC 与审计，Phase 4 的对象存储，以及 Phase 5 的额度预占和结算。

本阶段提供 Celery 异步任务、统一状态、Provider 适配器、多 Key 资源池、Redis 原子并发控制、RPM/日限额、429 冷却和故障转移、幂等消费、Worker 恢复、冻结额度扫描及任务 API。Listing、批量套图、A+ 三个工作台接入和任务中心页面属于 Phase 7，本阶段不改变 standalone 浏览器直连模式。

## 数据模型

迁移：`0005_tasks_resource_pool`，基于 `0004_quota_and_billing`。

| 表 | 作用 |
| --- | --- |
| `providers` | 服务商类型、后端 Base URL 和非敏感适配参数 |
| `models` | 平台模型代码、上游模型名和开关 |
| `model_capabilities` | text/image generation、image edit、多图参考等能力标签 |
| `resource_pools` | 全局或团队模型池、优先级和权重 |
| `api_keys` | Fernet 密文、SHA-256 指纹、末四位、限额和冷却状态 |
| `resource_pool_keys` | Key 与池的关联、优先级和权重 |
| `api_key_usage_stats` | 每次上游调用的结果、HTTP 状态和耗时 |
| `job_batches` | 后续工作台批量任务的统一批次状态和计数 |
| `jobs` | 团队任务、输入、状态、进度、额度预占、错误和心跳 |
| `job_attempts` | 每次 Provider/Key 尝试和错误记录 |

统一任务状态：`queued`、`dispatching`、`running`、`retry_waiting`、`succeeded`、`failed`、`cancelled`。统一批次状态已落库，Phase 7 接入三个工作台时创建和汇总批次。

## Key 安全边界

- 平台 Key 仅通过 `POST /api/v1/resource-pools/keys` 进入后端；
- 使用 `API_KEY_ENCRYPTION_KEY` 对 Key 做 Fernet 加密，数据库不保存明文；
- SHA-256 指纹用于查重，响应只返回指纹和 `****末四位`；
- Key 不出现在任务输入、任务响应、Provider 配置、前端环境变量、localStorage 或 IndexedDB；
- Provider 配置和任务输入会递归拒绝 `api_key`、`token`、`secret`、`authorization`、`password` 等凭据字段；
- 审计日志只记录 Key ID、指纹前缀和末四位；
- 生产环境拒绝默认开发加密密钥。更换加密密钥前必须迁移现有密文，否则旧 Key 无法解密。

生成生产 Fernet 密钥：

```powershell
server/.venv/Scripts/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

将输出放入服务器私密环境变量 `API_KEY_ENCRYPTION_KEY`，不要提交到 Git。

## Provider 与中转站配置

当前适配器支持 `openai_compatible`、`new_api` 和基于 OpenAI Images 协议的 `custom`。默认请求为：

```text
POST {base_url}/images/generations
Authorization: Bearer {decrypted_server_key}
```

OpenAI/NewAPI 风格中转站通常将 `base_url` 配为 `https://你的中转域名/v1`。若路径不同，在 Provider 的非敏感 `config.images_endpoint` 指定。配置顺序：

1. 平台管理员创建 Provider；
2. 在 Provider 下创建模型并声明能力；
3. 创建全局或团队资源池；
4. 通过 Key 专用接口提交中转站 Key；
5. 将 Key 关联到资源池；
6. 普通任务只提交平台模型代码，不提交 Key。

相关 API：

- `GET/POST /api/v1/resource-pools/providers`；
- `POST /api/v1/resource-pools/providers/{provider_id}/models`；
- `GET/POST /api/v1/resource-pools`；
- `GET/POST /api/v1/resource-pools/keys`；
- `POST /api/v1/resource-pools/{pool_id}/keys`。

写接口要求 `resource_pools.manage`，当前仅平台管理员拥有。普通团队成员只能读取可用池元数据，不能读取 Key 列表或密文。

## 调度与并发

调度不是随机轮换。候选顺序为：团队专属池优先于全局池，然后按池优先级、Key 优先级、连续失败次数、权重、最近使用时间和稳定 ID 排序。候选还必须满足：

- Provider、模型、池、关联和 Key 均启用；
- 模型代码与能力标签匹配；
- Key 属于当前团队或平台全局；
- 余额未明确耗尽；
- 数据库和 Redis 冷却均已结束。

Redis Lua 在一次原子操作内检查 Key 冷却、当前并发、RPM 和日调用量，并领取并发槽。Worker 始终在 `finally` 释放槽；租约 TTL 防止进程被强杀后永久占用。真实 Redis 验收结果：第一次领取 `1`、第二次因并发上限返回 `-1`、释放回到 `0`、冷却时返回 `-4`。

上游 429 或可重试网络错误会冷却当前 Key、增加失败次数并排除当前 Key，然后尝试下一候选。成功后清除连续失败和冷却状态。所有尝试写入 `job_attempts` 和 `api_key_usage_stats`。

## 任务、额度与恢复

`POST /api/v1/jobs` 在数据库事务中：

1. 按团队和幂等键检查重复提交；
2. 服务端重新计算费用；
3. 原子预占额度；
4. 创建 queued 任务；
5. 提交事务后发送 Celery 消息；
6. 立即返回 job ID。

同一幂等键和相同输入返回原任务；相同键不同输入返回 409。Worker 领取任务时加数据库行锁：已完成任务或带新鲜心跳的运行任务不会重复执行。成功任务上传结果到组织隔离的对象存储路径并结算 1 个计费单元；失败或取消释放预占；429 故障转移不会重复扣费。

后端按工作台和能力校验 operation_code，并强制使用实际模型代码与平台资源池计费因子，客户端提交的同名因子不能降低费用。一个 job 固定生成一张图片；多张生成必须由 Phase 7 的 batch 拆成多个子任务，避免 `n` 参数绕过按图片计费。

任务 API：

- `POST /api/v1/jobs`；
- `GET /api/v1/jobs`；
- `GET /api/v1/jobs/{job_id}`；
- `POST /api/v1/jobs/{job_id}/cancel`。

页面刷新后通过 GET 接口恢复状态，浏览器关闭不影响 Worker。Celery Beat 周期执行：

- 每 15 秒派发 broker 发送失败或到期重试任务；
- 每 60 秒恢复心跳过期的 running/dispatching 任务；
- 每 5 分钟释放到期额度预占；
- Worker 使用 late ack、丢失拒绝、prefetch 1、软硬超时和指数退避。

## 队列

Worker 监听：

```text
default
maintenance
planning_queue
listing_queue
batch_tryon_queue
aplus_queue
retry_queue
```

Flower 地址默认为 `http://127.0.0.1:15555`。Flower 只用于运维观察，任务真实状态以 MySQL 为准。

## 环境变量

```dotenv
API_KEY_ENCRYPTION_KEY=<Fernet key>
RESOURCE_LEASE_TTL_SECONDS=900
RESOURCE_KEY_COOLDOWN_SECONDS=60
PROVIDER_REQUEST_TIMEOUT_SECONDS=120
PROVIDER_OUTPUT_MAX_BYTES=26214400
JOB_TIMEOUT_SECONDS=600
JOB_HEARTBEAT_TIMEOUT_SECONDS=180
JOB_MAX_ATTEMPTS=3
```

## 测试与验收

自动测试覆盖 Key 加密脱敏、凭据注入拒绝、能力匹配、并发上限、冷却、任务提交幂等、跨团队隔离、取消退款、重复 Worker 消费、Worker 心跳恢复和 429 切换下一 Key。全量后端、前端回归和构建均必须通过。

真实栈验收：

1. `alembic current` 为 `0005_tasks_resource_pool (head)`；
2. `alembic check` 无新迁移；
3. readiness 中 MySQL、Redis、MinIO 全部为 ok；
4. Worker 注册 jobs 和 maintenance 任务并监听所有业务队列；
5. Celery heartbeat 经 Redis broker 往返并返回 UTC 时间；
6. Redis Lua 并发和冷却返回符合预期；
7. API 文档不在任何响应 schema 暴露 Key 明文。

## 下一阶段

Phase 7 将三个工作台的多人模式提交改为统一 jobs/batches，创建输出 Asset/GeneratedOutput，新增任务中心、生成历史、批量下载、暂停/批次取消和页面进度恢复。standalone 模式继续保留现有浏览器个人 Key 与 IndexedDB 流程。
