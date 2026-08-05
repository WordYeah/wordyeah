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
- AI 预标注只作为盲测模型建议；不得写入 `quality_decisions`、不得设置最终决定，也不得
  计入 1,100 条主审、110 条双审或仲裁完成数
- 预标注 prompt 不得包含 corpus 分层、来源标签或预期结论；入队前后人工决定数和已收敛
  样本数必须保持不变
- 预标注 worker 必须同时按 consumer 和受控 context marker 领取任务，不得为了绕过旧任务
  改写全局队列顺序、取消其他任务或复用人工身份

预标注排空期间使用只读审计命令核对覆盖率、当前任务、租约、重复成功、attempt 复用和
人工真值不变式。ETA 只估算“当前已经入队”的任务，不包含运行中可能新增的二审任务：

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_corpus_prelabel_progress.py \
  --database /path/to/private/wordyeah.sqlite3 \
  --consumer-id corpus-avatar \
  --batch-id corpus-primary-v1
```

`HEALTHY` 表示排空仍在进行且完整性门闸正常，`COMPLETE` 表示 1,100 条均已有可评测
AI 建议且当前任务已排空；`STALLED` 表示建议未齐但已无活动任务，`DEGRADED` 表示租约、
关联、结果、重复成功或人工真值边界异常。正式人工标注开始后必须显式加
`--allow-human-truth`，不能把 AI 建议写成真人结论。

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

shadow 规模门槛默认至少 1,100 条，与代表性 corpus 五个分层的最低样本总数一致。
证据还必须包含零失败、稳定重跑、生产状态未变化，以及关闭 feature flag 后 60 秒内停止。

## 聚合验收

浏览器证据必须由真实 Chromium 和独立 reviewer session 重跑生成，不能手写 PASS JSON。
默认使用隔离运行器：它用 SQLite `mode=ro + query_only` 读取源库并备份到 0700 临时目录，
只在 0600 临时副本中放置一条 `human_required` 项。浏览器脚本会阻止动作表单提交；
结束后还会比对临时审核项、事件数和质量决定数，并删除临时数据库：

```bash
python -m pip install -e '.[api,browser]'
python -m playwright install chromium
python scripts/run_isolated_browser_acceptance.py \
  --source-database /path/to/private/wordyeah.sqlite3 \
  --media-root /path/to/private/media \
  --runtime /path/to/private/reviewer-runtime.json \
  --output artifacts/browser-acceptance-mvp.json \
  --screenshot-dir output/playwright/browser-acceptance-mvp
```

`reviewer-runtime.json` 必须为 0600，固定包含 `reviewer-a`、`reviewer-b`、
`arbitrator` 和独立 session secret；报告和截图均以私有权限原子写入，不输出凭据。
只有已经明确属于一次性测试的数据实例，才直接运行底层 `audit_browser_acceptance.py`。
聚合验收要求浏览器报告同时证明 `isolated_fixture=true`、源库只读、审核决定未变化、
生产头像未写入，以及全部页面下拉框、质量页 AI 建议盲审与键盘提交契约、1,100 条质量
分页路径通过。独立 reviewer runtime 报告还必须证明 `reviewer-a`、`reviewer-b`、
`arbitrator` 三个会话各自只有一个 cookie，身份、CSRF 和两个冻结质量批次均可见，且报告
未输出 secret。

所有门槛统一由一个只读聚合器核对：

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_avatar_mvp.py \
  --output artifacts/avatar-mvp-acceptance.json
```

退出码含义：

- `0`：全部证据为 PASS。
- `2`：证据格式错误、门槛失败，或误用了 `--enforce`。
- `3`：证据缺失，或来源报告仍为 `SKIP/INCOMPLETE`。

聚合器要求代表性 corpus、15 分钟队列负载、故障演练、浏览器主路径、至少
1,100 条 Cravatar shadow、三角色 reviewer runtime 和真实高级视觉响应全部有证据。
缺失项不会被本地 mock、零样本或静态页面替代。
