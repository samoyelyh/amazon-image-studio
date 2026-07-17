# Phase 4：素材中心与项目系统

## 范围与优先级

优先级：P0。依赖 Phase 2 的 MySQL、MinIO/S3 和 Alembic，以及 Phase 3 的账号、团队、RBAC 与审计日志。本阶段为 Listing 图、批量套图和 A+ 图三个现有工作台提供统一素材与项目基础，不创建新的一级业务工作台。

本阶段实现私有图片上传、图片校验、短时签名访问、团队隔离、素材分类、项目草稿、不可变项目版本、素材关联和生成输出元数据表。额度、Celery 生图任务、Provider 适配器和 API Key 池仍由后续阶段接入。

## 数据模型

迁移：`0003_assets_and_projects`，基于 `0002_identity_and_rbac`。

| 表 | 作用 |
| --- | --- |
| `assets` | 团队私有图片的存储键、文件元数据、尺寸和 SHA-256 |
| `projects` | Listing、批量套图和 A+ 三类项目 |
| `project_versions` | 只增不改的 JSON 草稿版本 |
| `project_assets` | 项目素材、角色和顺序关联 |
| `generated_outputs` | 后续任务写入的生成结果、项目版本和模块元数据 |

所有业务记录都带 `organization_id` 和创建人；可变记录同时带更新人。接口只使用 Access Token 解析出的当前团队和用户，不接受客户端传入的租户身份。

项目软删除会解除项目素材关联，但不会删除素材对象。素材被有效项目或生成结果引用时不能删除；这避免草稿出现悬空文件。项目版本不提供更新和删除接口，保存草稿始终产生下一个版本。

## 素材与对象存储安全

- 支持 JPEG、PNG、WebP；后端使用 Pillow 按真实内容识别格式，不信任扩展名。
- 校验 MIME、文件大小、宽高、像素总数和解压炸弹警告。
- 存储键以 `organizations/{organization_id}/assets/...` 隔离，不使用原始文件名作为对象键。
- 数据库保存对象键，不保存永久公开 URL。
- 列表和详情只返回默认 15 分钟有效的 S3/MinIO 签名 URL。
- 签名 URL 只在服务端完成团队权限校验后生成。
- 上传、删除、项目创建、项目版本、关联和删除均写入审计日志。

内部服务通过 `S3_ENDPOINT_URL` 访问 MinIO；浏览器签名地址通过 `S3_PUBLIC_ENDPOINT_URL` 生成。局域网部署必须在根目录 `.env` 中将后者设为主机的局域网地址，例如：

```dotenv
S3_PUBLIC_ENDPOINT_URL=http://192.168.1.20:19000
```

若保持示例的 `127.0.0.1`，只有部署主机自身能打开素材图片。

## 接口

### 素材

- `POST /api/v1/assets`：multipart 图片上传；
- `GET /api/v1/assets`：按分类、文件名或哈希分页查询；
- `GET /api/v1/assets/{asset_id}`：查询素材；
- `GET /api/v1/assets/{asset_id}/url`：重新签发短时访问地址；
- `DELETE /api/v1/assets/{asset_id}`：删除未被引用的对象并软删除记录。

### 项目

- `GET/POST /api/v1/projects`；
- `GET/PATCH/DELETE /api/v1/projects/{project_id}`；
- `GET/POST /api/v1/projects/{project_id}/versions`；
- `POST /api/v1/projects/{project_id}/assets`；
- `DELETE /api/v1/projects/{project_id}/assets/{link_id}`。

新增版本请求必须提交 `expected_version`。与数据库当前版本不一致时返回 409 `project.version_conflict`，前端应重新加载后再保存，不能静默覆盖他人草稿。

## 权限

| 角色 | 素材 | 项目 |
| --- | --- | --- |
| organization admin / manager | 读、上传、删除 | 读、写、删除 |
| member | 读、上传 | 读、写 |
| viewer | 只读 | 只读 |

平台管理员通过统一 `platform.admin` 权限继承全部操作。后端对每个接口重新校验权限；前端隐藏按钮只用于体验优化。

## 前端

多人模式新增：

- `/assets` 素材上传、分类筛选、搜索、预览和删除；
- `/projects` 三类项目创建、列表、归档、删除和 JSON 草稿版本编辑；
- 公共中心新增项目系统入口；
- Nginx 对 `/assets` 应用路由做精确 SPA fallback，直接刷新不与 Vite 的 `/assets/` 静态目录冲突。

standalone 模式保持原浏览器本地数据流程，不调用多人素材和项目接口。

## 配置

```dotenv
ASSET_MAX_UPLOAD_BYTES=20971520
ASSET_MAX_IMAGE_PIXELS=40000000
ASSET_MAX_IMAGE_DIMENSION=12000
PROJECT_MAX_DRAFT_BYTES=1048576
S3_PRESIGNED_URL_TTL_SECONDS=900
```

限制只在服务端配置，前端不硬编码安全上限。

## 测试与验收

自动测试覆盖：

- 有效图片上传、真实格式识别、签名 URL 和对象元数据；
- 非图片拒绝且不写入对象存储；
- viewer 写入拒绝；
- 素材和项目跨团队返回 404；
- 项目 v1/v2 不可变版本链和乐观锁冲突；
- 项目素材引用阻止删除；
- 删除项目保留对象；
- multipart 请求边界和 JSON 草稿请求；
- 原后端、前端和三工作台回归。

可执行验收：

1. 以团队管理员登录，进入素材中心并上传 JPEG、PNG 或 WebP。
2. 数据库保存尺寸、大小和 SHA-256；MinIO 对象位于当前团队前缀。
3. 返回地址是短时签名地址，并能从浏览器读取图片。
4. 第二团队账号查询该素材返回 404，viewer 上传返回 403。
5. 创建 Listing、批量套图或 A+ 项目后立即获得 v1 草稿。
6. 使用 `expected_version=1` 保存后获得 v2，旧 v1 内容不变。
7. 再用过期版本号保存返回 409，不覆盖 v2。
8. 素材关联项目后直接删除返回 409。
9. 删除项目后项目不可查询，但关联素材对象仍存在。
10. 直接刷新 `/assets` 和 `/projects` 均返回平台页面而不是 Nginx 404。
11. `alembic current` 为 `0003_assets_and_projects (head)`，`alembic check` 无待生成迁移。
12. 后端测试、前端测试、生产构建和真实 MinIO 冒烟测试全部通过。
