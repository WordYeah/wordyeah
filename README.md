# WordYeah（无言会语）

自托管多类型内容识别、审查与人工复核系统。

## 模块

- `wy-core`：统一审查协议、策略、哈希、队列和审计
- `wy-word`：文字、敏感词、OCR、语义和政治内容
- `wy-media`：图片、视频、音频及视觉内容
- `wy-review`：人工复核页面和审核记录
- `wy-cravatar`：Cravatar 接入适配器

## 当前阶段

立项基线与隔离 PoC。当前不连接 Cravatar 生产判定，不调用腾讯云或其他外部审查 API。

审查结果统一为：`allow`、`block`、`review`、`error`。

## 相关计划

Linuxjoy 立项计划：`.omx/plans/2026-08-04-wordyeah-kickoff.md`
