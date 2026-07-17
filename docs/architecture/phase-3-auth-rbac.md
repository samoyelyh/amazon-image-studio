# Phase 3：账号、团队与权限

## 范围与优先级

优先级：P0。依赖 Phase 2 的 FastAPI、SQLAlchemy、Alembic 和 MySQL，是后续素材、项目、额度、任务和资源池实现团队数据隔离的统一身份基础。

本阶段实现登录、Refresh Token、用户、团队、角色、权限、团队隔离和审计日志。不会创建额度、素材、项目、任务或 API Key 业务表，也不会部署 Keycloak。认证入口通过 `IdentityProvider` 协议预留 OIDC 替换边界。

## 安全设计

- 密码使用 `pwdlib` 推荐的 Argon2id 参数哈希，数据库不保存明文密码。
- Access Token 使用带 issuer、audience、type、jti、iat、nbf 和 exp 的短时 JWT，默认 15 分钟。
- Refresh Token 是 64 字节随机不透明令牌，浏览器仅通过 HttpOnly、SameSite Cookie 持有；数据库只保存 SHA-256 摘要。
- 每次刷新都会轮换 Refresh Token，旧令牌再次出现时撤销整个 token family 并记录 `refresh_reuse` 登录审计。
- 账号状态、团队状态、成员状态和权限在每个受保护请求中重新从数据库解析，角色变更或禁用即时生效。
- JWT 只携带服务端签发的 `sub` 和 `org`。业务接口不得信任请求体里的 `user_id` 或 `organization_id`。
- 正式环境拒绝默认 JWT Secret，并强制启用 Secure Refresh Cookie。
- Refresh Cookie 限定在 `/api/v1/auth` 路径；Access Token 只保存在前端内存，页面刷新时通过 HttpOnly Cookie 恢复。

## 数据库迁移

迁移：`0002_identity_and_rbac`，基于 `0001_phase2_baseline`。

新增表：

| 表 | 作用 |
| --- | --- |
| `users` | 本地账号、密码哈希、状态、认证提供方和平台角色 |
| `organizations` | 团队及其状态、创建人与更新人 |
| `organization_members` | 用户与团队关系、团队角色和成员状态 |
| `roles` | `platform_admin`、`organization_admin`、`manager`、`member`、`viewer` |
| `permissions` | 后端权限代码 |
| `role_permissions` | 角色和权限映射 |
| `refresh_tokens` | 刷新令牌摘要、token family、过期、撤销和轮换关系 |
| `login_audits` | 登录、刷新、切换团队、退出和令牌重放审计 |
| `audit_logs` | 资料和团队变更等操作审计 |

执行和检查：

```powershell
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
docker compose exec backend alembic check
```

回滚本阶段会删除上述身份和审计数据：

```powershell
docker compose exec backend alembic downgrade 0001_phase2_baseline
```

## 接口

### 认证

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/switch-organization`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

### 用户、团队和权限

- `GET/PATCH /api/v1/users/me`
- `GET/POST /api/v1/organizations`
- `GET /api/v1/organizations/current`
- `GET/POST /api/v1/organizations/current/members`
- `PATCH /api/v1/organizations/current/members/{member_id}/role`
- `DELETE /api/v1/organizations/current/members/{member_id}`
- `GET /api/v1/rbac/roles`
- `GET /api/v1/rbac/permissions`

团队成员接口只操作令牌中的当前团队。平台管理员也必须切换到目标团队上下文后再操作成员，避免后台参数绕过隔离。系统阻止删除或降级团队最后一名 `organization_admin`。

### 审计

- `GET /api/v1/audit-logs`
- `GET /api/v1/audit-logs/logins`

审计查询默认限定当前团队；没有当前团队的 platform admin 才能查询全局记录。

## 前端

multiuser 构建新增：

- `/login` 登录页；
- 未登录路由保护；
- 页面刷新自动恢复会话；
- Access Token 过期后单次刷新并重试；
- `/profile` 真实账号资料和团队切换；
- 根据 `platform.admin` 权限显示管理后台入口。

standalone 构建不要求登录，原有工作台、IndexedDB 和个人 API Key 流程保持不变。

## 初始化与启动

Docker Compose 启动 backend 时依次执行：

1. `alembic upgrade head`；
2. 同步系统角色和权限；
3. 按环境变量幂等创建本地 bootstrap 管理员和默认团队；
4. 启动 Uvicorn。

本地示例账号为 `admin@example.com`，密码来自 `BOOTSTRAP_ADMIN_PASSWORD`。仓库示例值只允许本机开发，局域网共享或正式部署前必须在根目录 `.env` 中替换 JWT、管理员、MySQL 和 MinIO 密码。已有管理员不会在每次启动时被示例密码重置。

启动：

```powershell
docker compose up -d --build
docker compose ps
```

## 测试与验收

自动测试覆盖：

- 正确和错误账号登录；
- Access Token 鉴权；
- Refresh Token 轮换；
- 撤销令牌重放及整个 family 撤销；
- viewer 权限拒绝；
- 跨团队成员写入拒绝；
- 最后一名团队管理员保护；
- 团队成员变更审计和登录审计；
- 正式环境 Secret 和 Secure Cookie 校验；
- standalone 路由与原图片工作台回归。

可执行验收：

1. 使用 bootstrap 管理员登录，响应包含 Access Token，浏览器收到 HttpOnly Refresh Cookie。
2. 调用 `/auth/me`，身份、当前团队、角色和权限来自服务端。
3. 刷新后 Access Token 与 Refresh Token 均发生轮换。
4. 重放旧 Refresh Token 返回 `auth.refresh_token_reused`，同一 family 的新令牌同时失效。
5. viewer 调用成员列表返回 403。
6. 第一团队管理员尝试修改第二团队成员返回 403。
7. 增加成员后可以在团队审计日志中查询到操作。
8. 页面刷新后登录状态恢复；退出后 Refresh Cookie 被清除。
9. `alembic check` 返回 `No new upgrade operations detected.`。
10. 后端测试、前端测试和生产构建全部通过。
