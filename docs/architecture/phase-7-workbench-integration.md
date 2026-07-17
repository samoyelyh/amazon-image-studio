# Phase 7：三个工作台接入统一任务系统

## 范围、优先级与依赖

Phase 7 为 P1 核心业务阶段，依赖 Phase 3 的账号/RBAC、Phase 4 的对象存储与素材中心、Phase 5 的额度预占结算、Phase 6 的 Celery/Redis/Provider/API Key 资源池。

本阶段不新增一级工作台，而是完成：

- Listing 图工作台：AI 策划、生图/编辑接入服务端；
- 批量套图工作台：服务端批次拆分、并发、暂停、继续、取消、失败隔离；
- A+ 图工作台：AI 策划、生图/编辑接入服务端；
- 任务中心：任务/批次状态、进度、错误、取消、批量下载；
- 生成历史：成功输出、素材归档和批量下载。

standalone 模式继续使用原浏览器直连 API、IndexedDB 历史和本地队列，不改变已有用户数据与操作方式。

## 功能目标与用户流程

### Listing 图与 A+ 图

1. 用户登录后进入原工作台，粘贴 Listing 文本、上传产品参考图并选择参数。
2. 点击 AI 策划时，参考图先上传为团队私有素材，前端提交 `planning_queue` 文本任务并轮询状态。
3. 用户编辑策划生成的提示词，点击生图。
4. 前端上传产品图、风格图和遮罩，只向任务接口提交 Asset ID，不提交 API Key。
5. 服务端预占额度并立即返回任务 ID；Worker 从资源池选择 Key，调用 Provider。
6. 输出写入对象存储、`assets` 与 `generated_outputs`，前端恢复到原 TaskGrid，同时可在任务中心和生成历史查看。
7. 刷新或关闭页面不影响任务；重新登录后任务中心可恢复状态。

### 批量套图

1. 用户上传一张模特模板图和最多 50 张服装图，设置比例、质量、格式、额外要求和 1～3 并发。
2. 点击开始后，浏览器只提交一次批次请求；服务端拆成“一件服装一个 job”。
3. 每个子任务独立预占、执行、结算或退款；单个失败不影响其他子任务。
4. 用户可暂停、继续、取消批次，离开页面后任务继续执行。
5. 成功图片进入素材中心与生成历史，可单张下载或打包 ZIP。

## 输入与输出

- 文本：策划原文、可编辑提示词、批量套图额外要求；单任务输入 JSON 最大 128 KiB。
- 图片：JPEG/PNG/WebP；多人模式沿用素材中心 20 MB 单文件限制，standalone 批量套图保持 50 MB；Listing/A+ 最多 16 张参考图；批量套图 1 张模板加最多 50 张服装图。
- 参考图顺序：图片编辑保持前端顺序；批量套图固定为“模板图、服装图”。
- 输出：每个 job 固定一张图；格式 PNG/JPEG/WebP；尺寸、质量由任务参数与上游模型共同决定。
- 命名：Provider 输出名写入 Asset；批量下载增加三位序号并清理非法文件名字符。
- 归档：输出自动进入素材中心和生成历史；工作台本地缓存仅用于延续原预览、编辑与下载组件。

## AI 与 Prompt Builder

- Listing/A+ 的长基础策划提示词继续集中在 `listingPlannerApi.ts` 及原 Prompt Builder，不写入 React JSX。
- 批量套图使用现有 `batchTryOnPrompt.ts`，内置产品与模特保真规则仍不可被额外要求覆盖。
- 多人模式的策划和生图都走统一任务系统；支持文本生成、图片生成、单图编辑、多图参考和遮罩编辑能力。
- Provider 模型能力由后台资源池声明；无对应能力时返回明确错误，不回退到浏览器个人 Key。

## 异步任务、状态与恢复

- 单张操作对应一个 job；批量操作对应一个 `job_batch` 和多个子 job。
- 队列：`planning_queue`、`listing_queue`、`batch_tryon_queue`、`aplus_queue`。
- job 状态：`queued`、`dispatching`、`running`、`retry_waiting`、`succeeded`、`failed`、`cancelled`。
- batch 状态：`queued`、`running`、`paused`、`partially_succeeded`、`succeeded`、`failed`、`cancelled`。
- 服务端使用批次行锁限制子任务并发；API Key 并发、RPM、日限额和冷却继续使用 Redis 原子控制。
- Worker 心跳超时由 Phase 6 恢复器转为重试；页面轮询 API 恢复进度，页面不是任务所有者。
- 暂停会阻止未开始的任务领取；已经进入上游请求的任务可能完成。取消在上游完成后再次检查，并清理尚未确认归档的输出。

## 额度与权限

operation_code：

- `listing.plan`、`listing.generate`；
- `batch_tryon.generate`；
- `aplus.plan`、`aplus.generate`。

每个子 job 独立预占一个计费单元。成功按实际一张结算；失败/取消释放该 job 预占；部分成功只消费成功子任务。计费规则、模型倍率和资源池倍率只由服务端决定，前端不硬编码价格。多人模式当前只使用平台资源池，因此扣平台额度；standalone 个人 Key 不经过平台额度系统。

后端强制校验 `jobs.submit`、`jobs.read`、`jobs.cancel`、`assets.upload` 等权限以及 organization 数据隔离。浏览器隐藏按钮不作为权限边界。

## 数据模型与迁移

Alembic `0006_workbench_integration`：

- 扩展 `job_batches`：名称、模型、能力、幂等键/请求哈希、并发、错误和起止时间；
- 扩展 `jobs`：`client_item_id`；
- 扩展 `generated_outputs`：可空 `project_id`、`job_id`、`batch_id`、输出序号。

新增字段均为可空或带安全默认值，旧任务、旧项目和 standalone IndexedDB 数据可继续读取。

## 接口

- `POST/GET /api/v1/jobs`；
- `GET /api/v1/jobs/{job_id}`；
- `POST /api/v1/jobs/{job_id}/cancel`；
- `POST/GET /api/v1/job-batches`；
- `GET /api/v1/job-batches/{batch_id}`；
- `POST /api/v1/job-batches/{batch_id}/pause|resume|cancel`；
- 继续复用 `/assets`、`/resource-pools`、额度和登录接口。

任务与批次都使用 organization 范围的幂等键；同键不同请求返回 409。输入禁止出现 `api_key`、`token`、`secret`、`authorization`、`password` 等凭据字段。

## 页面与异常

任务中心和生成历史延续现有浅色/暗色卡片风格，包含加载、空、错误、执行、部分成功和终态。移动端使用单列，宽屏展示批次与图片网格。

已覆盖未登录、无权限、额度不足、输入缺失、格式/大小错误、素材不存在或越权、模型能力缺失、无可用 Key、429、上游超时、Worker 丢失、服务重启、空结果、部分失败、重复提交、暂停和取消。签名 URL 过期后通过重新查询任务获得新 URL。

## 测试与验收

自动化覆盖：参数与凭据校验、幂等与租户隔离、额度预占/成功结算/失败退款、批次拆分、批次并发、部分成功结算、暂停恢复、429 Key 故障转移、输出归档、Provider 文本与多图协议、前端单任务/批次请求不携带 Key、standalone 原测试回归与生产构建。

验收步骤：

1. 用普通团队成员登录多人模式。
2. 管理员配置支持 `text_generation`、`image_generation`、`image_edit`、`multi_image_reference`、`mask_edit` 的模型资源池及 Key。
3. 进入 Listing，上传产品图，运行 AI 策划并提交一张图。
4. 确认立即获得任务、额度出现预占，刷新后进度仍恢复。
5. 进入批量套图，上传模板和两件服装，以并发 1 提交。
6. 暂停并继续批次，确认未开始任务不会越过暂停状态。
7. 让一个子任务成功、一个失败，确认批次为部分成功且只消费成功任务额度。
8. 进入任务中心取消可取消任务，下载成功结果 ZIP。
9. 进入生成历史和素材中心确认输出已归档。
10. 使用另一团队账号访问原任务/素材 ID，确认返回 404。
11. 检查浏览器 Network 与构建产物，确认平台 API Key 从未下发。
12. 切换 standalone 构建，确认原 Listing、A+、批量套图和 IndexedDB 历史仍可使用。
