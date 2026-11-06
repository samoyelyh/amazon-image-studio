# Kimi Code 主控模型调用与真实路由测速

2026-11-06，北京时间。仅在 `experiment/dsh-superagent` 实验目录测试，未改变 18080 或现有 DSH 默认模型。

## 调用方式

用户提供的 [Hermes 接入文档](https://www.kimi.com/code/docs/third-party-tools/hermes.html) 使用 Kimi Code 会员 Key。Hermes 的配置为 `base_url=https://api.kimi.com/coding/v1`、`key_env=KIMI_API_KEY`、`api_mode=chat_completions`，客户端追加 `/chat/completions`。

实际请求：

```http
POST https://api.kimi.com/coding/v1/chat/completions
Authorization: Bearer <runtime-only Kimi Code key>
Content-Type: application/json
```

```json
{
  "model": "k3.1-pro-highspeed",
  "reasoning_effort": "low",
  "stream": true,
  "max_tokens": 1200,
  "messages": ["DSH Main system prompt and request"],
  "tools": ["route_task JSON Schema"]
}
```

以上 `messages/tools` 用简写说明，完整可运行格式在 `experiments/dsh/benchmark_kimi_main.py`。接口返回 SSE，包含推理片段、工具调用分片及用量。本次真实返回的模型名与请求的两个模型 ID 相符。

该方式可用于给 DSH 提供模型推理，不要求把 Hermes 作为中间执行层。当前 DSH 的模型允许列表和平台资源池尚未接入 Kimi；这次是复用真实 Main 提示词和 `route_task` Schema，直接请求 Kimi 的路由性能测试。

[官方模型说明](https://www.kimi.com/code/docs/kimi-code/models.html) 表明 K3.1 系列支持 `low/high/max`，不能关闭思考；高速版需要相应会员权限。本文的六次请求均使用 `low`，账号对两个模型均返回 HTTP 200。官方所述高速版更高额度消耗不等于本次已测得人民币价格，返回数据没有金额。

## 六次真实结果

完整决策耗时从发出 HTTP 请求到流结束且完整 `route_task` JSON 可用，包含本机网络/代理时间。工具仅提供 Schema，**没有执行生图、MCP 或业务写入**。

| 请求 | k3.1-pro | k3.1-pro-highspeed | 路由结果 |
|---|---:|---:|---|
| 普通 A+/Listing 问答 | 5.874 秒 | 5.065 秒 | chat，正确 |
| “帮我做一套图” | 7.556 秒 | 4.143 秒 | clarify，正确询问 A+ / Listing |
| 已上传商品图、明确 Basic A+ | 9.465 秒 | 2.654 秒 | task / amazon_aplus，正确 |
| 三次均值 | 7.632 秒 | 3.954 秒 | 两者均 3/3 |

首个 SSE 事件和完整决策不是同一指标。普通版三个首事件为 1.208 / 3.727 / 7.062 秒；高速版为 1.000 / 2.524 / 1.493 秒。首事件可能只是角色或推理开始，不能把它作为可执行路由已经完成的时间。

已知总 Token：普通版 2,060，高速版 2,101，共 4,161。货币金额未知，没有以 0 费用表示。六次均无自动重试，Key 通过终端不回显输入，只驻留进程内存，未写配置文件、报告或 Git。真实调用保留记录与之前 50 次文本记录共用原台账，本轮有独立最多 6 次额度边界；旧验收窗口仍保持原 50 次。

## 结论和限制

高速版在本次三个短路由样本中平均更快，适合作为下一步 DSH Main 的候选。样本每类每模型仅一次，第二、三次可能享受共享提示词缓存；没有并发、多轮工具回复或高峰稳定性测试。

这不是整套 A+ 策划/生图性能测试，也不是完整 Harness Session 集成验收。不能把这里 2.654 秒与上次包含视觉、MCP、排队和专业策划的 297 秒直接相比；尚不能断言整套任务会按同一倍数提速。

明细与工具参数：[main-routing.json](evidence/kimi/main-routing.json)。测速脚本使用实际 `native-controller.mjs` 的 Main 提示词。所有业务工具均未执行，两个原生模型返回的六个路由决策均通过现有 Schema 校验。
