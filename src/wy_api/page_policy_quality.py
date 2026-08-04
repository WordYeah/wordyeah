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
/* Policy ledger: dense configuration reading, not a dashboard card grid. */
.pq-policy-ledger,.pq-quality-sheet{color:var(--text);container-type:inline-size}
.pq-policy-ledger *,.pq-quality-sheet *{box-sizing:border-box}
.pq-ledger-head{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:24px;align-items:end;padding:4px 0 22px;border-bottom:2px solid var(--line-strong)}
.pq-eyebrow{margin:0 0 7px;color:var(--muted);font-size:11px;font-weight:750;letter-spacing:.12em;text-transform:uppercase}
.pq-ledger-head h2,.pq-quality-title h2{margin:0;font-size:clamp(22px,3vw,32px);line-height:1.12;letter-spacing:-.035em}
.pq-ledger-head p,.pq-quality-title p{max-width:68ch;margin:8px 0 0;color:var(--muted);line-height:1.55}
.pq-version-stamp{min-width:148px;padding:10px 13px;border:1px solid var(--line-strong);border-radius:8px;background:var(--panel-soft);text-align:right}
.pq-version-stamp span{display:block;color:var(--quiet);font-size:11px}
.pq-version-stamp strong{font-family:var(--mono);font-size:14px}
.pq-policy-grid{display:grid;grid-template-columns:minmax(240px,.82fr) minmax(0,1.65fr);gap:0;margin-top:22px;border-block:1px solid var(--line)}
.pq-policy-grid>section{padding:20px 0}
.pq-policy-grid>section+section{padding-left:26px;border-left:1px solid var(--line)}
.pq-section-kicker{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:14px}
.pq-section-kicker h3{margin:0;font-size:14px;letter-spacing:-.01em}
.pq-section-kicker span{color:var(--quiet);font-size:11px}
.pq-threshold-list{display:grid;gap:0;margin:0}
.pq-threshold{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 12px;padding:12px 0;border-top:1px solid var(--line)}
.pq-threshold:first-child{border-top:0}
.pq-threshold dt{font-size:13px;font-weight:650}
.pq-threshold dd{grid-row:1/3;grid-column:2;margin:0;font-family:var(--mono);font-size:15px;font-weight:700}
.pq-threshold small{color:var(--muted);font-size:12px;line-height:1.4}
.pq-route{display:grid;grid-template-columns:1fr;gap:0;margin:0;padding:0;list-style:none;counter-reset:route}
.pq-route li{position:relative;display:grid;grid-template-columns:30px minmax(0,1fr) auto;gap:3px 12px;padding:0 0 22px;counter-increment:route}
.pq-route li:before{display:grid;width:30px;height:30px;grid-column:1;grid-row:1/3;place-items:center;border:1px solid var(--line-strong);border-radius:50%;background:var(--panel);content:counter(route);font-family:var(--mono);font-size:11px;font-weight:700}
.pq-route li:after{position:absolute;top:30px;bottom:0;left:14px;width:1px;background:var(--line);content:""}
.pq-route li:last-child:after{display:none}
.pq-route strong,.pq-route span{grid-column:2}
.pq-route strong{font-size:13px}.pq-route span{color:var(--muted);font-size:12px;line-height:1.45}
.pq-route code{grid-column:3;grid-row:1/3;align-self:start;padding:3px 7px;border-radius:5px;background:var(--panel-soft);color:var(--text);font-family:var(--mono);font-size:11px}
.pq-release-log{padding-top:22px}.pq-release-log ol{margin:0;padding:0;list-style:none}
.pq-release{display:grid;grid-template-columns:minmax(95px,.3fr) minmax(130px,.55fr) minmax(0,1.5fr);gap:16px;padding:13px 0;border-top:1px solid var(--line);align-items:baseline}
.pq-release time,.pq-release code{font-family:var(--mono);font-size:11px}.pq-release time{color:var(--quiet)}
.pq-release p{margin:0;color:var(--muted);font-size:13px;line-height:1.45}

/* Quality sheet: a sampling worksheet with an evidence rail. */
.pq-quality-sheet{display:grid;grid-template-columns:minmax(0,1fr) minmax(220px,290px);grid-template-areas:"title rail" "sample rail" "cases rail";gap:20px 30px}
.pq-quality-title{grid-area:title;padding-bottom:18px;border-bottom:1px solid var(--line-strong)}
.pq-sample-band{grid-area:sample;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border-block:1px solid var(--line)}
.pq-sample-stat{padding:14px 16px 14px 0}.pq-sample-stat+.pq-sample-stat{padding-left:16px;border-left:1px solid var(--line)}
.pq-sample-stat span{display:block;color:var(--muted);font-size:11px}.pq-sample-stat strong{display:block;margin-top:4px;font-family:var(--mono);font-size:20px}.pq-sample-stat small{color:var(--quiet);font-size:11px}
.pq-casebook{grid-area:cases;min-width:0}.pq-casebook h3,.pq-evidence-rail h3{margin:0 0 12px;font-size:14px}
.pq-table-wrap{max-width:100%;overflow-x:auto;border-top:1px solid var(--line-strong)}
.pq-case-table{width:100%;border-collapse:collapse;font-size:12px}.pq-case-table caption{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.pq-case-table th,.pq-case-table td{padding:11px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}.pq-case-table th{color:var(--quiet);font-size:10px;letter-spacing:.08em;text-transform:uppercase}.pq-case-table td:first-child{font-family:var(--mono)}
.pq-verdict{display:inline-flex;padding:2px 7px;border:1px solid var(--line-strong);border-radius:99px;font-size:10px;font-weight:700}.pq-verdict[data-tone="danger"]{border-color:var(--red);color:var(--red)}.pq-verdict[data-tone="warning"]{border-color:var(--amber);color:var(--amber)}
.pq-case-action{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}.pq-case-action button{min-height:28px;padding:4px 9px;border:1px solid var(--line-strong);border-radius:6px;background:var(--panel);color:var(--text);font:inherit;font-size:11px;font-weight:700;cursor:pointer}.pq-case-action button[value="block"]{color:var(--red)}.pq-case-action button:hover{border-color:var(--accent)}
.pq-evidence-rail{grid-area:rail;padding-left:22px;border-left:1px solid var(--line)}
.pq-evidence-rail section{padding:17px 0;border-top:1px solid var(--line)}.pq-evidence-rail section:first-child{padding-top:0;border-top:0}
.pq-pair{display:grid;grid-template-columns:1fr auto;gap:6px 12px;margin:0}.pq-pair dt{color:var(--muted);font-size:12px}.pq-pair dd{margin:0;font-family:var(--mono);font-size:12px;font-weight:700}
.pq-tag-list{display:flex;flex-wrap:wrap;gap:6px;margin:0;padding:0;list-style:none}.pq-tag{padding:4px 8px;border:1px solid var(--line);border-radius:5px;background:var(--panel-soft);font-size:11px}
.pq-human-rule{margin:0;padding-left:11px;border-left:2px solid var(--line-strong);color:var(--muted);font-size:12px;line-height:1.55}
.pq-empty{padding:18px 0;color:var(--quiet);font-size:12px}.pq-sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@container (max-width:760px){.pq-ledger-head{grid-template-columns:1fr}.pq-version-stamp{text-align:left}.pq-policy-grid{grid-template-columns:1fr}.pq-policy-grid>section+section{padding-left:0;border-top:1px solid var(--line);border-left:0}.pq-quality-sheet{grid-template-columns:1fr;grid-template-areas:"title" "sample" "cases" "rail"}.pq-evidence-rail{padding:18px 0 0;border-top:1px solid var(--line-strong);border-left:0}}
@container (max-width:480px){.pq-release{grid-template-columns:1fr;gap:4px}.pq-sample-band{grid-template-columns:1fr}.pq-sample-stat+.pq-sample-stat{padding-left:0;border-top:1px solid var(--line);border-left:0}.pq-route li{grid-template-columns:30px minmax(0,1fr)}.pq-route code{grid-column:2;grid-row:auto;margin-top:5px;width:max-content}}
@media (prefers-reduced-motion:reduce){.pq-policy-ledger *,.pq-quality-sheet *{scroll-behavior:auto!important}}
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
        f'<dt>{_e(_map(raw).get("label") or _map(raw).get("name"), "未命名阈值")}</dt>'
        f'<dd>{_e(_map(raw).get("value") or _map(raw).get("threshold"), "—")}</dd>'
        f'<small>{_e(_map(raw).get("detail") or _map(raw).get("description"), "由后端策略源提供")}</small></div>'
        for raw in thresholds
    ) or '<div class="pq-empty" role="status">未提供生效阈值。</div>'

    routes = _records(source.get("upgrade_routes") or source.get("routes"))
    route_html = "".join(
        '<li>'
        f'<strong>{_e(_map(raw).get("stage") or _map(raw).get("title") or _map(raw).get("阶段"), "未命名阶段")}</strong>'
        f'<span>{_e(_map(raw).get("condition") or _map(raw).get("detail") or _map(raw).get("条件"), "未提供升级条件")}</span>'
        f'<code>{_e(_map(raw).get("target") or _map(raw).get("route") or _map(raw).get("去向"), "待确认")}</code></li>'
        for raw in routes
    ) or '<li><strong>未提供升级路由</strong><span>页面不推导缺失的阈值或去向。</span><code>SKIP</code></li>'

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
    stats = (
        ("抽检覆盖", sampling.get("coverage") or source.get("sample_coverage"), "覆盖的自动决策"),
        ("误判", sampling.get("false_positive") or source.get("false_positive"), "经复核确认"),
        ("模型分歧", sampling.get("disagreement") or source.get("disagreement"), "多模型结论不一致"),
    )
    return "".join(
        f'<div class="pq-sample-stat"><span>{_e(label)}</span><strong>{_e(value, "未采集")}</strong><small>{_e(detail)}</small></div>'
        for label, value, detail in stats
    )


def render_quality_body(data: object = None) -> str:
    """Render the sampling casebook, model disagreements, and evidence policy."""
    source = _map(data)
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
                f'<form class="pq-case-action" method="post" action="{_e(action_url)}">'
                f'<input type="hidden" name="csrf_token" value="{_e(csrf_token)}">'
                '<button type="submit" name="decision" value="allow">通过</button>'
                '<button type="submit" name="decision" value="review">需复核</button>'
                '<button type="submit" name="decision" value="block">拒绝</button></form>'
            )
        else:
            action_html = ""
        item_id = item.get("item_id")
        case_html = (
            f'<a href="/review?status=all&amp;view=focus&amp;focus={_e(item_id)}">{_e(case_id)}</a>'
            if item_id
            else _e(case_id)
        )
        rows.append(
            '<tr>'
            f'<td>{case_html}</td><td>{_e(ai)}</td><td>{_e(check)}</td><td>{_e(disagreement)}</td>'
            f'<td><span class="pq-verdict" data-tone="{_tone(item.get("tone"))}">{_e(verdict)}</span>{action_html}</td></tr>'
        )
    rows_html = "".join(rows) or '<tr><td colspan="5"><div class="pq-empty" role="status">SKIP · 未提供抽检样本。</div></td></tr>'

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
        '<header class="pq-quality-title"><p class="pq-eyebrow">Quality casebook</p><h2 id="pq-quality-title">抽检与分歧证据</h2>'
        '<p>默认由自动抽检闭环处理；这里只保留误判、模型分歧和可复现样本。</p></header>'
        f'{metrics_state}'
        f'<section class="pq-sample-band" aria-label="抽检概况">{_quality_stats(source)}</section>'
        '<section class="pq-casebook" aria-labelledby="pq-case-title"><h3 id="pq-case-title">样本复核簿</h3><div class="pq-table-wrap">'
        '<table class="pq-case-table"><caption>抽检、误判与模型分歧明细</caption><thead><tr>'
        '<th scope="col">样本</th><th scope="col">模型判断</th><th scope="col">复核</th><th scope="col">分歧</th><th scope="col">处置</th>'
        f'</tr></thead><tbody>{rows_html}</tbody></table></div></section>'
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
