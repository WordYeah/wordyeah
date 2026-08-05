"""Page-specific bodies for policy governance and quality review.

The renderers deliberately return fragments rather than complete documents.  A
caller can place them inside the shared review shell and append ``CSS`` to the
shell stylesheet.  All values supplied by callers are treated as display text.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from html import escape
from typing import Mapping, Sequence


CSS = r"""
/* Policy ledger: dense configuration reading, refined Windsor card layout. */
.pq-policy-ledger, .pq-quality-sheet { color: var(--text); }
.pq-policy-ledger *, .pq-quality-sheet * { box-sizing: border-box; }
.pq-ledger-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; padding: 4px 0 22px; border-bottom: 2px solid var(--line); }
.pq-eyebrow { margin: 0 0 6px; color: var(--accent); font-size: 11px; font-weight: 650; letter-spacing: 0.05em; text-transform: uppercase; }
.pq-ledger-head h2, .pq-quality-title h2 { margin: 0; font-size: 22px; font-weight: 650; line-height: 1.35; letter-spacing: normal; }
.pq-ledger-head p, .pq-quality-title p { max-width: 68ch; margin: 6px 0 0; color: var(--muted); font-size: 13px; line-height: 1.6; }
.pq-version-stamp { padding: 10px 16px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel-soft); text-align: right; }
.pq-version-stamp span { display: block; color: var(--quiet); font-size: 11px; }
.pq-version-stamp strong { font-family: var(--mono); font-size: 14px; font-weight: 650; color: var(--accent); }
.pq-policy-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 20px; margin-top: 22px; }
.pq-policy-grid > section { padding: 18px 20px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); }
.pq-section-kicker { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; padding-bottom: 10px; border-bottom: 1px solid var(--line); }
.pq-section-kicker h3 { margin: 0; font-size: 14px; font-weight: 650; }
.pq-section-kicker span { color: var(--quiet); font-size: 11px; background: var(--panel-soft); padding: 2px 8px; border-radius: 6px; }

.pq-threshold-list { display: grid; gap: 10px; margin: 0; }
.pq-threshold { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel-soft); }
.pq-threshold-info { display: flex; flex-direction: column; gap: 3px; }
.pq-threshold dt { font-size: 13px; font-weight: 650; margin: 0; color: var(--text); }
.pq-threshold small { color: var(--muted); font-size: 11.5px; line-height: 1.4; }
.pq-threshold dd { margin: 0; font-family: var(--mono); font-size: 14px; font-weight: 700; color: var(--accent); white-space: nowrap; background: var(--panel); padding: 4px 10px; border-radius: 6px; border: 1px solid var(--line); }

.pq-route { display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }
.pq-route li { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel-soft); }
.pq-route-info { display: flex; flex-direction: column; gap: 3px; }
.pq-route strong { font-size: 13px; font-weight: 650; color: var(--text); }
.pq-route span { color: var(--muted); font-size: 11.5px; line-height: 1.4; }
.pq-route code { font-family: var(--mono); font-size: 11.5px; font-weight: 600; padding: 4px 9px; border-radius: 6px; background: var(--accent-soft); color: var(--accent); white-space: nowrap; border: 1px solid rgba(99, 102, 241, 0.15); }

.pq-release-log { margin-top: 22px; padding: 18px 20px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); }
.pq-release-log ol { margin: 0; padding: 0; list-style: none; display: grid; gap: 8px; }
.pq-release { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 12px 16px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel-soft); }
.pq-release time { font-family: var(--mono); font-size: 11px; color: var(--quiet); white-space: nowrap; }
.pq-release code { font-family: var(--mono); font-size: 11.5px; font-weight: 700; color: var(--text); padding: 3px 8px; border-radius: 5px; background: var(--panel); border: 1px solid var(--line); }
.pq-release p { margin: 0; color: var(--muted); font-size: 12.5px; flex: 1; }

/* Quality sheet: refined worksheet with rich evidence cards */
.pq-quality-sheet { display: grid; grid-template-columns: minmax(0, 1fr) minmax(260px, 320px); gap: 20px 24px; }
.pq-quality-title { grid-column: 1 / -1; padding-bottom: 18px; border-bottom: 1px solid var(--line); }
.pq-batch-nav { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.pq-batch-nav a { display: inline-flex; align-items: center; gap: 7px; padding: 6px 12px; border: 1px solid var(--line); border-radius: 999px; background: var(--panel); color: var(--muted); font-size: 11px; font-weight: 650; text-decoration: none; transition: all 140ms ease; }
.pq-batch-nav a[aria-current="page"] { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.pq-batch-nav span { font-family: var(--mono); font-weight: 600; }

.pq-sample-band { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 10px; }
.pq-sample-stat { padding: 16px 18px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); }
.pq-sample-stat span { display: block; color: var(--muted); font-size: 11px; font-weight: 600; text-transform: uppercase; }
.pq-sample-stat strong { display: block; margin-top: 6px; font-family: var(--mono); font-size: 22px; font-weight: 700; color: var(--text); }
.pq-sample-stat small { color: var(--quiet); font-size: 11px; margin-top: 3px; display: block; }

.pq-casebook { min-width: 0; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); padding: 18px 20px; }
.pq-casebook-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 16px; }
.pq-casebook h3, .pq-evidence-rail h3 { margin: 0; font-size: 15px; font-weight: 700; }
.pq-shortcuts { color: var(--quiet); font-size: 11px; }
.pq-shortcuts kbd { padding: 2px 5px; border: 1px solid var(--line); border-radius: 4px; background: var(--panel-soft); font: 600 10.5px var(--mono); color: var(--text); }

.pq-table-wrap { width: 100%; overflow-x: auto; border: 1px solid var(--line); border-radius: 10px; }
.pq-case-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 12px; }
.pq-case-table caption { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.pq-case-table th { padding: 12px 14px; border-bottom: 1px solid var(--line); background: var(--panel-soft); color: var(--muted); font-size: 11px; font-weight: 650; letter-spacing: 0.04em; text-transform: uppercase; text-align: left; }
.pq-case-table td { padding: 14px; border-bottom: 1px solid var(--line); vertical-align: middle; text-align: left; background: var(--panel); }
.pq-case-table tr:last-child td { border-bottom: 0; }
.pq-case-table tr:hover td { background: var(--panel-soft); }

.pq-sample-link { display: inline-flex; align-items: center; gap: 10px; font-weight: 600; color: var(--text); text-decoration: none; }
.pq-sample-link img { width: 38px; height: 38px; border-radius: 8px; object-fit: cover; background: var(--panel-soft); border: 1px solid var(--line); flex-shrink: 0; }
.pq-quality-pages { display: flex; align-items: center; justify-content: flex-end; gap: 10px; padding-top: 14px; color: var(--quiet); font-size: 12px; }
.pq-quality-pages a { padding: 6px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel-soft); color: var(--text); font-weight: 600; text-decoration: none; }

.pq-verdict { display: inline-flex; padding: 3px 9px; border: 1px solid var(--line); border-radius: 99px; font-size: 11px; font-weight: 650; background: var(--panel-soft); }
.pq-verdict[data-tone="danger"] { border-color: rgba(239, 68, 68, 0.3); color: var(--red); background: rgba(239, 68, 68, 0.08); }
.pq-verdict[data-tone="warning"] { border-color: rgba(245, 158, 11, 0.3); color: var(--amber); background: rgba(245, 158, 11, 0.08); }

.pq-case-action { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.pq-case-action button { min-height: 28px; padding: 4px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel-soft); color: var(--text); font: inherit; font-size: 11px; font-weight: 650; cursor: pointer; transition: all 120ms ease; }
.pq-case-action button[value="allow"] { color: var(--green); }
.pq-case-action button[value="block"] { color: var(--red); }
.pq-case-action button:hover { border-color: var(--accent); background: var(--panel); }

.pq-evidence-rail { padding: 18px 20px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); }
.pq-evidence-rail section { padding: 16px 0; border-top: 1px solid var(--line); }
.pq-evidence-rail section:first-child { padding-top: 0; border-top: 0; }
.pq-pair { display: grid; grid-template-columns: 1fr auto; gap: 6px 12px; margin: 0; }
.pq-pair dt { color: var(--muted); font-size: 12px; }
.pq-pair dd { margin: 0; font-family: var(--mono); font-size: 12px; font-weight: 700; }
.pq-tag-list { display: flex; flex-wrap: wrap; gap: 6px; margin: 0; padding: 0; list-style: none; }
.pq-tag { padding: 4px 8px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel-soft); font-size: 11px; color: var(--muted); }
.pq-human-rule { margin: 0; padding-left: 12px; border-left: 3px solid var(--accent); color: var(--muted); font-size: 12px; line-height: 1.55; }
.pq-empty { padding: 18px 0; color: var(--quiet); font-size: 12px; text-align: center; }
.pq-sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
@media (max-width: 760px) {
  .pq-policy-grid { grid-template-columns: 1fr; }
  .pq-quality-sheet { grid-template-columns: 1fr; }
}
"""

PAGE_POLICY_QUALITY_CSS = CSS


def _plain(value: object) -> object:
    return asdict(value) if is_dataclass(value) and not isinstance(value, type) else value


def _map(value: object) -> Mapping[str, object]:
    value = _plain(value)
    return value if isinstance(value, Mapping) else {}


def _items(value: object) -> Sequence[object]:
    value = _plain(value)
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _text(value: object, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _e(value: object, default: str = "") -> str:
    return escape(_text(value, default), quote=True)


def _tone(value: object) -> str:
    candidate = _text(value).lower()
    return candidate if candidate in {"quiet", "warning", "danger"} else "quiet"


def _records(value: object) -> Sequence[object]:
    """Accept a record sequence or the existing {columns, rows} table shape."""
    mapped = _map(value)
    columns = tuple(_text(item) for item in _items(mapped.get("columns")))
    if not columns:
        return _items(value)
    output: list[Mapping[str, object]] = []
    for raw_row in _items(mapped.get("rows")):
        row = _items(raw_row)
        output.append({column: row[index] if index < len(row) else "" for index, column in enumerate(columns)})
    return output


def render_policy_body(data: object = None) -> str:
    """Render the policy-version, threshold, escalation, and release ledger."""
    source = _map(data)
    policy = _map(source.get("current_policy"))
    version = source.get("policy_version") or policy.get("版本") or policy.get("version") or "未提供"
    effective = source.get("effective_at") or policy.get("生效时间") or policy.get("effective_at") or "待确认"

    thresholds = _records(source.get("thresholds"))
    if not thresholds and policy:
        ignored = {"版本", "version", "生效时间", "effective_at"}
        thresholds = tuple({"label": key, "value": value} for key, value in policy.items() if key not in ignored)
    threshold_html = "".join(
        '<div class="pq-threshold">'
        '<div class="pq-threshold-info">'
        f'<dt>{_e(_map(raw).get("label") or _map(raw).get("name"), "未命名阈值")}</dt>'
        f'<small>{_e(_map(raw).get("detail") or _map(raw).get("description"), "由后端策略源提供")}</small>'
        '</div>'
        f'<dd>{_e(_map(raw).get("value") or _map(raw).get("threshold"), "—")}</dd>'
        '</div>'
        for raw in thresholds
    ) or '<div class="pq-empty" role="status">未提供生效阈值。</div>'

    routes = _records(source.get("upgrade_routes") or source.get("routes"))
    route_html = "".join(
        '<li>'
        '<div class="pq-route-info">'
        f'<strong>{_e(_map(raw).get("stage") or _map(raw).get("title") or _map(raw).get("阶段"), "未命名阶段")}</strong>'
        f'<span>{_e(_map(raw).get("condition") or _map(raw).get("detail") or _map(raw).get("条件"), "未提供升级条件")}</span>'
        '</div>'
        f'<code>{_e(_map(raw).get("target") or _map(raw).get("route") or _map(raw).get("去向"), "待确认")}</code></li>'
        for raw in routes
    ) or '<li><div class="pq-route-info"><strong>未提供升级路由</strong><span>页面不推导缺失的阈值或去向。</span></div><code>SKIP</code></li>'

    releases = _records(source.get("releases") or source.get("versions"))
    release_html = "".join(
        '<li class="pq-release">'
        f'<time datetime="{_e(_map(raw).get("datetime") or _map(raw).get("date") or _map(raw).get("time"))}">{_e(_map(raw).get("date") or _map(raw).get("time"), "时间未提供")}</time>'
        f'<code>{_e(_map(raw).get("version") or _map(raw).get("name"), "版本未提供")}</code>'
        f'<p>{_e(_map(raw).get("detail") or _map(raw).get("description") or _map(raw).get("title"), "未提供发布说明")}</p></li>'
        for raw in releases
    ) or '<li class="pq-empty" role="status">未提供策略发布记录。</li>'

    return (
        '<article class="pq-policy-ledger" data-tone="quiet" aria-labelledby="pq-policy-title">'
        '<header class="pq-ledger-head"><div><p class="pq-eyebrow">Policy ledger</p>'
        '<h2 id="pq-policy-title">生效策略账本</h2><p>顺着阈值与升级路由核对决策，不在浏览器中改写规则。</p></div>'
        f'<div class="pq-version-stamp"><span>当前版本</span><strong>{_e(version)}</strong><span>生效：{_e(effective)}</span></div></header>'
        '<div class="pq-policy-grid">'
        '<section aria-labelledby="pq-threshold-title"><div class="pq-section-kicker"><h3 id="pq-threshold-title">决策阈值</h3><span>只读</span></div>'
        f'<dl class="pq-threshold-list">{threshold_html}</dl></section>'
        '<section aria-labelledby="pq-route-title"><div class="pq-section-kicker"><h3 id="pq-route-title">升级路由</h3><span>从自动判断到例外</span></div>'
        f'<ol class="pq-route">{route_html}</ol></section></div>'
        '<section class="pq-release-log" aria-labelledby="pq-release-title"><div class="pq-section-kicker"><h3 id="pq-release-title">发布记录</h3><span>按时间追加</span></div>'
        f'<ol>{release_html}</ol></section></article>'
    )


def _quality_stats(source: Mapping[str, object]) -> str:
    sampling = _map(source.get("sampling"))
    def value(name: str, fallback: str) -> object:
        return sampling[name] if name in sampling else source.get(fallback)
    stats = (
        (sampling.get("coverage_label") or "抽检覆盖", value("coverage", "sample_coverage"), sampling.get("coverage_detail") or "覆盖的自动决策"),
        (sampling.get("progress_label") or "误判", value("false_positive", "false_positive"), sampling.get("progress_detail") or "经复核确认"),
        (sampling.get("disagreement_label") or "模型分歧", value("disagreement", "disagreement"), sampling.get("disagreement_detail") or "多模型结论不一致"),
    )
    return "".join(
        f'<div class="pq-sample-stat"><span>{_e(label)}</span><strong>{_e(value, "未采集")}</strong><small>{_e(detail)}</small></div>'
        for label, value, detail in stats
    )


def render_quality_body(data: object = None) -> str:
    """Render the sampling casebook, model disagreements, and evidence policy."""
    source = _map(data)
    batch_links = "".join(
        f'<a href="{_e(_map(raw).get("url"))}"'
        + (' aria-current="page"' if _map(raw).get("active") else "")
        + f'>{"全量主审" if _map(raw).get("required_reviewers") == 1 else "10% 双审"}'
        + f'<span>{_e(_map(_map(raw).get("progress")).get("resolved"), "0")} / {_e(_map(raw).get("selected_count"), "0")}</span></a>'
        for raw in _items(source.get("review_batches"))
    )
    batch_nav = (
        f'<nav class="pq-batch-nav" aria-label="质量审核批次">{batch_links}</nav>'
        if batch_links else ""
    )
    has_review_batches = bool(batch_links)
    quality_heading = "样本标注与仲裁" if has_review_batches else "抽检与分歧证据"
    quality_intro = (
        "先完成全量主审，再处理冻结 10% 独立双审；第二位 reviewer 提交前看不到第一位结论。"
        if has_review_batches
        else "默认由自动抽检闭环处理；这里只保留误判、模型分歧和可复现样本。"
    )
    metrics_state = "" if source.get("metrics") or source.get("sampling") else '<p class="pq-empty" role="status">未提供质量指标。</p>'
    cases = _records(source.get("samples") or source.get("cases"))
    rows: list[str] = []
    for raw in cases:
        item = _map(raw)
        case_id = item.get("id") or item.get("sample") or item.get("样本") or "—"
        ai = item.get("model") or item.get("ai_decision") or item.get("模型结论") or "—"
        check = item.get("review") or item.get("result") or item.get("复核结论") or "待复核"
        disagreement = item.get("disagreement") or item.get("difference") or item.get("分歧") or "—"
        verdict = item.get("verdict") or item.get("status") or item.get("结论") or "无需人工"
        action_url = item.get("action_url")
        csrf_token = item.get("csrf_token")
        if action_url and csrf_token:
            action_html = (
                f'<form class="pq-case-action" data-quality-action method="post" action="{_e(action_url)}">'
                f'<input type="hidden" name="csrf_token" value="{_e(csrf_token)}">'
                f'<input type="hidden" name="offset" value="{_e(item.get("offset") or 0)}">'
                f'<input type="hidden" name="batch" value="{_e(item.get("batch_id"))}">'
                '<button type="submit" name="decision" value="allow" aria-keyshortcuts="A">通过</button>'
                '<button type="submit" name="decision" value="review" aria-keyshortcuts="R">需复核</button>'
                '<button type="submit" name="decision" value="block" aria-keyshortcuts="B">拒绝</button></form>'
            )
        else:
            action_html = ""
        item_id = item.get("item_id")
        media_url = item.get("media_url")
        thumbnail_url = item.get("thumbnail_url")
        case_html = (
            f'<a class="pq-sample-link" href="{_e(media_url)}" target="_blank" rel="noreferrer">'
            + (
                f'<img src="{_e(thumbnail_url)}" alt="受控质量样本缩略图" loading="lazy">'
                if thumbnail_url else ""
            )
            + f'<span>{_e(case_id)}</span></a>'
            if media_url
            else
            f'<a href="/review?status=all&amp;view=focus&amp;focus={_e(item_id)}">{_e(case_id)}</a>'
            if item_id
            else _e(case_id)
        )
        rows.append(
            '<tr data-quality-row>'
            f'<td>{case_html}</td><td>{_e(ai)}</td><td>{_e(check)}</td><td>{_e(disagreement)}</td>'
            f'<td><span class="pq-verdict" data-tone="{_tone(item.get("tone"))}">{_e(verdict)}</span>{action_html}</td></tr>'
        )
    rows_html = "".join(rows) or '<tr><td colspan="5"><div class="pq-empty" role="status">SKIP · 未提供抽检样本。</div></td></tr>'
    pagination = _map(source.get("pagination"))
    total = int(pagination.get("total") or len(cases))
    offset = int(pagination.get("offset") or 0)
    page_size = int(pagination.get("page_size") or max(len(cases), 1))
    previous_url = pagination.get("previous_url")
    next_url = pagination.get("next_url")
    pages_html = (
        '<nav class="pq-quality-pages" aria-label="质量样本分页">'
        + (f'<a href="{_e(previous_url)}">上一页</a>' if previous_url else "")
        + f'<span>{offset + 1 if total else 0}–{min(offset + page_size, total)} / {total}</span>'
        + (f'<a href="{_e(next_url)}">下一页</a>' if next_url else "")
        + "</nav>"
    )

    retention = _map(source.get("retention"))
    retention_pairs = (
        ("留存期", retention.get("duration") or retention.get("period") or "未提供"),
        ("去标识", retention.get("deidentified") if "deidentified" in retention else "未提供"),
        ("数据集", retention.get("dataset") or "未提供"),
    )
    pair_html = "".join(f'<dt>{_e(key)}</dt><dd>{_e(value)}</dd>' for key, value in retention_pairs)
    labels = _items(source.get("labels") or retention.get("labels"))
    labels_html = "".join(f'<li class="pq-tag">{_e(label)}</li>' for label in labels) or '<li class="pq-empty">未提供样本标签。</li>'
    intervention = source.get("human_intervention") or "仅在误判已确认、模型持续分歧或策略无法覆盖时进入人工仲裁。"

    return (
        '<article class="pq-quality-sheet" aria-labelledby="pq-quality-title">'
        f'<header class="pq-quality-title"><p class="pq-eyebrow">Quality casebook</p><h2 id="pq-quality-title">{quality_heading}</h2>'
        f'<p>{quality_intro}</p>{batch_nav}</header>'
        f'{metrics_state}'
        f'<section class="pq-sample-band" aria-label="抽检概况">{_quality_stats(source)}</section>'
        '<section class="pq-casebook" aria-labelledby="pq-case-title"><div class="pq-casebook-head"><h3 id="pq-case-title">样本复核簿</h3>'
        '<span class="pq-shortcuts"><kbd>J</kbd>/<kbd>K</kbd> 选择 · <kbd>A</kbd> 通过 · <kbd>R</kbd> 复核 · <kbd>B</kbd> 拒绝</span></div><div class="pq-table-wrap">'
        '<table class="pq-case-table"><caption>抽检、误判与模型分歧明细</caption><thead><tr>'
        '<th scope="col">样本</th><th scope="col">模型判断</th><th scope="col">复核</th><th scope="col">分歧</th><th scope="col">处置</th>'
        f'</tr></thead><tbody>{rows_html}</tbody></table></div>{pages_html}</section>'
        '<aside class="pq-evidence-rail" aria-label="样本证据规则">'
        f'<section><h3>样本留存</h3><dl class="pq-pair">{pair_html}</dl></section>'
        f'<section><h3>标签</h3><ul class="pq-tag-list">{labels_html}</ul></section>'
        f'<section><h3>人工介入边界</h3><p class="pq-human-rule">{_e(intervention)}</p></section>'
        '</aside></article>'
    )


# Naming aliases keep integration explicit without coupling this module to the
# complete-document functions in review_pages.py.
render_policies_body = render_policy_body

__all__ = [
    "CSS",
    "PAGE_POLICY_QUALITY_CSS",
    "render_policy_body",
    "render_policies_body",
    "render_quality_body",
]
