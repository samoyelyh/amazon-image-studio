# Phase 2：后端基础框架

## 范围与优先级

优先级：P0。依赖 Phase 1 的部署模式和路由边界，是 Phase 3 账号权限、Phase 4 素材项目、Phase 5 额度以及 Phase 6 任务资源池的共同基础。

本阶段建立 FastAPI、SQLAlchemy、Alembic、MySQL 8、Redis、Celery、Celery Beat、Flower、MinIO/S3 和 Docker Compose。没有实现登录、业务表、计费或外部生图任务，避免抢跑后续 Phase。

## 组件边界

| 组件 | 本阶段职责 |
| --- | --- |
| FastAPI | API 路由、OpenAPI、CORS、请求 ID、统一异常和健康检查 |
| Pydantic Settings | 环境变量、SecretStr、连接信息和部署配置 |
| SQLAlchemy | 异步引擎、连接池、声明式 Base 和命名约定 |
| Alembic | 唯一迁移入口和 Phase 2 空业务基线 |
| MySQL 8.4 | 后续用户、团队、额度、项目、任务与审计的主数据库 |
| Redis | Celery Broker/结果后端以及后续并发与短期状态 |
| Celery | `default`、`maintenance` 队列和 Worker 基础配置 |
| Celery Beat | 每 60 秒投递系统心跳，不扫描业务数据库 |
| Flower | Worker 和队列监控入口 |
| StorageService | upload、download、delete、exists、签名 URL、metadata、health |
| MinIO | 开发环境私有对象存储；正式环境可替换任意 S3 兼容服务 |

## 接口

- `GET /health`：容器级轻量存活检查。
- `GET /api/v1`：服务名称、版本和环境。
- `GET /api/v1/health/live`：API 进程存活。
- `GET /api/v1/health/ready`：并行检查 MySQL、Redis、对象存储；失败返回 503。
- `GET /api/v1/docs`：FastAPI OpenAPI 文档。

健康响应只返回错误类型，不返回数据库密码、Redis URL 或 S3 密钥。

## 数据库迁移

迁移 `0001_phase2_baseline` 不创建业务表，只创建 Alembic 自身的 `alembic_version` 并记录版本。这样 Phase 3 可以从明确基线新增账号、团队、角色和审计模型，不需要回写或猜测数据库状态。

## 队列与对象存储

- FastAPI 不执行耗时生图任务。
- Celery 使用 JSON 序列化、late ack、Worker 丢失时拒绝确认、prefetch 1。
- 系统维护任务进入 `maintenance`，未来业务任务按 operation 类型进入独立队列。
- MinIO 初始化容器只创建私有桶，不设置公开匿名访问。
- 业务代码只依赖 `StorageService`，不直接依赖 MinIO URL 或永久公开地址。

## Docker Compose 服务

`frontend`、`backend`、`worker`、`celery-beat`、`flower`、`mysql`、`redis`、`minio` 和一次性 `minio-init` 均在 `platform` 网络内运行。后端启动前执行 `alembic upgrade head`；frontend 通过 Nginx 同源代理 `/api/v1/`。

默认宿主端口使用 18080、18000、15555、13306、16379、19000 和 19001，以避开本机常见的 80、8000、3306、6379、9000 冲突，均可由根目录 `.env` 覆盖。

## 安全与兼容性

- 示例密码仅用于本地开发，共享或生产部署必须替换。
- 平台公共 API Key 不进入前端，也不属于本阶段配置。
- standalone 构建、IndexedDB 和浏览器个人 Key 流程不变。
- multiuser 前端编译为 Browser Router，并通过同源 `/api/v1` 访问后端。
- MySQL 8 使用默认 `caching_sha2_password`，通过 `cryptography` 完成安全认证，不降级认证插件。
- Shell 脚本强制 LF，避免 Windows 工作区构建 Linux 容器时因 CRLF 启动失败。

## 验收步骤

1. 执行 `docker compose up -d --build`。
2. `docker compose ps` 显示 frontend/backend/mysql/redis/minio 健康，worker/beat/flower 运行。
3. readiness 返回 database、redis、storage 三项 `ok`。
4. MySQL `alembic_version` 为 `0001_phase2_baseline`。
5. Redis 返回 `PONG`。
6. 通过 `StorageService` 上传、下载、检查并删除测试对象成功。
7. 向 `maintenance` 队列发送 `system.heartbeat` 并得到成功结果。
8. Flower 页面返回 HTTP 200 并可看到 Worker。
9. 前端 `/api/v1/health/ready` 同源代理可用。
10. 后端测试、前端测试和生产构建全部通过。
