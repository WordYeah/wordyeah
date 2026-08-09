# WordYeah 审核台视觉验收

日期：2026-08-04

## 目标

审核台只把 AI 无法确定的例外交给人工。页面应让审核员快速理解“为什么需要我看”，而不是展示全部流水线数据。

## 参考图提取

- 浅灰外部画布，居中的白色应用窗口，细边框和克制阴影。
- 约 224px 的浅灰侧栏；当前入口使用白色或淡紫底，不使用重色大面积填充。
- 顶栏约 72px，只放面包屑、流水线状态、帮助和账户。
- 内容区使用 48–56px 左右页边距；标题、说明、操作之间有明确留白。
- 列表使用横向行和细分隔线，不把每个条目做成厚重卡片。
- 状态使用低饱和胶囊标签；主色仅用于当前状态和主要动作。
- 详情采用双栏焦点视图：一侧为精简配置/证据，另一侧为大媒体预览；关闭和决策动作位置固定。
- 图标使用内联开源 SVG 风格，统一 1.5–1.8px 描边，不使用 emoji 作为功能图标。

## 信息规则

- 默认首页展示 AI 自动处理摘要、异常数量和最多一组趋势，不展示大批指标卡。
- 默认队列仅展示低置信度、模型分歧、模型错误、抽检和仲裁条目。
- 一行只保留缩略图、异常原因、AI 建议、等待时间/状态和进入详情入口。
- 哈希、策略版本、完整 findings、事件时间线收进详情，不在列表铺开。
- 人工操作只在详情出现；拒绝、通过、留置必须沿用现有 CSRF 和版本冲突保护。
- 空队列是正常状态，应明确说明 AI 正在自动处理，而不是显示故障式空白。

## 必须通过

1. 1440×900 首屏无需滚动即可看到页面标题、AI 状态和至少 5 条例外记录。
2. 1280×800 不出现横向页面滚动；队列行仍可读。
3. 390×844 侧栏折叠，主要操作不被遮挡，详情改为单栏。
4. 登录、队列、详情、审核动作、409 冲突、会话过期和退出均通过真实浏览器流程。
5. 与参考图并排审查时，不得再出现旧版的密集指标区、重复解释和厚重卡片堆叠。

## 2026-08-04 验证记录

- 桌面队列：`output/playwright/review-final-v3-1440.png`
- 窄桌面队列：`output/playwright/review-final-v3-1280.png`
- 移动端队列：`output/playwright/review-final-v3-390.png`
- 桌面详情：`output/playwright/review-detail-final-v3-1440.png`
- 真实浏览器已验证：登录、队列加载、详情进入、填写备注、留置人工复核、动作后返回队列及全局数量更新。
- 自动化已验证：登录态、CSRF、consumer 隔离、审核事件、乐观锁 409、媒体访问和会话过期路径。
- 初版视觉复核结论：88/100，无阻断项；随后针对顶栏聚焦、列表基线和移动端占高继续精修，最终结果见下方复查记录。
- 工程验证：`62 passed, 1 warning, 8 subtests passed`；ruff、compileall、`git diff --check` 通过。warning 为 FastAPI TestClient 引入的 Starlette 弃用提示。

## 2026-08-04 UI 细节复查

- 统一审核队列与八个支持页的应用宽度、224px 侧栏、72px 顶栏、导航图标、账户入口、圆角、描边和间距，删除支持页原有的第二套后台风格。
- 支持页删除重复英文 eyebrow 和“单页目的”大卡片；页面标题、说明和 AI 例外提示收敛为单层标题区。
- 历史表格日期去掉微秒与时区噪声，长对象 ID 中段省略并保留完整 `title`，避免列文字粘连。
- 详情链接不再用 hash 把浏览器强制滚到卡片顶部；详情摘要改为中文标签，删除重复操作脉络，缩短图片高度并让决策栏在首屏可见且滚动时保持 sticky。
- 移动端九个入口收进单行横向导航，避免两排导航占用审核首屏。
- 最终证据：`output/playwright/ui-audit-final-v2-queue-1440.png`、`output/playwright/ui-audit-final-v2-queue-390.png`、`output/playwright/ui-audit-final-detail-1440.png`、`output/playwright/ui-audit-final-history-1440.png`、`output/playwright/ui-audit-final-history-390.png`。
- [CX] `$visual-verdict` 结构化复核为 92/100，达到 90 分门槛；结果保存在 `.omx/state/wordyeah-review-ui/ralph-progress.json`。

## 2026-08-04 多视图与批量模式复查

- [CX] 队列增加紧凑列表、视觉网格、快速标记三种 URL 可深链视图；紧凑列表单行高度由 104px 收到 82px。
- [CX] 批量模式只在显式开启后显示复选框和固定工具条；单批上限 50，后端逐项做版本校验和审计，部分失败单独报告。
- [CX] 快速标记支持 `A/R/H` 决策和 `J/K` 切换；备注输入聚焦时快捷键停用。
- [CX] Cravatar 预览支持严格的 `cravatar://<MD5>` 引用，并拼接到 allowlisted `cn.cravatar.com/avatar/`；不把图片 SHA-256 当邮箱 MD5。
- 视觉证据：`output/playwright/review-multiview-list-1440.png`、`output/playwright/review-multiview-grid-1440.png`、`output/playwright/review-batch-grid-1440.png`、`output/playwright/review-cravatar-api-preview-1440.png`。
- [CX] 独立视觉子代理复核为 84/100、无阻断项；指出列表横向留白、批量模式层级和单结果空白仍可继续收敛。随后已收紧列表列宽、强化批量条并增加当前结果数；精修后的截图尚未再次评分。

## 2026-08-09 列表节奏与模块边线复查

- [CX] 删除系统健康阶段卡片的彩色顶部边线和质量页人工规则的紫色左边线；状态继续通过文字与低饱和状态标签表达。
- [CX] 审核列表在首项顶部和末项底部各保留 12px，行高调整为 86px，头像缩至 56px，并消除最后一项多余的外间距。
- [CX] 搜索图标改由固定 16px 容器按输入框垂直中线定位，内部 Tabler 图标不再受 SVG 行盒影响。
- [CX] 真实浏览器复核截图：`output/playwright/review-list-spacing-final-1440.png`、`output/playwright/review-list-spacing-final-390.png`、`output/playwright/review-health-neutral-1440.png`。
- [CX] 隔离浏览器验收使用只读 corpus 数据库副本和三角色 reviewer runtime 运行，全部页面、下拉框、质量分页和移动端路径为 PASS；源数据库未变、未写生产头像。验收同时修正了历史页仍引用已删除移动工作区 selector 的测试代码。
