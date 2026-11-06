# 本地 DSH 实验使用

**当前模型（2026-11-06 后续切换）**：Main、业务 Executor、视觉 Session 均为 K2.8 Preview，实际 ID `kimi-for-coding`，固定 `reasoning_effort=low`。详见 [K2.8 切换记录](../../docs/dsh/KIMI_K28_SWITCH.md)。后文 Terra/Sol 与 K3.1 测量属于历史记录，不能当作当前默认配置。

本机已登记 Kimi 隔离资源池。全新环境需先在 `server` 目录运行 `python -m app.experiments.dsh.configure_kimi`，在不回显提示中输入用户授权的 Key；脚本只写加密凭据、不发送网络请求，也不修改已有额度上限。

当前运行真实官方 Harness Sessions，具体架构和验收见 [原生迁移报告](../../docs/dsh/NATIVE_MIGRATION.md)。旧 `verify_live.py` 中的 DSH 结果属于上一版 Ticket 包装实验，不能当作本次原生迁移证据。本次使用 `verify_native*.py`。

依赖安装：`./experiments/dsh/install-native.ps1`；启动：`./experiments/dsh/start.ps1`。默认使用 K2.8；历史模型可通过显式 `-MainModel`、`-ExecutorModel`、`-VisionModel` 参数选择，不自动回退。依赖锁固定 Harness `0.2.1-rc.3`，不启动 GitHub 编码 Executor。

当前累计文本调用 **50/50**，图片 **28/50**；文本额度不会重置。现环境适合查看、恢复已完成任务和下载。新的模型测试需要另行增加已授权额度。MCP 有一次真实请求超时且计费状态未知，禁止重发该查询。

本目录属于 `experiment/dsh-superagent` Worktree，不修改原工作目录。入口是 `http://127.0.0.1:18870/experiment`，内部 DSH 核心在 18871。原平台 18000/18080、Redis 16379 和生产数据库不变。

## 启停

在本 Worktree 根目录用 PowerShell 7 执行：

```powershell
# 首次初始化时，只有得到“复用之前接口”的明确授权后才用此开关。
& .\experiments\dsh\start.ps1 -ReuseAuthorizedProvider

# 后续启动复用本地实验配置，不再次访问生产资源配置。
& .\experiments\dsh\start.ps1

# 运行中仅重启主控，原 Worker 和已发出的图片请求继续执行。
& .\experiments\dsh\stop.ps1 -ControllerOnly
& .\experiments\dsh\start.ps1 -ControllersOnly

# 完整停止会先检查运行/派发中的 Job；数据和 Redis 均保留。
& .\experiments\dsh\stop.ps1
```

登录信息只在 `.state/login.json`，账号为 `dsh-admin`；不要为了登录打开包含接口私有配置的 runtime.json。生产侧复用已在本次任务中得到明确授权，已完成初始化，日常只需后续启动命令。

脚本使用相邻原工作目录现有 `server/.venv/Scripts/python.exe` 的已安装库，只读复用，不向该环境安装或写入项目代码。若独立搬迁，应自行建立 Python 环境并安装 `server/requirements-agent-dev.txt`，修改脚本中的 Python 路径；Node 要求本次验证的 24.14.0 或兼容版本，Docker 提供独立 Redis 容器 `ais-dsh-experiment-redis`。

## 操作

1. 登录，选择 DSH 或原 LangGraph。普通提问走只含文本 Job 的聊天路径，不能调用图片或 MCP。
2. 上传参考图会暂存 Asset，发送时通过原权限校验绑定到目标 Ticket 会话。
3. 选择“新任务”创建独立 Ticket；同一 Main Session 可保留多个任务。自动模式的修改请求继承焦点；有歧义时选择目标任务。
4. ASIN 调研不能作为我方商品事实。通过独立的“本轮明确确认的商品事实”输入保留人类确认原文，未知属性写未知。模型没有填写该字段的工具。
5. 需要先看方案时明确输入；通过原审核后再确认生成。A+ 指定小范围时使用明确表述，例如“只做2个模块”。
6. 对既有结果修改时选中原 Ticket；可在引用参数中指定 `parent_output_id` 或原 `amazon_plan_id` / `amazon_module_ids`。
7. 刷新后重新登录，保持同一 Main Session，点“恢复选中任务”。图片点击下载；有 A+ 方案时可下载原 ZIP。

原 LangGraph 选项调用原运行时，保留公共实验权限与付费上限。该 A/B 入口用于控制同样的外部条件，不等同于对原生产前端全部行为的全量对照。

## 测试和证据

```powershell
node --experimental-transform-types --test experiments/dsh/controller.test.ts
& ..\AI生图\server\.venv\Scripts\python.exe -X utf8 -m pytest server/tests/test_dsh_experiment.py server/tests/test_amazon_advisor.py -q

# 下列命令涉及真实接口；固定请求 ID 用于重读已接受的同一请求。
& ..\AI生图\server\.venv\Scripts\python.exe -X utf8 experiments/dsh/verify_live.py smoke
& ..\AI生图\server\.venv\Scripts\python.exe -X utf8 experiments/dsh/verify_live.py aplus
& ..\AI生图\server\.venv\Scripts\python.exe -X utf8 experiments/dsh/verify_isolation.py
& ..\AI生图\server\.venv\Scripts\python.exe -X utf8 experiments/dsh/verify_recovery.py
& ..\AI生图\server\.venv\Scripts\python.exe -X utf8 experiments/dsh/collect_evidence.py
```

真实验收脚本建立在本次已留存的 `.state/image-dsh-result.json` 等回执上；全新安装需要先建立对应的首张图片样本。本次脚本不是任意环境的一键生产验收工具。修改请求内容时必须使用新 ID；未知收费结果不会因为重新运行脚本而自动重试。

每类接口总上限为 50 次，跨 Worker/重启共享，不会自动重置。API 未返回货币金额时成本保持未知；Token、额度积分和 MCP 预留单位分别记录。

`.state`、官方 Harness 安装目录、凭据、数据库和日志不入 Git。可审阅的无密钥测量、隔离结果与真实图片样本位于 `docs/dsh/evidence`。
