# wy-review 审核工作台

完整的 AI 多级审核流水线、页面、交互、状态和数据合同见
[`REVIEW_WORKBENCH.md`](REVIEW_WORKBENCH.md)。本文只记录当前头像 MVP 已实现的接口和安全边界。

当前已实现 `/review/login`、`/review`、`/review/items` 及 approve/reject/hold/retry
动作。审核 session 与 API key 分离。单 reviewer 可使用
`WORDYEAH_REVIEWER_TOKEN`；双审/仲裁使用 `WORDYEAH_REVIEWERS_JSON` 的
`reviewer_id -> token` 映射，并通过 `WORDYEAH_REVIEW_SESSION_SECRET` 签发会话。
这些值只从环境变量读取。

```bash
WORDYEAH_REVIEWERS_JSON='{"reviewer-a":"runtime-secret-a","reviewer-b":"runtime-secret-b","arbitrator":"runtime-secret-c"}'
WORDYEAH_REVIEW_SESSION_SECRET='independent-runtime-session-secret'
```

同一 reviewer 不能提交两次双审，也不能仲裁自己参与过的样本。

真实 corpus 验收不要使用 `WORDYEAH_LOCAL_REVIEW_NO_AUTH`。运行时凭据保存在仓库外
0600 JSON，固定包含 `reviewer-a`、`reviewer-b`、`arbitrator` 和独立 session secret；
token 不写入文档、日志或验收证据。服务启动后可执行只读登录验收：

```bash
python scripts/audit_reviewer_runtime.py \
  --runtime /private/wordyeah/reviewer-runtime.json \
  --base-url http://127.0.0.1:8768 \
  --output artifacts/reviewer-runtime-acceptance-mvp.json
```

验收器只允许 loopback HTTP，要求凭据文件拒绝 group/other 访问，分别建立三份 cookie
session，并核对账户身份、`corpus-primary-v1` 和 `dual-review-10pct-v2`；输出不包含 token。

## 页面

`/review` 是 AI Agent 优先的图像审核工作台，视觉结构按 Windsor 风格参考稿收敛：
灰色页面背景中的白色圆角应用框、浅灰侧栏、顶部工作区栏、稀疏的状态标签和单行审核
列表。主列表只保留人工决策所需的信息：受控缩略图、AI 建议、finding 摘要、审核状态
和置信度，不把统计卡片和批量操作塞进同一屏。

交互逻辑：

- 状态标签切换 `待审核`、`已留置`、`已处理` 和 `全部`；`已处理` 覆盖通过与拒绝。
- 搜索框按 item ID、哈希、media ref、建议、策略和 finding 标签筛选；状态和风险下拉框
  可组合使用。
- 点击列表项打开单项证据视图；详情按“左侧 Configuration / 人工动作、右侧
  Controlled media preview / Model finding summary / Content evidence”分栏。
- 头像菜单、审核说明和操作记录使用折叠或下钻交互，默认不占用审核列表空间。
- 详情页的 approve / reject / hold / retry 是人工动作；YOLO/快速标记直接提交，不弹确认框。
- 网格、列表、沉浸三种视图可切换；显式批量模式最多处理 50 项，并逐项显示结果。
- 顶栏/侧栏工作区切换使用服务端工作区配置，切换后队列、事件、attempt 和 cursor 都按 consumer 隔离。
- 质量页直接显示真实抽检样本；独立 reviewer 可完成双审，结论分歧后只向未参与审核的仲裁员显示通过/拒绝动作，全程不弹确认框。

### 私有 corpus 的 AI 预标注

代表性 corpus 可以先进入与普通头像相同的高级视觉链，质量页把模型输出显示为
“AI 建议”，用于减少人工阅读成本。AI 预标注和人工真值是两条独立记录：预标注不会写入
`quality_decisions`，不会设置 `quality_samples.final_decision`，也不计入 1,100 条主审、
110 条双审或仲裁完成数。模型上下文不包含 corpus 分层或预期标签，避免把选样信息泄露给
被测模型。

命令默认只读；实际入队必须显式使用 `--apply`。写入模式要求数据库是非符号链接的 0600
普通文件，并受活动任务水位限制：

```bash
python scripts/enqueue_corpus_ai_prelabels.py \
  --database /private/wordyeah/avatar-corpus-review/wordyeah.sqlite3 \
  --consumer-id corpus-avatar

python scripts/enqueue_corpus_ai_prelabels.py \
  --database /private/wordyeah/avatar-corpus-review/wordyeah.sqlite3 \
  --consumer-id corpus-avatar \
  --max-active-jobs 2000 \
  --apply
```

脚本按 corpus item id 幂等关联审核项目，并按已归属的 proposal attempt 幂等确保下一阶段
`vision_review_1` 或 `vision_review_2` 任务。报告固定声明
`production_write=false`、`mutates_avatar=false` 和
`counts_toward_ground_truth=false`，同时比较执行前后的样本数、人工决定数和已收敛数；任何
变化都按错误处理。入队不等于模型已完成，只有 attempt 成功后质量页才显示实际 AI 建议。

质量预标注可以使用受限 worker 独立消费，避免前面的普通视觉任务阻塞本批次；筛选条件
同时约束 consumer、视觉任务种类和入队时写入的受控 context marker，默认 worker 行为不变：

```bash
.venv/bin/python -m wy_jobs --vision \
  --database /private/wordyeah/avatar-corpus-review/wordyeah.sqlite3 \
  --media-root /private/wordyeah/avatar-corpus-review/media \
  --consumer-id corpus-avatar \
  --vision-context-marker quality_ai_prelabel=true \
  --vision-stage vision_review_1 \
  --worker-id corpus-prelabel-1
```

二审使用同样的 consumer/context 约束，并将 `--vision-stage` 改为
`vision_review_2`；worker 会继续执行独立 provider/model/prompt 检查。G2A 或 Ollama
的超时、限流和无效响应仍按原有 lease/backoff/dead-letter 规则处理；筛选器不会跳过
同一预标注任务自身的失败重试，也不会把模型 attempt 写成人工决定或最终头像结论。
只有携带完整 proposal metadata、两个精确 context 标记，并能由成功 job result 追溯到的
attempt 才能进入质量建议；无来源 attempt 不参与路由或质量统计。

高级视觉调用可能同时经历远端超时和本机模型排队。worker 在模型调用期间按租约时长的
三分之一自动续租，避免超过默认 120 秒的请求被其他 worker 当成失联任务重新领取；续租
失败时不会继续写 attempt 或最终路由，而是安全重试或返回已经被接管的任务状态。

## 安全边界

- 只绑定 loopback/private network；不做公网匿名审核入口。
- 页面鉴权与 API 鉴权分开配置，所有决策动作需要 reviewer 身份。
- `media_ref` 默认只指向 allowlisted 本地/私有对象；Cravatar 队列可使用严格校验的 `cravatar://<32 位 MD5>`，UI 仅拼接到 allowlisted `https://cn.cravatar.com/avatar/`。禁止浏览器访问调用方提供的任意远程 URL。
- 默认 SQLite 只存哈希、模型结果、状态和审计，不存原始图片；图片预览只能通过 reviewer session 和 allowlisted `media://` 引用端点提供。
- 错误和超时进入 `held`，不显示成 `allow`。
- 单项与批量动作都受 CSRF + optimistic version 保护；高风险和特殊类别在服务端禁止批量决定。

## 最小动作 API

```text
GET  /review/items?status=pending&cursor=...
GET  /review/items/{id}
POST /review/items/{id}/approve
POST /review/items/{id}/reject
POST /review/items/{id}/hold
POST /review/items/{id}/retry
POST /review/items/batch
GET  /review/workspaces
POST /review/workspaces/{workspace_id}/select
GET  /review/quality/samples
POST /review/items/{id}/quality-label
POST /review/items/{id}/quality-sample
POST /review/quality/samples/{sample_id}/decision
POST /review/quality/samples/{sample_id}/arbitrate
```

所有动作写入 `review_events`，并保留 reviewer、时间、原始 decision hint
和备注。页面只绑定 reviewer session 当前选择的 workspace consumer；机器 API 继续绑定
进程配置的 `consumer_id`，不会改变 Cravatar 状态。

运行中的质量样本即使非空也只报告 `INCOMPLETE`，不会直接报告 `PASS`。只有代表性
corpus 评估器在分层数量、准确率、召回率、双人复核和延迟门槛全部满足后才可报告
`PASS`；零样本继续报告 `SKIP`。
