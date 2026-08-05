"""Dedicated fragments for the audit-history and system-health pages.

The history view is an event stream with filters.  The health view is a
pipeline/status view with component impact cards.  They intentionally do not
share a generic table renderer because the two pages answer different
questions.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Mapping, Sequence
from urllib.parse import quote

from wy_api.icons import icon


CSS = """
.audit-workspace,
.health-workspace { display: grid; gap: 16px; }
.audit-filters {
  display: grid;
  grid-template-columns: minmax(240px, 1.5fr) repeat(3, minmax(132px, .65fr)) auto auto;
  gap: 8px;
  align-items: center;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-soft);
}
.audit-filter { position: relative; display: flex; min-width: 0; align-items: center; }
.audit-filter-search .icon {
  position: absolute;
  left: 11px;
  width: 15px;
  height: 15px;
  color: var(--quiet);
  pointer-events: none;
}
.audit-filter input,
.audit-filter select {
  width: 100%;
  height: 36px;
  min-height: 36px;
  padding: 0 11px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  background: var(--panel);
  color: var(--text);
  font-size: 12px;
  line-height: normal;
}
.audit-filter-search input { padding-left: 34px; }
.audit-filter-select select {
  padding-right: 34px;
  appearance: none;
  -webkit-appearance: none;
}
.audit-filter input:focus-visible,
.audit-filter select:focus-visible,
.audit-apply:focus-visible,
.audit-reset:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.audit-apply,
.audit-reset {
  display: inline-flex;
  min-height: 36px;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 0 11px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  background: var(--panel);
  color: var(--text);
  font-size: 12px;
  font-weight: 650;
  text-decoration: none;
  white-space: nowrap;
}
.audit-apply { border-color: var(--accent); background: var(--accent); color: #fff; cursor: pointer; }
.audit-reset { color: var(--muted); }
.audit-apply .icon,
.audit-reset .icon { width: 14px; height: 14px; }
.audit-list-meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.audit-results { margin: 0; color: var(--muted); font-size: 12px; }
.audit-pagination { display: flex; align-items: center; gap: 6px; }
.audit-pagination a,
.audit-pagination span {
  display: inline-flex;
  min-height: 30px;
  align-items: center;
  gap: 4px;
  padding: 0 9px;
  border: 1px solid var(--line);
  border-radius: 7px;
  color: var(--muted);
  font-size: 11px;
  text-decoration: none;
}
.audit-pagination .icon { width: 13px; height: 13px; }
.audit-list { overflow: hidden; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); }
.audit-list-head,
.audit-event {
  display: grid;
  grid-template-columns: 142px 92px 170px minmax(150px, .8fr) minmax(220px, 1.3fr);
  gap: 14px;
  align-items: center;
}
.audit-list-head {
  min-height: 38px;
  padding: 0 14px;
  border-bottom: 1px solid var(--line);
  background: var(--panel-soft);
  color: var(--quiet);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .04em;
}
.audit-timeline { display: grid; margin: 0; padding: 0; list-style: none; }
.audit-event {
  min-height: 58px;
  padding: 9px 14px;
  border-bottom: 1px solid var(--line);
}
.audit-event:last-child { border-bottom: 0; }
.audit-event:hover { background: var(--panel-soft); }
.audit-time { color: var(--quiet); font-family: var(--mono); font-size: 10px; white-space: nowrap; }
.audit-action {
  display: inline-flex;
  width: fit-content;
  min-height: 24px;
  align-items: center;
  padding: 0 8px;
  border-radius: 6px;
  background: var(--panel-soft);
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
}
.audit-action[data-tone="success"] { background: var(--green-soft); color: var(--green); }
.audit-action[data-tone="warning"] { background: var(--amber-soft); color: var(--amber); }
.audit-action[data-tone="danger"] { background: var(--red-soft); color: var(--red); }
.audit-action[data-tone="info"] { background: var(--accent-soft); color: var(--accent); }
.audit-context { display: grid; min-width: 0; gap: 2px; }
.audit-context strong { overflow: hidden; color: var(--text); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.audit-context small { overflow: hidden; color: var(--quiet); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.audit-object { overflow: hidden; color: var(--muted); font-family: var(--mono); font-size: 10px; text-decoration: none; text-overflow: ellipsis; white-space: nowrap; }
.audit-object:hover { color: var(--accent); }
.audit-event-detail { margin: 0; overflow: hidden; color: var(--muted); font-size: 11px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }
.audit-empty,
.health-empty {
  padding: 18px;
  border: 1px dashed var(--line-strong);
  border-radius: 11px;
  background: var(--panel-soft);
  color: var(--muted);
  font-size: 12px;
}
.health-summary {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel-soft);
}
.health-summary-copy { display: grid; gap: 5px; }
.health-summary-copy strong { font-size: 14px; }
.health-summary-copy span { color: var(--muted); font-size: 12px; line-height: 1.55; }
.health-state,
.pipeline-state,
.component-state {
  display: inline-flex;
  width: fit-content;
  min-height: 25px;
  align-items: center;
  padding: 0 9px;
  border-radius: 999px;
  background: var(--panel);
  color: var(--muted);
  font-size: 10px;
  font-weight: 700;
}
[data-tone="success"] > .health-state,
[data-tone="success"] .pipeline-state,
[data-tone="success"] .component-state { background: var(--green-soft); color: var(--green); }
[data-tone="warning"] > .health-state,
[data-tone="warning"] .pipeline-state,
[data-tone="warning"] .component-state { background: var(--amber-soft); color: var(--amber); }
[data-tone="danger"] > .health-state,
[data-tone="danger"] .pipeline-state,
[data-tone="danger"] .component-state { background: var(--red-soft); color: var(--red); }
[data-tone="info"] > .health-state,
[data-tone="info"] .pipeline-state,
[data-tone="info"] .component-state { background: var(--accent-soft); color: var(--accent); }
.health-region { display: grid; gap: 12px; }
.health-region h3 { margin: 0; font-size: 13px; }
.health-pipeline {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.pipeline-stage {
  position: relative;
  display: grid;
  align-content: start;
  gap: 9px;
  min-height: 126px;
  padding: 15px;
  border: 1px solid var(--line);
  border-top: 3px solid var(--line-strong);
  border-radius: 10px;
  background: var(--panel);
}
.pipeline-stage[data-tone="success"] { border-top-color: var(--green); }
.pipeline-stage[data-tone="warning"] { border-top-color: var(--amber); }
.pipeline-stage[data-tone="danger"] { border-top-color: var(--red); }
.pipeline-stage[data-tone="info"] { border-top-color: var(--accent); }
.pipeline-order { color: var(--quiet); font-family: var(--mono); font-size: 10px; }
.pipeline-stage strong { font-size: 12px; overflow-wrap: anywhere; }
.pipeline-detail { margin: 0; color: var(--muted); font-size: 11px; line-height: 1.55; }
.component-impact-list { display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }
.component-impact {
  display: grid;
  grid-template-columns: minmax(150px, .65fr) minmax(0, 1.35fr);
  gap: 16px;
  padding: 15px 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel);
}
.component-title { display: grid; align-content: start; gap: 8px; }
.component-title strong { font-size: 12px; overflow-wrap: anywhere; }
.component-impact-copy { display: grid; gap: 6px; }
.component-impact-copy p { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.55; }
.component-impact-copy dl { display: grid; grid-template-columns: auto 1fr; gap: 4px 10px; margin: 0; }
.component-impact-copy dt { color: var(--quiet); font-size: 10px; font-weight: 700; }
.component-impact-copy dd { margin: 0; color: var(--text); font-size: 11px; overflow-wrap: anywhere; }
/* Above the mobile breakpoint the shell can still reserve a 220px rail.
   Wrap the filter controls before that reduced content width clips the
   selects or pushes the reset action outside the workspace. */
@media (min-width: 761px) and (max-width: 1180px) {
  .audit-filters {
    grid-template-columns: repeat(3, minmax(132px, 1fr)) auto auto;
  }
  .audit-filter-search { grid-column: 1 / -1; }
}
@media (max-width: 760px) {
  .audit-filters { grid-template-columns: 1fr 1fr; }
  .audit-filter-search { grid-column: 1 / -1; }
  .audit-filter-select:last-of-type { grid-column: 1 / -1; }
  .audit-list-meta { align-items: flex-start; flex-direction: column; }
  .audit-list-head { display: none; }
  .audit-event { grid-template-columns: 1fr auto; gap: 6px 10px; }
  .audit-time { grid-column: 1; }
  .audit-action { grid-column: 2; grid-row: 1; }
  .audit-context,
  .audit-object,
  .audit-event-detail { grid-column: 1 / -1; }
  .health-summary { display: grid; }
  .component-impact { grid-template-columns: 1fr; }
}
"""

PAGE_CSS = CSS
PAGE_HISTORY_HEALTH_CSS = CSS


def _require_mapping(data: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise TypeError("page data must be a Mapping")
    return data


def _text(value: object, default: str = "") -> str:
    return default if value is None else str(value)


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _tone(value: object) -> str:
    state = _text(value).strip().lower()
    if state in {
        "ready",
        "healthy",
        "ok",
        "success",
        "succeeded",
        "complete",
        "completed",
        "passed",
    }:
        return "success"
    if state in {
        "blocked",
        "down",
        "failed",
        "failure",
        "error",
        "danger",
        "unhealthy",
    }:
        return "danger"
    if state in {"warning", "degraded", "delayed", "stalled", "held"}:
        return "warning"
    if state in {"info", "running", "active", "processing", "queued"}:
        return "info"
    return "quiet"


def _options(values: object, selected: object, all_label: str) -> str:
    selected_text = _text(selected)
    rendered = [f'<option value="">{escape(all_label)}</option>']
    for raw in _sequence(values):
        value = _text(raw)
        chosen = " selected" if value == selected_text else ""
        rendered.append(
            f'<option value="{escape(value)}"{chosen}>{escape(value)}</option>'
        )
    return "".join(rendered)


_ACTION_LABELS = {
    "route": "自动路由",
    "approve": "人工通过",
    "reject": "人工拒绝",
    "blacklist": "加入黑名单",
    "hold": "留置复核",
    "retry": "重新执行",
    "submit": "提交任务",
}

_STAGE_LABELS = {
    "fast_scan": "快速扫描",
    "vision_review_1": "视觉一审",
    "vision_review_2": "视觉二审",
    "human_required": "等待人工",
    "auto_approved": "自动通过",
    "auto_rejected": "自动拒绝",
    "model_error": "模型异常",
}


def _format_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _pagination(data: object) -> str:
    if not isinstance(data, Mapping):
        return ""
    previous_url = _text(data.get("previous_url"))
    next_url = _text(data.get("next_url"))
    current = max(1, int(data.get("page", 1) or 1))
    total_pages = max(1, int(data.get("total_pages", 1) or 1))
    previous = (
        f'<a href="{escape(previous_url)}">{icon("arrow-left")}上一页</a>'
        if previous_url
        else ""
    )
    following = (
        f'<a href="{escape(next_url)}">下一页{icon("arrow-right")}</a>'
        if next_url
        else ""
    )
    return (
        '<nav class="audit-pagination" aria-label="审计历史分页">'
        f"{previous}<span>{current} / {total_pages}</span>{following}</nav>"
    )


def _history_events(value: object) -> list[Mapping[str, object]]:
    if isinstance(value, Mapping):
        columns = [
            _text(column).strip().lower() for column in _sequence(value.get("columns"))
        ]
        events: list[Mapping[str, object]] = []
        for raw_row in _sequence(value.get("rows")):
            row = _sequence(raw_row)
            by_column = {
                columns[index]: cell
                for index, cell in enumerate(row)
                if index < len(columns)
            }
            events.append(
                {
                    "created_at": by_column.get("时间", row[0] if len(row) > 0 else ""),
                    "item_id": by_column.get("对象", row[1] if len(row) > 1 else ""),
                    "actor": by_column.get("actor", row[2] if len(row) > 2 else ""),
                    "action": by_column.get("动作", row[3] if len(row) > 3 else "事件"),
                    "stage": by_column.get("阶段", row[4] if len(row) > 4 else ""),
                    "detail": by_column.get("原因", row[5] if len(row) > 5 else ""),
                }
            )
        return events
    return [item for item in _sequence(value) if isinstance(item, Mapping)]


def render_history_content(data: Mapping[str, object]) -> str:
    """Render an accessible audit filter bar and append-only event stream."""
    page = _require_mapping(data)
    filters = page.get("filters") if isinstance(page.get("filters"), Mapping) else {}
    assert isinstance(filters, Mapping)
    query = _text(filters.get("query") or filters.get("q"))
    actor = filters.get("actor")
    action = filters.get("action") or filters.get("type")
    stage = filters.get("stage")
    actors = page.get("actors") or filters.get("actors") or ()
    actions = (
        page.get("actions") or page.get("event_types") or filters.get("actions") or ()
    )
    stages = page.get("stages") or filters.get("stages") or ()
    events = _history_events(page.get("events"))
    pagination = _pagination(page.get("pagination"))
    total = int(page.get("total", len(events)) or 0)
    start = int(page.get("start", 1 if events else 0) or 0)
    end = int(page.get("end", start + len(events) - 1 if events else 0) or 0)

    filter_html = (
        '<form class="audit-filters" role="search" method="get" aria-label="筛选审计历史">'
        '<label class="audit-filter audit-filter-search">'
        f'{icon("search")}<span class="sr-only">搜索对象、原因或事件</span>'
        f'<input type="search" name="q" value="{escape(query)}" autocomplete="off" placeholder="搜索对象、原因或事件"></label>'
        '<label class="audit-filter audit-filter-select select-control"><span class="sr-only">执行者</span><select name="actor" aria-label="执行者">'
        f"{_options(actors, actor, '全部执行者')}</select><span class=\"select-control__icon\" aria-hidden=\"true\">{icon('chevron-down')}</span></label>"
        '<label class="audit-filter audit-filter-select select-control"><span class="sr-only">事件类型</span><select name="action" aria-label="事件类型">'
        f"{_options(actions, action, '全部事件')}</select><span class=\"select-control__icon\" aria-hidden=\"true\">{icon('chevron-down')}</span></label>"
        '<label class="audit-filter audit-filter-select select-control"><span class="sr-only">流水线阶段</span><select name="stage" aria-label="流水线阶段">'
        f"{_options(stages, stage, '全部阶段')}</select><span class=\"select-control__icon\" aria-hidden=\"true\">{icon('chevron-down')}</span></label>"
        f'<button class="audit-apply" type="submit">{icon("search")}筛选</button>'
        f'<a class="audit-reset" href="/review/history">{icon("x")}清除</a></form>'
    )

    rendered: list[str] = []
    for event in events:
        timestamp = _text(
            event.get("created_at") or event.get("timestamp") or event.get("time"),
            "时间未知",
        )
        action_text = _text(
            event.get("action") or event.get("type") or event.get("title"), "未命名事件"
        )
        actor_text = _text(
            event.get("actor") or event.get("actor_id") or event.get("reviewer"),
            "system",
        )
        stage_text = _text(event.get("stage") or event.get("after_stage"))
        object_text = _text(
            event.get("item_id") or event.get("object_id") or event.get("subject")
        )
        detail = _text(
            event.get("detail")
            or event.get("reason")
            or event.get("reason_code")
            or event.get("note")
        )
        tone = _tone(event.get("tone") or event.get("status") or action_text)
        action_label = _ACTION_LABELS.get(action_text, action_text)
        stage_label = _STAGE_LABELS.get(stage_text, stage_text or "未记录阶段")
        object_html = (
            f'<a class="audit-object" title="{escape(object_text)}" '
            f'href="/review?status=all&amp;risk=all&amp;view=focus&amp;focus={quote(object_text)}">'
            f"{escape(object_text)}</a>"
            if object_text
            else '<span class="audit-object">—</span>'
        )
        detail_html = (
            f'<p class="audit-event-detail" title="{escape(detail)}">{escape(detail)}</p>'
            if detail
            else '<p class="audit-event-detail">—</p>'
        )
        rendered.append(
            f'<li class="audit-event" data-tone="{tone}">'
            f'<time class="audit-time" datetime="{escape(timestamp)}">{escape(_format_timestamp(timestamp))}</time>'
            f'<span class="audit-action" data-tone="{tone}" title="{escape(action_text)}">{escape(action_label)}</span>'
            f'<span class="audit-context"><strong>{escape(actor_text)}</strong><small>{escape(stage_label)}</small></span>'
            f"{object_html}{detail_html}</li>"
        )
    stream = (
        '<div class="audit-list">'
        '<div class="audit-list-head" aria-hidden="true"><span>时间</span><span>事件</span><span>执行者 / 阶段</span><span>对象</span><span>原因</span></div>'
        f'<ol class="audit-timeline" aria-label="审计事件流">{"".join(rendered)}</ol></div>'
        if rendered
        else '<p class="audit-empty" role="status">没有符合当前筛选条件的审计事件。</p>'
    )
    return (
        '<section class="audit-workspace" aria-labelledby="audit-stream-title">'
        f'{filter_html}<div class="audit-list-meta"><p class="audit-results" role="status">'
        f"共 {total} 条事件，显示 {start}–{end}</p>{pagination}</div>"
        '<h3 class="sr-only" id="audit-stream-title">事件流</h3>'
        f"{stream}</section>"
    )


def _health_items(value: object) -> list[Mapping[str, object]]:
    if isinstance(value, Mapping):
        columns = [
            _text(column).strip().lower() for column in _sequence(value.get("columns"))
        ]
        items: list[Mapping[str, object]] = []
        for raw_row in _sequence(value.get("rows")):
            row = _sequence(raw_row)
            by_column = {
                columns[index]: cell
                for index, cell in enumerate(row)
                if index < len(columns)
            }
            items.append(
                {
                    "name": by_column.get("组件", row[0] if len(row) > 0 else ""),
                    "status": by_column.get(
                        "状态", row[1] if len(row) > 1 else "unknown"
                    ),
                    "detail": by_column.get("说明", row[2] if len(row) > 2 else ""),
                    "impact": by_column.get(
                        "影响", row[3] if len(row) > 3 else "未报告用户影响"
                    ),
                }
            )
        return items
    return [item for item in _sequence(value) if isinstance(item, Mapping)]


def render_health_content(data: Mapping[str, object]) -> str:
    """Render pipeline state and component impact without a tabular layout."""
    page = _require_mapping(data)
    raw_pipeline = page.get("pipeline")
    pipeline_meta = raw_pipeline if isinstance(raw_pipeline, Mapping) else {}
    assert isinstance(pipeline_meta, Mapping)
    stages_value = pipeline_meta.get("stages") if pipeline_meta else raw_pipeline
    if stages_value is None:
        stages_value = page.get("stages")
    stages = _health_items(stages_value)
    components = _health_items(page.get("components") or page.get("services"))
    overall = _text(page.get("status") or pipeline_meta.get("status"), "unknown")
    summary = _text(
        page.get("summary") or pipeline_meta.get("summary"), "未提供流水线整体说明。"
    )
    overall_tone = _tone(overall)
    metrics_state = (
        ""
        if page.get("metrics")
        else '<p class="health-empty" role="status">未提供系统健康指标。</p>'
    )

    rendered_stages: list[str] = []
    for index, stage in enumerate(stages, start=1):
        name = _text(
            stage.get("name") or stage.get("title") or stage.get("stage"), "未命名阶段"
        )
        state = _text(stage.get("status") or stage.get("state"), "unknown")
        detail = _text(
            stage.get("detail") or stage.get("description") or stage.get("impact")
        )
        tone = _tone(stage.get("tone") or state)
        detail_html = (
            f'<p class="pipeline-detail">{escape(detail)}</p>' if detail else ""
        )
        rendered_stages.append(
            f'<li class="pipeline-stage" data-tone="{tone}">'
            f'<span class="pipeline-order">{index:02d}</span><strong>{escape(name)}</strong>'
            f'<span class="pipeline-state">{escape(state)}</span>'
            f"{detail_html}</li>"
        )
    pipeline_html = (
        f'<ol class="health-pipeline" aria-label="流水线阶段状态">{"".join(rendered_stages)}</ol>'
        if rendered_stages
        else '<p class="health-empty" role="status">未提供流水线阶段状态。</p>'
    )

    rendered_components: list[str] = []
    for component in components:
        name = _text(
            component.get("name")
            or component.get("component")
            or component.get("title"),
            "未命名组件",
        )
        state = _text(component.get("status") or component.get("state"), "unknown")
        detail = _text(component.get("detail") or component.get("description"))
        impact = _text(
            component.get("impact") or component.get("user_impact"), "未报告用户影响"
        )
        dependency = _text(
            component.get("dependency") or component.get("dependencies"), "—"
        )
        tone = _tone(component.get("tone") or state)
        rendered_components.append(
            f'<li class="component-impact" data-tone="{tone}">'
            f'<div class="component-title"><strong>{escape(name)}</strong>'
            f'<span class="component-state">{escape(state)}</span></div>'
            '<div class="component-impact-copy">'
            f"{f'<p>{escape(detail)}</p>' if detail else ''}"
            "<dl><dt>用户影响</dt>"
            f"<dd>{escape(impact)}</dd><dt>依赖范围</dt><dd>{escape(dependency)}</dd></dl>"
            "</div></li>"
        )
    component_html = (
        f'<ul class="component-impact-list" aria-label="组件影响">{"".join(rendered_components)}</ul>'
        if rendered_components
        else '<p class="health-empty" role="status">未提供组件状态与影响范围。</p>'
    )

    return (
        '<section class="health-workspace" aria-labelledby="pipeline-health-title">'
        f"{metrics_state}"
        f'<div class="health-summary" data-tone="{overall_tone}" role="status">'
        '<div class="health-summary-copy"><strong id="pipeline-health-title">流水线状态</strong>'
        f'<span>{escape(summary)}</span></div><span class="health-state">{escape(overall)}</span></div>'
        f'<section class="health-region" aria-labelledby="pipeline-stages-title"><h3 id="pipeline-stages-title">阶段状态</h3>{pipeline_html}</section>'
        f'<section class="health-region" aria-labelledby="component-impact-title"><h3 id="component-impact-title">组件影响</h3>{component_html}</section>'
        "</section>"
    )


# Short aliases keep integration call sites readable.
render_history = render_history_content
render_health = render_health_content
render_history_body = render_history_content
render_health_body = render_health_content


__all__ = [
    "CSS",
    "PAGE_CSS",
    "PAGE_HISTORY_HEALTH_CSS",
    "render_history",
    "render_history_body",
    "render_history_content",
    "render_health",
    "render_health_body",
    "render_health_content",
]
