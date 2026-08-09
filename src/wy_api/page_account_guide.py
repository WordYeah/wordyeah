"""Account and reviewer-guide content for the review workbench.

The renderers in this module return page content rather than a complete document.
They do not infer identity, permissions, or sessions: account facts are rendered only
when supplied by the authenticated server-side caller.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from html import escape
from typing import Mapping, Sequence


CSS = """
.account-guide { display: grid; gap: 18px; }
.account-guide__panel {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
}
.account-guide__heading { margin: 0; font-size: 18px; font-weight: 650; line-height: 1.4; letter-spacing: normal; }
.account-guide__copy { margin: 5px 0 0; color: var(--muted); font-size: 13px; line-height: 1.6; }
.account-guide__panel > header { padding: 20px 24px 16px; border-bottom: 1px solid var(--line); }
.account-guide__body { display: grid; gap: 22px; padding: 20px 24px 24px; }
.account-guide__section { display: grid; gap: 12px; }
.account-guide__section + .account-guide__section { padding-top: 20px; border-top: 1px solid var(--line); }
.account-guide__section h3 { margin: 0; font-size: 14px; font-weight: 650; color: var(--text); }
.account-guide__facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin: 0; }
.account-guide__fact-card { padding: 14px 16px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel-soft); display: flex; flex-direction: column; gap: 4px; }
.account-guide__facts dt { color: var(--muted); font-size: 11px; font-weight: 650; text-transform: uppercase; letter-spacing: 0.04em; }
.account-guide__facts dd { margin: 0; font-size: 14px; font-weight: 650; font-family: var(--mono); color: var(--text); word-break: break-all; }
.account-profile { display: flex; align-items: center; gap: 14px; padding: 14px 16px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel-soft); }
.account-profile__avatar { width: 52px; height: 52px; flex: 0 0 52px; overflow: hidden; border-radius: 50%; background: var(--panel); }
.account-profile__avatar img { width: 100%; height: 100%; object-fit: cover; }
.account-profile__copy { min-width: 0; }
.account-profile__copy strong { display: block; font-size: 15px; }
.account-profile__copy span { display: block; margin-top: 3px; color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.account-guide__list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.account-guide__item { padding: 12px 16px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel-soft); display: flex; justify-content: space-between; align-items: center; }
.account-guide__item strong { font-size: 13px; font-weight: 650; }
.account-guide__item span { color: var(--muted); font-size: 12px; }
.account-guide__state { margin: 0; padding: 14px 16px; border: 1px dashed var(--line); border-radius: 10px; color: var(--muted); font-size: 12px; text-align: center; }
.account-guide__table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 10px; }
.account-guide__table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 12px; }
.account-guide__table caption { padding: 12px 16px; color: var(--muted); font-size: 11px; font-weight: 650; text-align: left; background: var(--panel-soft); border-bottom: 1px solid var(--line); letter-spacing: 0.04em; text-transform: uppercase; }
.account-guide__table th,
.account-guide__table td { padding: 12px 16px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: middle; }
.account-guide__table th { color: var(--muted); font-size: 11px; font-weight: 650; background: var(--panel-soft); letter-spacing: 0.04em; text-transform: uppercase; }
.account-guide__table td { background: var(--panel); }
.account-guide__table tbody tr:last-child td { border-bottom: 0; }
.account-guide__table tbody tr:hover td { background: var(--panel-soft); }
.account-guide__table td[data-label]::before { content: attr(data-label); display: none; }
.account-guide__badge { display: inline-flex; align-items: center; gap: 6px; min-height: 24px; padding: 2px 9px; border-radius: 999px; background: var(--panel-soft); border: 1px solid var(--line); font-size: 11px; font-weight: 600; }
.account-guide__badge::before { content: ""; display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--green); }
.account-guide__action {
  min-height: 38px;
  padding: 0 16px;
  border: 1px solid var(--red);
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.06);
  color: var(--red);
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 650;
  transition: all 140ms ease;
}
.account-guide__action:hover { background: rgba(239, 68, 68, 0.12); }
.account-guide__action:focus-visible,
.account-guide__toc a:focus-visible { outline: 3px solid var(--accent-soft); outline-offset: 2px; }
.account-guide__toc ul { display: flex; flex-wrap: wrap; gap: 8px; margin: 0; padding: 0; list-style: none; }
.account-guide__toc a { display: inline-flex; padding: 7px 12px; border: 1px solid var(--line); border-radius: 999px; color: var(--text); font-weight: 600; text-decoration: none; }
.account-guide__steps { margin: 0; padding-left: 22px; }
.account-guide__steps li { padding: 4px 0 10px 4px; font-size: 12px; line-height: 1.6; }
.account-guide kbd { display: inline-block; min-width: 25px; padding: 2px 6px; border: 1px solid var(--line-strong); border-radius: 5px; background: var(--panel-soft); font: 600 11px/1.5 var(--mono); text-align: center; }
@media (max-width: 640px) {
  .account-guide__facts { grid-template-columns: 1fr; }
  .account-guide__panel > header,
  .account-guide__body { padding-left: 16px; padding-right: 16px; }
  .account-guide__table-wrap { overflow: visible; }
  .account-guide__table { width: 100%; min-width: 0; border-spacing: 0; }
  .account-guide__table thead { position: absolute; width: 1px; height: 1px; margin: -1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
  .account-guide__table tbody { display: grid; gap: 10px; }
  .account-guide__table tr { display: grid; gap: 0; padding: 12px 14px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); }
  .account-guide__table td { display: grid; grid-template-columns: minmax(88px, 38%) minmax(0, 1fr); gap: 10px; padding: 8px 0; border-bottom: 0; background: transparent; white-space: normal; overflow-wrap: anywhere; }
  .account-guide__table td[data-label]::before { display: block; content: attr(data-label); color: var(--muted); font-size: 10px; font-weight: 650; letter-spacing: .04em; text-transform: uppercase; }
  .account-guide__table td[colspan] { display: block; padding: 8px 0; }
  .account-guide__table td[colspan]::before { content: none; }
  .account-guide__table td:first-child { padding-top: 0; }
  .account-guide__table td:last-child { padding-bottom: 0; }
  .account-guide__item { align-items: flex-start; flex-direction: column; }
}
"""


_DEFAULT_RISKS = (
    ("允许", "没有命中风险定义，且证据足以支持放行。"),
    ("需复核", "证据不足、模型分歧、画面语义不明确或策略边界不清。"),
    ("阻止", "明确命中色情裸露、血腥暴力、仇恨标识、欺诈冒充等禁用风险。"),
    ("留置", "媒体无法安全读取、证据已失效或当前无法形成可靠决定。"),
)

_DEFAULT_REASONS = (
    ("safe_avatar", "允许", "未发现策略定义的风险。"),
    ("sexual_content", "阻止", "色情、明确裸露或性暗示内容。"),
    ("graphic_violence", "阻止", "血腥、肢解或令人不适的暴力画面。"),
    ("hate_symbol", "阻止", "仇恨符号或针对受保护群体的攻击表达。"),
    ("impersonation", "阻止", "以头像冒充他人或误导身份。"),
    ("uncertain_evidence", "需复核", "证据不足或模型结论冲突。"),
    ("media_unavailable", "留置", "媒体不可读取或受控预览已失效。"),
)

_DEFAULT_SHORTCUTS = (
    ("A", "允许当前项"),
    ("B", "阻止当前项"),
    ("H", "留置当前项"),
    ("J / K", "下一项 / 上一项"),
    ("?", "显示或隐藏快捷键帮助"),
)


def _mapping(value: object) -> Mapping[str, object]:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    return value if isinstance(value, Mapping) else {}


def _items(value: object) -> Sequence[object]:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _text(value: object, default: str = "") -> str:
    return default if value is None else str(value)


def _facts(facts: Mapping[str, object], empty: str) -> str:
    if not facts:
        return f'<p class="account-guide__state">{escape(empty)}</p>'
    rows = "".join(
        f'<div class="account-guide__fact-card"><dt>{escape(_text(label))}</dt><dd>{escape(_text(value, "—"))}</dd></div>'
        for label, value in facts.items()
    )
    return f'<dl class="account-guide__facts">{rows}</dl>'


def _named_list(value: object, empty: str) -> str:
    rows: list[str] = []
    for raw in _items(value):
        item = _mapping(raw)
        if item:
            name = _text(item.get("name") or item.get("label") or item.get("title"), "—")
            detail = _text(item.get("detail") or item.get("description") or item.get("scope"))
        else:
            name, detail = _text(raw, "—"), ""
        rows.append(
            f'<li class="account-guide__item"><strong>{escape(name)}</strong>'
            f'{f"<span>{escape(detail)}</span>" if detail else ""}</li>'
        )
    return f'<ul class="account-guide__list">{"".join(rows)}</ul>' if rows else f'<p class="account-guide__state">{escape(empty)}</p>'


def _section(section_id: str, title: str, body: str) -> str:
    return f'<section class="account-guide__section" id="{section_id}" aria-labelledby="{section_id}-title"><h3 id="{section_id}-title">{escape(title)}</h3>{body}</section>'


def render_account_content(data: object = None, *, csrf_token: str | None = None) -> str:
    """Render authenticated identity, access, session, and security facts.

    ``data`` may contain ``identity`` (mapping), ``permissions`` (sequence), and
    ``sessions`` (sequence). A logout control is emitted only when a CSRF token is
    supplied by the authenticated request context.
    """

    account = _mapping(data)
    identity = _mapping(account.get("identity") or account.get("profile"))
    avatar_url = _text(account.get("avatar_url"))
    identity_intro = ""
    if avatar_url:
        identity_intro = (
            '<div class="account-profile">'
            f'<span class="account-profile__avatar"><img src="{escape(avatar_url, quote=True)}" alt=""></span>'
            '<span class="account-profile__copy">'
            f'<strong>{escape(_text(identity.get("显示名称"), identity.get("用户名") or "Reviewer"))}</strong>'
            f'<span>{escape(_text(identity.get("邮箱"), identity.get("Reviewer ID") or ""))}</span>'
            "</span></div>"
        )
    permissions = account.get("permissions")
    sessions_value = account.get("sessions")
    sessions_table = _mapping(sessions_value)
    sessions = _items(sessions_value)

    session_rows: list[str] = []
    session_headers = ("会话 ID", "建立时间", "最近活动", "状态")
    for raw in sessions:
        item = _mapping(raw)
        if not item:
            continue
        session_rows.append(
            "<tr>"
            f'<td data-label="{session_headers[0]}"><code style="font-family: var(--mono); font-size: 11.5px; padding: 2px 6px; border-radius: 4px; background: var(--panel-soft); border: 1px solid var(--line);">{escape(_text(item.get("session_id") or item.get("id"), "—"))}</code></td>'
            f'<td data-label="{session_headers[1]}">{escape(_text(item.get("created_at"), "—"))}</td>'
            f'<td data-label="{session_headers[2]}">{escape(_text(item.get("last_seen_at") or item.get("last_seen"), "—"))}</td>'
            f'<td data-label="{session_headers[3]}"><span class="account-guide__badge">{escape(_text(item.get("status"), "当前活动"))}</span></td>'
            "</tr>"
        )
    if sessions_table.get("columns"):
        columns = _items(sessions_table.get("columns"))
        rows = _items(sessions_table.get("rows"))
        sessions_html = _guide_table(
            "服务端报告的活动会话",
            tuple(_text(column) for column in columns),
            tuple(_items(row) for row in rows),
        )
    else:
        sessions_html = (
        '<div class="account-guide__table-wrap"><table class="account-guide__table">'
        '<caption>服务端报告的活动会话</caption><thead><tr><th scope="col">会话 ID</th><th scope="col">建立时间</th>'
        '<th scope="col">最近活动</th><th scope="col">状态</th></tr></thead>'
        f'<tbody>{"".join(session_rows)}</tbody></table></div>'
        if session_rows
        else '<p class="account-guide__state">未提供活动会话信息。</p>'
        )
    security = (
        '<form method="post" action="/review/logout">'
        f'<input type="hidden" name="csrf_token" value="{escape(csrf_token, quote=True)}">'
        '<button class="account-guide__action" type="submit">退出当前会话</button></form>'
        if csrf_token is not None
        else '<p class="account-guide__state">当前请求未提供可验证的会话退出凭据。</p>'
    )
    return (
        '<div class="account-guide" data-page="account">'
        '<section class="account-guide__panel" aria-labelledby="account-title">'
        '<header><h2 class="account-guide__heading" id="account-title">账户与访问</h2>'
        '<p class="account-guide__copy">核对当前请求对应的身份、权限范围与活动会话；本页不推断未提供的账户事实。</p></header>'
        '<div class="account-guide__body">'
        + _section("account-identity", "身份", identity_intro + _facts(identity, "未提供已验证的 reviewer 身份。"))
        + _section(
            "account-permissions",
            "权限范围",
            _facts(_mapping(permissions), "未提供权限范围。")
            if _mapping(permissions)
            else _named_list(permissions, "未提供权限范围。"),
        )
        + _section("account-sessions", "会话", sessions_html)
        + _section("account-security", "安全操作", security)
        + "</div></section></div>"
    )


def _guide_table(caption: str, headings: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    head = "".join(f'<th scope="col">{escape(item)}</th>' for item in headings)
    body = "".join(
        "<tr>"
        + "".join(
            f'<td data-label="{escape(headings[index])}">{escape(_text(cell))}</td>'
            for index, cell in enumerate(row)
        )
        + "".join(
            f'<td data-label="{escape(headings[index])}"></td>'
            for index in range(len(row), len(headings))
        )
        + "</tr>"
        for row in rows
    )
    return (
        '<div class="account-guide__table-wrap"><table class="account-guide__table">'
        f'<caption>{escape(caption)}</caption><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
    )


def _shortcuts_table(rows: Sequence[object]) -> str:
    rendered: list[str] = []
    for raw in rows:
        row = _items(raw)
        key = _text(row[0], "—") if row else "—"
        action = _text(row[1], "—") if len(row) > 1 else "—"
        rendered.append(
            f'<tr><td data-label="按键"><kbd>{escape(key)}</kbd></td><td data-label="操作">{escape(action)}</td></tr>'
        )
    return (
        '<div class="account-guide__table-wrap"><table class="account-guide__table">'
        '<caption>审核工作台键盘操作</caption><thead><tr><th scope="col">按键</th>'
        f'<th scope="col">操作</th></tr></thead><tbody>{"".join(rendered)}</tbody></table></div>'
    )


def render_guide_content(data: object = None) -> str:
    """Render the reviewer reference: contents, decisions, risks, reasons, keys."""

    guide = _mapping(data)
    risks = _items(guide.get("risks")) or _DEFAULT_RISKS
    reasons = _items(guide.get("reasons")) or _DEFAULT_REASONS
    shortcuts = _items(guide.get("shortcuts")) or _DEFAULT_SHORTCUTS
    principles = _items(guide.get("principles")) or (
        "先核对受控预览与证据，再作决定。",
        "常规明确样本由 AI 处理；人工聚焦低置信度、分歧、错误、抽检与仲裁。",
        "证据不足时留置或升级，不以猜测替代决定。",
        "使用最具体的结构化原因；备注只补充原因词典无法表达的事实。",
    )
    return (
        '<div class="account-guide" data-page="guide">'
        '<nav class="account-guide__panel account-guide__toc" aria-labelledby="guide-toc-title">'
        '<header><h2 class="account-guide__heading" id="guide-toc-title">审核说明目录</h2></header>'
        '<div class="account-guide__body"><ul>'
        '<li><a href="#guide-principles">审核原则</a></li><li><a href="#guide-flow">决策流程</a></li>'
        '<li><a href="#guide-risks">风险定义</a></li><li><a href="#guide-reasons">原因词典</a></li>'
        '<li><a href="#guide-shortcuts">快捷键</a></li></ul></div></nav>'
        '<section class="account-guide__panel" aria-labelledby="guide-title">'
        '<header><h2 class="account-guide__heading" id="guide-title">审核参考</h2>'
        '<p class="account-guide__copy">用于例外审核、抽检和仲裁；最终决定仍以当前生效策略及证据为准。</p></header>'
        '<div class="account-guide__body">'
        + _section("guide-principles", "审核原则", _named_list(principles, "暂无审核原则。"))
        + _section(
            "guide-flow",
            "决策流程",
            '<ol class="account-guide__steps"><li>确认条目、受控预览与证据属于同一审核 attempt。</li>'
            '<li>核对模型建议、置信度、策略版本及是否存在分歧。</li>'
            '<li>按风险定义选择允许、阻止或留置；边界不清时进入复核或仲裁。</li>'
            '<li>选择最具体的原因码，提交前复核决定与备注。</li></ol>',
        )
        + _section("guide-risks", "风险定义", _guide_table("头像审核风险与处理", ("处理", "定义"), risks))
        + _section("guide-reasons", "原因词典", _guide_table("结构化原因码", ("原因码", "建议决定", "适用条件"), reasons))
        + _section(
            "guide-shortcuts",
            "快捷键",
            _shortcuts_table(shortcuts)
            + '<p class="account-guide__copy">焦点位于输入框、文本域或选择控件时，不触发审核快捷键。</p>',
        )
        + "</div></section></div>"
    )


ACCOUNT_GUIDE_CSS = CSS
render_account_body = render_account_content
render_guide_body = render_guide_content


__all__ = [
    "ACCOUNT_GUIDE_CSS",
    "CSS",
    "render_account_body",
    "render_account_content",
    "render_guide_body",
    "render_guide_content",
]
