"""Reviewer login document for the WordYeah workbench."""

from __future__ import annotations

import html

from wy_api.icons import icon


_CSS = """
    :root {
      color-scheme: light;
      --font-display: -apple-system, BlinkMacSystemFont, "Inter", "SF Pro Display", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      --font-body: -apple-system, BlinkMacSystemFont, "Inter", "SF Pro Text", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      --font-mono: "SF Mono", "JetBrains Mono", "Fira Code", ui-monospace, Menlo, Monaco, Consolas, monospace;
      --text: #20222d;
      --muted: #6f7483;
      --quiet: #9ba1b0;
      --line: #e7e9f0;
      --line-strong: #cfd3df;
      --panel: #ffffff;
      --panel-soft: #f8f9fc;
      --page: #f3f4f7;
      --accent: #5f63df;
      --accent-strong: #4f52c9;
      --accent-soft: rgba(95, 99, 223, 0.09);
      --warning-bg: #fff5e8;
      --warning-ink: #875f23;
      --shadow: 0 24px 64px rgba(15, 23, 42, 0.08);
      --radius-app: 24px;
      --radius-panel: 14px;
      --radius-control: 10px;
      --control-height: 48px;
    }
    :root[data-theme="dark"] {
      color-scheme: dark;
      --text: #f8fafc;
      --muted: #94a3b8;
      --quiet: #64748b;
      --line: #222638;
      --line-strong: #333852;
      --panel: #12141d;
      --panel-soft: #1b1e2e;
      --page: #090a0f;
      --accent: #6f74ff;
      --accent-strong: #5c61e6;
      --accent-soft: rgba(111, 116, 255, 0.16);
      --warning-bg: rgba(217, 142, 50, 0.14);
      --warning-ink: #d98e32;
      --shadow: 0 32px 80px rgba(0, 0, 0, 0.55);
    }
    * { box-sizing: border-box; }
    html { background: var(--page); transition: background-color 200ms ease; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 32px;
      background: var(--page);
      color: var(--text);
      font-family: var(--font-body);
      font-size: 14px;
      line-height: 1.58;
      letter-spacing: -0.01em;
      -webkit-font-smoothing: antialiased;
    }
    button, input { font: inherit; }
    .window {
      width: min(920px, 100%);
      display: grid;
      grid-template-columns: minmax(280px, 36%) minmax(0, 64%);
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: var(--radius-app);
      background: var(--panel);
      box-shadow: var(--shadow);
      transition: background-color 200ms ease, border-color 200ms ease, box-shadow 200ms ease;
    }
    .intro {
      display: grid;
      align-content: space-between;
      gap: 24px;
      padding: 36px;
      background: var(--panel-soft);
      border-right: 1px solid var(--line);
    }
    .brand {
      display: inline-flex;
      align-items: center;
      gap: 12px;
      font-family: var(--font-display);
      font-size: 20px;
      font-weight: 700;
      letter-spacing: -0.03em;
      color: var(--text);
    }
    .brand-mark {
      width: 36px;
      height: 36px;
      display: grid;
      place-items: center;
      border-radius: 11px;
      background: var(--accent);
      color: #fff;
      font-family: var(--font-mono);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: -0.04em;
      box-shadow: none;
    }
    .intro-copy { display: grid; gap: 12px; max-width: 280px; }
    .eyebrow {
      margin: 0;
      color: var(--accent);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    h1 {
      margin: 0;
      font-family: var(--font-display);
      font-size: 32px;
      font-weight: 750;
      line-height: 1.14;
      letter-spacing: -0.045em;
      color: var(--text);
    }
    .intro-copy > p:last-child {
      margin: 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.58;
    }
    .intro-notes {
      margin: 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: 12px;
    }
    .intro-notes li {
      display: grid;
      gap: 3px;
      padding: 12px 14px;
      border: 1px solid var(--line);
      border-radius: var(--radius-control);
      background: var(--panel);
    }
    .intro-notes strong { font-size: 12px; color: var(--text); }
    .intro-notes span { color: var(--muted); font-size: 12px; line-height: 1.5; }
    .login { display: grid; align-content: center; padding: 44px; }
    .form-wrap { display: grid; gap: 18px; max-width: 360px; }
    .form-wrap h2 {
      margin: 0;
      font-family: var(--font-display);
      font-size: 28px;
      font-weight: 700;
      letter-spacing: -0.04em;
    }
    .sub { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.55; }
    .field { display: grid; gap: 8px; }
    .field label { color: var(--muted); font-size: 12px; font-weight: 650; }
    .field input {
      width: 100%;
      min-height: var(--control-height);
      padding: 0 14px;
      border: 1px solid var(--line-strong);
      border-radius: var(--radius-control);
      background: var(--panel-soft);
      color: var(--text);
      outline: 0;
    }
    .field input:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }
    button[type="submit"] {
      min-height: var(--control-height);
      border: 0;
      border-radius: var(--radius-control);
      background: var(--accent);
      color: #fff;
      font-size: 14px;
      font-weight: 700;
      cursor: pointer;
    }
    button[type="submit"]:hover,
    button[type="submit"]:focus-visible { background: var(--accent-strong); }
    .notice {
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: var(--radius-control);
      background: var(--warning-bg);
      color: var(--warning-ink);
      font-size: 12px;
    }
    .security {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin: 0;
      color: var(--quiet);
      font-size: 12px;
    }
    .security svg { width: 15px; height: 15px; flex: 0 0 15px; }
    .meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      color: var(--quiet);
      font-size: 11px;
    }
    .meta code { font-family: var(--font-mono); font-size: 12px; color: var(--muted); }
    @media (max-width: 920px) {
      .window { grid-template-columns: 1fr; }
      .intro { padding: 30px; border-right: 0; border-bottom: 1px solid var(--line); }
      .login { padding: 38px 30px; }
    }
    @media (max-width: 720px) {
      body { padding: 0; background: var(--panel); }
      .window { min-height: 100vh; border: 0; border-radius: 0; box-shadow: none; }
      .intro { gap: 20px; padding: 24px; }
      .intro-copy { max-width: none; }
      h1 { font-size: 28px; }
      .login { padding: 28px 24px 32px; }
      .form-wrap h2 { font-size: 26px; }
      .meta { display: grid; justify-content: stretch; }
    }
"""


def render_login_page(
    *,
    expired: bool = False,
    show_reviewer_id: bool = False,
    default_reviewer_id: str = "",
) -> str:
    notice = (
        '<div class="notice" role="alert">会话已过期，请重新登录。</div>'
        if expired
        else ""
    )
    if show_reviewer_id:
        reviewer_field = """
          <div class="field">
            <label for="reviewer_id">审核员 ID</label>
            <input id="reviewer_id" type="text" name="reviewer_id" autocomplete="username" required autofocus>
          </div>"""
        token_autofocus = ""
    else:
        reviewer_field = (
            '<input type="hidden" name="reviewer_id" value="'
            + html.escape(default_reviewer_id, quote=True)
            + '">'
        )
        token_autofocus = " autofocus"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>登录 · WordYeah</title>
  <style>{_CSS}</style>
  <script>
    (function(){{
      var saved = localStorage.getItem('wy-theme') || 'light';
      document.documentElement.setAttribute('data-theme', saved);
    }})();
  </script>
</head>
<body>
  <main class="window">
    <section class="intro" aria-label="审核员访问说明">
      <div class="brand"><span class="brand-mark">wy</span><span>WordYeah</span></div>
      <div class="intro-copy">
        <p class="eyebrow">受限访问</p>
        <h1>审核登录</h1>
        <p>仅用于验证 reviewer 会话并进入工作台。</p>
      </div>
      <ul class="intro-notes">
        <li><strong>范围</strong><span>只显示当前 consumer 的受控审核数据。</span></li>
        <li><strong>存储</strong><span>媒体预览与敏感记录不写入浏览器持久存储。</span></li>
      </ul>
    </section>
    <section class="login">
      <div class="form-wrap">
        <h2>进入工作台</h2>
        <p class="sub">使用审核令牌完成受控登录。</p>
        {notice}
        <form method="post" action="/review/login">
          {reviewer_field}
          <div class="field">
            <label for="token">审核令牌</label>
            <input id="token" type="password" name="token" autocomplete="current-password" required{token_autofocus}>
          </div>
          <button type="submit">登录工作台</button>
        </form>
        <p class="security">{icon("shield-lock")}会话受限，原始媒体不会写入浏览器存储。</p>
        <div class="meta"><span>受控审核会话</span><code>/review/login</code></div>
      </div>
    </section>
  </main>
</body>
</html>"""


__all__ = ["render_login_page"]
