# G2A 高级视觉模型接入草案

本草案定义 provider-neutral 接口、G2A HTTP adapter，以及审核路由的受控调用入口。真实调用默认关闭，当前代码不会自动发送生产流量。

## 配置

所有运行参数来自环境变量；密钥不进入仓库、配置样例、日志、测试输出或审核证据。

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `WORDYEAH_G2A_ENABLED` | `false` | 只有显式设为 `true` 才允许 HTTP 调用 |
| `WORDYEAH_G2A_ENDPOINT` | 空 | 完整的 G2A endpoint；默认要求 HTTPS，HTTP 只允许 loopback |
| `WORDYEAH_G2A_ALLOW_PRIVATE_HTTP` | `false` | 显式允许私网 IP literal 使用 HTTP；不会允许域名或公网 IP 绕过 HTTPS |
| `WORDYEAH_G2A_API_KEY` | 空 | 运行时 secret；启用时必填 |
| `WORDYEAH_G2A_MODEL` | 空 | G2A 提供的模型 ID；启用时必填 |
| `WORDYEAH_G2A_MODEL_VERSION` | 空 | 可选的模型版本或部署版本 |
| `WORDYEAH_G2A_TIMEOUT_SECONDS` | `20` | 单次 HTTP 超时，范围 `(0, 300]` |
| `WORDYEAH_G2A_PROMPT_VERSION` | `wordyeah-avatar-review-v1` | 写入审核 attempt 的提示词版本 |
| `WORDYEAH_G2A_MAX_IMAGE_BYTES` | `10485760` | 发送前的图片字节上限 |
| `WORDYEAH_OLLAMA_ENABLED` | `false` | G2A Web 调用失败时启用本机视觉模型兜底 |
| `WORDYEAH_OLLAMA_REASONING_EFFORT` | `none` | OpenAI 兼容接口的推理强度；头像结构化审核默认关闭长推理 |
| `WORDYEAH_OLLAMA_MAX_TOKENS` | `1024` | 单次结构化结论的最大生成 token，范围 `64..4096` |
| `WORDYEAH_OLLAMA_ENDPOINT` | `http://127.0.0.1:11434/v1/chat/completions` | Ollama OpenAI-compatible endpoint |
| `WORDYEAH_OLLAMA_MODEL` | `qwen3-vl:8b` | 本机一审兜底模型 |
| `WORDYEAH_OLLAMA_SECONDARY_ENABLED` | 继承本机一审开关 | 是否启用独立二审模型 |
| `WORDYEAH_OLLAMA_SECONDARY_MODEL` | `gemma3:12b` | 低置信度或结论分歧时使用的本机二审模型 |

启用时必须同时提供 endpoint、API key 和模型 ID。不要在 shell history、截图、工单或文档中粘贴真实 secret；部署系统应通过受限环境或 secret store 注入。

Ollama 的 OpenAI 兼容响应在部分视觉模型上会出现 `message.content` 为空、请求的 JSON
结论位于 `message.reasoning` 的情况，即使请求设置了 `reasoning_effort=none`。本地 adapter
只在 content 为空且 reasoning 为非空字符串时把它作为候选结构化结论解析；content 非空时
始终以 content 为准，任何非 JSON 或字段不完整的结果仍按 `invalid_response` 失败关闭。

## 接口与响应

`src/wy_media/vision_provider.py` 定义 `AdvancedVisionProvider`、输入请求、结构化结论和稳定错误类别。G2A 只是其中一个 adapter；审核路由不需要依赖 G2A 名称。

adapter 发送 OpenAI-compatible multimodal chat JSON，并要求模型只返回：

- `decision`: `allow`、`review` 或 `block`
- `confidence`: 0 到 1
- `reasons`: 字符串数组
- `findings`: category、label、可选 score/explanation/region
- `evidence`: kind、description、可选 region

解析失败会得到 `invalid_response`，不会降级为 `allow`。鉴权错误、限流、超时、网络错误、请求错误和上游错误分别分类，并携带是否适合自动重试的标记；错误文本不包含请求 Authorization header 或响应正文。

## 升级链

建议沿用现有链路，不改变生产判定：

```text
Falconsai 本机 fast_scan 边界/低置信度
  -> vision_review_1：G2A Web 号池 grok-chat-fast
  -> G2A Web 超时、限流、网络/上游错误或无效结构：本机 Ollama qwen3-vl:8b 兜底
  -> 低置信度/与 fast_scan 分歧
  -> vision_review_2：本机 Ollama gemma3:12b 独立盲审
  -> 仍不确定、两次结论分歧、证据缺失或重试耗尽
  -> human_review
```

同一模型和提示词的再次调用应记录为 retry，而不是独立二审。每次结论通过 `VisionReviewConclusion.to_attempt_payload()` 转换成现有 attempt 字段，继续保存 provider、模型、提示词版本、findings 和 evidence。

API 接线位于 `POST /v1/review/items/{item_id}/advanced-vision`。接口只运行审核路由当前要求的 `vision_review_1` 或 `vision_review_2`，读取受控 `media://` 预览、校验图片、调用已启用 provider、追加 attempt，再重新计算路由。provider 未启用时返回 503，不创建伪 attempt。`/health/live` 与 `/health/ready` 只报告配置启用状态，不把未探测的上游写成健康。

异步入口为 `wordyeah-worker --vision`；`--once` 用于单次验收。应用在 fast scan 路由到一审后自动入队，一审结果需要独立二审时自动创建二审任务。默认二审使用 `WORDYEAH_OLLAMA_SECONDARY_*`；显式配置 `WORDYEAH_G2A_SECONDARY_*` 时由该独立 provider 取代本机二审。未配置独立 provider 时不会把同模型重试伪装成二审。job 持久化记录可运行时间、lease、attempt、错误类别和死信状态。

审核图片预览经过 JPEG 归一化后可能与原始内容哈希不同。队列同时保存原始 `content_sha256` 和受控预览 `media_sha256`：前者用于内容身份和幂等，后者用于 worker 读取前的文件完整性校验。

## Mock 与验证边界

`G2AVisionProvider` 支持注入 transport；单元测试不访问网络，也不需要真实 API key。当前验证覆盖默认关闭、请求构造、超时、HTTP 错误分类、直接/兼容 envelope 响应解析、结构化 attempt 转换和失败不放行。

2026-08-05 受控 canary 结果：

- `grok-chat-fast` 通过现有 G2A 网关对两张合成图片返回可解析的结构化视觉结论，决定均为 `allow`，单次延迟约 5.6–5.9 秒；验收证据只保存图片哈希、模型、决定、置信度和计数，不保存 API key 或原始响应。
- `grok-chat-fast` 对一张 Cravatar 受控头像预览返回 `allow`、置信度 `0.95`；同一队列任务在 G2A Web 未能给出可用结论时由本机 `qwen3-vl:8b` 成功兜底，attempt 保留实际 provider 和模型。
- `grok-4.3`、`grok-4.5` 仍返回 HTTP 429，原因是现有 Build 池可用账号为 0；错误被正确分类为可重试限流。Web 池的 `grok-chat-fast` 可用不代表 Build 模型恢复。
- 真实调用脚本为 `scripts/run_vision_canary.py`；仍需显式设置 `WORDYEAH_G2A_ENABLED=true`，默认不会访问网络。

以下尚未验证：

- 持续负载下 G2A Web 的延迟、限流、图片尺寸/MIME 约束、内容保留政策和服务条款。
- 定时上游健康探测和生产服务守护；worker 自动创建、异步退避、lease 回收、死信与 attempt 持久化已完成测试。
- 代表性 Cravatar 头像上的准确率、误报率、召回率、分歧率和人工介入率。
- 持续生产 shadow 服务的长期稳定性；本草案不授权 `enforce`，也不改变 Cravatar 头像。

代码和 systemd 样例默认关闭外部调用。本机开发审核队列已显式启用 G2A Web 与 Ollama 兜底；Cravatar 仍为只读数据接入，未启用头像写回或 `enforce`。
