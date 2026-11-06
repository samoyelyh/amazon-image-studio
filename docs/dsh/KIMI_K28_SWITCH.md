# 切换 K2.8 Preview

2026-11-06，北京时间。范围为独立实验目录 `AI生图-dsh-superagent` / 18870，18080 仍维持原部署。

- Main、业务 Executor、视觉分析统一配置为 `kimi-for-coding`。
- 思考档显式固定为 `low`，避免该模型默认的 `max`；流式请求保留。
- K3.1 和高速版未加入 DSH 自动路由或回退列表。
- 现有 `gpt-image-2` → `gpt-image-2.5-flare` 生图资源保持原样。
- 使用已有资源池和 Worker 发起未来请求。用户提供的 Key 仅以原平台加密格式存入隔离数据库，无明文 Key 配置或 Git 记录。
- 旧 Ticket、图片、成功回执和 Session 历史保留；新模型使用不同 Session ID，避免混用旧模型的历史推理。
- 补充思考内容的流式收集及工具调用历史回传，保留 Kimi 连续工具调用所需上下文。

配置入口为 `experiments/dsh/start.ps1`、`model-policy.mjs` 和隔离资源池。内部 18871 `/health` 返回各角色的实际配置型号，可不调用模型核对切换。

本次没有发送收费模型请求，没有测 K2.8 延迟，也没有重置既有测试次数上限。此前六次 K3.1 路由速度不能作为 K2.8 的速度结果。

官方模型 ID 与思考档依据：[Kimi 模型配置](https://www.kimi.com/code/docs/kimi-code/models.html)。官方对应关系为 `kimi-for-coding` → K2.8 Preview，`kimi-for-coding-highspeed` 对应的是 K2.7 高速版。
