# Phase 5：统一额度与计费

## 范围与优先级

优先级：P0。依赖 Phase 3 的账号、团队、RBAC 和审计日志，以及 Phase 4 的项目基础。本阶段提供后续 Celery 任务系统必须复用的额度事务能力，不创建任务、Provider 或 API Key 资源池。

实现内容：额度账户、额度流水、额度预占、成功/部分成功结算、失败释放、消费后退款、计费规则、额度套餐、费用预估接口和多人额度中心。

## 数据模型

迁移：`0004_quota_and_billing`，基于 `0003_assets_and_projects`。

| 表 | 作用 |
| --- | --- |
| `quota_accounts` | 每个团队唯一账户，总余额、冻结余额和版本号 |
| `quota_transactions` | grant、recharge、reserve、consume、release、refund、adjust、expire 不可变流水 |
| `quota_reservations` | 操作预占、数量、单价、实际消费、释放、退款和过期状态 |
| `quota_rules` | operation_code、基础费用、四类倍率和生效区间 |
| `quota_packages` | 可购买额度包的额度、价格、币种和有效期元数据 |

额度使用整数点数。账户满足：

```text
available_balance = balance - reserved_balance
0 <= reserved_balance <= balance
```

每条流水同时保存 `balance_delta`、`reserved_delta`、操作后的余额和冻结额，因此任何账户变化都能重放与审计。

## 原子操作与幂等

所有写操作在一个数据库事务中完成，并按统一顺序锁定团队额度账户行，再读取或锁定预占记录。唯一约束为：

- `quota_accounts.organization_id`；
- `quota_reservations(organization_id, idempotency_key)`；
- `quota_transactions(organization_id, idempotency_key)`。

### 预占

1. 后端读取当前生效计费规则并计算费用。
2. `SELECT ... FOR UPDATE` 锁定团队账户。
3. 在锁内重新读取幂等键，重复输入返回原预占；相同键不同输入返回 409。
4. 检查可用额度，不足返回 402，不创建预占或流水。
5. 增加冻结余额，创建 reservation 和 reserve 流水。

### 结算

- 全部成功：消费完整预占，余额和冻结额同时减少。
- 部分成功：按预占时锁定的整数单价乘实际数量消费，并释放剩余冻结额度。
- 全部失败或取消：余额不变，释放全部冻结额度。
- 消费后退款：增加余额并创建 refund 流水；支持部分退款与幂等重试。
- 预占默认 60 分钟到期；Phase 6 由 Celery Beat 调用释放服务扫描长期冻结记录。

相同结算幂等键和相同实际数量可安全重复执行；不同输入尝试重结算返回 409。

## 计费规则

当前统一 operation_code：

```text
listing.plan
listing.generate
batch_tryon.generate
aplus.plan
aplus.generate
```

启动时幂等创建全局默认规则，默认基础费用为每计费单元 10 点。规则支持：

- 模型倍率；
- 质量倍率；
- 分辨率倍率；
- 资源池倍率；
- 团队级覆盖；
- 生效和失效时间；
- 启用状态。

单价在服务端使用 Decimal 计算并向上取整，最终费用为整数单价乘数量。默认示例将个人资源池倍率设为 0，表示使用个人 Key 时不扣平台额度；该行为由后端规则控制，不由 React 判断。

## API

团队成员可调用：

- `GET /api/v1/quota/account`；
- `GET /api/v1/quota/transactions`；
- `GET /api/v1/quota/reservations`；
- `GET /api/v1/quota/rules`；
- `GET /api/v1/quota/packages`；
- `POST /api/v1/quota/estimate`。

只有平台管理员可调用：

- `POST /api/v1/quota/adjustments`。

预占、结算、释放和退款不作为普通浏览器业务接口暴露。Phase 6 的任务创建与 Worker 通过 `billing_service` 在服务端事务中调用，防止客户端伪造任务状态或实际费用。

费用预估请求只提交 operation_code、数量和倍率选择；后端查规则并返回费用、当前可用余额及是否充足。最终任务提交时必须再次由后端计算并预占，不能信任此前的预估值。

## 权限与审计

- viewer、member、manager、organization admin：`quota.read`、`quota.estimate`；
- platform admin：额外拥有 `quota.manage`；
- 人工调整写入额度流水和统一审计日志；
- 所有读取按 Access Token 当前团队过滤，跨团队数据不可见。

组织管理员不能给自己的团队增发额度。支付充值、规则管理和套餐管理界面留到管理后台阶段。

## 初始化与配置

后端启动顺序：

1. `alembic upgrade head`；
2. 身份和 RBAC 初始化；
3. 计费规则、套餐和团队账户初始化；
4. Uvicorn 启动。

本地 Compose 默认给 bootstrap 团队 10,000 点，便于后续阶段联调：

```dotenv
BOOTSTRAP_QUOTA_BALANCE=10000
QUOTA_RESERVATION_TTL_MINUTES=60
```

生产环境应按真实套餐和运营流程配置初始额度，不应沿用本地示例赠送值。初始化是幂等的，服务重启不会重复赠送。

## 前端

多人模式 `/quota` 提供：

- 可用、冻结和总余额；
- 后端费用预估；
- 生效规则和套餐展示；
- 不可变额度流水；
- 预占状态；
- 仅平台管理员可见的人工调整入口。

额度数据由 TanStack Query 从服务端读取，不写入 localStorage，不在前端模拟冻结、扣减或退款。standalone 模式继续显示阶段说明，不调用多人额度服务。

## 测试与验收

自动测试覆盖：

- 基础费用和四类倍率；
- 个人资源池零倍率；
- 额度不足不写预占；
- 重复预占幂等和不同输入冲突；
- 完整消费、部分成功结算和剩余额度释放；
- 失败释放；
- 消费后退款与退款幂等；
- 团队数据隔离；
- 平台管理员调整与普通团队管理员拒绝；
- 前端预估请求不提交客户端费用；
- 原登录、素材、项目和工作台回归。

真实 MySQL 并发验收：

1. 创建 100 点临时团队账户。
2. 两个事务并发预占 60 点。
3. 仅一个成功，另一个返回 `quota.insufficient`。
4. 两个事务用同一幂等键并发预占 40 点。
5. 两者返回同一个 reservation ID。
6. 数据库只有一笔对应 reserve 流水。
7. 清理临时团队，级联删除测试账户和流水。

页面验收：使用 bootstrap 管理员打开 `/quota`，可见 10,000 可用额度；数量 20、默认单价 10 时，后端预估显示消耗 200，且当前页面没有控制台错误。
