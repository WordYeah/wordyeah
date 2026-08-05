# WordYeah avatar API

头像 MVP 使用 FastAPI + 独立 worker；领域服务仍不依赖 Web 框架。旧的
stdlib server 仍保留为隔离 smoke 入口，但不作为新 API 的实现目标。

完整接口草案：`docs/openapi-avatar-v1.yaml`。

## `GET /health/live`

只报告进程存活，不代表模型 ready。模型调用仍为本地路径。

## `GET /health/ready`

模型、数据库和配置完成启动预热后返回 200；否则返回 503。冷启动期间不接图片请求。

## `POST /v1/moderate/image`

- Bind: `127.0.0.1:18765` by default (`WORDYEAH_BIND`/`WORDYEAH_PORT`)
- A non-loopback bind requires `WORDYEAH_API_KEY`; without it startup fails.
- Body: raw image bytes (`Content-Length` required)
- Supported content types: `image/jpeg`, `image/png`, `image/webp`, `image/gif`, `image/bmp`
- Maximum body: 10 MiB by default (`WORDYEAH_MAX_BODY_BYTES`)
- No URL input; the service does not fetch remote content.
- Model loading uses `local_files_only=True`.
- If `WORDYEAH_API_KEY` is set, requests require `Authorization: Bearer ...`.
- Adapter requests select a preconfigured workspace with
  `X-WordYeah-Workspace`. Unknown or disabled workspace IDs are rejected;
  `WORDYEAH_WORKSPACES_JSON` declaratively creates/reconciles the allowed
  workspace list at startup.
- Adapters may attach local, non-URL identifiers with
  `X-WordYeah-Source-ID` and `X-WordYeah-Source-Ref`. They are stored with the
  model run and review item so a final decision can be traced back to the
  originating Cravatar job without storing credentials or remote URLs.
- Results are bounded in-memory by content SHA-256 for repeated-request
  idempotency; image bytes are not stored in SQLite.
- 每次新来源结果会写入 `submissions`、`model_runs` 和 `findings` 元数据表；同一
  workspace 下重复的 `source_id` 不会重复计数，原始图片不进入 SQLite。
- `review`、`block` 会进入 pending review；`error` 会进入 `held`，没有可用持久化或队列时不返回 allow。
- 图片在模型解码前执行格式、尺寸、像素数和动图帧数限制；动图默认拒绝，不取第一帧冒充静态头像。

Example response shape:

```json
{
  "request_id": "...",
  "content_sha256": "...",
  "media_type": "image",
  "decision": "allow|block|review|error",
  "reasons": [],
  "findings": [],
  "top_score": 0.002,
  "model_versions": {
    "media.nsfw": "Falconsai/nsfw_image_detection",
    "policy": "policy-1-<content-hash-prefix>"
  },
  "elapsed_ms": 12.3,
  "error": null
}
```

## `POST /v1/moderate/text`

Accepts a bounded JSON body such as `{"text":"..."}` and returns the same
result contract. The PoC has no built-in sensitive-word list. To load a local
rule file at startup, set `WORDYEAH_TEXT_RULES=/private/path/text-rules.json`.
The file must have the versioned shape shown below; a missing or invalid file
aborts startup rather than silently allowing all text.

```json
{
  "version": 1,
  "rules": [
    {"label": "example_block", "terms": ["example-token"], "decision": "block"},
    {"label": "example_review", "terms": ["review-token"], "decision": "review"}
  ]
}
```

The example terms are placeholders, not a production sensitive-word list.

`error` is fail-closed at the API boundary. The Cravatar adapter is not part
of this PoC and no production decision is changed.

## `POST /v1/jobs`

头像 MVP 只接受受控的本地 `media://` 引用，例如：

```json
{"kind":"moderate_image","media_ref":"media://avatar-001.png"}
```

任务会持久化到 SQLite，worker 使用 lease claim；远程 URL、任意路径和未受控文件引用都会被拒绝。
`WORDYEAH_MAX_QUEUE_DEPTH`（默认 1000）限制单个 workspace 的 queued/running
任务数；超过上限返回 `429` 和 `Retry-After: 1`。

策略从 `WORDYEAH_POLICY_PATH` 加载。启动时会校验 profile、阈值和 `enforce=false`，
并把策略内容哈希加入结果的 `model_versions.policy`；策略变更不会复用旧内存缓存。

## `GET /v1/jobs/{job_id}` / `POST /v1/jobs/{job_id}/cancel`

分别读取和取消 queued job。worker 崩溃或 lease 到期后任务会重新进入队列，达到最大尝试次数后进入 `failed`。

## 审核 session 和页面

- `GET /review/login`、`POST /review/login`：使用环境变量中的 reviewer token 建立 HttpOnly、SameSite=Strict session。
- `GET /review`：服务端渲染证据优先页面。
- `GET /review/items`、`GET /review/items/{id}`：只返回当前 `consumer_id` 的项目和事件。
- `POST /review/items/{id}/approve|reject|hold|retry`：必须带 session CSRF token 和版本号；冲突返回 `409`。
- `GET /review/items/{id}/attempts`：返回追加式 AI 审核 attempt。
- `POST /v1/review/items/{id}/attempts`：供已认证 Agent 写入完整 attempt，随后执行
  `fast_scan → vision_review_1 → vision_review_2 → human_required/auto decision` 路由。
- `GET /review/items/{id}/media`：只服务 `media://` 下的安全静态图片，拒绝路径穿越、远程 URL、SVG 和动图。
- `/review/overview|agents|policies|quality|history|health|account|guide`：要求 reviewer session
  的运营、模型、策略、质量、审计、健康、账户和指南页面。

服务路径基线脚本为 `scripts/benchmark_avatar.py`，示例结果写入
`artifacts/avatar-service-benchmark.json`。小样本 CPU 结果只用于开发预算，不能替代
M3/MPS、真实头像 corpus 或 15 分钟过载测试。

## Text baseline

The `wy-word` module exposes a deterministic rule service for tests and local
integration. OCR and semantic models are separate future adapters and are not
implied by a rule match.
