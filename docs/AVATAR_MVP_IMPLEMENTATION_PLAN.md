# WordYeah 头像审核 MVP 实施方案

更新日期：2026-08-05  
执行状态：实施中  
安全模式：`shadow -> review`；`enforce=false`

## 1. 目标

交付一条可持续运行、可审计、可回退的头像审核链：

```text
Cravatar 增量 shadow 输入
  -> 本地快速扫描
  -> 高级视觉 AI 一审
  -> 独立 AI 二审
  -> 自动允许 / 自动拒绝候选 / 人工例外
  -> 抽检与仲裁
  -> shadow 结果与质量报告
```

系统默认由 AI 完成常规判断。人工只处理模型分歧、低置信度、错误重试耗尽、质量抽检、申诉和仲裁。

## 2. 本期边界

### 包含

- 头像图片审核。
- provider-neutral 高级视觉接口与可配置 G2A adapter。
- 一审、二审任务自动创建、worker 执行、退避重试和路由收敛。
- consumer/workspace 隔离。
- Cravatar 增量 shadow 导入、游标、幂等、失败重放和水位。
- 人工审核、结构化原因码、批量安全限制、抽检和最小仲裁。
- 代表性 corpus 的导入、去重、分层与质量门槛报告。
- 审核台桌面、窄屏和移动端验收。

### 不包含

- Cravatar/WordPress 头像写回、删除、替换或生产黑名单变更。
- `enforce=true`。
- 代持或提交真实 G2A 密钥。
- 文本敏感词、OCR、视频、音频正式实现。
- 跨组织统一身份、复杂计费和完整 RBAC。

## 3. 不可突破的安全边界

1. `shadow` 和 `review` 始终 `mutates_avatar=false`。
2. provider 未启用、超时、限流、解析失败或证据不足时不得降级为 allow。
3. AI 二审必须是独立 attempt；同模型同提示词重试不算二审。
4. 人工队列只显示 `human_required`、抽检、仲裁和错误耗尽项目。
5. 政治人物、疑似未成年人、严重风险、模型分歧和仲裁项目禁止批量决定。
6. 零样本为 `SKIP`，不能报告 PASS。
7. 原图不写 SQLite，不接受任意远程媒体 URL。
8. 密钥不进入 Git、日志、截图、审核事件和错误正文。

## 4. 交付阶段

状态说明：P0-P4 的核心代码和自动化测试已实现；P5 已完成 15 分钟持久队列负载门槛、故障演练与浏览器主路径验收，代表性 corpus、生产级 shadow 调度和真实高级视觉响应仍未完成。

### P0：基线与真实性

- 保存现有 UI 差异和当前提交。
- 删除重复生成代码、伪造指标、固定进度和虚假工作区。
- 固化现有 API、数据库 schema、路由和测试基线。

验收：全量测试通过；页面不显示没有运行时证据的健康、准确率或进度。

### P1：高级视觉自动审核

- 新增高级视觉 job 类型和稳定幂等键。
- 路由进入 `vision_review_1` 时自动创建一审任务。
- 一审低置信度或分歧时创建二审任务。
- worker 调用配置的 provider，保存 attempt 后重新路由。
- 实现可重试错误、指数退避、最大 attempt、lease 回收和死信状态。
- 人工 retry 创建新的模型 job，而不是只修改状态。

验收：mock provider 可完整跑通 allow、block、分歧、超时、限流、无效响应和重试耗尽路径。

### P2：人工审核流程

- 服务端 cursor 分页，默认按风险和新鲜度排序。
- 保留筛选、视图和返回位置。
- 单项决定后自动进入下一条；无下一条时返回队列。
- 409 冲突返回当前版本并提供就地刷新。
- 批量上限 50，逐项报告成功、失败和原因。
- 高风险和特殊类别服务端强制禁止批量决定。
- 结构化原因码与可选备注分离。

验收：人工不提前看到 AI 一审/二审待处理项；批量限制无法由前端绕过。

### P3：工作区与 Cravatar shadow

- 建立 workspace 配置、consumer 映射和审核页面切换。
- 每个 workspace 独立队列、游标、策略版本和统计。
- Cravatar importer 使用增量 cursor 和稳定 source ID。
- 导入去重、失败重放、暂停/恢复和水位报告。
- shadow submit 失败不阻塞 Cravatar 原流程。

验收：两个 consumer 的数据、attempt、事件、游标和页面互不可见；重复导入不产生重复项目。

### P4：质量、样本与仲裁

- 版本化原因词表。
- 标签：误报、漏报、模型分歧、边界、稀有类别、模型失败、质量抽检。
- 受控样本 manifest、哈希去重、近重复隔离和保留状态。
- 自动抽检自动允许/拒绝结果。
- 双人复核和最小仲裁状态机。
- 自动停止条件：错误率、分歧率、误报率或人工积压越界。

验收：所有抽检和仲裁变更均有 actor、前后状态、策略、模型和 request ID。

### P5：代表性验收与运行验证

- 普通真人 allow >= 300。
- 动漫/卡通 allow >= 300。
- logo/文字头像 allow >= 100。
- 边界/低俗 review >= 200。
- 明确违规 block >= 200。
- 10% 双人复核；冻结 test split；近重复不跨集合。
- 两倍目标峰值压测 15 分钟。
- provider 故障、worker 中止、lease 回收、数据库重启和 feature flag 关闭演练。

验收指标以 `docs/ACCEPTANCE.md` 为准；样本不足只输出 INCOMPLETE/SKIP。

## 5. 数据与接口设计

需要新增或确认的持久对象：

- `workspaces`：consumer、名称、适配器、策略和启用状态。
- `source_cursors`：workspace、source、cursor、水位和更新时间。
- `review_jobs`：阶段、attempt、可运行时间、lease、错误类别和幂等键。
- `review_attempts`：provider、模型、提示词、结论、置信度、findings、evidence。
- `review_labels`：受控 reason code、标签版本、actor 和事件关联。
- `quality_samples`：抽检原因、分层、复核状态、仲裁状态和留存状态。

所有查询必须显式带 consumer/workspace 约束；仅依赖全局唯一 item ID 不视为隔离。

## 6. 测试矩阵

- 单元：配置、解析、路由、退避、幂等、cursor、批量准入。
- API：登录、CSRF、consumer 隔离、分页、409、逐项批量结果。
- worker：崩溃恢复、lease 回收、重复投递、最大重试。
- adapter：Cravatar 重复输入、游标恢复、故障不阻塞。
- 浏览器：1440x900、1280x800、390x844；登录、三种队列视图、详情、动作、冲突、会话过期和退出。
- 性能：warm 推理、同步 API、队列吞吐和 15 分钟过载。
- 质量：按类别输出样本量、误报率、召回率、review 率、分歧率和人工介入率。

## 7. 实施顺序与预计工期

| 阶段 | 预计 |
|---|---:|
| P0 基线与真实性 | 0.5–1 天 |
| P1 自动高级视觉链 | 2–3 天 |
| P2 人工审核流程 | 1.5–2 天 |
| P3 工作区与 Cravatar shadow | 2–3 天 |
| P4 质量与仲裁 | 2–3 天 |
| P5 验收与故障演练 | 2–4 天，不含样本收集等待 |

单人连续开发预计 10–16 个工作日；并行开发可压缩到约 6–9 个工作日。代表性样本收集和人工双审时间另计。

## 8. 完成定义

- 自动 AI 链无需人工触发即可收敛到最终自动决定或人工例外。
- Cravatar shadow 可增量持续运行、可暂停、可恢复、可查水位。
- 人工队列没有 AI 尚未执行的项目。
- 所有决定可追溯并通过 consumer 隔离测试。
- 质量报告达到规定样本量后才允许判 PASS。
- 浏览器、全量测试、压测和故障演练留下可复现证据。
- `enforce=false`，不存在生产头像写回。

## 9. 2026-08-05 验证记录

- 全量测试：201 passed，12 subtests passed；仅有 Starlette/httpx 弃用警告。
- 质量双审：人工标签结论已扩展为 `allow/review/block`，两名独立 reviewer 可把边界样本收敛为 `review`；旧 `allow/block` 文件库迁移在提交前执行外键校验，失败会完整回滚。
- 浏览器：真实 reviewer session 下验证 1440×900 三种队列视图、显式批量模式与最多 50 项提示、快速标记四种动作且零弹窗；1280×800 验证紧凑列表；390×844 验证质量页与工作区菜单且无横向溢出。证据保存在本地忽略文件 `artifacts/browser-acceptance-mvp.json`。
- 持久队列负载：50 jobs/s 连续 900 秒，完成 45,000 项、零 active 残留、49.9998 jobs/s、cycle p95 1.02ms；时长与速率门槛均 `PASS`。结果保存在本地忽略文件 `artifacts/review-queue-load-15m.json`。
- G2A canary：网关可达，`grok-4.5` 与 `grok-4.3` 返回 HTTP 429；限流重试分类通过，真实视觉能力未验收。
- 故障演练：数据库重启持久性、过期 lease 回收、死信、provider 关闭、429、无效响应和 shadow 非写入均通过；证据保存在本地忽略文件 `artifacts/avatar-fault-drills-mvp.json`。
- 聚合验收：`queue_load_15m`、`fault_drills`、`browser_acceptance` 和 `production_write_boundary` 为 PASS；`representative_corpus`、`cravatar_shadow` 与 `advanced_vision_canary` 为 INCOMPLETE，聚合退出码为 3。证据保存在本地忽略文件 `artifacts/avatar-mvp-acceptance.json`。
- corpus 候选准备：通过受控 Hugging Face viewer/archive/Parquet 采集器在仓库外私有目录准备真人 300、动漫 300、logo/文字 100、边界 200、明确违规 200 条候选；共 1,100 条、哈希唯一、文件与 manifest 均为 0600。候选全部保持 `unreviewed`，没有 `expected_decision`，不能作为准确率或双审通过证据。
- corpus：1,100 条候选尚未形成正式双审标签，必须保持 `INCOMPLETE/SKIP`。
- 生产边界：没有 WordPress、头像、Cavalcade、腾讯云或生产数据库写入。
