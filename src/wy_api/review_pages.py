"""Server-rendered, read-only pages for the review workbench.

These support pages stay AI-agent-first: automated handling does the normal work,
and humans only inspect exceptions, drift, disputes, or access state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from html import escape
from typing import Mapping, Sequence

from wy_api.review_ui import CSS as REVIEW_CSS, THEME_INIT_JS, _top_icon


@dataclass(frozen=True)
class ReviewPageContext:
    consumer_id: str = "default"
    reviewer_id: str = "Reviewer"
    csrf_token: str | None = None
    service_ready: bool = True
    service_error: str | None = None


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

_NAV_ICONS = {
    "overview": '<path d="M4 13h6V4H4zM14 20h6v-9h-6zM4 20h6v-3H4zM14 7h6V4h-6z"></path>',
    "queue": '<rect x="4" y="4" width="16" height="16" rx="3"></rect><path d="M8 9h8M8 12h6M8 15h4"></path>',
    "agents": '<path d="M8 8h8v8H8zM12 3v3M12 18v3M3 12h3M18 12h3"></path><circle cx="10.5" cy="11" r=".7"></circle><circle cx="13.5" cy="11" r=".7"></circle><path d="M10 14h4"></path>',
    "policies": '<path d="M12 3.5l7 3v5.2c0 4.2-2.8 7.5-7 8.8-4.2-1.3-7-4.6-7-8.8V6.5z"></path><path d="M9 12l2 2 4-4"></path>',
    "quality": '<circle cx="12" cy="12" r="8.5"></circle><path d="m8.5 12 2.2 2.2 4.8-5"></path>',
    "history": '<path d="M6 4.5h12v15H6z"></path><path d="M9 8h6M9 11.5h6M9 15h4"></path>',
    "health": '<path d="M3.5 12h4l1.8-4.5 3.2 9 2.1-4.5h5.9"></path>',
    "account": '<circle cx="12" cy="8" r="3.5"></circle><path d="M5.5 20c.7-4 3-6 6.5-6s5.8 2 6.5 6"></path>',
    "guide": '<circle cx="12" cy="12" r="8.5"></circle><path d="M12 10v5M12 7.5h.01"></path>',
}


def _icon(path: str) -> str:
    return f'<svg viewBox="0 0 24 24" aria-hidden="true">{path}</svg>'

_CSS = REVIEW_CSS + """
/* Support pages reuse the queue shell but tighten typography, states, and spacing. */
:root {
  --font-display: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  --font-body: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
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
  font-size: 30px;
  font-weight: 620;
  line-height: 1.14;
  letter-spacing: -0.045em;
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

@media (max-width: 760px) {
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
    return candidate if candidate in {"quiet", "info", "warning", "danger", "success"} else "quiet"


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
            f'{f"<p>{detail}</p>" if detail else ""}</article>'
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
    return f'<div class="stats" aria-label="关键指标">{"".join(cards)}</div>' if cards else ""


def _render_data_state(status: str, detail: str) -> str:
    return (
        '<div class="data-state">'
        f"<strong>{escape(status)}</strong>"
        f"<span>{escape(detail)}</span>"
        "</div>"
    )


def _section_block(title: str, body: str, description: str = "") -> str:
    copy = f'<p class="section-copy">{escape(description)}</p>' if description else ""
    return f'<section class="section-block"><h3>{escape(title)}</h3>{copy}{body}</section>'


def _section_stack(*sections: str) -> str:
    return f'<div class="section-stack">{"".join(section for section in sections if section)}</div>'


def _render_metrics_block(value: object, *, empty_detail: str) -> str:
    return _render_metrics(value) or _render_data_state("未采集", empty_detail)


def _render_records_block(value: object, *, empty_status: str, empty_detail: str, empty_message: str) -> str:
    return (
        _render_records(value, empty_message)
        if _sequence(value)
        else _render_data_state(empty_status, empty_detail)
    )


def _render_table_block(value: object, *, empty_status: str, empty_detail: str, empty_message: str) -> str:
    table = _mapping(value)
    columns = _sequence(table.get("columns"))
    if not columns:
        return _render_data_state(empty_status, empty_detail)
    normalized = dict(table)
    normalized.setdefault("empty_message", empty_message)
    return _render_table(normalized)


def _render_definitions_block(value: object, *, empty_status: str, empty_detail: str) -> str:
    return (
        _render_definitions(value)
        if _mapping(value)
        else _render_data_state(empty_status, empty_detail)
    )


def _render_records(value: object, empty: str) -> str:
    records: list[str] = []
    for raw in _sequence(value):
        item = _mapping(raw)
        title = escape(_text(item.get("title") or item.get("name") or item.get("label"), "—"))
        detail = escape(_text(item.get("detail") or item.get("description") or item.get("status")))
        meta = escape(_text(item.get("meta") or item.get("value") or item.get("version")))
        records.append(f'<li class="record"><strong>{title}</strong><span>{detail}</span><code>{meta}</code></li>')
    return f'<ul class="record-list">{"".join(records)}</ul>' if records else f'<div class="empty">{escape(empty)}</div>'


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
        cells = "".join(_table_cell(row[index]) if index < len(row) else "<td></td>" for index in range(len(columns)))
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
    elif len(raw) == 32 and all(character in "0123456789abcdefABCDEF" for character in raw):
        shown = f"{raw[:10]}…{raw[-4:]}"
    return f'<td title="{escape(raw)}">{escape(shown)}</td>'


def _render_definitions(value: object) -> str:
    definitions = _mapping(value)
    if not definitions:
        return '<div class="empty">暂无信息</div>'
    parts = [f'<dt>{escape(_text(key))}</dt><dd>{escape(_text(item))}</dd>' for key, item in definitions.items()]
    return f'<dl class="definition-grid">{"".join(parts)}</dl>'


def _panel(title: str, description: str, body: str) -> str:
    return (
        '<section class="panel">'
        f'<header class="panel-head"><div><h2>{escape(title)}</h2><p>{escape(description)}</p></div></header>'
        f'<div class="panel-body">{body}</div></section>'
    )


def _link_row(*links: tuple[str, str]) -> str:
    rendered = [f'<a class="deep-link" href="{escape(href)}">{escape(label)}</a>' for href, label in links]
    return f'<div class="link-row">{"".join(rendered)}</div>' if rendered else ""


def _coerce_context(context: ReviewPageContext | Mapping[str, object] | None) -> ReviewPageContext:
    if context is None:
        return ReviewPageContext()
    if isinstance(context, ReviewPageContext):
        return context
    raw = _mapping(context)
    return ReviewPageContext(
        consumer_id=_text(raw.get("consumer_id"), "default"),
        reviewer_id=_text(raw.get("reviewer_id"), "Reviewer"),
        csrf_token=None if raw.get("csrf_token") is None else _text(raw.get("csrf_token")),
        service_ready=bool(raw.get("service_ready", True)),
        service_error=None if raw.get("service_error") is None else _text(raw.get("service_error")),
    )


def _page_body(page: str, data: Mapping[str, object], logout: str) -> str:
    notices = _render_notices(data.get("exceptions") or data.get("attention"))
    metrics = data.get("metrics")

    if page == "overview":
        return _panel(
            "人工关注摘要",
            "只展示传入的异常、概览指标与阶段事实；未采集数据直接标注。",
            _section_stack(
                _section_block("需要关注", notices, "这里只保留人工需要接手的异常。"),
                _section_block(
                    "关键指标",
                    _render_metrics_block(metrics, empty_detail="未提供概览指标。"),
                    "不再补画前端伪图表。",
                ),
                _section_block(
                    "流水线阶段",
                    _render_records_block(
                        data.get("pipeline"),
                        empty_status="未采集",
                        empty_detail="未提供阶段积压或延迟信息。",
                        empty_message="暂无流水线异常",
                    ),
                    "按传入阶段数据展示积压、延迟或 live 状态。",
                ),
                _section_block("入口", _link_row(("/review", "打开审核队列"), ("/review/history", "查看审计历史"))),
            ),
        )
    if page == "agents":
        return _panel(
            "AI 任务",
            "聚焦异常阶段、attempt 与积压，不再重复展示流程示意图。",
            _section_stack(
                _section_block("需要关注", notices, "先看失败、阻塞与人工兜底入口。"),
                _section_block(
                    "任务指标",
                    _render_metrics_block(metrics, empty_detail="未提供 AI 任务指标。"),
                ),
                _section_block(
                    "阶段明细",
                    _render_table_block(
                        data.get("agents"),
                        empty_status="未采集",
                        empty_detail="未提供 AI 任务分阶段明细。",
                        empty_message="没有需要人工关注的异常",
                    ),
                    "重试会生成新的 attempt；这里只展示真实阶段数据。",
                ),
                _section_block("入口", _link_row(("/review", "回到审核队列"))),
            ),
        )
    if page == "policies":
        return _panel(
            "策略与路由",
            "页面只读，只展示后端传入的生效策略、路由条件与版本事实。",
            _section_stack(
                _section_block("需要关注", notices, "策略异常或漂移先在这里暴露。"),
                _section_block(
                    "当前策略",
                    _render_definitions_block(
                        data.get("current_policy"),
                        empty_status="未采集",
                        empty_detail="未提供当前生效策略。",
                    ),
                ),
                _section_block(
                    "路由条件",
                    _render_table_block(
                        data.get("routes"),
                        empty_status="未采集",
                        empty_detail="未提供路由条件。",
                        empty_message="暂无路由规则",
                    ),
                    "本页不在前端推导阈值。",
                ),
                _section_block(
                    "版本记录",
                    _render_records_block(
                        data.get("versions"),
                        empty_status="未采集",
                        empty_detail="未提供策略版本记录。",
                        empty_message="暂无策略版本记录",
                    ),
                ),
                _section_block("入口", _link_row(("/review", "审核队列"), ("/review/history", "历史事件"))),
            ),
        )
    if page == "quality":
        return _panel(
            "质量与仲裁",
            "只展示传入的抽检、分歧与仲裁数据；零样本只记为 SKIP。",
            _section_stack(
                _section_block("需要关注", notices, "人工重点看分歧、推翻与需仲裁样本。"),
                _section_block(
                    "质量指标",
                    _render_metrics_block(metrics, empty_detail="未提供质量指标。"),
                    "不再补充前端伪指标。",
                ),
                _section_block(
                    "抽检与分歧",
                    _render_table_block(
                        data.get("cases"),
                        empty_status="SKIP",
                        empty_detail="未提供抽检样本或仲裁明细。",
                        empty_message="SKIP · 未采集抽检样本",
                    ),
                    "展示当前样本、阶段和是否进入仲裁。",
                ),
                _section_block("入口", _link_row(("/review/history", "查看审计历史"))),
            ),
        )
    if page == "history":
        return _panel(
            "审计历史",
            "按追加式事件查看审核链路，先确认模型与人工动作的先后顺序。",
            _section_stack(
                _section_block("需要关注", notices),
                _section_block(
                    "事件记录",
                    _render_table_block(
                        data.get("events"),
                        empty_status="未采集",
                        empty_detail="未提供历史事件。",
                        empty_message="暂无历史事件",
                    ),
                    "历史事件只追加，不覆盖。",
                ),
                _section_block("入口", _link_row(("/review", "回到审核队列"), ("/review/health", "系统健康"))),
            ),
        )
    if page == "health":
        return _panel(
            "系统健康",
            "检查流水线是否阻塞、组件是否 ready，以及哪里需要人工介入。",
            _section_stack(
                _section_block("需要关注", notices),
                _section_block(
                    "健康指标",
                    _render_metrics_block(metrics, empty_detail="未提供系统健康指标。"),
                    "只显示后端传入的真实指标或明确未采集状态。",
                ),
                _section_block(
                    "组件状态",
                    _render_table_block(
                        data.get("services"),
                        empty_status="未采集",
                        empty_detail="未提供组件状态。",
                        empty_message="暂无组件状态",
                    ),
                    "这里只呈现真实组件状态，不附带批量控制入口。",
                ),
                _section_block("入口", _link_row(("/review/agents", "AI 任务"))),
            ),
        )
    if page == "account":
        return _panel(
            "账户与会话",
            "确认 reviewer 身份、consumer 范围与退出条件，只展示当前真实 session 信息。",
            _section_stack(
                _section_block("需要关注", notices),
                _section_block(
                    "身份与范围",
                    _render_definitions_block(
                        data.get("profile"),
                        empty_status="未采集",
                        empty_detail="未提供 reviewer 或 consumer 信息。",
                    ),
                ),
                _section_block(
                    "活动会话",
                    _render_table_block(
                        data.get("sessions"),
                        empty_status="未采集",
                        empty_detail="未提供当前 session 信息。",
                        empty_message="暂无活动会话",
                    ) + logout,
                ),
            ),
        )
    return _panel(
        "审核说明",
        "把人工规则压缩成单页参考，不把说明拆成重复卡片。",
        _section_stack(
            _section_block("需要关注", notices),
            _section_block(
                "审核原则",
                _render_records_block(
                    data.get("principles"),
                    empty_status="未采集",
                    empty_detail="未提供审核原则。",
                    empty_message="暂无审核原则",
                ),
            ),
            _section_block(
                "风险类别",
                _render_table_block(
                    data.get("categories"),
                    empty_status="未采集",
                    empty_detail="未提供风险类别。",
                    empty_message="暂无风险类别",
                ),
            ),
            _section_block(
                "快捷参考",
                _render_table_block(
                    data.get("shortcuts"),
                    empty_status="未采集",
                    empty_detail="未提供快捷键。",
                    empty_message="暂无快捷键说明",
                )
                + _render_records_block(
                    data.get("reasons"),
                    empty_status="未采集",
                    empty_detail="未提供结构化原因说明。",
                    empty_message="暂无原因说明",
                ),
            ),
        ),
    )


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
            f'<span class="nav-icon">{_icon(_NAV_ICONS[key])}</span><span>{escape(label)}</span></a>'
        )
    workspace_nav = "".join(nav_items[key] for key in ("overview", "queue", "agents", "history"))
    settings_nav = "".join(nav_items[key] for key in ("policies", "quality", "health", "account", "guide"))
    nav = (
        '<div class="nav-scroll">'
        '<nav class="nav-section" aria-label="工作区"><p class="nav-label">Workspace</p>'
        f"{workspace_nav}</nav>"
        '<nav class="nav-section" aria-label="设置"><p class="nav-label">Settings</p>'
        f"{settings_nav}</nav>"
        '</div>'
    )

    service_label = "Pipeline ready" if ctx.service_ready else "Pipeline blocked"
    service_tone = "success" if ctx.service_ready else "danger"
    service_notice = ""
    if not ctx.service_ready:
        service_notice = _render_notices((Notice("审核流水线受阻", ctx.service_error or "服务未就绪", "danger"),))

    logout = ""
    if page == "account" and ctx.csrf_token:
        logout = (
            '<form class="logout" method="post" action="/review/logout">'
            f'<input type="hidden" name="csrf_token" value="{escape(ctx.csrf_token)}">'
            '<button type="submit">安全退出</button></form>'
        )

    body = _page_body(page, page_data, logout)
    intent = _PAGE_INTENTS[page]
    service_icon = _icon('<path d="M12 3l1.4 4.1 4.1 1.4-4.1 1.4L12 14l-1.4-4.1-4.1-1.4 4.1-1.4z"></path>')
    help_icon = _icon(_NAV_ICONS["guide"])
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>{escape(title)} · WordYeah</title>{THEME_INIT_JS}<style>{_CSS}</style></head>
<body><a class="skip-link" href="#main-content">跳到主要内容</a><div class="app-frame">
<aside class="side-nav" aria-label="审核导航"><a class="brand" href="/review/overview"><span class="brand-mark">wy</span><span>wordyeah</span></a>
<nav aria-label="工作台页面"><div class="support-nav">{nav}</div></nav><div class="nav-spacer"></div>
<div class="consumer-switcher"><span class="consumer-avatar">{escape(ctx.consumer_id[:1].upper() or 'W')}</span><span class="consumer-copy"><strong>{escape(ctx.consumer_id)}</strong><small>Consumer workspace</small></span><span class="chevron" aria-hidden="true">⌄</span></div></aside>
<div class="app-main"><header class="topbar"><div class="toolbar-title"><nav class="topbar-breadcrumbs" aria-label="面包屑"><a href="/review/overview">WordYeah</a><span class="divider" aria-hidden="true">/</span><span class="current-crumb">{escape(nav_label)}</span></nav></div>
<div class="toolbar-actions">
<button class="theme-toggle-btn" type="button" data-action="toggle-layout" title="切换全宽/盒装居中" aria-label="切换全宽/盒装居中">{_top_icon('layout')}</button>
<button class="theme-toggle-btn" type="button" data-action="toggle-theme" title="切换深色/浅色模式" aria-label="切换深色/浅色模式"><span class="theme-icon-sun">{_top_icon('sun')}</span><span class="theme-icon-moon">{_top_icon('moon')}</span></button>
<span class="topbar-icon service-status" data-tone="{service_tone}" role="status" title="{service_label}" aria-label="{service_label}">{service_icon}</span>
<a class="topbar-icon" href="/review/guide" title="审核说明" aria-label="审核说明">{help_icon}</a>
<details class="account-menu"><summary><span class="reviewer-avatar">{escape(ctx.reviewer_id[:1].upper() or 'R')}</span><span>{escape(ctx.reviewer_id)}</span><span aria-hidden="true">⌄</span></summary>
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
