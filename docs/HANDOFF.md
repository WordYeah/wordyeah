# WordYeah 工作交接

更新：2026-08-20 Asia/Shanghai · 本地头像 Shadow MVP 自动化链收口

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
- 960 个唯一内容现已全部终审：自动通过 864、自动拒绝 3、人工通过 92、人工拒绝 1；
  G2A 一审成功 302、Ollama 一审成功 658、Ollama 二审成功 160，活动任务 0。
- 调和 cursor 完成 960/960、失败 0；SQLite integrity=`ok`，错误路径产生 allow=0。
- 首轮完整采集发生在延迟分位数埋点定稿前，只有 27 条重试保留 p50=285ms、p95=725ms。
  因此数据与队列终态 PASS，但该批仍不能充当完整采集性能或准确率 PASS，也不授权 10,000 条阶段。

仓库外证据目录：

```text
/Users/feibisi-studio/data/wordyeah/registry-shadow/20260809-canary-1000/
```

原始总证据为 `registry-canary-evidence.json`；2026-08-20 只读终态补充为
`registry-canary-terminal-evidence-20260820.json`。目录、数据库、媒体、manifest 和 cursor
均不得提交到 Git。

## 3. 正在运行的本地任务

- API：`http://127.0.0.1:18767`；2026-08-20 已重启并加载 `ff9bda6`。
- `/health/ready` 为 ready，`advanced_vision.provider=g2a-web+ollama`、`enabled=true`；审核页 200。
- Cravatar 活动 job 为 0；此前的一审、二审和调和批次均已结束，不需要保持批次 worker 常驻。
- 调和 cursor：`queue-reconcile-cursor.json`；状态输出：`queue-reconcile-status.json`；
  日志：`queue-reconcile.log`。
- 调和只重放最新 route reason 为 `vision_queue_full` 的对象；其他模型错误保持留置。该规则
  继续适用于后续批次。

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


## 3b. G2A Web 一审运行时启用（已执行）

**决策**：接受 [`adr/0002-enable-g2a-web-vision.md`](./adr/0002-enable-g2a-web-vision.md)——将 **shadow/开发** 链路的 `WORDYEAH_G2A_ENABLED` 设为 **`true`**，一审走本机 g2a 转发 Web 池（推荐模型 `grok-chat-fast`）。  
本地运行时已使用仓库外配置启用，并保留 Ollama 兜底；secret 未进入仓库或证据。

### 接手时现状（2026-08-20）

- API：`http://127.0.0.1:18767`
- `GET /health/live`：`external_model_calls=true`、`advanced_vision_provider=g2a-web+ollama`
- `GET /health/ready`：`advanced_vision.enabled=true`
- G2A 串行探针曾为 2/3，第三次 429；独立 G2A canary 超时后，完整链由本机
  `qwen3-vl:8b` 兜底得到真实 `allow/1.0`。这证明故障转移可用，不证明 G2A 池稳定。

### 已执行配置与回退

1. **仓库外**运行配置已设置（勿提交 Git、勿贴聊天）：
   - `WORDYEAH_G2A_ENABLED=true`
   - `WORDYEAH_G2A_ENDPOINT=http://127.0.0.1:18000/v1/chat/completions`（或经批准的等价 g2a 入口）
   - `WORDYEAH_G2A_MODEL=grok-chat-fast`
   - `WORDYEAH_G2A_API_KEY`（secret store / 0600 文件注入）
   - 私网 IP 字面量 HTTP 时：`WORDYEAH_G2A_ALLOW_PRIVATE_HTTP=true`
   - 建议同时确认 Ollama 一审兜底与二审开关按 `docs/G2A_INTEGRATION_DRAFT.md` / env.example
2. `wordyeah-api` 已重启；当前批次无活动 vision job，不保留空转批次 worker。
3. readiness 与完整链 canary 已复核，证据只保存哈希、决定、provider、回退和耗时。
4. 回退：`WORDYEAH_G2A_ENABLED=false` 后重启。

### 仍禁止

- `enforce=true` 或任何 Cravatar/生产写回
- 默认改用 Build `grok-4.5` / junsen 作为审核主上游
- 腾讯云或其他第三方内容审核 API 作为默认路径
- 在文档或工单粘贴 API key

合同：`docs/G2A_INTEGRATION_DRAFT.md` · 实现：`src/wy_media/g2a.py`

## 4. 未完成项

### P3：先完成本批次

- [x] 调和 cursor `failed=0`；960 个唯一内容全部进入队列并到达终态。
- [x] 已分别统计自动通过、自动拒绝、一审、二审和人工结论。
- [x] 错误路径 allow=0，SQLite integrity=`ok`，活动任务=0。
- [x] `STATUS.md`、本交接和仓库外只读终态证据已更新。
- [ ] 进入 10,000 条前，另做一个具有完整 p50/p95、错误率和总耗时的独立有界采集样本；
  不用旧缓存冒充新的 CDN 采集性能。

只有以上五项完成，才可评审是否进入 10,000 条；现阶段不允许启动。

### P4：质量门槛

- 1,100 条冻结 corpus 的 AI 建议已完成，但独立人工真值仍为 0/1,100。
- 固定 10% 独立双审仍为 0/110，分歧仲裁尚未发生。
- 在真人标签、双审和仲裁完成前，不能计算可用于放量的误杀、漏放和人工介入率，也不能开启
  自动生产处置。
- 该门槛不会再要求项目负责人逐项人工标注；它保持为未来独立质量评测/生产 enforce 门闸，
  不阻塞当前 `enforce=false` 的本地与只读 Shadow MVP。

### P5b：G2A ENABLED 运行时（决策 ADR-0002）

- [x] 仓库外 env：`WORDYEAH_G2A_ENABLED=true` 及 endpoint/model/key（见 §3b）
- [x] 重启 API；按批次启动 vision worker，空队列不保留批次 worker
- [x] `health/ready` 显示 advanced_vision.enabled=true
- [x] 完整主链 canary 验证 G2A 失败可回退 Ollama，失败不会默认放行
- [x] `enforce=false`，未配置 Cravatar 生产写回变量

### P5：目标主机运行

- API、快速 worker、高级视觉 worker、增量采集和调和目前只在本机运行；目标主机受管部署不在
  本地 Shadow MVP 完成范围内，也没有据本地完成状态擅自选择生产主机。
- 仍需确定目标主机、0600 运行配置、服务用户、备份恢复、磁盘水位、队列年龄、provider 错误、
  死信和模型超时告警。
- 部署前需重做进程重启、数据库恢复、G2A 不可用、Ollama 回退和队列背压演练。

### P6：生产处置

- 人工「加黑名单」写回适配器已实现：`wy_cravatar.writeback.post_blacklist`，默认关闭。
  仅当 `CRAVATAR_BAN_URL` + `CRAVATAR_BAN_TOKEN` 同时设置，且审核员点了 blacklist 才 POST
  到 Cravatar `/wp-json/cravatar/console/bans`。reject / AI 结论不会写。
- 未设置 token 时审核动作照常成功，响应带 `cravatar_writeback.status=skipped`。
- 适配器只接受 `cravatar` 工作区、已终审 `block/blacklist` 项和固定 bans 路径；公网只允许
  HTTPS 443，拒绝重定向、userinfo、query、fragment 与非白名单主机，并发送幂等键。上游
  非 2xx 响应正文不回显。当前运行环境未设置写回变量。
- 仍不批准 AI 自动 enforce，也不把 G2A 单轮结论写成生产封禁。

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
