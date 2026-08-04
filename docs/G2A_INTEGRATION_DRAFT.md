# G2A 高级视觉模型接入草案

本草案定义 provider-neutral 接口、G2A HTTP adapter，以及审核路由的受控调用入口。真实调用默认关闭，当前代码不会自动发送生产流量。

## 配置

所有运行参数来自环境变量；密钥不进入仓库、配置样例、日志、测试输出或审核证据。

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `WORDYEAH_G2A_ENABLED` | `false` | 只有显式设为 `true` 才允许 HTTP 调用 |
| `WORDYEAH_G2A_ENDPOINT` | 空 | 完整的 G2A endpoint；远端必须使用 HTTPS，HTTP 只允许 loopback 开发地址 |
| `WORDYEAH_G2A_API_KEY` | 空 | 运行时 secret；启用时必填 |
| `WORDYEAH_G2A_MODEL` | 空 | G2A 提供的模型 ID；启用时必填 |
| `WORDYEAH_G2A_MODEL_VERSION` | 空 | 可选的模型版本或部署版本 |
| `WORDYEAH_G2A_TIMEOUT_SECONDS` | `20` | 单次 HTTP 超时，范围 `(0, 300]` |
| `WORDYEAH_G2A_PROMPT_VERSION` | `wordyeah-avatar-review-v1` | 写入审核 attempt 的提示词版本 |
| `WORDYEAH_G2A_MAX_IMAGE_BYTES` | `10485760` | 发送前的图片字节上限 |

启用时必须同时提供 endpoint、API key 和模型 ID。不要在 shell history、截图、工单或文档中粘贴真实 secret；部署系统应通过受限环境或 secret store 注入。

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
fast_scan 边界/低置信度
  -> vision_review_1：G2A 或其他高级视觉 provider
  -> 低置信度/与 fast_scan 分歧
  -> vision_review_2：不同模型或不同模型家族的独立 provider，默认盲审
  -> 仍不确定、两次结论分歧、证据缺失或重试耗尽
  -> human_review
```

同一模型和提示词的再次调用应记录为 retry，而不是独立二审。每次结论通过 `VisionReviewConclusion.to_attempt_payload()` 转换成现有 attempt 字段，继续保存 provider、模型、提示词版本、findings 和 evidence。

API 接线位于 `POST /v1/review/items/{item_id}/advanced-vision`。接口只运行审核路由当前要求的 `vision_review_1` 或 `vision_review_2`，读取受控 `media://` 预览、校验图片、调用已启用 provider、追加 attempt，再重新计算路由。provider 未启用时返回 503，不创建伪 attempt。`/health/live` 与 `/health/ready` 只报告配置启用状态，不把未探测的上游写成健康。

## Mock 与验证边界

`G2AVisionProvider` 支持注入 transport；单元测试不访问网络，也不需要真实 API key。当前验证覆盖默认关闭、请求构造、超时、HTTP 错误分类、直接/兼容 envelope 响应解析、结构化 attempt 转换和失败不放行。

以下尚未验证：

- G2A 实际 endpoint、鉴权头、模型 ID 和响应 envelope 是否与当前 OpenAI-compatible 假设一致。
- 真实调用的延迟、限流、计费、图片尺寸/MIME 约束、内容保留政策和服务条款。
- worker job 自动创建、异步重试退避和定时健康探测；同步受控 API、attempt 持久化和 vision_review_1/2 路由接线已经完成测试。
- 代表性 Cravatar 头像上的准确率、误报率、召回率、分歧率和人工介入率。
- 生产 shadow；本草案不授权 `enforce`，也不改变 Cravatar 头像。

在获得 endpoint 契约和单独授权前，保持 `WORDYEAH_G2A_ENABLED=false`。
