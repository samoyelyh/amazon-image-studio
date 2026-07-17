# Phase 2 后端基础框架

本目录提供多人模式的公共后端基础设施。当前 Phase 只包含配置、健康检查、数据库迁移、Redis/Celery 和 S3 兼容对象存储抽象，不包含账号、额度或业务任务接口。

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

当前迁移头为 `0002_identity_and_rbac`。`0001_phase2_baseline` 是空业务基线，第二个迁移创建 Phase 3 的用户、团队、角色、令牌与审计表。

## 测试

```powershell
server/.venv/Scripts/python -m pytest -q server/tests
npm test
npm run build
docker compose config --quiet
```

## Phase 3 identity bootstrap

The backend now runs `alembic upgrade head` and synchronizes the built-in RBAC definitions before Uvicorn starts. Configure `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` to create the first local administrator idempotently. Existing administrator passwords are never reset during startup.

The Compose values are local development examples. Replace `JWT_SECRET`, `BOOTSTRAP_ADMIN_PASSWORD`, the MySQL passwords, and MinIO credentials before LAN sharing or production use. Production mode also requires `REFRESH_COOKIE_SECURE=true`.

See `docs/architecture/phase-3-auth-rbac.md` for the authentication flows, endpoints, migration, and acceptance tests.

`/api/v1/health/live` 仅判断 API 进程是否运行；`/api/v1/health/ready` 会实际检查 MySQL、Redis 和对象存储桶，任一失败时返回 HTTP 503。
