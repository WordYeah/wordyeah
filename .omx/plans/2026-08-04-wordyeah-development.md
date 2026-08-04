# WordYeah（无言会语）完整开发任务计划

> 日期：2026-08-04  
> 基线提交：`9fd652a`  
> 目标：把现有隔离 PoC 开发成可持续评测、可人工复核、可批量处理，并能在明确授权后接入 Cravatar shadow 的自托管内容审查服务。  
> 生产红线：本计划本身不授权修改 Cravatar 生产判定；`enforce` 不属于自动执行范围。

> 当前执行优先级（2026-08-04）：先完成 Cravatar 头像审查，不让文本、敏感词、OCR、视频或音频阻塞头像 MVP。完整多模态内容仍保留在后续路线中。

## 1. 已有基线与缺口

### 1.1 已有能力

- 项目模块已划分为 `wy-core`、`wy-word`、`wy-media`、`wy-review`、`wy-cravatar`，统一结果为 `allow`、`review`、`block`、`error`（`README.md:5-20`）。
- 图片和文字 PoC API 已有请求体限制、图片类型白名单、API key、内容哈希和本地模型约束（`docs/API.md:6-66`、`src/wy_media/http_server.py:12-95`）。
- Falconsai 适配器只从本地加载权重，推理请求不会下载模型或调用外部服务（`src/wy_media/falconsai.py:14-80`）。
- 图片模型错误会返回 `error`，不会转成 `allow`（`src/wy_media/service.py:28-70`）。
- 文字侧已有版本化本地规则格式和确定性规则匹配（`src/wy_word/service.py:13-115`）。
- SQLite 审核队列只存元数据，已有 pending 去重和审核事件（`src/wy_review/store.py:49-164`）。
- Cravatar 适配器是纯函数；`shadow` 和 `review` 不写头像状态（`src/wy_cravatar/adapter.py:21-46`）。
- 现有 19 样本验证只能证明模型与评测链路工作，不能证明真实头像准确率（`docs/MODELS.md:15-31`）。

### 1.2 必须补齐的缺口

1. 没有稳定的应用配置、数据库迁移、持久任务、API 版本和策略版本管理。
2. 没有真实且人工复核的 Cravatar-like 图片、文本、OCR、视频或音频数据集。
3. 图片只有单一二分类模型，尚未校准真人、动漫、文字海报和边界样本。
4. 文字只有关键词包含匹配，没有规范化、正则/词边界、OCR 或语义模型。
5. 审核队列没有 HTTP API、页面、鉴权、并发冲突保护和安全媒体预览。
6. 视频、音频、批量任务尚未实现。
7. 没有完整服务性能基线、可观测性、模型许可证清单和部署/回滚包；现有进程内基准只能作为开发预算。
8. 没有 Cravatar shadow connector；现有生产判定必须保持不变（`docs/CRAVATAR.md:3-19`）。

## 2. 范围与非目标

### 2.1 第一开发周期范围（0.1）

- 小头像的本地有界同步审查，首个强制类别为 NSFW；其他视觉类别未达到数据门槛时只允许 review 或 deferred。
- 持久化批量任务和独立模型 worker。
- Cravatar-like 头像数据标注、去重、分层指标与阈值校准。
- 内网审核页面、审核 API 和不可覆盖的审核事件。
- 模型、策略和图片结果的版本追踪。
- Cravatar connector 的隔离实现、契约测试和 staging 验证；生产只允许在单独授权后进入 shadow。

### 2.2 后续周期范围（0.2）

- 文本敏感词、规则管理、OCR 和语义模型。
- 政治人物提示、政治符号和政治文字的 review-only 识别，不做人脸身份确认。
- 多接入方适配器和批量离线作业。

### 2.3 远期范围（0.3）

- 视频抽帧、场景采样和音轨转写。
- 音频本地 ASR 后复用文字审查。

### 2.4 明确非目标

- 不调用腾讯云或其他外部内容审查 API。
- 不接受服务端任意 URL 抓取。
- 不在仓库提交真实用户头像、显式内容、模型权重或敏感词正式库。
- 不把总体 accuracy 当作唯一验收指标。
- 不自动封禁政治人物、政治符号、政治文字或模型分歧样本。
- 不在没有用户授权、shadow 证据和回滚验证时启用 `enforce`。

## 3. 开发原则

1. **先数据后阈值**：没有人工标签和各类样本数量，不调整生产阈值。
2. **错误不放行**：解码、模型、OCR、任务或数据库错误统一为 `error/held`。
3. **政治内容只复核**：规则、OCR、语义或视觉模型命中政治内容时最高只到 `review`。
4. **原始媒体最小留存**：应用数据库默认只存哈希、引用、结果和事件；原始媒体由独立私有存储按保留策略管理。
5. **API 与 worker 分离**：HTTP 进程不承担长视频、OCR、ASR 或大批量模型任务。
6. **每次决定可解释**：结果必须能追溯到内容哈希、策略版本、规则版本、模型版本和 finding。
7. **shadow 先于写入**：Cravatar 生产验证先记录、后人工复核，最后才讨论自动处理。

## 4. 推荐结构与待确认决策

### 4.1 推荐结构

```text
wordyeah/
  src/wy_api/          FastAPI 路由、鉴权、请求限制、OpenAPI
  src/wy_core/         合同、策略、配置、版本、指标、聚合
  src/wy_jobs/         SQLite 持久任务、claim、lease、retry、dead letter
  src/wy_media/        图片、视频、音频适配器
  src/wy_word/         规则、OCR、语义审查
  src/wy_review/       审核存储、服务、HTTP API、页面
  src/wy_cravatar/     connector 合同与 shadow 客户端
  migrations/          数据库 schema 迁移
  config/              只提交 schema 和 example，不提交正式词库或 secret
  scripts/             数据导入、标注导出、评测、基准、回滚验证
  tests/               unit / integration / contract / e2e
```

推荐把 stdlib HTTP PoC 迁移成 FastAPI，但保留领域服务不依赖 Web 框架。FastAPI 官方文档明确提醒重计算任务不应只依赖进程内 `BackgroundTasks`，因此模型任务采用持久 job 表和独立 worker，而不是请求结束后的内存任务：<https://fastapi.tiangolo.com/tutorial/background-tasks/>。

备选取舍：

- 保留 stdlib HTTP：依赖少，但 OpenAPI、请求校验、审核 session 和页面路由都需要重复实现，不推荐进入 0.1。
- FastAPI `BackgroundTasks`：适合短小收尾任务，但模型、视频、OCR 需要持久状态和崩溃恢复，不采用。
- Celery/Redis 或 NATS worker：跨主机能力更强，但第一台隔离主机还没有实测并发需求；达到 SQLite 写竞争或跨机要求后再引入。
- Label Studio：用于 corpus 标注；不承载 WordYeah 的审核状态机、策略版本和生产动作。

### 4.2 决策门

| ID | 决策 | 推荐默认 | 何时必须确认 |
|---|---|---|---|
| D1 | HTTP 框架 | FastAPI，领域服务保持纯 Python | 开始阶段 P1 前 |
| D2 | 单机存储 | SQLite WAL + schema migration | 多实例或多人高并发前再评估 PostgreSQL |
| D3 | 后台任务 | SQLite durable queue + 独立 worker | 跨主机并发前再评估 NATS/Redis |
| D4 | 标注工具 | Label Studio 只用于数据标注，不替代产品审核页 | 数据导入前 |
| D5 | 审核鉴权 | 独立 reviewer session，API key 不作为浏览器登录 | 审核页实现前 |
| D6 | 原始媒体保留 | 默认 7 天、私有目录、可配置为 0 天 | 导入真实样本前由用户确认 |
| D7 | 部署机器 | 先本机/隔离开发机，生产主机另行决定 | shadow 前由用户确认 |
| D8 | 人脸身份识别 | 0.1 不实现；政治内容先用 OCR/规则/语义提示 review | 任何人脸库建设前由用户明确批准 |
| D9 | 多接入方隔离 | 从 0.1 起要求 `consumer_id` + `policy_profile`，但不做复杂租户计费 | 第二个接入方开发前复核 |
| D10 | 性能与容量预算 | 小图片可同步；文本策略在 0.2 决定，OCR、语义、视频、音频默认持久异步 | P1 开工前确认首台机器和目标峰值，shadow 前用真实流量修订 |
| D11 | 已收集项目复用 | 词库按许可证和质量门闸导入；无许可证前端只参考，不复制代码 | P0 确认，文本 0.2 开工前复核上游状态 |

Label Studio 支持本地或 Docker 部署并能用于图片分类标注，适合作为 corpus 工具，但产品审核需要 WordYeah 自己的状态、策略版本和事件语义：[Label Studio 安装文档](https://labelstud.io/guide/install.html)、[快速开始](https://labelstud.io/guide/quick_start)。

## 5. 数据与策略合同

### 5.1 统一结果合同扩展

在现有 `ModerationResult`（`src/wy_core/contracts.py:28-53`）上增加：

- `schema_version`
- `policy_version`
- `rule_set_versions`
- `job_id`（异步任务时）
- `consumer_id` 与 `policy_profile`
- `source_ref`（受控引用，不包含任意 URL）
- `input_metadata`（宽高、帧数、时长、MIME；不含 EXIF 隐私字段）
- `decision_source`（rule/model/ocr/aggregate/reviewer）
- `review_required`

兼容规则：0.1 内只新增字段；已有字段不改名。任何破坏性变化必须新建 `/v2`。

### 5.2 分类与 policy

第一版 finding category：

- `sexual_explicit`
- `sexual_suggestive`
- `violence_gore`
- `hate_symbol`
- `sensitive_term`
- `political_person`
- `political_symbol`
- `political_text`
- `ocr_text`
- `model_disagreement`
- `invalid_media`

聚合规则：

1. 输入/模型/OCR 错误 -> `error`，进入 `held`。
2. 政治类命中 -> `review`，不得聚合成 `block`。
3. 任一模型落在未校准区或多模型分歧 -> `review`。
4. 只有经过人工数据校准的明确违规类别才允许输出 `block`。
5. 每次策略更新生成不可变 `policy_version`，旧审核记录继续引用旧版本。

### 5.3 数据清单

扩展现有 JSONL 规范（`docs/DATASET.md:1-20`）：

```json
{
  "sample_id": "uuid",
  "content_sha256": "...",
  "local_ref": "dataset://avatars/uuid",
  "media_type": "image",
  "style": "real|anime|cartoon|logo|poster|other",
  "expected_decision": "allow|review|block",
  "categories": ["sexual_suggestive"],
  "source": "internal-consented|public-dataset",
  "license": "private|apache-2.0|...",
  "reviewer_count": 2,
  "split": "train|calibration|test",
  "duplicate_group": "sha-or-perceptual-group"
}
```

要求：原始路径不进入评测报告；报告只保留 sample id、哈希、标签、结果和版本。

### 5.4 性能与容量基线

2026-08-04 在 M3 Ultra / MPS 上对现有 PoC 做了进程内基准。该基准使用 256/512 px 生成 fixture，不包含 HTTP、内容落盘、SQLite、任务队列、OCR、语义模型和审核写入，因此只能作为开发预算，不能当作完整服务吞吐：

| 路径 | 已测基线 | 0.1 完整服务预算 | 使用方式 |
|---|---:|---:|---|
| Falconsai 冷启动首请求 | 4.92 s | ready 前不接流量 | worker 启动时预热 |
| Falconsai warm 图片推理 | mean 9.78 ms，p95 12.01 ms，约 102 张/s | 单个 warm MPS worker 持续 30-70 张/s；小头像空队列 p95 <= 100 ms | 同步只接小图片；批量走 job |
| 1000 条规则的短文本 | mean 0.104 ms，约 9652 条/s | 单进程 1000-4000 条/s | 同步；规则集预编译并原子切换 |
| OCR | 未实测 | 规划值 100-400 ms/张，2.5-10 张/s/worker | 默认异步，只对需要 OCR 的 profile 或候选图片执行 |
| Qwen3Guard 0.6B / 4B | 未实测 | 规划值分别 5-20 / 1-5 条短文本/s | 规则优先；只处理选定类别或不确定样本 |
| 视频 | 未实测 | 最多 120 帧时，单纯图片模型约 1.2 s；完整短视频目标 1-5 s，不含 ASR | 始终异步，受总时间预算约束 |
| 音频 ASR | 未实测 | 不预设发布吞吐；P6 以实时倍率、内存和准确率实测决定 | 始终异步 |

容量推演：1 万张头像/日平均约 0.12 张/s；100 万张/日平均约 11.6 张/s。图片分类单机有余量，但若每张图片都串行执行 OCR 和 4B 语义模型，整体吞吐会降到约 1-5 条/s。因此默认执行级联：确定性规则/图片分类 -> 仅候选或不确定样本进入 OCR/语义 -> 少量进入人工复核。

容量验收规则：

1. 报告必须区分模型净推理、完整同步请求、异步 job 完成时间和人工复核效率。
2. 每次报告固定硬件、输入尺寸/时长、样本构成、并发、模型/策略版本和冷暖状态。
3. 0 样本或未安装组件记为 `SKIP`，规划值不得写成实测值。
4. MPS worker 数量不按 CPU 核数直接扩张；先比较 1/2/4 worker 的吞吐、内存和尾延迟，再确定并发。
5. 过载时使用有界队列、每 consumer 并发上限和 `429/503 + Retry-After`，不得无限堆积内存任务。

### 5.5 WordYeah GitHub 组织与外部可复用资产

2026-08-04 对 WordYeah 组织已收集仓库做了只读核查：

| 仓库 | 可复用内容 | 结论 |
|---|---|---|
| `WordYeah/Sensitive-lexicon` | MIT 中文词库；当前 fork 的 `Vocabulary` 约 87,042 行、51,340 个唯一非空词条 | 文本 0.2 的主要导入源；存在约 35,702 条重复和 505 个单字词，必须去重、分类、标来源和人工校准，不能整库直接 block |
| `WordYeah/sensitive-word` | Apache-2.0 Java DFA/Trie 实现、规范化和标签设计 | 只参考算法和测试用例；头像 MVP 与 Python 服务不引入 Java runtime |
| `WordYeah/SensitiveWordsDetection` | FastAPI + Vue 3 + Vite + Naive UI，已有敏感词、文本检测、用户和日志页面 | 仓库没有 LICENSE，且后端耦合 MySQL/阿里云 OSS并含固定初始凭据；许可证明确前只作为页面与交互参考，不复制代码或直接部署 |
| `WordYeah/sensitive-word-admin` | MIT，Vue 2 + Element UI 的敏感词控台 | 可依法参考/复用，但含完整 RuoYi/Spring/Redis/MySQL 栈，直接接入会扩大头像 MVP；文本 0.2 再评估拆取前端页面 |
| `WordYeah/node-word-detection` | Apache-2.0 Node 原生扩展，高吞吐敏感词匹配 | Python 规则基准达不到目标后才做对照，不作为首选依赖 |

复用要求：保存 upstream、commit、许可证和导入日期；词库进入 `candidate` 后先经过 normalize/deduplicate/classify，再由人工批准为不可变 `rule_set_version`。WordYeah 组织内存在 fork 不等于自动取得无许可证项目的再分发权。

图片/视频项目核查：

| 仓库 | 可借鉴内容 | 决定 |
|---|---|---|
| `qirtaiba/modtools` | MIT，Flask/Jinja 图片队列，多用户、approve/dismiss/escalate、筛选和插件状态 | 作为头像审核流程和页面信息结构参考；不引入其 HiveAI、PhotoDNA、NCMEC、PostgreSQL 和 base64 上传合同 |
| `SashiDo/content-moderation-application` | Apache-2.0，React 图片审核网格、移动端页面、阈值到人工复核的流程 | 只拆取交互思路；代码停留在 React 16、Node 10、Parse Server 3 和 2020 依赖，不作为 WordYeah runtime |
| `muxinc/content-moderation-dashboard` | Apache-2.0，现代视频审核表格、detail drawer、逐帧缩略图、阈值、批量操作，并区分 classification 与历史 decision | 作为会语 0.3 视频页面和状态语义的主要参考；不引入 Mux Robots、Convex、Vercel 或云端凭据 |
| `KOKOSde/localmod` | MIT，本地文本/图片 API，图片同样使用 Falconsai | 用作 API/测试设计对照；没有替换现有图片适配器的模型收益，不整套接入 |
| `HumanSignal/label-studio` / `voxel51/fiftyone` / `cvat-ai/cvat` | Apache-2.0/MIT，图片视频标注、模型评估和数据浏览 | 只用于 corpus 标注与模型评估，不承载 WordYeah 的审核状态、生产动作和接入方权限 |

产品分工：无言复用已有敏感词后台的信息结构，必要时在许可证确认后迁移 Vue 3 页面；会语保留自己的图片/视频审核页面和领域合同，但复用上述项目经验证的交互方式，不复制它们的云服务架构。统一设计原则是“证据跟着内容走”：图片 finding 指向区域/裁剪，视频 finding 指向时间戳/关键帧/音轨文本，审核员不需要只看一串模型分数来猜原因。

## 6. 分阶段任务

### P0 — 规格与工程基线

**目标**：在改主代码前固定合同、配置和决策边界。

任务：

- P0.1 新增 `docs/adr/`，记录 D1-D11。
- P0.2 新增头像 image/job/review/health API 的 OpenAPI 草案和统一错误码表；文本/视频接口只保留路线说明，不在头像 MVP 实现。
- P0.3 新增 `config/policy.schema.json`、`config/app.example.toml`；`config/text-rules.schema.json` 延后到 P4。
- P0.4 把图片、job、头像 review、Cravatar 的验收指标写入 `docs/ACCEPTANCE.md`。
- P0.5 建模型依赖与许可证清单：来源、版本、权重哈希、许可证、训练数据可见性、最后验证日期。
- P0.6 建 `docs/THIRD_PARTY_ASSETS.md`，记录 WordYeah 组织已收集词库/前端的 upstream、commit、许可证、允许用途和禁止直接复用项。

验收：

- D1-D11 每项都有 `accepted/deferred/rejected` 状态和负责人。
- 配置示例不含 secret；schema 能拒绝未知 decision、空词条和非法阈值。
- 头像 API 草案覆盖 image/job/review/health/metrics；未来接口不影响 0.1 schema 稳定。
- `enforce` 在所有 example 配置中均为 false。

预计：0.5-1 个开发日。

### P1 — 应用骨架、持久化与任务执行

**目标**：把单文件 PoC 变成可测试、可迁移、可恢复的本地服务。

任务：

- P1.1 新增 `wy_api` FastAPI app，先迁移 image 路由；现有 text PoC 保持隔离但不进入头像默认 app，领域服务保持无 FastAPI 依赖。
- P1.2 增加 `/health/live`、`/health/ready`、`/version`、`/metrics`。
- P1.3 增加统一配置加载和启动校验；当前 policy profile 要求的模型/规则缺失或阈值非法时 ready=false。
- P1.4 建立 schema migration 和持久表：`submissions`、`model_runs`、`findings`、`review_items`、`review_events`、`jobs`、`policy_versions`。
- P1.5 实现 job claim/lease/heartbeat/retry/dead-letter，进程崩溃后任务可恢复。
- P1.6 独立 `wordyeah-worker` 进程加载模型；API 只入队或执行有界的短图片请求。
- P1.7 增加内容哈希 + policy version 幂等键，避免策略更新后错误复用旧缓存。
- P1.8 API key 绑定 `consumer_id` 和允许的 policy profile；审核查询按 consumer 隔离。
- P1.9 CI 拆为不加载模型的快速检查和显式模型 smoke；模型缺失不能伪装成通过。
- P1.10 worker 启动时加载并预热模型；readiness 只有在必需模型、规则和数据库均可用后才为 true，关闭时先停止 claim 再完成或归还 lease。
- P1.11 增加有界同步并发、队列深度和 per-consumer 限额；过载返回可重试错误，不在 API 内存中排无限任务。
- P1.12 建首个端到端 benchmark：分别记录 API-only、API+SQLite、API+worker 的 p50/p95/p99、吞吐、错误率和峰值内存。

验收：

- API 重启后 pending job 和审核记录仍存在。
- worker 在处理中被终止后，lease 到期可被另一个 worker 回收；同一 job 不重复写最终结果。
- API 未配置 key 时只允许 loopback；绑定非 loopback 且无 key 时启动失败。
- 10 MiB 上限、MIME 白名单、畸形 JSON、空文本、模型缺失均有契约测试。
- API/worker 在测试中禁止外部网络，测试仍全部通过。
- 两个 consumer 使用同一内容哈希时结果和审核记录不串读；越权查询返回 404/403。
- 冷启动期间 ready=false；预热完成后小头像空队列 p95 <= 100 ms，达不到时记录瓶颈并调整同步预算，不通过提高超时掩盖。
- 以 2 倍目标峰值压测 15 分钟，无任务丢失、无无界内存增长；过载响应和 `Retry-After` 有契约测试。

预计：3-5 个开发日。

### P2 — 数据集、标注与质量检查

**目标**：建立真实头像和文本阈值的证据来源。

任务：

- P2.1 建私有 corpus 目录和访问规则；仓库只提交 manifest schema 和脱敏报告。
- P2.2 用 Label Studio 建图片三态标签及多类别标签模板。
- P2.3 写 `scripts/dataset_import.py`：哈希、MIME/尺寸检查、EXIF 清理、来源/许可校验。
- P2.4 写 `scripts/dataset_deduplicate.py`：SHA-256 精确去重 + perceptual hash 近重复分组。
- P2.5 写 `scripts/dataset_validate.py`：缺标签、零类别、split 泄漏、路径越界、重复样本一律失败。
- P2.6 对 test split 冻结哈希清单；模型调参不能读取 test 标签。
- P2.7 10% 样本双人复核；分歧进入仲裁。

首轮最低样本：

| 数据层 | 最低数量 | 主要指标 |
|---|---:|---|
| 普通真人头像 allow | 300 | block/review 误报 |
| 动漫/卡通头像 allow | 300 | block/review 误报 |
| logo/文字海报 allow | 100 | OCR/图像误报 |
| 边界/低俗 review | 200 | review 召回与分歧 |
| 明确违规 block | 200 | block recall |
| 政治人物/符号图片（0.2） | 100 | review recall、block=0 |
| 普通文本 allow（0.2） | 500 | 规则/语义误报 |
| 敏感/政治/变体文本（0.2） | 500 | review/block 召回 |

验收：

- test split 各关键类别样本数非零；零样本继续报告 `SKIP`，不得 PASS。
- 精确重复不跨 split；近重复组不跨 train/calibration/test。
- 所有真实数据有来源、许可/授权和保留期限。
- 双人复核子集 Cohen's kappa >= 0.75；未达到则先修标签指南，不调模型。

预计：2-5 个开发日 + 人工标注时间。

### P3 — 图片审查 v1

**目标**：形成可比较、可校准的图片模型链路。

任务：

- P3.1 定义 `ImageClassifier` adapter protocol，标准输出类别分数、模型版本、权重哈希、耗时。
- P3.2 保留 Falconsai 基线；增加 OpenNSFW2 对照适配器，不直接把任何候选设为自动封禁模型。
- P3.3 对历史误报较高的 Marqo 只做基准比较，不进入默认自动 block。
- P3.4 增加图片解码保护：像素上限、帧数上限、Pillow decompression bomb、损坏文件、GIF/WebP 动图处理。
- P3.5 增加真人、动漫、logo/poster 分层指标和阈值搜索报告。
- P3.6 增加模型分歧策略；一票 block 不等于最终 block，分歧默认 review。
- P3.7 生成 `model-card-wordyeah.json`：模型、数据版本、阈值、指标、限制和批准状态。
- P3.8 为 violence/gore、hate symbol 等类别只建立候选 adapter 和评测入口；0.1 未达到独立样本与指标门槛时只能输出 review。
- P3.9 新模型先生成对照报告并在 shadow profile 运行；不得原地替换已批准模型版本。
- P3.10 基准覆盖 256/512/1024 px、真人/动漫/poster、单张与批量，并比较 1/2/4 个 MPS worker；根据实测固定默认并发。

候选依据：Falconsai 已有本地证据（`docs/MODELS.md:3-31`）；OpenNSFW2 是 Yahoo Open-NSFW 的 Keras 实现，可作为不同架构对照：[OpenNSFW2 GitHub](https://github.com/bhky/opennsfw2)。候选必须先过许可证和真实 corpus 门闸。

验收（首轮进入 shadow 的最低指标）：

- 普通真人 block 误报率 <= 0.5%，review 率 <= 3%。
- 动漫/卡通 block 误报率 <= 0.5%，review 率 <= 5%。
- 明确违规 block recall >= 95%。
- 头像 MVP 不启用政治身份判定；若可选政治提示 profile 被启用，则政治样本 block 必须为 0，否则该项记为 deferred。
- 解码/模型 error rate < 0.5%；所有 error 均进入 held。
- M3 Ultra 模型净推理 warm p95 <= 50 ms，小头像完整同步请求空队列 p95 <= 100 ms；冷启动模型加载 <= 15 s；输出峰值内存实测并记录。真实 corpus 未达标时不得用生成 fixture 单独判 PASS。

预计：3-5 个开发日，不含数据标注。

### P4 — 文字、OCR 与政治内容 v1（0.2，头像 MVP 后执行）

**目标**：让图片中文字和独立文本进入同一策略，同时避免政治内容自动封禁。

执行条件：P7 staging 头像链路已经可用，或用户明确调整优先级。P4 不得阻塞头像 MVP 的 Gate A/B。

任务：

- P4.1 规则引擎增加 Unicode NFKC、大小写、全半角、空白/标点折叠和可选同形字规范化。
- P4.2 支持 exact、word-boundary、regex 三种规则；限制 regex 复杂度和执行时间。
- P4.3 规则文件增加 category、severity、language、effective_at、expires_at、source、version。
- P4.4 新增本地 OCR adapter；先评测 PaddleOCR 本地 PP-OCRv5/v6，禁止使用其 hosted API。
- P4.5 OCR 文本复用 `wy-word`，并把框坐标、OCR 置信度和规则命中写入 findings。
- P4.6 评测 Qwen3Guard-Gen 0.6B/4B 作为中文/多语语义候选；只在本地推理，先映射 `controversial -> review`，不得直接替代正式规则。
- P4.7 政治内容首版使用：政治词表 + OCR + 语义提示；所有命中只到 review。
- P4.8 人脸身份识别不进入 0.1；若以后需要，必须单独做隐私/法律 ADR、名单来源、误认率和删除机制。
- P4.9 增加规则集 validate/diff/activate/rollback 命令；每次激活生成不可变版本，不支持无审计的页面直接改词库。
- P4.10 规则加载时生成不可变预编译快照；exact/word-boundary 与 regex 分开执行，regex 有条数、复杂度和总时间预算。
- P4.11 增加级联路由：默认不对每张头像执行 OCR/语义模型；记录触发原因、跳过原因和各阶段耗时，允许 policy profile 明确要求全量 OCR。
- P4.12 分别基准 OCR 和 Qwen3Guard 0.6B/4B 的延迟、吞吐、内存及准确率；未达同步预算的组件只能走 job。

PaddleOCR 当前通用 OCR 支持本地 Python 安装及多语言模型，计划只采用本地推理路径：[本地安装](https://www.paddleocr.ai/main/en/version3.x/installation.html)、[OCR pipeline](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html)。Qwen3Guard 提供 safe/controversial/unsafe 三态多语安全模型，但其训练目标不是 WordPress 头像业务，因此只作为候选，必须用 WordYeah 数据独立评测：[Qwen3Guard-Gen-4B model card](https://huggingface.co/Qwen/Qwen3Guard-Gen-4B)。

验收：

- 规则规范化的旁路样本有回归测试；空 term 和高风险 regex 被拒绝。
- 200 个含文字图片测试中，需审查词条的 OCR+规则 recall >= 90%。
- 普通文本 allow 误报率 <= 1%；明确敏感词 block/review recall >= 95%。
- 政治文本/图片 block=0，review recall >= 90%。
- OCR 或语义模型失败返回 error/held，不回落到 allow。
- 规则更新可原子切换并回退到上一版本；历史结果仍能读取原规则版本。
- 普通头像 profile 的 OCR/语义触发比例、额外召回和误报分别报告；没有收益证据时不得默认全量开启。

预计：4-7 个开发日。

### P5 — 头像审核 API 与 Web 面板

**目标**：形成安全、可追溯的人工闭环。

任务：

- P5.1 实现 `docs/REVIEW.md:22-34` 中的 list/detail/approve/reject/hold/retry API。
- P5.2 增加 reviewer session、密码哈希或反向代理身份、CSRF、防暴力登录和会话过期。
- P5.3 做服务端渲染页面；列表、过滤、详情、模型 findings、规则版本、审核历史可见。
- P5.4 媒体预览只能通过受控 media id 读取；校验 allowlist、MIME、大小和访问权限。
- P5.5 所有响应加 CSP、`X-Content-Type-Options: nosniff`、禁止 iframe 和私有缓存。
- P5.6 审核动作使用 optimistic version；两个 reviewer 同时操作时只能一个成功，另一个收到 409。
- P5.7 `review_events` 追加 actor、before/after、policy version、request id、IP 摘要；禁止 UPDATE/DELETE 的应用接口。
- P5.8 增加待审数量、平均等待时间、审核分歧和 overturned decisions 指标。
- P5.9 增加键盘操作、下一条预取和批量低风险操作，但每条审核仍生成独立事件；记录匿名化的单条处理时长。
- P5.10 头像 MVP 只实现队列、筛选、缩略图/原图安全预览、findings、approve/reject/hold/retry 和事件历史；词库管理、用户组织树、爬虫和报表延后。
- P5.11 会语头像详情采用 evidence-first 布局：原图为主体，finding 可关联区域/裁剪和模型来源；分类结果与人工 decision 分开展示，阈值变化不得改写历史 decision。

验收：

- 未登录访问 review 页面和 API 均失败；API key 不能直接成为 reviewer session。
- 路径穿越、任意 URL、伪造 MIME、超大文件和 SVG 主动内容均被拒绝。
- approve/reject/hold/retry 全部有事件；并发审核产生确定的 409。
- Playwright 覆盖登录、过滤、查看、通过、拒绝、暂缓和并发冲突。
- 浏览器控制台无错误，页面无匿名公网入口。
- 用不少于 200 条混合 fixture 做审核效率演练，报告每小时处理量和误操作率；规划参考为 200-500 条/人时，不作为未实测的硬门槛。

预计：3-6 个开发日。

### [CX] 2026-08-04 执行记录

- P0 已落地：ADR、头像 OpenAPI、policy/app 示例、验收标准、第三方资产登记、SQLite schema 和模型卡已写入仓库。
- P1 已落地的范围：FastAPI image/job/health/metrics、SQLite WAL、结果与 finding 元数据持久化、job lease/retry、策略版本缓存、consumer 队列上限、独立 worker 和真实本地模型 smoke。
- P3 已落地的范围：图片适配器 protocol、静态图片解码资源限制、像素/尺寸/帧数校验、损坏图片 fail-closed；真实头像数据集和阈值校准仍未完成。
- P5 已落地的范围：reviewer token session、CSRF、登录限流、安全响应头、consumer 隔离、list/detail、approve/reject/hold/retry、乐观版本冲突、审计事件和服务端渲染页面。
- 已验证：真实 Uvicorn 审核登录、review list、服务端页面和 `media://` 安全预览 smoke。
- 已记录：`scripts/benchmark_avatar.py` 和 `artifacts/avatar-service-benchmark.json`，当前为本机 CPU 10 样本开发基线，不替代真实 corpus 或 MPS 容量验收。
- [CX] P2 工具链已开始：新增 `config/dataset-manifest.schema.json`、`scripts/dataset_import.py`、`scripts/dataset_deduplicate.py` 和 `scripts/dataset_validate.py`，支持受控本地路径、SHA-256、图片解码边界、精确/近重复报告、duplicate group 跨 split 泄漏和最低分层样本 `SKIP/INCOMPLETE` 报告；尚未导入真实头像 corpus。
- P7 只完成本地 shadow contract：`wy_cravatar.shadow` 默认关闭且只记录 metadata；未连接 WordPress、未触碰生产。
- 尚未宣称完成：代表性头像 corpus、P5 完整效率演练、Cravatar staging shadow 和生产授权。

### P6 — 批量、视频与音频（0.3，后续执行）

**目标**：复用同一合同处理长耗时媒体，不阻塞 API。

执行条件：头像 MVP 和文本 0.2 均完成，或用户明确调整优先级。P6 不得阻塞头像 shadow。

任务：

- P6.1 增加 `/v1/jobs`、`/v1/jobs/{id}`、取消和重试；批量输入只接受受控本地引用或上传。
- P6.2 图片批量任务支持 manifest、并发上限、断点续跑和逐项结果。
- P6.3 用 `ffprobe` 获取时长、codec、分辨率和轨道；先校验再解码。
- P6.4 视频采用固定间隔 + 场景变化采样；每个文件限制时长、像素、帧数和总处理时间。
- P6.5 每帧复用图片审查；保留时间戳和 top findings，不保存全部帧。
- P6.6 音轨用本地 faster-whisper 转写，再进入文字规则/语义链路。
- P6.7 视频/音频聚合策略版本化；政治类仍只 review，error 不被正常帧覆盖。
- P6.8 将解码、抽帧、图片推理、ASR、文字审查分别计时；总预算到期后任务进入明确的 timeout/held，不继续后台消耗资源。
- P6.9 对 faster-whisper 记录实时倍率、峰值内存和中文短音频错误率，再决定模型尺寸、量化和并发；不得引用其他硬件结果作为本机验收。
- P6.10 会语视频详情提供关键帧条带和风险时间轴；点击 finding 必须定位到时间戳，并同时显示该帧、视觉分数和对应音轨文本，不把视频审核退化成普通表格。

FFmpeg 官方文档是媒体探测和滤镜的实现依据：<https://ffmpeg.org/documentation.html>。音频候选采用本地 CTranslate2 推理的 faster-whisper，并在开发时固定版本和模型哈希：[SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper)。

验收：

- 任务在 API/worker 重启后可恢复；取消后不再继续写新帧结果。
- 10 个短视频 fixture 覆盖正常、边界、明确违规、损坏、无音轨、纯音频和超限文件。
- 单视频最多 120 个采样帧；超限返回明确 error，不无限消耗 CPU/GPU/磁盘。
- 转写文本、帧时间戳和最终 decision 可追溯到同一 job id。
- 原始抽帧默认任务结束即删除；失败清理有测试。
- 1/5/15 分钟视频分别报告完成时间和资源峰值；超过目标时优先减少重复帧和限制 ASR，而不是放宽总任务超时。

预计：5-8 个开发日。

### P7 — Cravatar shadow connector

**目标**：在不改变头像状态的前提下验证真实流量。

任务：

- P7.1 先在 WordYeah 仓库定义 connector HTTP contract、签名、超时、幂等和结果落库。
- P7.2 建 mock WordPress producer，发送图片 bytes，不让 WordYeah 抓任意远程 URL。
- P7.3 在 Cravatar 独立开发分支实现 feature flag，默认 `off`；`shadow` 只异步上报并记录 request id。
- P7.4 写静态检查，禁止 shadow 路径调用 BAN、删除、替换头像或更新审核状态。
- P7.5 staging 运行 100 个固定 canary，比较 WordYeah 结果、review queue 和原头像状态。
- P7.6 准备一键关闭、队列清理、connector 回退和审计查询脚本。
- P7.7 生产 shadow 前走生产系统卡、Board、变更窗口和用户明确授权。

验收：

- `shadow`、`review` 的 adapter contract 全部 `mutates_avatar=false`（延续 `tests/test_review_and_adapter.py:30-36`）。
- staging 前后头像状态哈希、数量和数据库相关字段无变化。
- WordYeah 不可用、超时、401、500 时 Cravatar 现有流程不被阻塞、不改头像。
- 关闭 feature flag 后 1 分钟内不再产生新 shadow request。
- 未获得用户授权前，不修改 `feicode-prod`，不执行生产 canary。

预计：2-4 个开发日 + 独立 shadow 观察期。

### P8 — 安全、性能、可观测性与运维

**目标**：让故障、容量和数据处理行为可验证。

任务：

- P8.1 先完成头像范围 threat model：上传、图片解析、媒体预览、模型文件、审核会话、connector；regex/OCR/视频在对应后续阶段扩展。
- P8.2 模型目录只读；记录权重 SHA-256；启动时校验允许的模型清单。
- P8.3 API/worker 资源限制：请求大小、像素、帧数、时长、并发、CPU/GPU、磁盘水位。
- P8.4 Prometheus 指标：请求数、延迟、decision、category、error、queue depth、lease、review age、model load time；不使用 email/hash 原文作为 label。
- P8.5 JSON 日志默认不含图片、完整 OCR 文本、敏感词原文或 secret。
- P8.6 SQLite backup/restore 演练；原始媒体目录按 retention 清理。
- P8.7 建 model warmup 和 readiness；模型未就绪不能 ready=true。
- P8.8 建性能报告：冷启动、warm p50/p95/p99、吞吐、内存、MPS/CPU 差异。
- P8.9 生成离线部署包、模型 manifest、systemd/container 示例和版本回退说明；不在本阶段选择或改动生产主机。
- P8.10 增加容量回归脚本和固定 benchmark manifest；每个发布候选与上一版本比较，warm p95、吞吐或峰值内存退化超过 20% 时失败或写明批准理由。
- P8.11 增加队列容量模型和告警：arrival rate、service rate、queue age、dead letter、review inflow/throughput；分别判断机器积压和人工积压。

Prometheus Python client 支持通过 HTTP 暴露指标，但 label 必须保持低基数且不包含内容标识：[官方 HTTP 导出文档](https://prometheus.github.io/client_python/exporting/http/)。

验收：

- 输入模糊测试 10 分钟无进程崩溃、无限内存增长或路径越界。
- secret、原始 OCR 文本和原始媒体不出现在日志测试快照。
- 数据库备份恢复后 submission、review item、event、job 数量和哈希一致。
- 模型缺失、磁盘低水位、worker 全离线时 ready=false 并有告警指标。
- 性能报告固定硬件、模型、输入尺寸、样本数和版本，不只给单次耗时。
- 压测覆盖目标峰值和 2 倍峰值；目标峰值下错误率 < 0.1%，2 倍峰值下允许限流但无任务丢失或内存失控。
- 从当前版本回退到上一版本后，旧 job、审核记录和 policy version 仍可读取。

预计：3-5 个开发日。

### P9 — 发布与生产决策门

**目标**：只依据证据决定是否进入 shadow、review 或 enforce。

#### Gate A：开发环境完成

- P0-P3 和 P5 的头像范围全部验收通过；P4 文本/OCR 标记为 deferred，不计入头像 Gate A。
- 真实 test corpus 达到最低数量且冻结。
- image 指标达到 P3 门槛。
- 审核页面安全与并发测试通过。
- P1/P3 性能报告完成；实测值与规划值分列，未测组件不得进入头像默认 profile。

#### Gate B：允许生产 shadow

- Gate A 通过。
- P7 staging canary 通过。
- P8 安全、容量、备份恢复、readiness 和回退验收通过。
- 部署主机、网络、鉴权、保留期限、回滚负责人已确认。
- 用户明确批准生产 shadow；Board/生产 SOP 完整。

#### Gate C：允许 review 模式

- shadow 至少运行 7 天且真实样本 >= 1000。
- 人工抽查 >= 200，普通真人和动漫分别统计。
- 没有头像状态写入事件；error/timeout 都能追踪。
- reviewer 值班、积压上限和故障处理有负责人。
- shadow 的峰值到达率低于已验证持续处理率的 50%，review 日流入不高于已演练人工处理量的 80%。

#### Gate D：讨论 enforce，不自动执行

- review 模式至少运行 14 天。
- 明确违规 block recall >= 95%。
- 普通真人、动漫 block 误报率均 <= 0.1%。
- 100% 政治类 block=0。
- 误封恢复、feature flag 关闭和数据库回滚均实测。
- 必须再次获得用户明确批准；本计划不授权该变更。

## 7. API 目标清单

```text
# 0.1 avatar
GET  /health/live
GET  /health/ready
GET  /version
GET  /metrics

POST /v1/moderate/image
POST /v1/jobs
GET  /v1/jobs/{job_id}
POST /v1/jobs/{job_id}/cancel
POST /v1/jobs/{job_id}/retry

GET  /review/items
GET  /review/items/{item_id}
POST /review/items/{item_id}/approve
POST /review/items/{item_id}/reject
POST /review/items/{item_id}/hold
POST /review/items/{item_id}/retry
GET  /review/items/{item_id}/events

# 0.2 word/OCR
POST /v1/moderate/text
POST /v1/moderate/ocr
```

所有写接口要求 request id；重试接口要求幂等键；审核写接口要求 reviewer session + CSRF。

## 8. 测试与验证矩阵

| 层 | 覆盖 | 主要证据 |
|---|---|---|
| Unit | 合同、策略、阈值、规则、聚合、lease、retention | `pytest/unittest` |
| Contract | OpenAPI、错误码、Cravatar mode、job 状态机 | schema snapshots |
| Integration | API + SQLite + worker + 本地模型 | 临时目录和真实进程 |
| Model eval | 真人、动漫、边界、违规、政治、OCR、文本 | 冻结 manifest 报告 |
| E2E | 上传 -> 模型 -> review -> 审核事件 | API/Playwright |
| Security | auth、CSRF、路径穿越、MIME、解压炸弹、regex | 负向测试与 fuzz |
| Performance | cold/warm、p50/p95/p99、吞吐、内存 | 固定 benchmark JSON |
| Shadow | request/receipt、无状态写入、关闭与回滚 | staging/生产只读证据 |

每次提交最低检查：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src scripts
ruff check src tests scripts
git diff --check
```

每个 milestone 额外运行模型 eval、API 真实进程、浏览器 E2E 和无外网测试。模型 eval 的样本数为 0 时必须 `SKIP`，不能 PASS。

## 9. 依赖顺序与里程碑

```text
P0 -> P1 -> P2
           └─> P3 image -> P5 avatar review -> P7 Cravatar staging
P1-P3-P5-P7 -------------------------------> P8 hardening -> P9 avatar gates

头像 MVP 后：P4 word/OCR -> P6 video/audio
```

- M1：P0-P1，稳定 API、数据库、worker 和配置。
- M2：P2-P3，真实头像数据、图片模型和阈值。
- M3：P5，头像审核闭环。
- M4：P7-P8，staging shadow、运维和安全证据。
- M5：P9，只做头像生产模式决策，不自动切换。
- M6（后续）：P4 文本、敏感词、OCR 和政治 review-only。
- M7（远期）：P6 视频、音频与批量。

每个里程碑都更新容量报告，不把性能工作全部推迟到 P8：M1 测请求/队列，M2 测图片模型，M3 测人工处理量，M4 用 staging 到达率修订容量和告警；M6/M7 再分别测文本级联和媒体实时倍率。

单开发者 + AI 辅助估算：可内部使用的头像功能版约 8-12 个开发日；补齐真实数据、加固、connector 和 staging 后，shadow-ready 累计约 15-22 个开发日，通常为 3-5 周；至少 7 天 shadow 观察另计。文本/敏感词/OCR 0.2 预计再用 1-2 周；视频/音频 0.3 另需约 1-2 周。

## 10. 风险与处理

| 风险 | 证据/原因 | 处理 |
|---|---|---|
| 动漫头像误报 | 通用 NSFW 模型域偏移 | 动漫单列指标；模型分歧 review；block 误报单独闸门 |
| 小样本指标虚高 | 现有正样本仅 5 个目录标签 | 冻结真实 test split；最低样本数；双人标签 |
| OCR/语义误判 | 模型语言和字体域不同 | OCR 置信度、规则和语义分别记录；政治只 review |
| 政治人物误认 | 人脸识别偏差及隐私风险 | 0.1 不做人脸身份库；以后单独授权和 ADR |
| 显式内容泄露 | 数据本身敏感 | 私有存储、最短保留、无日志、无仓库提交、受控预览 |
| API 进程被模型拖死 | 重推理、视频和 OCR 耗时 | 持久 job + 独立 worker + 资源限制 |
| SQLite 并发限制 | 多 worker 写竞争 | 单机 WAL、短事务；达到实测阈值后再评估 PostgreSQL |
| 全量 OCR/语义拖垮吞吐 | 慢组件串行套在每个请求上 | profile 级联、记录触发率；无收益证据不默认全量开启 |
| MPS 并发越加越慢 | 多进程争用统一内存/GPU | 比较 1/2/4 worker 后固定并发；按实测扩容，不按核数推算 |
| 峰值流量导致内存积压 | API 内存队列或无限并发 | 有界队列、per-consumer 限额、429/503、持久 job 和 queue age 告警 |
| 模型许可证不清 | 第三方权重训练数据/条款不同 | 每个候选先做 model manifest；不清楚即不进入发布 |
| shadow 意外改变生产 | connector 与旧逻辑耦合 | 默认 off、静态禁止写、staging 状态 diff、用户单独批准 |
| 审核积压 | review 阈值过宽或人手不足 | queue age/size 告警；按容量调 review，不以放宽 block 代替 |

## 11. 完成定义

### 0.1 开发完成

- 图片、job、头像 review API 和页面均有真实进程验证。
- 头像数据清单、标签指南、评测报告和模型 manifest 可复现。
- 关键类别样本数非零，真人/动漫误报与明确违规召回分别报告。
- 所有错误均为 error/held；没有失败默认 allow。
- review 操作可追踪且不可由匿名用户调用。
- Cravatar connector 只在 staging 验证，生产保持不变。

### shadow 准备完成

- Gate A 和 Gate B 的证据齐全。
- 用户明确批准生产 shadow。
- 已验证关闭、超时、故障和回滚路径。

### 不包含在“完成”里的事项

- `enforce` 开启。
- 政治人物自动封禁。
- 人脸身份库。
- 外部审查 API。
- 未经用户批准的 Cravatar 生产改动。
