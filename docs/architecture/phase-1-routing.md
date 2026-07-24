# Phase 1：前端路由与工作台边界

## 本阶段目标

在不改变现有生成链路的前提下，把原单页应用拆分为统一应用壳层和三个独立工作台。默认 `VITE_DEPLOYMENT_MODE=standalone`，继续使用浏览器 API 配置、IndexedDB、现有 Provider 调用和本地批量队列；`multiuser` 只建立前端部署边界，不伪造服务端数据。

优先级：P0。后续账号、素材、额度和异步任务都依赖稳定的路由、工作台和部署模式边界。

## 归类与复用判断

| 能力 | 处理方式 | 原因 |
| --- | --- | --- |
| Listing 图 | 保留为现有工作台，路由 `/workspaces/listing` | 复用策划、Prompt Builder、生成、历史与下载 |
| 批量套图 | 保留为现有工作台，路由 `/workspaces/batch-tryon` | 复用批次模型、本地队列、重试和 ZIP 下载 |
| A+ 图 | 保留为现有工作台，路由 `/workspaces/aplus` | 复用 A+ 模块规则、策划和文案生成 |
| 设置、弹窗、图片缓存、IndexedDB | 公共基础设施，继续复用 | 避免为单个工作台重复实现 |
| 任务/素材/额度/个人/管理页面 | 只建立正式路由与阶段说明 | 对应后续服务端 Phase，不提供虚假数据 |

## 必须改造的耦合

- `App.tsx`：从固定单页组件树改为 Query Provider、Router 和全局弹窗层。
- `AmazonPlanner.tsx`：由组件内部三页签改为固定 `mode`，不能在同一实例中跨工作台切换。
- `store.ts`：Listing 与 A+ 分别保存 Prompt、参考图、蒙版和生成参数；批量套图继续使用独立 `batchTryOnBatch`。
- `Header` 与应用壳层：统一桌面侧栏、移动端导航和部署模式提示。

## 路由与部署模式

- standalone 使用 Hash Router，保证 GitHub Pages、静态文件和局域网静态部署直接刷新可用。
- multiuser 使用 Browser Router，并为后续 FastAPI 网关保留 `VITE_API_BASE_URL`。
- 桌面端使用侧栏，移动端使用底部横向导航；暗色模式沿用现有系统主题。

## 后续依赖与开发顺序

1. Phase 1（本阶段，P0）：路由、应用壳层、部署模式、工作台状态隔离。
2. Phase 2（P0，依赖 Phase 1）：FastAPI、SQLAlchemy、Alembic、MySQL、Redis、Celery、MinIO/S3 骨架与健康检查。
3. Phase 3（P0，依赖 Phase 2）：统一账号、团队、角色与后端权限校验。
4. Phase 4（P1，依赖 Phase 2/3）：项目、素材中心、对象存储和统一历史。
5. Phase 5（P0，依赖 Phase 2/3）：额度账户、流水、预占、结算与退款。
6. Phase 6（P0，依赖 Phase 2/3/5）：任务中心、Celery 拆分、Redis 并发、API Key 池与 Provider 适配器。
7. Phase 7（P1，依赖 Phase 4/5/6）：三个工作台接入服务端任务、素材、额度与审计。
8. Phase 8（P1/P2，依赖前述阶段）：管理后台、运维能力与完整端到端测试。

## 后续数据库影响（本阶段不建表）

Phase 2 起按公共基础设施建模，核心实体包括用户、团队、成员与角色、套餐、额度账户与流水、额度预占、项目、素材、任务、任务子项、生成历史、API Key 资源、Provider 配置和审计日志。所有表使用团队/用户归属字段实现数据隔离，任务和计费操作使用幂等键；新增可选字段优先允许为空并通过 Alembic 迁移兼容旧数据。

## 后续接口边界（本阶段不发请求）

- `/api/v1/auth/*`：登录、刷新、退出和当前用户。
- `/api/v1/projects`、`/assets`：项目与素材。
- `/api/v1/tasks`、`/batches`：任务提交、拆分、查询、取消和重试。
- `/api/v1/quota/estimate`、`/quota/transactions`：费用预估、流水与结算结果。
- `/api/v1/admin/*`：团队、套餐、额度、Key 池、Provider、任务和审计。

后端必须重新校验身份、团队、角色、套餐、数量、并发和额度。前端不得直接循环调用外部生图接口；multiuser 模式统一提交服务端任务并立即返回任务 ID。

## 风险与兼容性

- 旧入口自动重定向到 Listing；standalone 不强制登录。
- 原 `galleryInputDraft` 继续作为当前工作台兼容别名，旧持久化草稿迁移到 Listing。
- Listing/A+ 非当前草稿中的图片 ID 必须参与引用扫描，防止 IndexedDB 清理误删。
- Hash Router 改变 standalone 地址为 `#/workspaces/...`，但不要求服务器增加 SPA fallback。
- 大包体警告属于原应用整体依赖问题，后续可按工作台懒加载拆包，不阻塞本阶段。

## Phase 1 验收步骤

1. 使用默认 standalone 模式启动应用，无需登录。
2. 访问 Listing、批量套图和 A+ 三个独立路由，刷新后仍可打开。
3. 在 Listing 填写 Prompt、加入参考图并修改生成参数。
4. 切换 A+，确认初始 Prompt、参考图和参数不继承 Listing。
5. 在 A+ 填写另一份数据，再返回 Listing，确认 Listing 草稿恢复。
6. 进入批量套图，确认模板、服装列表、队列、重试和下载入口仍存在。
7. 打开设置、图片详情、Lightbox 和历史记录，确认公共弹窗正常。
8. 在桌面和移动宽度检查导航、空状态、暗色模式。
9. 执行 `npm test` 和 `npm run build` 均通过。

