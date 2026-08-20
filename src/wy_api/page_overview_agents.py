"""Scoped body renderers for the overview and AI-task review pages.

The main review renderer owns the document shell.  This module only returns the
contents placed inside that shell and a stylesheet whose selectors are rooted
at ``.oa-page``.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from html import escape
from typing import Mapping, Sequence


CSS = """
.oa-page { display: grid; gap: 18px; color: var(--text); }
.oa-page [hidden] { display: none !important; }
.oa-page .oa-section { overflow: hidden; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); }
.oa-page .oa-section-head { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; padding: 17px 20px 12px; border-bottom: 1px solid var(--line); }
.oa-page .oa-section-head h2 { margin: 0; font-size: 15px; line-height: 1.35; }
.oa-page .oa-section-head p { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.55; }
.oa-page .oa-attention { border-color: var(--line-strong, var(--line)); }
.oa-page .oa-list { margin: 0; padding: 0; list-style: none; }
.oa-page .oa-alert { display: grid; grid-template-columns: 9px minmax(0, 1fr) auto; gap: 4px 11px; padding: 14px 20px; border-top: 1px solid var(--line); }
.oa-page .oa-alert:first-child { border-top: 0; }
.oa-page .oa-alert::before { grid-row: 1 / span 2; width: 8px; height: 8px; margin-top: 5px; border-radius: 50%; background: var(--amber); content: ""; }
.oa-page .oa-alert[data-tone="danger"]::before { background: var(--red); }
.oa-page .oa-alert[data-tone="info"]::before { background: var(--accent); }
.oa-page .oa-alert strong { font-size: 13px; line-height: 1.45; }
.oa-page .oa-alert p { grid-column: 2; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.55; }
.oa-page .oa-alert code { color: var(--quiet, var(--muted)); font-size: 11px; white-space: nowrap; }
.oa-page .oa-clear, .oa-page .oa-missing { margin: 16px 20px; padding: 12px 14px; border: 1px dashed var(--line-strong, var(--line)); border-radius: 9px; color: var(--muted); font-size: 12px; line-height: 1.55; }
.oa-page .oa-clear::before { margin-right: 8px; color: var(--green); content: "✓"; }
.oa-page .oa-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); margin: 0; }
.oa-page .oa-summary div { padding: 15px 20px; border-left: 1px solid var(--line); }
.oa-page .oa-summary div:first-child { border-left: 0; }
.oa-page .oa-summary dt { color: var(--muted); font-size: 11px; font-weight: 650; }
.oa-page .oa-summary dd { margin: 7px 0 0; font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }
.oa-page .oa-summary small { display: block; margin-top: 4px; color: var(--quiet, var(--muted)); font-size: 11px; font-weight: 400; }
.oa-page .oa-rows { margin: 0; padding: 0 20px; list-style: none; }
.oa-page .oa-row { display: grid; grid-template-columns: minmax(145px, .6fr) minmax(0, 1.4fr) auto; gap: 16px; padding: 13px 0; border-top: 1px solid var(--line); }
.oa-page .oa-row:first-child { border-top: 0; }
.oa-page .oa-row strong { font-size: 12px; }
.oa-page .oa-row span { color: var(--muted); font-size: 12px; line-height: 1.55; }
.oa-page .oa-row code { color: var(--quiet, var(--muted)); font-size: 11px; white-space: nowrap; }
.oa-page .oa-chain { display: grid; grid-template-columns: repeat(3, 1fr); margin: 0; padding: 18px 20px; list-style: none; counter-reset: stage; }
.oa-page .oa-chain li { position: relative; min-width: 0; padding: 0 28px 0 36px; counter-increment: stage; }
.oa-page .oa-chain li + li { border-left: 1px solid var(--line); }
.oa-page .oa-chain li::before { position: absolute; top: 0; left: 10px; display: grid; width: 20px; height: 20px; place-items: center; border-radius: 50%; background: var(--accent-soft); color: var(--accent); content: counter(stage); font-size: 10px; font-weight: 700; }
.oa-page .oa-chain strong { display: block; font-size: 12px; }
.oa-page .oa-chain p { margin: 6px 0 0; color: var(--muted); font-size: 11.5px; line-height: 1.55; }
.oa-page .oa-chain b { display: block; margin-top: 7px; color: var(--green); font-size: 10px; letter-spacing: .04em; text-transform: uppercase; }
.oa-page .oa-chain .oa-human b { color: var(--amber); }
.oa-page .oa-table-wrap { overflow-x: auto; }
.oa-page .oa-table { width: 100%; border-collapse: collapse; }
.oa-page .oa-table caption { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
.oa-page .oa-table th, .oa-page .oa-table td { padding: 12px 16px; border-top: 1px solid var(--line); text-align: left; font-size: 12px; line-height: 1.5; white-space: nowrap; }
.oa-page .oa-table th { color: var(--muted); font-size: 10px; letter-spacing: .05em; text-transform: uppercase; }
.oa-page .oa-table td[data-label]::before { content: attr(data-label); display: none; }
.oa-page .oa-links { display: flex; flex-wrap: wrap; gap: 8px; }
.oa-page .oa-link { display: inline-flex; min-height: 34px; align-items: center; padding: 0 13px; border: 1px solid var(--line); border-radius: 999px; color: var(--text); font-size: 11px; font-weight: 650; text-decoration: none; }
.oa-page .oa-link:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.oa-page .oa-charts { display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px; }
.oa-page .oa-charts--single { margin-top: 4px; }
.oa-page .oa-charts--single .oa-chart-card { max-width: none; }
.oa-page .oa-overview-summary .oa-charts { margin: 18px 20px; }
.oa-page .oa-overview-summary > .oa-links { padding: 0 20px 20px; }
.oa-page .oa-chart-card { min-width: 0; overflow: hidden; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); }
.oa-page .oa-chart-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding: 17px 20px 8px; }
.oa-page .oa-chart-head h2 { margin: 0; font-size: 15px; line-height: 1.35; }
.oa-page .oa-chart-head p { margin: 4px 0 0; color: var(--muted); font-size: 11.5px; line-height: 1.5; }
.oa-page .oa-chart-total { color: var(--quiet, var(--muted)); font-size: 11px; white-space: nowrap; }
.oa-page .oa-bar-chart { display: block; width: 100%; min-height: 190px; padding: 0 12px 12px; }
.oa-page .oa-chart-grid { stroke: var(--line); stroke-width: 1; }
.oa-page .oa-axis-label { fill: var(--quiet, var(--muted)); font-size: 9px; font-family: var(--mono); }
.oa-page .oa-bar-incoming { fill: var(--accent); opacity: .86; }
.oa-page .oa-bar-decided { fill: var(--green); opacity: .78; }
.oa-page .oa-donut-body { display: grid; grid-template-columns: 132px minmax(0, 1fr); align-items: center; gap: 12px; padding: 8px 20px 20px; }
.oa-page .oa-donut { display: block; width: 132px; height: 132px; }
.oa-page .oa-donut-track { fill: none; stroke: var(--panel-soft); stroke-width: 18; }
.oa-page .oa-donut-segment { fill: none; stroke-width: 18; }
.oa-page .oa-donut-center { fill: var(--text); font-size: 17px; font-weight: 700; text-anchor: middle; }
.oa-page .oa-donut-caption { fill: var(--quiet, var(--muted)); font-size: 8px; text-anchor: middle; }
.oa-page .oa-chart-legend { display: grid; gap: 9px; margin: 0; padding: 0; list-style: none; }
.oa-page .oa-chart-legend li { display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; align-items: center; gap: 8px; color: var(--muted); font-size: 11px; }
.oa-page .oa-legend-dot { width: 8px; height: 8px; border-radius: 3px; background: var(--legend-color); }
.oa-page .oa-chart-legend strong { color: var(--text); font-size: 11px; font-variant-numeric: tabular-nums; }
.oa-page .oa-chart-empty { display: grid; min-height: 180px; place-items: center; padding: 20px; color: var(--muted); font-size: 12px; }
@media (max-width: 720px) {
  .oa-page .oa-section-head { display: grid; gap: 5px; }
  .oa-page .oa-alert, .oa-page .oa-row { grid-template-columns: minmax(0, 1fr); }
  .oa-page .oa-alert::before { display: none; }
  .oa-page .oa-alert p { grid-column: 1; }
  .oa-page .oa-summary { grid-template-columns: 1fr; }
  .oa-page .oa-summary div { border-top: 1px solid var(--line); border-left: 0; }
  .oa-page .oa-summary div:first-child { border-top: 0; }
  .oa-page .oa-chain { grid-template-columns: 1fr; gap: 16px; }
  .oa-page .oa-chain li + li { padding-top: 16px; border-top: 1px solid var(--line); border-left: 0; }
  .oa-page .oa-chain li + li::before { top: 16px; }
  .oa-page .oa-charts { grid-template-columns: 1fr; }
  .oa-page .oa-donut-body { grid-template-columns: 116px minmax(0, 1fr); }
  .oa-page .oa-donut { width: 116px; height: 116px; }
  .oa-page .oa-table-wrap { overflow: visible; }
  .oa-page .oa-table { width: 100%; min-width: 0; border-spacing: 0; }
  .oa-page .oa-table thead { position: absolute; width: 1px; height: 1px; margin: -1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
  .oa-page .oa-table tbody { display: grid; gap: 10px; }
  .oa-page .oa-table tr { display: grid; gap: 0; padding: 12px 14px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); }
  .oa-page .oa-table td { display: grid; grid-template-columns: minmax(92px, 38%) minmax(0, 1fr); gap: 10px; padding: 8px 0; border-top: 0; white-space: normal; }
  .oa-page .oa-table td[data-label]::before { display: block; content: attr(data-label); color: var(--muted); font-size: 10px; font-weight: 650; letter-spacing: .04em; text-transform: uppercase; }
  .oa-page .oa-table td[colspan] { display: block; padding: 8px 0; }
  .oa-page .oa-table td[colspan]::before { content: none; }
  .oa-page .oa-table td:first-child { padding-top: 0; }
  .oa-page .oa-table td:last-child { padding-bottom: 0; }
}
"""

OVERVIEW_AGENTS_CSS = CSS


def _plain(value: object) -> object:
    return asdict(value) if is_dataclass(value) and not isinstance(value, type) else value


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


def _section(identifier: str, title: str, description: str, body: str, extra_class: str = "") -> str:
    return (
        f'<section class="oa-section {extra_class}" aria-labelledby="{identifier}">'
        f'<header class="oa-section-head"><h2 id="{identifier}">{escape(title)}</h2>'
        f'<p>{escape(description)}</p></header>{body}</section>'
    )


def _attention(data: Mapping[str, object]) -> str:
    items = _sequence(data.get("exceptions") or data.get("attention"))
    if not items:
        return '<p class="oa-clear" role="status">没有需要人工接手的异常。<span class="sr-only">没有需要人工关注的异常</span></p>'
    rows: list[str] = []
    for raw in items:
        item = _mapping(raw)
        title = escape(_text(item.get("title") or item.get("label"), "未命名异常"))
        detail = escape(_text(item.get("detail") or item.get("message")))
        meta = escape(_text(item.get("meta") or item.get("value")))
        rows.append(
            f'<li class="oa-alert" data-tone="{_tone(item.get("tone"))}"><strong>{title}</strong>'
            f'{f"<p>{detail}</p>" if detail else ""}{f"<code>{meta}</code>" if meta else ""}</li>'
        )
    return f'<ul class="oa-list">{"".join(rows)}</ul>'


def _metrics(value: object, empty_message: str) -> str:
    items = _sequence(value)
    if not items:
        return f'<p class="oa-missing">{escape(empty_message)}</p>'
    entries: list[str] = []
    for raw in items:
        item = _mapping(raw)
        entries.append(
            f'<div><dt>{escape(_text(item.get("label"), "指标"))}</dt>'
            f'<dd>{escape(_text(item.get("value"), "—"))}'
            f'<small>{escape(_text(item.get("detail")))}</small></dd></div>'
        )
    return f'<dl class="oa-summary" aria-label="关键指标">{"".join(entries)}</dl>'


def _records(value: object, empty_message: str) -> str:
    items = _sequence(value)
    if not items:
        return f'<p class="oa-missing">{escape(empty_message)}</p>'
    rows: list[str] = []
    for raw in items:
        item = _mapping(raw)
        rows.append(
            '<li class="oa-row">'
            f'<strong>{escape(_text(item.get("title") or item.get("name") or item.get("label"), "—"))}</strong>'
            f'<span>{escape(_text(item.get("detail") or item.get("description") or item.get("status")))}</span>'
            f'<code>{escape(_text(item.get("meta") or item.get("value") or item.get("version")))}</code></li>'
        )
    return f'<ul class="oa-rows">{"".join(rows)}</ul>'


def _table(value: object, empty_message: str) -> str:
    table = _mapping(value)
    columns = tuple(_text(column) for column in _sequence(table.get("columns")))
    if not columns:
        return f'<p class="oa-missing">{escape(empty_message)}</p>'
    headers = "".join(f'<th scope="col">{escape(column)}</th>' for column in columns)
    rows: list[str] = []
    for raw_row in _sequence(table.get("rows")):
        row = _sequence(raw_row)
        cells = "".join(
            f'<td data-label="{escape(columns[index])}">{escape(_text(row[index])) if index < len(row) else ""}</td>'
            for index in range(len(columns))
        )
        rows.append(f'<tr>{cells}</tr>')
    body = "".join(rows) or f'<tr><td colspan="{len(columns)}">{escape(_text(table.get("empty_message"), empty_message))}</td></tr>'
    return (
        '<div class="oa-table-wrap"><table class="oa-table"><caption>AI 任务阶段明细</caption>'
        f'<thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>'
    )


def _integer(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _overview_charts(data: Mapping[str, object]) -> str:
    series = [_mapping(item) for item in _sequence(data.get("volume_series"))]
    if not series:
        return ""

    values = [max(_integer(item.get("incoming")), _integer(item.get("decided"))) for item in series]
    maximum = max(values, default=0)
    scale_max = max(1, maximum)
    plot_left, plot_top, plot_width, plot_height = 38, 18, 500, 126
    slot = plot_width / max(1, len(series))
    bar_width = max(4.0, min(11.0, slot * .27))
    grid = []
    for index, ratio in enumerate((0.0, .5, 1.0)):
        y = plot_top + plot_height * ratio
        label = round(scale_max * (1 - ratio))
        grid.append(
            f'<line class="oa-chart-grid" x1="{plot_left}" y1="{y:.1f}" x2="{plot_left + plot_width}" y2="{y:.1f}"/>'
            f'<text class="oa-axis-label" x="{plot_left - 7}" y="{y + 3:.1f}" text-anchor="end">{label}</text>'
        )
    bars: list[str] = []
    labels: list[str] = []
    for index, item in enumerate(series):
        incoming = _integer(item.get("incoming"))
        decided = _integer(item.get("decided"))
        center = plot_left + slot * index + slot / 2
        incoming_height = plot_height * incoming / scale_max
        decided_height = plot_height * decided / scale_max
        bars.append(
            f'<rect class="oa-bar-incoming" x="{center - bar_width - 1:.1f}" y="{plot_top + plot_height - incoming_height:.1f}" '
            f'width="{bar_width:.1f}" height="{incoming_height:.1f}" rx="2"><title>{escape(_text(item.get("label")))}：模型处理 {incoming}</title></rect>'
            f'<rect class="oa-bar-decided" x="{center + 1:.1f}" y="{plot_top + plot_height - decided_height:.1f}" '
            f'width="{bar_width:.1f}" height="{decided_height:.1f}" rx="2"><title>{escape(_text(item.get("label")))}：完成判定 {decided}</title></rect>'
        )
        if index % 2 == 0 or index == len(series) - 1:
            labels.append(
                f'<text class="oa-axis-label" x="{center:.1f}" y="162" text-anchor="middle">{escape(_text(item.get("label")))}</text>'
            )
    total_incoming = sum(_integer(item.get("incoming")) for item in series)
    total_decided = sum(_integer(item.get("decided")) for item in series)
    chart = (
        '<section class="oa-chart-card" aria-labelledby="oa-volume-title">'
        '<header class="oa-chart-head"><div><h2 id="oa-volume-title">处理趋势</h2>'
        '<p>最近 14 天模型处理量与人工结论量。</p></div>'
        f'<span class="oa-chart-total">模型 {total_incoming} · 人工 {total_decided}</span></header>'
        '<svg class="oa-bar-chart" viewBox="0 0 560 178" role="img" aria-label="最近十四天审核处理趋势">'
        + "".join(grid + bars + labels)
        + '</svg></section>'
    )
    return f'<div class="oa-charts oa-charts--single">{chart}</div>'


def render_overview_body(data: Mapping[str, object] | None = None) -> str:
    """Render the overview body, with exceptions before compact supporting facts."""
    page_data = _mapping(data)
    return (
        '<div class="oa-page oa-overview">'
        + _section(
            "oa-overview-attention",
            "人工关注摘要",
            "只看需要接手的异常、积压与波动；正常吞吐继续交给 AI Agent。",
            _attention(page_data)
            + _metrics(page_data.get("metrics"), "未提供概览指标。")
            + _overview_charts(page_data)
            + '<nav class="oa-links" aria-label="概览快捷入口"><a class="oa-link" href="/review">打开审核队列</a><a class="oa-link" href="/review/history">查看审计历史</a></nav>',
            "oa-attention oa-overview-summary",
        )
        + _section("oa-overview-pipeline", "流水线动态", "按阶段查看正在积压或需要跟进的链路。", _records(page_data.get("pipeline"), "未提供阶段积压或延迟信息。"))
        + '</div>'
    )


def render_agents_body(data: Mapping[str, object] | None = None) -> str:
    """Render the AI-task body and its automatic escalation chain."""
    page_data = _mapping(data)
    chain = (
        '<ol class="oa-chain" aria-label="自动审核升级链">'
        '<li><strong>自动审核</strong><p>基础模型先完成常规识别、规则校验与明确决策。</p><b>自动执行</b></li>'
        '<li><strong>高级视觉模型</strong><p>基础阶段不确定时自动升级，以更强视觉理解复核。</p><b>自动升级</b></li>'
        '<li class="oa-human"><strong>人工最终复核</strong><p>仅高级视觉模型仍无法确定的项目进入人工队列。</p><b>最终不确定项</b></li>'
        '</ol>'
    )
    return (
        '<div class="oa-page oa-agents">'
        + _section("oa-agents-attention", "阻塞与失败", "先处理失败 attempt、异常重试和最终人工兜底。", _attention(page_data), "oa-attention")
        + _section("oa-agents-chain", "自动审核链", "常规任务由 AI 闭环，人工只接收最后仍不确定的项目。", chain)
        + _section("oa-agents-metrics", "任务信号", "展示后端传入的任务指标。", _metrics(page_data.get("metrics"), "未提供 AI 任务指标。"))
        + _section("oa-agents-detail", "阶段明细", "重试应生成新的 attempt；本页不伪造阶段状态。", _table(page_data.get("agents"), "未提供 AI 任务分阶段明细。"))
        + '<nav class="oa-links" aria-label="AI 任务快捷入口"><a class="oa-link" href="/review">回到审核队列</a></nav>'
        + '</div>'
    )


def render_page_body(page: str, data: Mapping[str, object] | None = None) -> str:
    """Dispatch an overview or agents body for integration by the main renderer."""
    if page == "overview":
        return render_overview_body(data)
    if page == "agents":
        return render_agents_body(data)
    raise ValueError(f"unsupported overview/agents page: {page}")


__all__ = ["CSS", "OVERVIEW_AGENTS_CSS", "render_agents_body", "render_overview_body", "render_page_body"]
