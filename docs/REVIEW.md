# wy-review 审核工作台

完整的 AI 多级审核流水线、页面、交互、状态和数据合同见
[`REVIEW_WORKBENCH.md`](REVIEW_WORKBENCH.md)。本文只记录当前头像 MVP 已实现的接口和安全边界。

当前已实现 `/review/login`、`/review`、`/review/items` 及 approve/reject/hold/retry
动作。审核 session 与 API key 分离，`WORDYEAH_REVIEWER_TOKEN` 和
`WORDYEAH_REVIEW_SESSION_SECRET` 只从环境变量读取。

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
