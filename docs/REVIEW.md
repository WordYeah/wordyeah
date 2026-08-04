# wy-review 最小审核面板方案

## 页面

`/review` 只展示 `pending` 项，按创建时间排序，支持按 `media_type`、
`decision_hint`、模型和分数筛选。每行展示：

- 安全缩略图或受控媒体预览
- content SHA-256、媒体类型和来源引用
- 模型版本、分数和命中原因
- `通过`、`拒绝`、`暂缓`、`重试`
- 操作人、时间和审计记录

## 安全边界

- 只绑定 loopback/private network；不做公网匿名审核入口。
- 页面鉴权与 API 鉴权分开配置，所有决策动作需要 reviewer 身份。
- `media_ref` 只能指向 allowlisted 本地/私有对象，禁止浏览器直接访问任意路径或远程 URL。
- 默认 SQLite 只存哈希、模型结果、状态和审计，不存原始图片；预览由后续受控媒体引用适配器提供。
- 错误和超时进入 `held`，不显示成 `allow`。

## 最小动作 API

```text
GET  /review/items?status=pending
GET  /review/items/{id}
POST /review/items/{id}/approve
POST /review/items/{id}/reject
POST /review/items/{id}/hold
POST /review/items/{id}/retry
```

所有动作写入 `review_events`，并保留 reviewer、时间、原始 decision hint
和备注。面板尚未接入生产，也不会改变 Cravatar 状态。
