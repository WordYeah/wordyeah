# WordYeah 在线数据接入运行手册

本文规定 Cravatar 与 Gravatar 在线数据如何进入 WordYeah。现阶段只允许读取、采集、审核和生成拟执行动作；不授权修改 WordPress、头像状态、Cavalcade 任务或生产数据库。

## 1. 当前允许范围

- 在线新增数据：可以通过有界导出、受控采集和增量 cursor 持续进入 Shadow。
- 历史数据：可以按 1,000、10,000、100,000、全量四级逐步放量。
- 审核结果：写入 WordYeah 本地 submission、finding、attempt、review item 和事件。
- 人工队列：只接收 AI 两轮后仍不确定、模型分歧、模型错误、特殊风险和抽检项目。
- 生产处置：保持 `enforce=false`，只生成 proposal，不执行替换默认头像、拒绝或黑名单写回。

## 2. 接入前检查

1. 确认来源字段语义：registry ID、`status`、`type`、`hash_type`、来源 URL 和当前返回内容。
2. 明确读取方式：优先只读副本或不可变快照；使用生产 keyset 查询必须单独批准负载窗口。
3. 固定批次：记录预计数量、最大 ID/游标、开始时间和来源查询指纹。
4. 检查 WordYeah：API ready、数据库备份、磁盘空间、队列高水位、worker 和模型版本。
5. 检查 provider：G2A Web 真实 canary、Ollama 主/二审模型、超时和 fallback；池水位不等于请求成功。
6. 检查安全边界：只使用 `cravatar.com`/`cn.cravatar.com`，无腾讯云或其他审核 API，凭据不进入 manifest。

任一来源状态无法解释、生产查询负载不明确或模型错误可能进入 `allow` 时停止接入。

## 3. 数据流水线

```text
只读 snapshot/keyset
  -> metadata export
  -> allowlisted CDN fetch
  -> decode/size/hash validation
  -> immutable controlled media + manifest
  -> WordYeah incremental shadow
  -> local fast scan
  -> G2A Web AI 一审
  -> Ollama fallback / 独立 AI 二审
  -> auto proposal 或 human_required
  -> local audit/checkpoint
```

来源 ID 用于幂等，内容 SHA-256 用于内容去重；历史邮箱 MD5、来源 URL 和当前内容身份必须分开保存。相同来源重跑不得新增审核对象，内容变化必须产生新的内容证据，不能冒充旧图重放。

当高级视觉 active job 达到 `WORDYEAH_MAX_QUEUE_DEPTH` 时，强制 AI 审核的提交返回 HTTP
429，并留在本地失败账本等待重放，不得以 fast-scan 结果冒充已经排队。因并发竞争已经建立的
`vision_queue_full` 留置项允许使用同一 source ID 幂等恢复；其他 `model_error` 不自动重排。

## 4. 放量阶段

### A. 1,000 条在线只读 canary

- 同时覆盖 Cravatar 与 Gravatar、不同 registry 状态、URL 形态、图片类型和失败样本。
- 验证暂停、恢复、失败重放、重跑幂等、源记录前后不变和生产零写入。
- 输出采集成功率、去重率、快筛分布、provider 成功率和人工升级率。

登记表导出使用 `scripts/cravatar_registry_export.php`。它只执行一条按 `image_md5` 主键
排序的有界 SELECT，单页最多 5,000 条，stderr 输出实际 SQL 耗时；游标使用
`WORDYEAH_CRAVATAR_EXPORT_AFTER_KEY`，固定快照上界时同时设置
`WORDYEAH_CRAVATAR_EXPORT_MAX_KEY`。旧 `cravatar.cn` 只作为输入元数据解析，导出 URL
立即改写为 `cravatar.com`。

本地采集入口：

```bash
python scripts/cravatar_registry_collect.py export.jsonl \
  --database /private/wordyeah/registry/wordyeah.sqlite3 \
  --snapshot-id registry-YYYYMMDD \
  --source-mode live_keyset \
  --root /private/wordyeah/registry/media \
  --manifest /private/wordyeah/registry/manifest.jsonl \
  --workers 8
```

采集只向 `cn.cravatar.com` 请求当前图片，使用内容 SHA-256 地址存储；每条登记 source
保留独立映射，相同内容只保存一份。`invalid_metadata`、下载失败和缺失图片不进入 allow。
生产导出文件、manifest、ledger 和报告必须保持 0600，且不得放进仓库。

2026-08-09 的 1,000 条 canary 已完成采集与本地提交完整性检查，但整体仍为 `INCOMPLETE`：
963 条来源采集成功，27 条 metadata 无效，10 条 CDN 404；960 个唯一内容提交失败 0，幂等
重跑新增 0。首次提交暴露了既有队列达到 1,000 active job 时仍返回成功的问题；API 已改为
429 背压，并以本地幂等调和把仅因 `vision_queue_full` 留置的项目随水位下降重新排队。
2026-08-20 只读终态复核为 960/960 完成、活动任务 0、调和失败 0、错误路径 allow 0；队列终态
已完成。首轮采集仍缺少完整延迟分位数和代表性准确率真值，因此不能进入 10,000 条阶段。
原始证据为仓库外 `registry-canary-evidence.json`，终态补充为
`registry-canary-terminal-evidence-20260820.json`；不得提交图片、manifest、cursor 或运行数据库。

### B. 10,000 条 pilot

- 连续运行至少两小时，固定并发和 token bucket。
- 检查 CDN 错误、数据库查询 p95、队列最老年龄、G2A fallback 和 Ollama 耗时。
- 从 pilot 建立分层人工标签，校准自动通过、自动拒绝和升级阈值。

### C. 100,000 条 soak

- 连续运行至少六小时并执行 429、超时、无效响应、Ollama 停止、数据库重启和 CDN 失败演练。
- 并发只按观测结果逐级增加；G2A 熔断时不得瞬间把全量任务转给 Ollama。
- 门槛为覆盖率 100%、重复 0、丢失 0、错误路径 allow 0。

### D. 全量 Shadow

- 建立不可变批次，每 100,000 条生成 checkpoint，在 1M、2M 和全量位置备份与核对。
- 全量期间接住新增头像；结束后执行差异补扫。
- 只生成拟执行动作。是否进入生产写回必须另开评审，不因全量 Shadow 完成而自动开启。

## 5. 监控和停止条件

持续记录 expected/exported/collected/submitted/terminal 数量、失败和重试、内容去重、CDN p50/p95 与状态码、各模型 p95 与错误、队列深度和最老年龄、SQLite WAL/锁等待、AI 二审和人工升级量。

命中任一条件立即暂停当前批次：

- 发现任何生产写操作；
- CDN 五分钟错误率超过 5%；
- 生产数据库查询 p95 超过 2 秒，或出现明显负载/复制延迟；
- 计数不守恒、来源游标无法解释或重复任务增加；
- 模型错误、超时或无效响应被路由为 `allow`；
- G2A 熔断且 Ollama 队列超过高水位；
- 批次中途模型、提示词或策略版本漂移；
- SQLite 锁或磁盘问题导致任务不能可靠落盘。

## 6. 暂停、恢复和回滚

- 暂停 runner 和新导出，保留 cursor、manifest、失败账本、数据库和 checkpoint。
- 等待运行中的 lease 正常完成或到期，不通过删除任务强行“清空”。
- 核对最后完整 checkpoint、源最大 ID、成功数、失败数和 WordYeah 终态数。
- 修复后从同一批次和同一 cursor 恢复；先小批重放失败项，再恢复原并发。
- Shadow 阶段没有生产状态需要回滚；如果发现生产写入，立即停止并按来源系统事故流程处理。

## 7. 批次验收记录

每批至少保存：代码提交、来源查询/快照指纹、批次 ID、游标范围、expected 与 terminal 数、采集和模型错误、去重率、模型/提示词/策略版本、人工升级率、开始结束时间、checkpoint、生产零写入声明和验收结论。

结论只能是 `PASS`、`FAIL`、`INCOMPLETE` 或 `SKIP`。没有真人标签时可以通过数据完整性与非写入验收，但不能宣称准确率通过；小样本 canary 不能代表全库覆盖。

## 8. 生产写回前的独立门槛

生产写回不属于本手册的默认流程。进入写回评审前至少需要：

- 代表性 corpus 真人主审与固定双审完成；
- 自动拒绝精确率、违规召回率和自动通过漏审率达到 `ACCEPTANCE.md` 门槛；
- 生产动作映射、黑名单条件、默认头像条件和重新确认当前内容身份的规则已经书面确定；
- 逐项审计、幂等写回、限速、暂停和来源系统回滚经过 staging 验证；
- 明确批准首批写回范围、观察窗口和自动停止条件。
