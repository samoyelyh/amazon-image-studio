# DSH 全品类营销与创意总监交付

2026-11-06；工作分支 `experiment/dsh-superagent`。本次在现有 18080 React / FastAPI / MySQL 平台部署，默认仍为原生 DSH + K2.8；没有调用 LangGraph 的需求、Skill 或图片规划入口。最终镜像为 `amazon-image-studio-backend:dsh-creative-final`、`ais-dsh-native:creative-final`，前端 `amazon-image-studio-frontend:creative-v2`。

## 已实现的业务链路

Main Session 决定聊天、澄清、任务归属、是否研究、是否只审方案。专业 Executor 在**同一次策划**里提交商品事实、五条购买理由、创意概念、模块与独立槽位。没有增加串行的“创意总监规划模型”。

`CreativeStrategy` 保存每条理由的事实引用、优先级、消费者利益、场景、可信程度和展示方式。五条主题由模型按商品决定，允许复用事实、多个理由进入同一模块或同一理由贯穿多个模块。它们是内部营销推理，不能直接视为合规刊登文案。没有 MCP 数据的任务明确标注市场假设；`verified_mcp` 必须引用当前用户、本对话真实有数据的回执。

创意概念包含主题、受众、动机、情绪、记忆元素、配色、摄影语言、字体与叙事。模块的 `narrative` 引用购买理由并说明故事段落、镜头目的和表现方法。Prompt Composer 将主题、配色、镜头目的、相关消费者利益与真实事实编入最终执行 Prompt，已有 Skill 哈希与这些决策一同进入 Job 的 `design_trace`。

精确标题、正文和规格保存在原生文字字段；现有 React 模块预览与 ZIP 的 HTML 使用这些文字。新版选择的受限字体类别和十六进制颜色也实际作用于原生排版。没有新增生图引擎或通用 Shell/SQL 工具。

生成前在同次策划中写明取舍并校验事实引用、映射、真实模块与槽位。生成后用一次受控视觉 Session 看真实商品参考及整套输出，保存具体问题、对应 Output ID、修改建议和局限，**不打审美分数，不自动重收费生成**。超过九张独立输出时明确转人工完整审阅，不能假称已经看完。

“先审方案”在 Main 工具选择和 Python 服务端都有付费图片拦截；普通明确生成仍直接提交。失败策划的后续对话可继续原 Ticket；历史用户事实只从同用户同组织的真实 user 消息引用，不从 assistant 文本获得“用户确认”。

## 真实三品类结果

家居与电子资料按用户授权使用公开官方商品。杯子事实与原图来自 [IKEA FÄRGKLAR 官方页面](https://www.ikea.com/us/en/p/faergklar-mug-matte-green-40478189/)；鼠标来自 [Logitech 官方页面](https://www.logitech.com/en-us/shop/p/mx-anywhere-3s.910-006925)及[官方规格](https://support.logi.com/hc/en-gb/articles/12895017855127-Specification-MX-Anywhere-3S)。Seattle 卫衣沿用用户原图。公开商品不是我方商品事实，也未假称做过 Amazon VOC/竞品研究。

| 品类 | 旧版完整结果 | 新版完整结果 | 新版主题 | 生成前规划 | 专业 Executor 次数 |
|---|---:|---:|---|---:|---:|
| Seattle 卫衣 A+ | 8 张 / 5 模块 | 8 张 / 5 模块 | Home Field Feeling | 174.039 秒 | 2（含一次校验修正） |
| IKEA 杯子 A+ | 7 张 / 5 模块 | 8 张 / 5 模块 | Quiet Green Ritual | 108.288 秒 | 1 |
| Logitech 鼠标 Listing | 5 张 | 5 张 | Work Anywhere, Focus Quietly | 174.804 秒 | 2（含一次校验修正） |

两套 A+ 包含 header、左右图文、三图文与侧栏等真实模块；不是等尺寸宣传图合集。新版 A+ 各有 970×600、600×600、600×800、600×350 等独立槽位；Listing 为独立 1600×1600 附图。

完整拼接包含所有画面与原生文案，没有挑选最佳单图：

- [卫衣新旧整套](evidence/creative/hoodie-full-comparison.jpg)
- [杯子新旧整套](evidence/creative/mug-full-comparison.jpg)
- [鼠标新旧整套](evidence/creative/mouse-full-comparison.jpg)

拼接图便于完整检查画面，实际模块排版以平台“双端排版预览”和 ZIP 中 `preview.html` 为准。原始图片、全部版本、精确文案与 ZIP 在忽略目录 `experiments/dsh/.state/creative/delivery/{案例名}/`；每套还提取了可直接打开的 `native-preview/preview.html`。

当前验收浏览器可打开：

- [卫衣](http://127.0.0.1:18080/workspaces/agent-control?conversation_id=5047e347-f9ca-40d5-a0d4-91b02e10ac7b)
- [杯子](http://127.0.0.1:18080/workspaces/agent-control?conversation_id=82c267cd-1469-4c35-a604-c834efbe5523)
- [鼠标](http://127.0.0.1:18080/workspaces/agent-control?conversation_id=6ca2cf30-4ed1-4193-a617-1bbb32a37198)

记录属于隔离测试账号；其他账号不能读取这些任务和文件。每套的五点、创意方向、模块映射、完整实际 Prompt、Skill 哈希、Job / Output / Ticket / Session、延迟与 Token 在 [measurements.json](evidence/creative/measurements.json)及同目录各案例 JSON。

## 修复与验收

真实调用发现并修复了三个执行问题：

1. 旧 Listing 校验强制服装方向，且新模块映射在 Schema 中可省略。新版使用必填映射及全品类方向；关联理由的事实由编译器继承，避免要求模型重复抄写 ID。参数校验现在返回具体 422 业务错误。
2. 原交付契约强制“整件不得裁切”，与局部特写矛盾；多槽位 Prompt 又混入整个模块目标。新版仅对已策划的创意任务遵循槽位景别，保留旧任务原行为。卫衣颜色槽位已从整件加气泡改为一张独立局部画面，其他七张 Output ID 均保持。
3. 读取旧 Run 会向同 Ticket 新 Assignment 报告完成，导致修改后的视觉 Session 无可用授权。报告现在绑定原 Assignment；旧轮询不能结束新任务。第一次鼠标修改的自动审阅因此未启动，未发出该次模型请求；修复后卫衣修改的真实视觉审阅成功。旧失败记录保留，不改写成成功。

| 项目 | 真实结果 |
|---|---|
| 普通聊天 | Main 回答；零图片 Job |
| “帮我做一套图” | 澄清 A+ / Listing；零图片 Job |
| 完整商品资料 | 自动策划并生成；无生成许可申请 |
| 三品类完整套图 | 新版 21 张全部成功，原版完整结果保留 |
| 并发与进度 | Provider 调用时间重叠峰值 6；原页面百分比、逐张结果可见 |
| 指定鼠标图修改 | 仅一个 Job；其余四个 Output ID 不变 |
| 指定卫衣细节修改 | 仅一个 Job；其余七个 Output ID 不变；父版本链正确 |
| 只审方案 | 真实 `save_listing`，五点映射到三张；零图片 Job；继承历史商品资料 |
| 隔离 | 另一账号访问对话、Run、图片、ZIP 均 404；成员切主控 403 |
| 持久化 | 服务更新与浏览器刷新后，原任务、方案、图片及版本仍可读取 |
| 管理员回退 | LangGraph → DSH 往返，21 个新版初始 Output ID 不变，无新增模型调用 |
| ZIP | 浏览器真实下载杯子整套；各套 API ZIP 解包完整性通过 |
| 零付费检查 | 69 项后端、12 项原生 Engine / Harness、7 项 React 检查通过；React 生产构建通过 |

本次没有新 MySQL 表或破坏性迁移；新增策划与审阅保存在既有 HermesMessage JSON，Job / Worker / Provider / 文件交付保持原服务。持久化的辅助策略与预算窗口为 SQLite 增量表。原工作区 `git status --porcelain=v1 -z` 哈希仍为 `e67059e21fb30bc4ef5737a1299dc91abbe840234e645fc01bc1c3acd5d0b4a6`。

## 耗时、额度与限制

三案例旧版平均规划 **109.016 秒**，新版 **152.377 秒**。新版鼠标与卫衣包含校验修正，不能称整体提速；最终修复后杯子只用 Main + 一次专业 Executor，约 108 秒，复用了先前视觉事实。杯子 Executor 为 97.038 秒，旧版 89.935 秒；新增分析并非零耗时。旧卫衣使用两张额外风格模板，视觉缓存也不同，因此这不是严格控制变量的性能实验。

生成后视觉审阅分别约 104.6 / 41.9 / 211.2 秒。该阶段不阻止已生成图片的预览与下载，但鼠标的高分辨率多图输入仍显著偏慢。

本轮预算窗口上限每类 40 次，实际 **文本 36、图片 35、MCP 0**。包含两类旧版基线、开发校验失败及恢复、三套新版、两次单图修改、聊天与方案审核；不是只计算成功展示案例。36 次文本均收到 usage，合计 **486,127 Token**（含缓存及开发调用）；图片 Token 和现金费用未返回，记为未知。旧成功回执、未知付费防重不因新预算窗口清空。

视觉验收是**部分通过**：鼠标的滚轮、共享空间、多设备与出行叙事更明确；杯子以生活仪式与清理事实组成一套；卫衣的细节槽位已纠正，但整套仍有前后视角重复。Logo、复杂印花、小字和微观纹理仍可能重绘，不能称像素保真；颜色近景的合成织纹也不能证明真实材质。原生标题正文可准确排版，但商品自身字形依旧需要人工对照。

事实推断也有局限：鼠标模型曾将玻璃厚度写成错误限定；杯子文案曾补出未经尺寸数据支持的杯架兼容性。两处已用原生文案编辑移除，无新增图片请求；原始 Job 快照仍保留以供追溯。这也说明自动审阅不能替代事实校对。内部购买理由仍可能把材质观感推断为耐用等价值，不应自动视为已验证功能。语义事实校验、重复构图与专业审美仍需继续改进；没有用固定分数宣称质量达标。

卖家精灵历史 ASIN 的未知费用状态保持阻断；本轮没有新 ASIN，未再次调用 MCP，不能据此宣称其历史超时已解决。

## 改动入口

- `server/app/agents/creative_strategy.py`、`amazon_brief.py`、`amazon_contracts.py`：五点、创意主题、事实与模块契约。
- `professional_prompts.py`、`amazon.py`、`aplus_design.py`、`image_delivery_service.py`：实际 Prompt、追踪、独立槽位与特写交付。
- 原有三个 `capabilities/skills/*/SKILL.md`：策划、事实、摄影、排版与审阅规则。
- `experiments/dsh/native-controller.mjs`、`controller.ts`、`sidecar.ts`、`native-runtime.mjs`：真实 Main / Executor / 视觉审阅、只审方案和 Assignment 归属。
- `server/app/experiments/dsh/native.py`、`ledger.py`、`dsh_platform.py`、`openai_compatible.py`：受控工具、持久化、全局付费防重、Token 记录。
- 现有 `AgentAmazonCard.tsx`、`AmazonModulePreview.tsx`、`amazonAgentApi.ts`、`amazon_export.py`：原聊天页的创意、五点、映射、审阅与精确排版。
- `creative_accept.py`、`creative_checks.py`、`collect_creative.py`、`creative_deploy.py` 及相关测试：可追溯的真实验收与安全更新。
