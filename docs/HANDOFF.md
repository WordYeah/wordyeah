# WordYeah 工作交接

更新：2026-08-09 18:42 Asia/Shanghai `[CX]`

本文只记录可接续执行的事实、未完成项和边界。长期设计分别见
`PRODUCTION_READINESS_PLAN.md`、`ONLINE_DATA_RUNBOOK.md` 和
`CRAVATAR_FULL_REGISTRY_REVIEW_PLAN.md`。

## 1. 已提交版本

- `5ee5ea6 feat: add read-only Cravatar registry shadow` 已推送到 `origin/main`。
- 该版本包含生产只读 keyset 导出、本地采集与来源账本、内容去重、失败分类、快照封存、
  WordYeah 来源元数据校验、强制 AI 队列 HTTP 429 背压，以及 `vision_queue_full` 幂等恢复。
- 提交时验证为：315 个 pytest、12 个 subtest、Ruff、compileall、PHP syntax 和
  `git diff --check` 全部通过；唯一警告是 Starlette/httpx 弃用提示。
- 仓库内 `var/` 是本地未跟踪运行目录，没有加入提交，不应纳入 Git。

## 2. 1,000 条只读 canary 事实

批次：`registry-canary-20260809-1000`。

- 来源：`wp_9_avatar_verify` 只读 keyset SELECT，共 1,000 行；Gravatar 995、Cravatar 5。
- 来源查询耗时：4–5ms；前后业务字段语义摘要一致；生产数据库和头像写入均为 0。
- 来源终态：963 `collected`、27 `invalid_metadata`、10 `fetch_missing`。
- 963 条来源映射为 960 个唯一当前内容；本地 WordYeah 已保存 960 个来源审核对象。
- G2A `grok-chat-fast` 单图真实 canary 为 PASS；这不代表整批 AI 已完成。
- 首轮完整采集发生在延迟分位数埋点定稿前，只有 27 条重试保留 p50=285ms、p95=725ms。
  因此该批结论仍是 `INCOMPLETE`，不能授权 10,000 条阶段。

仓库外证据目录：

```text
/Users/feibisi-studio/data/wordyeah/registry-shadow/20260809-canary-1000/
```

总证据文件：`registry-canary-evidence.json`。目录、数据库、媒体、manifest 和 cursor 均不得
提交到 Git。

## 3. 正在运行的本地任务

- API：`http://127.0.0.1:18767`；代码已加载 `5ee5ea6`。
- 四个 G2A 一审 worker 和一个 Ollama 二审 worker 通过仓库外 PID 文件管理。
- 队列调和进程的 PID 文件：
  `.../20260809-canary-1000/queue-reconcile.pid`。
- 调和 cursor：`queue-reconcile-cursor.json`；状态输出：`queue-reconcile-status.json`；
  日志：`queue-reconcile.log`。
- 2026-08-09 18:42 快照：960 个对象中 593 个处于 `vision_review_1/pending`，367 个因
  `vision_queue_full` 仍为 `model_error/held`；Cravatar active job 为 999。数字会随 worker
  消费而变化，接手时必须重新查询，不能把本快照当成终态。
- 调和只重放最新 route reason 为 `vision_queue_full` 的对象；其他模型错误保持留置。

只读检查：

```bash
curl -fsS http://127.0.0.1:18767/health/live
python3 - <<'PY'
import json, sqlite3
from pathlib import Path
root = Path('/Users/feibisi-studio/data/wordyeah/registry-shadow/20260809-canary-1000')
state = next(iter(json.loads((root / 'queue-reconcile-cursor.json').read_text())['streams'].values()))
print({'completed': len(state['completed']), 'failed': len(state['failures'])})
db = sqlite3.connect('/Users/feibisi-studio/data/wordyeah/cravatar-workbench-live/wordyeah.sqlite3')
print(list(db.execute("select stage,status,count(*) from review_items where consumer_id='cravatar' and source_id like 'cravatar-registry:%' group by stage,status order by stage,status")))
print(db.execute("select count(*) from jobs where consumer_id='cravatar' and status in ('queued','running')").fetchone())
PY
```

调和进程停止或 Mac 重启后，必须使用同一 manifest、同一 source ID 和同一 cursor 恢复；
不得删除 cursor 或重新创建来源 ID。启动方式以 `ONLINE_DATA_RUNBOOK.md` 的 loopback、0600、
失败重放约束为准。

## 4. 未完成项

### P3：先完成本批次

1. 等待调和 cursor 的 `failed=0`，核对 960 个唯一内容均已进入 AI 队列且没有重复 job。
2. 等待一审、二审和自动路由到终态；分别统计自动通过、自动拒绝、二审、人工、模型错误。
3. 核对错误路径没有产生 `allow`，SQLite integrity 为 `ok`，worker 租约、死信和队列年龄可解释。
4. 更新 `registry-canary-evidence.json`、`STATUS.md` 和本交接中的终态数字。
5. 使用定稿后的采集埋点完成一个有完整 p50/p95、错误率和总耗时的独立有界样本。新的生产
   读取批次需要另行确认，不能用本批缓存数据冒充 CDN 采集性能。

只有以上五项完成，才可评审是否进入 10,000 条；现阶段不允许启动。

### P4：质量门槛

- 1,100 条冻结 corpus 的 AI 建议已完成，但人工主审仍为 0/1,100。
- 固定 10% 独立双审仍为 0/110，分歧仲裁尚未发生。
- 在真人标签、双审和仲裁完成前，不能计算可用于放量的误杀、漏放和人工介入率，也不能开启
  自动生产处置。

### P5：目标主机运行

- API、快速 worker、高级视觉 worker、增量采集和调和目前只在本机运行，尚未安装为目标主机
  受管服务。
- 仍需确定目标主机、0600 运行配置、服务用户、备份恢复、磁盘水位、队列年龄、provider 错误、
  死信和模型超时告警。
- 部署前需重做进程重启、数据库恢复、G2A 不可用、Ollama 回退和队列背压演练。

### P6：生产处置

- `allow/reject/default-avatar/blacklist/hold` 到 Cravatar 动作的写回适配器尚未实现。
- 当前没有 WordPress、头像状态、默认头像或黑名单写入权限，也没有批准生产 canary。
- 写回必须独立进程、最小权限、逐项幂等、内容身份复核、审计、限速和可回滚；黑名单不得因
  AI 单轮结论直接执行。

## 5. 其他未完成事实

- Reviewer 账户结构、角色和服务端 session 已实现；真实目标主机账户资料和凭据仍需写入
  仓库外 0600 配置。
- 在线增量来源尚未在目标主机常驻；首次全量期间的新头像补扫和最终差异扫描尚未执行。
- 首批 1,000 行的来源分布严重偏向 Gravatar，不能代表 Cravatar 原生头像、不同状态和特殊风险
  的质量表现。
- 10 个 `fetch_missing` 和 27 个 `invalid_metadata` 只有证据终态，没有安全结论；后续需决定
  来源修复、默认头像或人工处置规则，不能自动记为通过。
- Starlette/httpx 弃用警告尚未处理，但当前测试通过。

## 6. 不可突破的边界

- 保持 `enforce=false`，不写生产数据库、WordPress、头像状态、默认头像或黑名单。
- 不恢复腾讯云或其他第三方内容审核 API。
- G2A 只能走池化 Web 网关，不复制个人登录态，不把 available 数量解释为并发能力。
- 不删除或倒带 cursor、失败账本、任务、attempt、审计事件和 canary 媒体。
- 任何 `SKIP`、零真人标签、单图 canary、队列已进入但未到终态，都不能写成质量通过。
