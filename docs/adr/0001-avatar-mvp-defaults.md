# ADR-0001：头像 MVP 的工程默认值

- 状态：accepted for 0.1 / deferred where noted
- 记录日期：2026-08-04
- 记录人：`[CX]`
- 范围：WordYeah 头像审查，不授权 Cravatar 生产写入

## 决策

| ID | 状态 | 决定 |
|---|---|---|
| D1 | accepted | HTTP 使用 FastAPI；`wy-core`、`wy-media`、`wy-review` 不依赖 Web 框架 |
| D2 | accepted | 单机先用 SQLite WAL 和迁移文件；出现多实例/多人高并发证据后再评估 PostgreSQL |
| D3 | accepted | 任务使用 SQLite durable job 表和独立 worker；不使用进程内内存任务 |
| D4 | deferred | Label Studio 只用于 corpus 标注；头像审核状态由 WordYeah 自己维护 |
| D5 | accepted | 审核 session 与 API key 分离；头像 MVP 先限 loopback/private network |
| D6 | accepted | 原始媒体默认不进入 SQLite，保留期限默认 7 天；头像 MVP 先以受控 media ref 接口占位 |
| D7 | accepted | 首先在本机/隔离开发机验证；生产主机、网络和部署账号在 shadow 前确认 |
| D8 | accepted | 0.1 不做脸部身份识别；政治人物等识别不作为头像自动封禁条件 |
| D9 | accepted | 结果合同保留 `consumer_id` 和 `policy_profile` 扩展位；0.1 不做计费和复杂租户 |
| D10 | accepted | 小头像可做有界同步；慢任务走持久 job；默认并发由 MPS 实测决定 |
| D11 | accepted | 外部代码/词库必须记录 upstream、commit 和许可证；无许可证的仓库只能做交互参考 |

## 头像 MVP 非目标

- 文本敏感词和 OCR 不进入头像 Gate A。
- 视频、音频和批量离线作业不进入头像 Gate A。
- `shadow`、`review` 均不得改变头像状态。
- `enforce` 不由本 ADR 授权。

## 回退

FastAPI、job worker 或 SQLite 迁移出现问题时，保留现有 stdlib PoC 作为隔离 smoke 入口；不把未验证的新服务切到 Cravatar。
