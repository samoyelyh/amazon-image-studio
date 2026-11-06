# DSH 实验交付记录

> **当前状态：18080 已正式接入并默认使用原生 DSH / K2.8。** 当前代码、真实八图 A+、单图修改、MySQL、React、回退及遗留问题见 [正式交付](PLATFORM_18080.md)。以下为历史阶段记录。

> **原生迁移更新**：当前 DSH 路径已使用真实 Harness Main / Vision / Executor Sessions，退出旧 LangGraph 规划器。完整真实商品结果、未通过项和 18080 切换限制见 [NATIVE_MIGRATION.md](NATIVE_MIGRATION.md)。以下是之前 Ticket 包装实验的历史记录。

2026-11-06，北京时间。结论：值得继续验证 **DSH Ticket 管理层**；现有证据不足以采用完整编码原型替换生产主控。独立 Adapter 已能运行真实任务，规划、Skill、Job、Worker、Provider 和图片版本继续使用原平台。

## 分支与访问

- 实验分支：`experiment/dsh-superagent`
- 起点：`codex/agent-control-v2`，`b838c7cf80db2d46665375ba29dda7b836163d6a`
- 原未提交源码的隔离快照：`502d3601073bbbee0c963215b01c5cb48f2f0246`
- 实验目录：`C:\Users\Woda\Documents\AI生图-dsh-superagent`
- 最终实现 Commit：本分支 HEAD，完整 SHA 随交付消息提供；可执行 `git rev-parse HEAD` 核对。
- 本地入口：[DSH 实验页面](http://127.0.0.1:18870/experiment)
- 本地登录：`experiments/dsh/.state/login.json`；不包含生产接口密钥。

启动/停止/控制器单独重启命令见 [使用说明](../../experiments/dsh/README.md)。原生产分支的 HEAD、Git 状态和本次快照涵盖的全部源码哈希保持不变；原生产健康检查 HTTP 200。没有修改或部署原主控，没有合并或推送。

## DSH 实际运行到了哪一层

[官方原型](https://github.com/deepseek-ai/dsh-superagent-prototype) 固定到 `8c32a9dc5d72c033816c6a8110b37f40cf94fba4`。依赖安装、typecheck、build 成功。完整 Harness / Superagent 插件曾真实返回管理 API HTTP 200，但停在 `setupPending / repositoryUnset`；没有启用其 GitHub 编码 Executor，探针结束后已停止。

**当前运行的是官方 DSH 核心 Engine 的受限 Sidecar**。它真实持久化 Trigger、Ticket、Mandate、Subscription、Assignment 和恢复记录；平台 Adapter 实现 Main Session 路由和固定 Executor 端口。语义规划仍由现有 LangGraph 完成。没有用 Mock Ticket DTO 或第二套图片引擎替代这些实现。

直接嵌入完整原型需要适配 Cordis/Harness 服务注入、GitHub/飞书 Sources、编码工作目录、默认 OS 命令权限以及单机管理 API；其多用户模型与本平台不同。实际接入图、原平台盘点、依赖版本和文件清单见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 本地验证结果

| 测试 | 实际结果 |
|---|---|
| 普通聊天 | 真实文本返回；没有创建 Ticket、图片 Job 或 MCP 查询 |
| 单图及连续修改 | 真实生成红杯 V1；同 Ticket 修改背景得到 V2，父版本正确，下载成功 |
| 同一 Main Session 的多任务 | 两个独立 Ticket 和原生会话，分别产出 2 张黄色碗图、1 张绿色瓶图 |
| 批量并发 | 原 JobBatch.concurrency=2；两个图片请求的真实执行时间重叠 |
| 运行中重启 | 图片请求进行时重启 API 和 DSH Sidecar，Worker 未停止；两个 Ticket 的 Assignment 从 1 增为 2，原 Ticket ID 保留 |
| 付费防重 | 重启中的图片请求账本仍为一条；再次发送同一 A+ 修改请求复用原 Run，额外 Provider 调用为 0 |
| 受控 ASIN 工具 | 真实 `asin.detail` 返回 US / B0716YP6VJ 商品数据；实际 tools/call=1，chargedUnits 未返回 |
| ASIN Agent 整链 | 未通过。该链的一次 MCP 连接在 tools/call 前失败，原业务保留 unknown，后续被 `agent.research_unverified` 阻断；未强行补发 |
| 商品事实 → A+ 方案 | 确认原文同时进入门禁和原 user 历史后，通过原证据质检，产出两模块真实方案并等待审核 |
| A+ 整套生成 | 确认方案后并发生成 2 张真实图片 |
| 只改第二模块 | 只增加 1 个图片任务/结果，目标 `cup_detail` 生成 V2，第一模块原 Output 保留 |
| ZIP | 原 ZIP 接口返回可完整解压的文件，包含 3 个图片版本，缺失输出模块为 0 |
| 账号/组织隔离 | 同组织其他用户、跨组织用户：任务列表为空；会话、图片和伪造续聊均返回 404 |
| 浏览器交互 | 尚未验收。浏览器控制连接报 timeoutMs 错误，原生窗口捕获不可用/最小化；HTTP 页面及脚本解析通过，不能视作浏览器操作通过 |

真实生成共 **8 张图片**：杯子 V1/V2、并发任务 3 张、A+ 初版 2 张、第二模块 V2 1 张。测试使用明确标记的合成商品输入，不等同于客户真实商品保真验收。

专项回归为官方核心 Adapter Node 测试 7 项、Python Adapter 与既有 Amazon 回归 26 项。原上游在 Windows 上为 1155 通过、42 失败及 17 个未处理错误，涉及 POSIX 命令、路径和权限假设；没有宣称其完整测试通过。

## 模型、耗时和成本

截至本次固定请求验证，实际请求为：

| 请求 | 次数 |
|---|---:|
| `gpt-6.1-sol` | 16 |
| `gpt-6.1-terra` | 3 |
| 文本合计 | 19 |
| `gpt-image-2.5-flare` | 8 |
| 卖家精灵 `tools/call` | 1 |

每类硬上限均为用户授权的 50 次，账本跨 Worker/重启保留。MCP metadata `tools/list` 与真实 `tools/call` 分开；Schema/连接预检查失败不冒充已完成调研。曾发现实时 Schema 比旧快照少了 `SA` 站点，只更新了实验审批文件，未改生产配置。

已知 Token 为 **173539**（输入 159145、输出 14394；reasoning 1881 是输出细分，不再另加）。一个失败文本请求没有 usage。Provider 没有返回货币金额，MCP 没有返回 chargedUnits，因此 API 金额成本保持未知，不能写成 0，也不能把内部额度当人民币。

本机 DSH 领域路由样本为 1.03–7.16ms，这只是同步 Ticket 操作，不是模型规划耗时。真实杯子修改从 Run 创建到首个图片 Job 约 33s，A+ 第二模块修改约 44s，均包含原模型/工具规划与等待。所测新请求的 API 接收回执如杯子修改 4.79s、A+ 方案 1.01s；有流式数据的文本首字指标约 4.58–20.34s，未返回该指标的请求保留空值。

真实杯子修改从请求到最终结果 72.78s；A+ 方案审核前 131.68s，确认后的图片生成 44.67s，第二模块修改 77.01s。批量两图通过持久时间戳得到约 65.86s，另一个任务约 42.85s。重读已完成请求的毫秒级时间单列为缓存回放，不当作模型速度。

完整逐请求统计、JobAttempt、首字/usage 和失败码见 [measurements.json](evidence/measurements.json)。规则路由样例为 14/14，仅为确定性门禁回归，不能作为通用语义路由准确率。

## A/B 对照与真实阻塞

相同红杯单图请求在 DSH 模式下完成真实生图；原 LangGraph 对照样本的文本 Provider 发生 `provider.network_error`，没有产出图片，未知收费结果未重试。两边仍共用原 LangGraph 规划器、Skill 和 Provider。此次无法得出同条件的速度、成本或成功率提升结论。

两次早期 A+ 失败也完整保留：一次原质检没有识别“恰好2个Amazon Basic A+模块”的小范围表达；另一次模型的用户确认引文不能与原文对齐。实验 Adapter 修复了“事实确认只进入新门禁、不进入原用户历史”的接入缺口，随后以明确范围与逐字事实引用复测通过，未禁用原证据检查。

尚未完成的验收包括：ASIN Agent 整链成功对照、原 LangGraph 稳定的多样本 A/B、浏览器完整交互、复杂多任务语义消歧、Worker 在未知付费响应期间崩溃后的自动恢复、生产级负载与 OS 沙箱。当前自动归属依赖保守规则和焦点/目标选择；不能声称已经具备完整官方 Main Session 的语义能力。

## 采用建议

继续保留这个可切换的 Ticket Adapter 有价值：独立任务上下文、长期任务实体、明确聊天/执行边界、运行中恢复和原付费链防重已经有真实证据。下一步应围绕这些能力做同条件多样本验证，并补齐 MCP 整链与浏览器验收。当前不具备替换或部署生产主控的依据。

可审阅证据：[账号隔离与下载](evidence/isolation.json)、[A+ 模块/版本/ZIP/防重](evidence/aplus-delivery.json)、[真实杯子 V1](evidence/cup-v1.png)、[杯子 V2](evidence/cup-v2.png)、[A+ 第一模块](evidence/aplus-module-1.png)、[A+ 第二模块 V2](evidence/aplus-module-2-v2.png)。
