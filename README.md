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

头像 MVP P5 实施中：FastAPI 边界、SQLite WAL 元数据表、持久 job lease、本地 Falconsai worker、高级视觉任务链、审核页面和 Cravatar 增量 shadow runner 已接入开发链路。当前不连接 Cravatar 生产判定，不调用腾讯云；高级视觉 provider 默认关闭，受控 G2A canary 只得到 HTTP 429。
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

## 相关计划

Linuxjoy 立项计划：`../linuxjoy/.omx/plans/2026-08-04-wordyeah-kickoff.md`

完整开发计划：`.omx/plans/2026-08-04-wordyeah-development.md`
