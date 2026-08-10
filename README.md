# WordYeah（无言会语）

自托管多类型内容识别、审查与人工复核系统。

## 模块

- `wy-core`：统一审查协议、策略、哈希和批测指标
- `wy-word`：文字、敏感词、OCR、语义和政治内容
- `wy-media`：图片、视频、音频及视觉内容
- `wy-review`：人工复核队列、页面边界和审核记录
- `wy-cravatar`：Cravatar 接入适配器

The current MVP includes a metadata-only SQLite review queue, append-only AI
attempts, a multi-page reviewer workbench, deterministic multi-stage routing,
and a non-mutating Cravatar shadow importer. Production has only been sampled
read-only; WordYeah does not write to WordPress, avatar state, or Cavalcade.

## 当前阶段

头像 MVP P5 实施中：FastAPI 边界、SQLite WAL 元数据表、持久 job lease、本地 Falconsai worker、自管 G2A Web 号池一审、本机 Ollama 兜底与独立二审、审核页面和 Cravatar 增量 shadow runner 已接入开发链路。Cravatar 与 Gravatar 镜像来源会随受控图片快照进入审核记录；新数据只使用 `cravatar.com`/`cn.cravatar.com`。系统不调用腾讯云或其他第三方内容审核 API，模型不可用时留置而不是外部降级；高级视觉代码默认关闭外呼；**产品决策（ADR-0002）**要求 shadow/开发链路由专员在仓库外 env 将 `WORDYEAH_G2A_ENABLED=true`（见 `docs/HANDOFF.md` §3b），**仍不授权 enforce**。
配置启动会校验头像 policy；`enforce` 当前固定为 `false`。队列有单 consumer 深度上限，超限返回可重试的 429。

审查结果统一为：`allow`、`block`、`review`、`error`。头像接口只接收原始图片 bytes，不接受远程 URL。

开发入口：

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[api,test]'
PYTHONPATH=src .venv/bin/wordyeah-api
```

API 合同见 `docs/openapi-avatar-v1.yaml`；当前首版默认绑定 loopback。
持续 shadow 的只读 Cavalcade 导出器、本地受控采集器、禁用式 systemd 模板与安装边界见 `docs/DEPLOYMENT.md`。
聚合 MVP 验收现有六项通过；代表性 corpus 仍必须由真人完成全量主审和固定 10% 独立双审，不能用 AI 结果替代 ground truth。

## 相关计划

Linuxjoy 立项计划：`../linuxjoy/.omx/plans/2026-08-04-wordyeah-kickoff.md`

完整开发计划：`.omx/plans/2026-08-04-wordyeah-development.md`

## 文档入口

- 长期开发、维护、发布与回滚：`docs/PROJECT_MAINTENANCE.md`
- 在线只读数据接入和分阶段放量：`docs/ONLINE_DATA_RUNBOOK.md`
- API 与鉴权合同：`docs/API.md`
- AI 多级审核与人工工作台：`docs/REVIEW_WORKBENCH.md`
- 部署目录和服务边界：`docs/DEPLOYMENT.md`
- 质量、安全、负载和浏览器验收：`docs/ACCEPTANCE.md`
- Cravatar/Gravatar 全量历史审核计划：`docs/CRAVATAR_FULL_REGISTRY_REVIEW_PLAN.md`
- 已实现、已验证和未完成事实：`docs/STATUS.md`
- 当前运行任务、未完成项和恢复入口：`docs/HANDOFF.md`
- 系统定位、风险与接入判断（2026-08-10）：`docs/ASSESSMENT_2026-08-10.md`
