"""Server-rendered, read-only pages for the review workbench.

These support pages stay AI-agent-first: automated handling does the normal work,
and humans only inspect exceptions, drift, disputes, or access state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from html import escape
from typing import Mapping, Sequence

from wy_api.icons import icon
from wy_api.page_account_guide import CSS as ACCOUNT_GUIDE_CSS
from wy_api.page_account_guide import render_account_content, render_guide_content
from wy_api.page_history_health import CSS as HISTORY_HEALTH_CSS
from wy_api.page_history_health import render_health_content, render_history_content
from wy_api.page_overview_agents import CSS as OVERVIEW_AGENTS_CSS
from wy_api.page_overview_agents import render_agents_body
from wy_api.page_policy_quality import CSS as POLICY_QUALITY_CSS
from wy_api.page_policy_quality import render_policies_body, render_quality_body
from wy_api.review_ui import CSS as REVIEW_CSS, THEME_INIT_JS


@dataclass(frozen=True)
class ReviewPageContext:
    consumer_id: str = "default"
    reviewer_id: str = "Reviewer"
    csrf_token: str | None = None
    service_ready: bool = True
    service_error: str | None = None
    workspaces: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Metric:
    label: str
    value: str | int | float
    detail: str = ""
    tone: str = "quiet"


@dataclass(frozen=True)
class Notice:
    title: str
    detail: str = ""
    tone: str = "warning"


@dataclass(frozen=True)
class TableData:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    empty_message: str = "暂无记录"


_NAV = (
    ("overview", "概览"),
    ("queue", "审核队列"),
    ("agents", "AI 任务"),
    ("policies", "审核策略"),
    ("quality", "质量与仲裁"),
    ("history", "操作记录"),
    ("health", "系统健康"),
    ("account", "账户"),
    ("guide", "审核说明"),
)

_PAGE_META = {
    "overview": (
        "运营概览",
        "只保留人工需要接手的变化、积压和风险，不重复展示 AI 已正常处理的流量。",
        "概览",
    ),
    "agents": (
        "AI 任务",
        "查看自动任务链路中的异常阶段、重试与人工兜底入口。",
        "AI 任务",
    ),
    "policies": (
        "策略与路由",
        "确认当前生效规则、路由条件与版本变更；页面只读，不在前端推导阈值。",
        "策略",
    ),
    "quality": (
        "质量与仲裁",
        "聚焦抽检、分歧与推翻，不把零样本误写成通过。",
        "质量",
    ),
    "history": (
        "审计历史",
        "按追加式事件查看审核链路，保留模型 attempt 与人工动作的真实顺序。",
        "历史",
    ),
    "health": (
        "系统健康",
        "检查流水线是否阻塞、组件是否 ready，以及哪里需要人工介入。",
        "健康",
    ),
    "account": (
        "Reviewer 账户",
        "确认身份、consumer 范围与会话状态；退出动作只在真实 session 存在时展示。",
        "账户",
    ),
    "guide": (
        "审核指南",
        "把人工规则压缩成需要时再看的参考页，不占用主审核流的注意力。",
        "指南",
    ),
}

_PAGE_INTENTS = {
    "overview": "人工只处理异常变化、积压与风险。",
    "agents": "先处理阻塞 attempt、重试与人工兜底入口。",
    "policies": "先核对生效策略，再查看路由与版本差异。",
    "quality": "先看抽检、分歧与仲裁，零样本只记为 SKIP。",
    "history": "先核对事件顺序，再决定是否继续追查。",
    "health": "先判断是否阻塞，再定位组件或队列异常。",
    "account": "先确认身份与会话范围，再处理退出或切换。",
    "guide": "只在例外场景查阅本页，不打断主审核流。",
}

_PAGE_ICON_NAMES = {
    "overview": "overview",
    "queue": "queue",
    "agents": "agents",
    "history": "history",
    "policies": "policy",
    "quality": "quality",
    "health": "health",
    "account": "account",
    "guide": "guide",
}

_CSS = (
    REVIEW_CSS
    + OVERVIEW_AGENTS_CSS
    + POLICY_QUALITY_CSS
    + HISTORY_HEALTH_CSS
    + ACCOUNT_GUIDE_CSS
    + """
/* Support pages reuse the queue shell but tighten typography, states, and spacing. */
:root {
  --font-display: -apple-system, BlinkMacSystemFont, "Inter", "SF Pro Display", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  --font-body: -apple-system, BlinkMacSystemFont, "Inter", "SF Pro Text", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  --font-mono: "SF Mono", "JetBrains Mono", "Fira Code", ui-monospace, Menlo, Monaco, Consolas, monospace;
  --font: var(--font-body);
  --mono: var(--font-mono);
  --support-line: var(--line);
  --support-line-strong: var(--line-strong);
  --support-panel: var(--panel);
  --support-panel-soft: var(--panel-soft);
}

:root[data-theme="dark"] {
  --support-line: var(--line);
  --support-line-strong: var(--line-strong);
  --support-panel: var(--panel);
  --support-panel-soft: var(--panel-soft);
}

.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}
.metric-card-windsor {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 17px 18px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
  box-shadow: var(--shadow-sm);
}
.metric-card-info { display: grid; min-width: 0; gap: 3px; }
.metric-card-info .label { color: var(--muted); font-size: 11px; font-weight: 650; }
.metric-card-info .val { color: var(--text); font-size: 25px; line-height: 1.1; letter-spacing: -0.035em; font-variant-numeric: tabular-nums; }
.metric-card-info small { overflow: hidden; color: var(--quiet); font-size: 10.5px; text-overflow: ellipsis; white-space: nowrap; }
.metric-card-icon {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  flex: 0 0 34px;
  border-radius: 9px;
  background: var(--accent-soft);
  color: var(--accent);
}
.metric-card-icon svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.charts-row { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(270px, 1fr); gap: 14px; }
.chart-card {
  min-width: 0;
  padding: 18px 20px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
  box-shadow: var(--shadow-sm);
}
.chart-card-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.chart-card-header h4 { margin: 0; font-size: 14px; font-weight: 680; letter-spacing: -0.02em; }
.chart-card-header p { margin: 3px 0 0; color: var(--muted); font-size: 11px; }
.chart-card-header > span { padding: 2px 8px; border-radius: 6px; background: var(--panel-soft); color: var(--quiet); font-size: 10.5px; white-space: nowrap; }
.svg-bar-chart { display: block; width: 100%; height: auto; margin-top: 4px; }
.chart-legend { display: flex; justify-content: flex-end; gap: 12px; margin-top: -2px; color: var(--muted); font-size: 10.5px; }
.chart-legend span { display: inline-flex; align-items: center; gap: 5px; }
.chart-legend i { width: 7px; height: 7px; border-radius: 2px; background: var(--accent); }
.chart-legend i[data-tone="decided"] { background: var(--green); }
.donut-layout { display: grid; grid-template-columns: 120px minmax(0, 1fr); align-items: center; gap: 16px; min-height: 150px; }
.donut-layout svg { width: 120px; height: 120px; }
.donut-total { fill: var(--text); font-size: 17px; font-weight: 700; text-anchor: middle; }
.donut-caption { fill: var(--quiet); font-size: 8px; text-anchor: middle; }
.donut-legend { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.donut-legend li { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 11px; }
.donut-legend li > span { display: flex; align-items: center; gap: 6px; color: var(--muted); }
.donut-legend i { width: 8px; height: 8px; border-radius: 2px; }
.donut-legend strong { color: var(--text); font-size: 11px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.donut-legend small { color: var(--quiet); font-size: 9px; font-weight: 500; }

body {
  font-family: var(--font-body);
  letter-spacing: -0.01em;
  background: var(--page);
  color: var(--text);
}

.brand,
.toolbar-title,
.consumer-copy strong,
.support-hero h1,
.panel-head h2,
.notice strong,
.stat-label,
.deep-link,
.logout button,
.status-pill,
.intent-note {
  font-family: var(--font-display);
}

code,
.mono,
.record code,
.consumer-avatar,
.reviewer-avatar {
  font-family: var(--font-mono);
}

.support-nav { display: grid; gap: 20px; }

.service-status {
  position: relative;
  color: var(--green);
}
.service-status::after {
  position: absolute;
  right: 7px;
  bottom: 7px;
  width: 7px;
  height: 7px;
  border: 2px solid var(--support-panel);
  border-radius: 50%;
  background: currentColor;
  content: "";
}
.service-status[data-tone="danger"] { color: var(--red); }

.topbar-breadcrumbs {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 560;
  letter-spacing: -0.01em;
}

.topbar-breadcrumbs a {
  color: var(--muted);
  text-decoration: none;
  transition: color 140ms ease;
}

.topbar-breadcrumbs a:hover {
  color: var(--text);
}

.topbar-breadcrumbs .divider {
  color: var(--line-strong);
  font-size: 11px;
  user-select: none;
}

.topbar-breadcrumbs span.current-crumb {
  color: var(--text);
  font-weight: 700;
}
.support-mobile-workspace { display: none; position: relative; }
.support-mobile-workspace > summary { min-height: 34px; align-items: center; gap: 6px; padding: 0 10px; border: 1px solid var(--line); border-radius: 8px; color: var(--muted); font-size: 11px; font-weight: 700; line-height: 1; cursor: pointer; }
.support-mobile-workspace .consumer-popover-menu {
  right: auto;
  left: 0;
  width: min(250px, calc(100vw - 32px));
  min-width: 0;
}

.support-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 28px;
  margin-bottom: 24px;
}
.support-hero-copy {
  display: grid;
  gap: 10px;
  max-width: 760px;
}
.support-hero h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 650;
  line-height: 1.35;
  letter-spacing: normal;
}
.support-hero p {
  max-width: 720px;
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.72;
}
.hero-meta {
  display: grid;
  justify-items: end;
  gap: 10px;
  min-width: 240px;
}
.status-pill,
.intent-note {
  display: inline-flex;
  min-height: 34px;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  border: 1px solid var(--support-line);
  border-radius: 999px;
  background: var(--support-panel);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.status-pill {
  color: var(--text);
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.04);
}
.status-pill[data-tone="success"] { border-color: var(--support-line); background: var(--green-soft); color: var(--green); }
.status-pill[data-tone="danger"] { border-color: var(--support-line); background: var(--red-soft); color: var(--red); }
.intent-note {
  color: var(--accent);
  background: var(--accent-soft);
  border-color: var(--line);
}
.status-pill svg,
.intent-note svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.6; }

.content-stack { display: grid; gap: 18px; }
.panel {
  overflow: hidden;
  border: 1px solid var(--support-line);
  border-radius: 12px;
  background: var(--support-panel);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}
.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 22px 26px 12px;
  border-bottom: 1px solid var(--support-line);
}
.panel-head h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
  letter-spacing: -0.025em;
  color: var(--text);
}
.panel-head p {
  max-width: 560px;
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 12.5px;
  line-height: 1.6;
}
.panel-body { padding: 20px 26px 24px; }
.section-stack {
  display: grid;
  gap: 18px;
}
.section-block {
  display: grid;
  gap: 12px;
  padding-top: 18px;
  border-top: 1px solid var(--support-line);
}
.section-block:first-child {
  padding-top: 0;
  border-top: 0;
}
.section-block h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 650;
  letter-spacing: -0.02em;
  color: var(--text);
}
.section-block p.section-copy {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.65;
}
.data-state {
  display: grid;
  gap: 6px;
  padding: 14px 16px;
  border: 1px dashed var(--support-line-strong);
  border-radius: 8px;
  background: var(--support-panel-soft);
}
.data-state strong {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text);
}
.data-state span {
  color: var(--quiet);
  font-size: 12px;
  line-height: 1.6;
}

.notice-stack {
  display: grid;
  margin-bottom: 16px;
  overflow: hidden;
  border: 1px solid var(--support-line);
  border-radius: 10px;
  background: var(--support-panel);
}
.notice {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr);
  align-items: start;
  column-gap: 10px;
  row-gap: 2px;
  padding: 11px 14px;
  border: 0;
  border-bottom: 1px solid var(--support-line);
  border-radius: 0;
  background: transparent;
}
.notice:last-child { border-bottom: 0; }
.notice::before {
  grid-row: 1 / span 2;
  width: 7px;
  height: 7px;
  margin-top: 5px;
  border-radius: 50%;
  background: var(--amber);
  content: "";
}
.notice[data-tone="danger"]::before { background: var(--red); }
.notice[data-tone="info"]::before { background: var(--accent); }
.notice[data-tone="success"]::before { background: var(--green); }
.notice strong {
  grid-column: 2;
  display: block;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.4;
}
.notice p {
  grid-column: 2;
  margin: 3px 0 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
}
.quiet-state,
.empty {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border: 1px dashed var(--support-line-strong);
  border-radius: 12px;
  background: var(--support-panel-soft);
  color: var(--quiet);
  font-size: 12.5px;
  line-height: 1.55;
}
.quiet-state::before,
.empty::before {
  display: inline-flex;
  flex: 0 0 20px;
  width: 20px;
  height: 20px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--support-panel);
  border: 1px solid var(--support-line);
  color: var(--quiet);
  content: "✓";
  font-size: 10px;
}
.quiet-state { margin-bottom: 14px; }

.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(172px, 1fr));
  gap: 12px;
  margin: 0 0 18px;
}
.stat {
  position: relative;
  display: grid;
  align-content: start;
  gap: 0;
  min-height: 96px;
  padding: 16px 18px 18px;
  border: 1px solid var(--support-line);
  border-radius: 10px;
  background: var(--support-panel);
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.04);
  transition: transform 120ms ease, box-shadow 120ms ease;
  overflow: hidden;
}
.stat:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.06);
}
.stat-label {
  display: block;
  color: var(--quiet);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  line-height: 1.3;
}
.stat-value {
  display: block;
  margin-top: 10px;
  font-size: 28px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums;
  color: var(--text);
}
.stat-detail {
  display: block;
  margin-top: 6px;
  color: var(--muted);
  font-size: 11.5px;
  line-height: 1.45;
}
.stat[data-tone="danger"] .stat-value { color: var(--red); }
.stat[data-tone="warning"] .stat-value { color: var(--amber); }
.stat[data-tone="success"] .stat-value { color: var(--green); }

.record-list { margin: 0; padding: 0; list-style: none; }
.record {
  display: grid;
  grid-template-columns: minmax(150px, .65fr) minmax(0, 1.35fr) auto;
  align-items: baseline;
  gap: 18px;
  min-height: 52px;
  padding: 14px 0;
  border-top: 1px solid var(--support-line);
}
.record:first-child { border-top: 0; padding-top: 4px; }
.record strong {
  font-size: 12px;
  font-weight: 620;
  letter-spacing: -0.01em;
}
.record span {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.65;
}
.record code {
  color: var(--quiet);
  font-size: 11px;
  white-space: nowrap;
}

.table-wrap {
  overflow: auto;
  border: 1px solid var(--support-line);
  border-radius: 14px;
  background: var(--support-panel);
}
table { width: 100%; min-width: 860px; border-collapse: collapse; background: var(--support-panel); color: var(--text); }
th,
td {
  padding: 13px 16px;
  border-bottom: 1px solid var(--support-line);
  text-align: left;
  vertical-align: top;
  font-size: 12px;
  white-space: nowrap;
}
td {
  font-variant-numeric: tabular-nums;
  line-height: 1.58;
}
th {
  background: var(--support-panel-soft);
  color: var(--quiet);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
tbody tr:last-child td { border-bottom: 0; }
tbody tr:hover { background: var(--support-panel-soft); }

.definition-grid {
  display: grid;
  grid-template-columns: minmax(170px, .58fr) minmax(0, 1.42fr);
  margin: 0;
  overflow: hidden;
  border: 1px solid var(--support-line);
  border-radius: 14px;
}
.definition-grid dt,
.definition-grid dd {
  margin: 0;
  padding: 12px 14px;
  border-bottom: 1px solid var(--support-line);
}
.definition-grid dt {
  background: var(--support-panel-soft);
  color: var(--muted);
  font-size: 11px;
  font-weight: 600;
}
.definition-grid dd {
  font-size: 12px;
  line-height: 1.65;
}
.definition-grid dt:last-of-type,
.definition-grid dd:last-of-type { border-bottom: 0; }

.link-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.deep-link,
.logout button {
  display: inline-flex;
  min-height: 36px;
  align-items: center;
  justify-content: center;
  padding: 0 13px;
  border: 1px solid var(--support-line);
  border-radius: 999px;
  background: var(--support-panel);
  color: var(--muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: -0.01em;
  text-decoration: none;
  transition: border-color 140ms ease, background 140ms ease, color 140ms ease;
}
.deep-link:hover,
.deep-link:focus-visible,
.logout button:hover,
.logout button:focus-visible {
  border-color: var(--support-line-strong);
  background: var(--support-panel-soft);
  color: var(--text);
}
.logout { margin-top: 12px; }
.logout button { cursor: pointer; }
.support-footer {
  margin: 24px 0 0;
  padding-top: 14px;
  border-top: 1px solid var(--support-line);
  color: var(--quiet);
  font-size: 11px;
  line-height: 1.6;
}

@media (min-width: 761px) and (max-width: 980px) {
  .side-nav > nav { min-width: 0; flex: 1 1 0; overflow: hidden; }
  .support-nav { display: flex; gap: 4px; overflow-x: auto; }
  .support-nav .nav-section { display: flex; flex: 0 0 auto; }
  .support-mobile-workspace { display: block; margin-left: auto; }
  .support-mobile-workspace .consumer-popover-menu {
    top: calc(100% + 8px);
    right: auto;
    bottom: auto;
    left: 0;
    width: min(250px, calc(100vw - 48px));
  }
}

@media (max-width: 760px) {
  .side-nav > nav { display: none; }
  .support-mobile-workspace { display: block; }
  .support-mobile-workspace .consumer-popover-menu {
    top: calc(100% + 8px);
    right: auto;
    bottom: auto;
    left: 0;
    width: min(250px, calc(100vw - 32px));
  }
  .dashboard-grid,
  .charts-row { grid-template-columns: 1fr; }
  .donut-layout { grid-template-columns: 108px minmax(0, 1fr); }
  .donut-layout svg { width: 108px; height: 108px; }
  .support-nav { display: flex; gap: 4px; overflow-x: auto; }
  .support-nav .nav-section { display: flex; flex: 0 0 auto; }
  .support-hero {
    display: grid;
    gap: 14px;
    margin-bottom: 22px;
  }
  .support-hero h1 { font-size: 28px; }
  .hero-meta {
    justify-items: start;
    min-width: 0;
  }
  .status-pill,
  .intent-note { width: fit-content; }
  .panel-head { padding: 18px 16px 10px; }
  .panel-body { padding: 0 16px 18px; }
  .stats { grid-template-columns: 1fr; }
  .stat + .stat { border-top: 1px solid var(--support-line); border-left: 0; }
  .record { grid-template-columns: 1fr; gap: 4px; }
  .definition-grid { grid-template-columns: 1fr; }
  .definition-grid dt { border-bottom: 0; padding-bottom: 3px; }
  .definition-grid dd { padding-top: 3px; }
}
"""
)


def _plain(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


def _mapping(value: object) -> Mapping[str, object]:
    value = _plain(value)
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    value = _plain(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _text(value: object, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _tone(value: object) -> str:
    candidate = _text(value).lower()
    return (
        candidate
        if candidate in {"quiet", "info", "warning", "danger", "success"}
        else "quiet"
    )


def _render_notices(value: object) -> str:
    notices = _sequence(value)
    if not notices:
        return '<div class="quiet-state">没有需要人工关注的异常。</div>'
    rendered: list[str] = []
    for raw in notices:
        item = _mapping(raw)
        title = escape(_text(item.get("title") or item.get("label"), "未命名异常"))
        detail = escape(_text(item.get("detail") or item.get("message")))
        rendered.append(
            f'<article class="notice" data-tone="{_tone(item.get("tone"))}"><strong>{title}</strong>'
            f"{f'<p>{detail}</p>' if detail else ''}</article>"
        )
    return f'<div class="notice-stack" aria-label="需要关注">{"".join(rendered)}</div>'


def _render_metrics(value: object) -> str:
    cards: list[str] = []
    for raw in _sequence(value):
        item = _mapping(raw)
        cards.append(
            f'<article class="stat" data-tone="{_tone(item.get("tone"))}">'
            f'<span class="stat-label">{escape(_text(item.get("label"), "指标"))}</span>'
            f'<strong class="stat-value">{escape(_text(item.get("value"), "—"))}</strong>'
            f'<span class="stat-detail">{escape(_text(item.get("detail")))}</span></article>'
        )
    return (
        f'<div class="stats" aria-label="关键指标">{"".join(cards)}</div>'
        if cards
        else ""
    )


def _render_data_state(status: str, detail: str) -> str:
    return (
        '<div class="data-state">'
        f"<strong>{escape(status)}</strong>"
        f"<span>{escape(detail)}</span>"
        "</div>"
    )


def _section_block(title: str, body: str, description: str = "") -> str:
    copy = f'<p class="section-copy">{escape(description)}</p>' if description else ""
    return (
        f'<section class="section-block"><h3>{escape(title)}</h3>{copy}{body}</section>'
    )


def _section_stack(*sections: str) -> str:
    return f'<div class="section-stack">{"".join(section for section in sections if section)}</div>'


def _render_metrics_block(value: object, *, empty_detail: str) -> str:
    return _render_metrics(value) or _render_data_state("未采集", empty_detail)


def _render_records_block(
    value: object, *, empty_status: str, empty_detail: str, empty_message: str
) -> str:
    return (
        _render_records(value, empty_message)
        if _sequence(value)
        else _render_data_state(empty_status, empty_detail)
    )


def _render_table_block(
    value: object, *, empty_status: str, empty_detail: str, empty_message: str
) -> str:
    table = _mapping(value)
    columns = _sequence(table.get("columns"))
    if not columns:
        return _render_data_state(empty_status, empty_detail)
    normalized = dict(table)
    normalized.setdefault("empty_message", empty_message)
    return _render_table(normalized)


def _render_definitions_block(
    value: object, *, empty_status: str, empty_detail: str
) -> str:
    return (
        _render_definitions(value)
        if _mapping(value)
        else _render_data_state(empty_status, empty_detail)
    )


def _render_records(value: object, empty: str) -> str:
    records: list[str] = []
    for raw in _sequence(value):
        item = _mapping(raw)
        title = escape(
            _text(item.get("title") or item.get("name") or item.get("label"), "—")
        )
        detail = escape(
            _text(item.get("detail") or item.get("description") or item.get("status"))
        )
        meta = escape(
            _text(item.get("meta") or item.get("value") or item.get("version"))
        )
        records.append(
            f'<li class="record"><strong>{title}</strong><span>{detail}</span><code>{meta}</code></li>'
        )
    return (
        f'<ul class="record-list">{"".join(records)}</ul>'
        if records
        else f'<div class="empty">{escape(empty)}</div>'
    )


def _render_table(value: object) -> str:
    table = _mapping(value)
    columns = tuple(_text(v) for v in _sequence(table.get("columns")))
    rows = _sequence(table.get("rows"))
    empty = _text(table.get("empty_message"), "暂无记录")
    if not columns:
        return f'<div class="empty">{escape(empty)}</div>'
    head = "".join(f'<th scope="col">{escape(column)}</th>' for column in columns)
    body_rows: list[str] = []
    for raw_row in rows:
        row = _sequence(raw_row)
        cells = "".join(
            _table_cell(row[index]) if index < len(row) else "<td></td>"
            for index in range(len(columns))
        )
        body_rows.append(f"<tr>{cells}</tr>")
    body = "".join(body_rows) or (
        f'<tr><td colspan="{len(columns)}"><div class="empty">{escape(empty)}</div></td></tr>'
    )
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _table_cell(value: object) -> str:
    raw = _text(value)
    shown = raw
    if "T" in raw and len(raw) >= 19 and raw[:4].isdigit():
        shown = raw[:19].replace("T", " ")
    elif len(raw) == 32 and all(
        character in "0123456789abcdefABCDEF" for character in raw
    ):
        shown = f"{raw[:10]}…{raw[-4:]}"
    return f'<td title="{escape(raw)}">{escape(shown)}</td>'


def _render_definitions(value: object) -> str:
    definitions = _mapping(value)
    if not definitions:
        return '<div class="empty">暂无信息</div>'
    parts = [
        f"<dt>{escape(_text(key))}</dt><dd>{escape(_text(item))}</dd>"
        for key, item in definitions.items()
    ]
    return f'<dl class="definition-grid">{"".join(parts)}</dl>'


def _panel(title: str, description: str, body: str) -> str:
    return (
        '<section class="panel">'
        f'<header class="panel-head"><div><h2>{escape(title)}</h2><p>{escape(description)}</p></div></header>'
        f'<div class="panel-body">{body}</div></section>'
    )


def _link_row(*links: tuple[str, str]) -> str:
    rendered = [
        f'<a class="deep-link" href="{escape(href)}">{escape(label)}</a>'
        for href, label in links
    ]
    return f'<div class="link-row">{"".join(rendered)}</div>' if rendered else ""


def _coerce_context(
    context: ReviewPageContext | Mapping[str, object] | None,
) -> ReviewPageContext:
    if context is None:
        return ReviewPageContext()
    if isinstance(context, ReviewPageContext):
        return context
    raw = _mapping(context)
    return ReviewPageContext(
        consumer_id=_text(raw.get("consumer_id"), "default"),
        reviewer_id=_text(raw.get("reviewer_id"), "Reviewer"),
        csrf_token=None
        if raw.get("csrf_token") is None
        else _text(raw.get("csrf_token")),
        service_ready=bool(raw.get("service_ready", True)),
        service_error=None
        if raw.get("service_error") is None
        else _text(raw.get("service_error")),
        workspaces=tuple(
            (_text(item[0]), _text(item[1]))
            for item in _sequence(raw.get("workspaces"))
            if isinstance(item, Sequence)
            and not isinstance(item, (str, bytes))
            and len(item) >= 2
        ),
    )


def _dashboard_integer(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _render_dashboard_charts(data: Mapping[str, object]) -> str:
    series = [_mapping(item) for item in _sequence(data.get("volume_series"))]
    distribution = [
        _mapping(item) for item in _sequence(data.get("decision_distribution"))
    ]
    cards = [_mapping(item) for item in _sequence(data.get("overview_metrics"))]
    if not series and not distribution and not cards:
        return ""

    if not cards:
        total_items = sum(
            _dashboard_integer(item.get("value")) for item in distribution
        )
        passed = next(
            (
                _dashboard_integer(item.get("value"))
                for item in distribution
                if _text(item.get("label")) == "已通过"
            ),
            0,
        )
        finalized = sum(
            _dashboard_integer(item.get("value"))
            for item in distribution
            if _text(item.get("label")) in {"已通过", "已拒绝"}
        )
        pending = sum(
            _dashboard_integer(item.get("value"))
            for item in distribution
            if _text(item.get("label")) in {"待处理", "留置"}
        )
        cards = [
            {"label": "审核总量", "value": total_items, "detail": "当前工作区"},
            {
                "label": "14 天入队",
                "value": sum(
                    _dashboard_integer(item.get("incoming")) for item in series
                ),
                "detail": "按创建时间统计",
            },
            {
                "label": "通过率",
                "value": f"{passed * 100 / finalized:.1f}%" if finalized else "—",
                "detail": f"{finalized} 条已有最终结论",
            },
            {"label": "待处理", "value": pending, "detail": "含留置项目"},
        ]

    card_icons = ("photo", "chart-line", "percentage", "clock-hour-4")
    metric_cards: list[str] = []
    for index, item in enumerate(cards[:4]):
        metric_cards.append(
            '<article class="metric-card-windsor">'
            '<div class="metric-card-info">'
            f'<span class="label">{escape(_text(item.get("label"), "指标"))}</span>'
            f'<strong class="val">{escape(_text(item.get("value"), "—"))}</strong>'
            f"<small>{escape(_text(item.get('detail')))}</small></div>"
            f'<span class="metric-card-icon">{icon(card_icons[index])}</span>'
            "</article>"
        )
    metrics_html = (
        f'<div class="dashboard-grid">{"".join(metric_cards)}</div>'
        if metric_cards
        else ""
    )

    charts: list[str] = []
    if series:
        values = [
            max(
                _dashboard_integer(item.get("incoming")),
                _dashboard_integer(item.get("decided")),
            )
            for item in series
        ]
        scale_max = max(1, max(values, default=0))
        plot_left, plot_top, plot_width, plot_height = 36, 16, 480, 110
        slot = plot_width / max(1, len(series))
        bar_width = max(4.0, min(10.0, slot * 0.28))
        grid: list[str] = []
        for ratio in (0.0, 0.5, 1.0):
            y = plot_top + plot_height * ratio
            label = round(scale_max * (1 - ratio))
            grid.append(
                f'<line x1="{plot_left}" y1="{y:.1f}" x2="{plot_left + plot_width}" y2="{y:.1f}" stroke="var(--line)" stroke-width="1" stroke-dasharray="3 3"/>'
                f'<text x="{plot_left - 6}" y="{y + 3:.1f}" fill="var(--muted)" font-size="9" text-anchor="end" font-family="var(--mono)">{label}</text>'
            )
        bars: list[str] = []
        labels: list[str] = []
        for index, item in enumerate(series):
            incoming = _dashboard_integer(item.get("incoming"))
            decided = _dashboard_integer(item.get("decided"))
            center = plot_left + slot * index + slot / 2
            incoming_height = plot_height * incoming / scale_max
            decided_height = plot_height * decided / scale_max
            day_label = escape(_text(item.get("label")))
            bars.append(
                f'<rect fill="var(--accent)" opacity="0.85" x="{center - bar_width - 1:.1f}" y="{plot_top + plot_height - incoming_height:.1f}" width="{bar_width:.1f}" height="{incoming_height:.1f}" rx="2"><title>{day_label} 模型处理：{incoming}</title></rect>'
                f'<rect fill="var(--green)" opacity="0.75" x="{center + 1:.1f}" y="{plot_top + plot_height - decided_height:.1f}" width="{bar_width:.1f}" height="{decided_height:.1f}" rx="2"><title>{day_label} 人工结论：{decided}</title></rect>'
            )
            if index % 2 == 0 or index == len(series) - 1:
                labels.append(
                    f'<text x="{center:.1f}" y="142" fill="var(--muted)" font-size="9" text-anchor="middle" font-family="var(--mono)">{day_label}</text>'
                )
        incoming_total = sum(
            _dashboard_integer(item.get("incoming")) for item in series
        )
        charts.append(
            '<section class="chart-card">'
            '<header class="chart-card-header"><div><h4>处理趋势</h4><p>最近 14 天模型处理与人工结论量</p></div>'
            f"<span>{incoming_total} 条模型处理</span></header>"
            '<div class="chart-legend"><span><i data-tone="incoming"></i>模型处理</span><span><i data-tone="decided"></i>人工结论</span></div>'
            '<svg class="svg-bar-chart" viewBox="0 0 530 150" role="img" aria-label="最近十四天审核处理趋势">'
            + "".join(grid + bars + labels)
            + "</svg></section>"
        )

    if distribution:
        total = sum(_dashboard_integer(item.get("value")) for item in distribution)
        color_by_label = {
            "已通过": "var(--accent)",
            "模型通过": "var(--accent)",
            "待处理": "var(--amber)",
            "进入复核": "var(--amber)",
            "已拒绝": "var(--red)",
            "模型拒绝": "var(--red)",
            "留置": "var(--quiet)",
            "处理错误": "var(--quiet)",
        }
        circumference = 276.46
        offset = 0.0
        segments: list[str] = []
        legend: list[str] = []
        for item in distribution:
            label = _text(item.get("label"), "未分类")
            value = _dashboard_integer(item.get("value"))
            color = color_by_label.get(label, "var(--quiet)")
            length = circumference * value / total if total else 0.0
            if length:
                segments.append(
                    f'<circle cx="60" cy="60" r="44" fill="none" stroke="{color}" stroke-width="16" stroke-dasharray="{length:.2f} {circumference - length:.2f}" stroke-dashoffset="{-offset:.2f}"/>'
                )
            percentage = value * 100 / total if total else 0.0
            legend.append(
                "<li>"
                f'<span><i style="background:{color}"></i>{escape(label)}</span>'
                f"<strong>{percentage:.1f}% <small>{value}</small></strong></li>"
            )
            offset += length
        charts.append(
            '<section class="chart-card">'
            '<header class="chart-card-header"><h4>决策分布</h4></header>'
            '<div class="donut-layout"><svg viewBox="0 0 120 120" role="img" aria-label="审核决策分布">'
            '<g transform="rotate(-90 60 60)"><circle cx="60" cy="60" r="44" fill="none" stroke="var(--panel-soft)" stroke-width="16"/>'
            + "".join(segments)
            + f'</g><text x="60" y="58" class="donut-total">{total}</text><text x="60" y="72" class="donut-caption">总计</text></svg>'
            f'<ul class="donut-legend">{"".join(legend)}</ul></div></section>'
        )

    charts_html = f'<div class="charts-row">{"".join(charts)}</div>' if charts else ""
    return metrics_html + charts_html


def _page_body(
    page: str,
    data: Mapping[str, object],
    *,
    csrf_token: str | None = None,
) -> str:
    """Dispatch to page-specific information architectures."""
    notices = _render_notices(data.get("exceptions") or data.get("attention"))
    metrics = data.get("metrics")

    if page == "overview":
        charts_html = _render_dashboard_charts(data)
        metrics_block = _render_metrics_block(metrics, empty_detail="未提供概览指标。")
        pipeline_block = _render_records_block(
            data.get("pipeline"),
            empty_status="未采集",
            empty_detail="未提供阶段积压或延迟信息。",
            empty_message="暂无流水线异常",
        )
        sections: list[str] = []
        if charts_html:
            sections.append(charts_html)
        else:
            sections.append(_panel("概览数据", "后端未提供趋势数据。", metrics_block))
        if _sequence(data.get("exceptions") or data.get("attention")):
            sections.append(_panel("需要关注", "只显示需要人工接手的异常。", notices))
        if _sequence(data.get("pipeline")):
            sections.append(
                _panel(
                    "待处理流水线", "按当前阶段显示仍在等待处理的项目。", pipeline_block
                )
            )
        elif not charts_html:
            sections.append(
                _panel("待处理流水线", "后端未提供阶段数据。", pipeline_block)
            )
        return "".join(sections)
    if page == "agents":
        return render_agents_body(data)
    if page == "policies":
        return render_policies_body(data)
    if page == "quality":
        return render_quality_body(data)
    if page == "history":
        return render_history_content(data)
    if page == "health":
        return render_health_content(data)
    if page == "account":
        return render_account_content(data, csrf_token=csrf_token)
    if page == "guide":
        return render_guide_content(data)
    raise ValueError(f"unsupported review page: {page}")


def render_review_page(
    page: str,
    data: Mapping[str, object] | object | None = None,
    *,
    context: ReviewPageContext | Mapping[str, object] | None = None,
) -> str:
    """Render one of the read-only workbench pages as a complete HTML document."""
    if page not in _PAGE_META:
        raise ValueError(f"unknown review page: {page}")
    page_data = _mapping(data)
    ctx = _coerce_context(context)
    title, subtitle, nav_label = _PAGE_META[page]

    nav_items: dict[str, str] = {}
    for key, label in _NAV:
        active_class = " is-active" if key == page else ""
        current = ' aria-current="page"' if key == page else ""
        href = "/review" if key == "queue" else f"/review/{key}"
        nav_items[key] = (
            f'<a class="nav-item{active_class}" href="{href}"{current}>'
            f'<span class="nav-icon">{icon(_PAGE_ICON_NAMES[key])}</span><span>{escape(label)}</span></a>'
        )
    workspace_nav = "".join(
        nav_items[key] for key in ("overview", "queue", "agents", "history")
    )
    settings_nav = "".join(
        nav_items[key] for key in ("policies", "quality", "health", "account", "guide")
    )
    nav = (
        '<div class="nav-scroll">'
        '<nav class="nav-section" aria-label="工作区"><p class="nav-label">Workspace</p>'
        f"{workspace_nav}</nav>"
        '<nav class="nav-section" aria-label="设置"><p class="nav-label">Settings</p>'
        f"{settings_nav}</nav>"
        "</div>"
    )

    service_label = (
        "Local scanner ready" if ctx.service_ready else "Local scanner blocked"
    )
    service_tone = "success" if ctx.service_ready else "danger"
    service_notice = ""
    if not ctx.service_ready:
        service_notice = _render_notices(
            (Notice("审核流水线受阻", ctx.service_error or "服务未就绪", "danger"),)
        )

    body = _page_body(page, page_data, csrf_token=ctx.csrf_token)
    intent = _PAGE_INTENTS[page]
    service_icon = icon("spark")
    help_icon = icon("guide")
    workspace_choices = ctx.workspaces or ((ctx.consumer_id, ctx.consumer_id),)
    workspace_items = "".join(
        (
            '<div class="consumer-popover-item is-active">'
            f'<span class="consumer-avatar">{escape(name[:1].upper())}</span>'
            f'<div class="item-info"><strong>{escape(name)}</strong><small>当前审核工作区</small></div>'
            f'<span class="check-icon">{icon("check")}</span></div>'
            if workspace_id == ctx.consumer_id
            else '<form class="workspace-select-form" method="post" action="/review/workspaces/'
            + escape(workspace_id, quote=True)
            + '/select"><input type="hidden" name="csrf_token" value="'
            + escape(ctx.csrf_token or "", quote=True)
            + '"><input type="hidden" name="return_to" value="/review/'
            + escape(page, quote=True)
            + '"><button class="consumer-popover-item" type="submit">'
            + f'<span class="consumer-avatar">{escape(name[:1].upper())}</span>'
            + f'<span class="item-info"><strong>{escape(name)}</strong><small>{escape(workspace_id)}</small></span>'
            + "</button></form>"
        )
        for workspace_id, name in workspace_choices
    )
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>{escape(title)} · WordYeah</title>{THEME_INIT_JS}<style>{_CSS}</style></head>
<body><a class="skip-link" href="#main-content">跳到主要内容</a><div class="app-frame">
<aside class="side-nav" aria-label="审核导航"><a class="brand" href="/review/overview"><span class="brand-mark">wy</span><span>wordyeah</span></a>
<nav aria-label="工作台页面"><div class="support-nav">{nav}</div></nav>

<div class="usage-widget">
  <div class="usage-header">
    <span class="usage-icon">{icon("spark")}</span>
    <span class="usage-title">审查引擎状态</span>
    <button class="usage-gear-btn" type="button" title="查看策略与健康状态" onclick="location.href='/review/health'">
      {icon("settings")}
    </button>
  </div>
  <p class="usage-subtitle">当前 consumer 的审核流水线</p>
  <div class="usage-meta">
    <span class="usage-count">工作区 <strong>{escape(ctx.consumer_id)}</strong></span>
  </div>
  <div class="usage-tag">
    <span class="dot" style="background: {"var(--green)" if ctx.service_ready else "var(--red)"};"></span>
    {"本地扫描服务可用" if ctx.service_ready else "本地扫描服务受阻"}
  </div>
  <a class="usage-upgrade-btn" href="/review/health">检查系统健康</a>
</div>

<div class="nav-spacer"></div>
<details class="consumer-popover-wrapper" name="review-dropdown">
  <summary class="consumer-switcher dropdown-trigger">
    <span class="consumer-avatar">{escape(ctx.consumer_id[:1].upper() or "W")}</span>
    <span class="consumer-copy"><strong>{escape(ctx.consumer_id)}</strong><small>Consumer workspace</small></span>
    <span class="chevron">{icon("chevron-down")}</span>
  </summary>
  <div class="consumer-popover-menu">
    <div class="consumer-popover-header">Reviewer: {escape(ctx.reviewer_id)}</div>
    <div class="consumer-popover-list">
      {workspace_items}
    </div>
    <div class="consumer-popover-actions">
      <a class="popover-action-btn" href="/review/account">账户与会话</a>
      {'<form class="logout" method="post" action="/review/logout"><input type="hidden" name="csrf_token" value="' + escape(ctx.csrf_token) + '"><button class="popover-action-btn logout-btn" type="submit">Log out</button></form>' if ctx.csrf_token else '<a class="popover-action-btn" href="/review/account">Account Details</a>'}
    </div>
  </div>
</details>
</aside>
<div class="app-main"><header class="topbar"><div class="toolbar-title"><nav class="topbar-breadcrumbs" aria-label="面包屑"><a href="/review/overview">WordYeah</a><span class="divider" aria-hidden="true">/</span><span class="current-crumb">{escape(nav_label)}</span></nav></div>
<div class="toolbar-actions">
<details class="support-mobile-workspace" name="review-dropdown"><summary class="dropdown-trigger" aria-label="切换工作区">{escape(ctx.consumer_id)}{icon("chevron-down")}</summary><div class="consumer-popover-menu"><div class="consumer-popover-header">切换工作区</div><div class="consumer-popover-list">{workspace_items}</div></div></details>
<button class="theme-toggle-btn" type="button" data-action="toggle-layout" title="切换全宽/盒装居中" aria-label="切换全宽/盒装居中">{icon("layout")}</button>
<button class="theme-toggle-btn" type="button" data-action="toggle-theme" title="切换深色/浅色模式" aria-label="切换深色/浅色模式"><span class="theme-icon-sun">{icon("sun")}</span><span class="theme-icon-moon">{icon("moon")}</span></button>
<span class="topbar-icon service-status" data-tone="{service_tone}" role="status" title="{service_label}" aria-label="{service_label}">{service_icon}</span>
<a class="topbar-icon" href="/review/guide" title="审核说明" aria-label="审核说明">{help_icon}</a>
<details class="account-menu" name="review-dropdown"><summary class="dropdown-trigger"><span class="reviewer-avatar">{escape(ctx.reviewer_id[:1].upper() or "R")}</span><span>{escape(ctx.reviewer_id)}</span><span class="chevron">{icon("chevron-down")}</span></summary>
<div class="account-popover"><p>{escape(ctx.consumer_id)} · 受限审核会话</p>{'<form class="logout" method="post" action="/review/logout"><input type="hidden" name="csrf_token" value="' + escape(ctx.csrf_token) + '"><button type="submit">安全退出</button></form>' if ctx.csrf_token else '<a class="toolbar-link" href="/review/account">账户与会话</a>'}</div></details></div></header>
<main class="shell" id="main-content"><header class="support-hero"><div class="support-hero-copy"><h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>
<div class="hero-meta"><span class="status-pill" data-tone="{service_tone}">{service_icon}{service_label}</span><span class="intent-note">{help_icon}{escape(intent)}</span></div></header>
<div class="content-stack">{service_notice}{body}</div><footer class="support-footer">当前 consumer：{escape(ctx.consumer_id)} · Reviewer：{escape(ctx.reviewer_id)}</footer></main></div></div><script src="/review/assets/workbench.js"></script></body></html>'''


def render_overview_page(data: object = None, *, context: object = None) -> str:
    return render_review_page("overview", data, context=context)


def render_agents_page(data: object = None, *, context: object = None) -> str:
    return render_review_page("agents", data, context=context)


def render_policies_page(data: object = None, *, context: object = None) -> str:
    return render_review_page("policies", data, context=context)


def render_quality_page(data: object = None, *, context: object = None) -> str:
    return render_review_page("quality", data, context=context)


def render_history_page(data: object = None, *, context: object = None) -> str:
    return render_review_page("history", data, context=context)


def render_health_page(data: object = None, *, context: object = None) -> str:
    return render_review_page("health", data, context=context)


def render_account_page(data: object = None, *, context: object = None) -> str:
    return render_review_page("account", data, context=context)


def render_guide_page(data: object = None, *, context: object = None) -> str:
    return render_review_page("guide", data, context=context)


__all__ = [
    "Metric",
    "Notice",
    "ReviewPageContext",
    "TableData",
    "render_review_page",
    "render_overview_page",
    "render_agents_page",
    "render_policies_page",
    "render_quality_page",
    "render_history_page",
    "render_health_page",
    "render_account_page",
    "render_guide_page",
]
