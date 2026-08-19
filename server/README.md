# 多人平台后端（已完成 Phase 6）

本目录提供多人模式的账号、团队/RBAC、素材与项目、额度计费、Celery 任务和多 API Key 资源池。Phase 7 已将 Listing、批量套图、A+、任务中心和生成历史接入统一服务端任务系统，详见 `docs/architecture/phase-7-workbench-integration.md`。

## 本地 Python 开发

在项目根目录执行：

```powershell
py -3.10 -m venv server/.venv
server/.venv/Scripts/python -m pip install -r server/requirements-dev.txt
Copy-Item server/.env.example server/.env
Set-Location server
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m uvicorn app.main:app --reload --port 18000
```

MySQL、Redis 和 MinIO 连接参数通过 `server/.env` 配置。不要提交真实密码或平台 API Key。

## Docker Compose

从项目根目录启动完整平台：

```powershell
docker compose up -d --build
docker compose ps
```

默认地址：

- 前端：`http://127.0.0.1:18080`
- 后端文档：`http://127.0.0.1:18000/api/v1/docs`
- 后端 readiness：`http://127.0.0.1:18000/api/v1/health/ready`
- Flower：`http://127.0.0.1:15555`
- MinIO Console：`http://127.0.0.1:19001`
- MySQL：`127.0.0.1:13306`
- Redis：`127.0.0.1:16379`

宿主端口可在根目录 `.env` 中覆盖。容器内部仍使用标准端口。

停止服务但保留数据：

```powershell
docker compose down
```

删除本阶段创建的 MySQL、Redis 和 MinIO 数据卷：

```powershell
docker compose down -v
```

`down -v` 会永久删除本地容器数据，仅应在明确需要重置开发环境时使用。

## 数据库迁移

```powershell
docker compose exec backend alembic current
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade -1
```

当前迁移头为 `0005_tasks_resource_pool`。迁移按 Phase 2 基线、身份/RBAC、素材/项目、额度计费、任务/资源池顺序执行。

## 测试

```powershell
server/.venv/Scripts/python -m pytest -q server/tests
npm test
npm run build
docker compose config --quiet
```

## Phase 3 identity bootstrap

The backend now runs `alembic upgrade head` and synchronizes the built-in RBAC definitions before Uvicorn starts. Configure `BOOTSTRAP_ADMIN_ACCOUNT` and `BOOTSTRAP_ADMIN_PASSWORD` to create the first local administrator idempotently. Existing administrator passwords are never reset during startup.

The Compose values are local development examples. Replace `JWT_SECRET`, `BOOTSTRAP_ADMIN_PASSWORD`, the MySQL passwords, and MinIO credentials before LAN sharing or production use. Production mode also requires `REFRESH_COOKIE_SECURE=true`.

See `docs/architecture/phase-3-auth-rbac.md` for the authentication flows, endpoints, migration, and acceptance tests.

Phase 6 的中转站 Key 必须通过后端 Key 接口加密保存。不要将平台 Key 放入前端环境变量、Provider config、任务 input 或任何浏览器存储。完整配置和恢复机制见 `docs/architecture/phase-6-tasks-resource-pool.md`。

`/api/v1/health/live` 仅判断 API 进程是否运行；`/api/v1/health/ready` 会实际检查 MySQL、Redis 和对象存储桶，任一失败时返回 HTTP 503。
