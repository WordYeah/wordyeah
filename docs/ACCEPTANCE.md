# WordYeah 头像 MVP 验收指标

## 范围

本文件只覆盖头像 image -> result -> review -> Cravatar shadow 链路。文本、敏感词、OCR、视频和音频在后续阶段单独验收，不能用头像结果替代。

## 数据门槛

- 真人普通头像 allow：至少 300
- 动漫/卡通头像 allow：至少 300
- logo/文字海报 allow：至少 100
- 边界/低俗 review：至少 200
- 明确违规 block：至少 200
- 10% 样本双人复核；分歧进入仲裁
- test split 哈希冻结；近重复不能跨 train/calibration/test
- 任何类别样本数为 0 时为 `SKIP`，不是 PASS

## 图片结果

- 普通真人头像：block 误报率 <= 0.5%，review 率 <= 3%
- 动漫/卡通头像：block 误报率 <= 0.5%，review 率 <= 5%
- 明确违规头像：block recall >= 95%
- 解码或模型错误率 < 0.5%；错误进入 `error/held`
- 模型净推理 warm p95 <= 50ms
- 小头像完整同步请求空队列 p95 <= 100ms
- 冷启动模型加载 <= 15s；ready 之前不接流量

## API、队列和安全

- API 重启后 pending job、submission 和审核事件仍存在
- worker 被终止后 lease 到期可回收；同一 job 不重复写最终结果
- 10MiB、MIME 白名单、畸形请求、模型缺失和超限输入有负向测试
- 过载使用有界队列和 `429/503 + Retry-After`，2 倍目标峰值压测 15 分钟无任务丢失
- 原始媒体不进入 SQLite；预览只能通过受控 media ref
- 所有 review 动作有 reviewer、时间、前后状态、策略版本和 request id

可复现故障演练：

```bash
PYTHONPATH=src .venv/bin/python scripts/run_avatar_fault_drills.py \
  --output artifacts/avatar-fault-drills-mvp.json
```

报告必须覆盖数据库重启、worker lease 回收、死信、provider 关闭、429、无效响应
以及 Cravatar shadow 非写入语义；任何 provider 错误都不得产生 `allow`。

## Cravatar shadow

- `shadow` 和 `review` 的 `mutates_avatar` 必须为 false
- staging 前后头像状态哈希、数量和相关数据库字段无变化
- WordYeah 超时、401、500、不可用时 Cravatar 现有流程不被阻塞
- 关闭 feature flag 后 1 分钟内不再产生新 shadow request
- 未经明确授权不修改 Cravatar 生产判定
