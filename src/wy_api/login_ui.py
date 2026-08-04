"""Reviewer login document for the WordYeah workbench."""

from __future__ import annotations


_CSS = """
    :root {
      --font-display: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      --font-body: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      --font-mono: "SF Mono", "JetBrains Mono", "Fira Code", ui-monospace, Menlo, Monaco, Consolas, monospace;
      --ink: #171923;
      --muted: #676d79;
      --quiet: #8d93a1;
      --line: #e5e8ef;
      --line-strong: #d6dbe6;
      --panel: #ffffff;
      --panel-soft: #f7f8fb;
      --canvas: #f1f3f7;
      --accent: #5459d8;
      --accent-strong: #4348c7;
      --accent-soft: #eef0ff;
      --warning-bg: #fff5e8;
      --warning-ink: #875f23;
      --shadow: 0 24px 64px rgba(19, 23, 34, 0.09);
      --radius-app: 24px;
      --radius-panel: 18px;
      --radius-control: 12px;
      --control-height: 48px;
    }
    :root[data-theme="dark"] {
      color-scheme: dark;
      --ink: #f0f2f6;
      --muted: #949aae;
      --quiet: #62687c;
      --line: #262a37;
      --line-strong: #373c4f;
      --panel: #16181f;
      --panel-soft: #1c1f2b;
      --canvas: #0b0c0e;
      --accent: #6c72f4;
      --accent-strong: #5a60e0;
      --accent-soft: rgba(108, 114, 244, 0.16);
      --warning-bg: rgba(217, 142, 50, 0.14);
      --warning-ink: #d98e32;
      --shadow: 0 24px 64px rgba(0, 0, 0, 0.45);
    }
    @media (prefers-color-scheme: dark) {
      :root:not([data-theme="light"]) {
        color-scheme: dark;
        --ink: #f0f2f6;
        --muted: #949aae;
        --quiet: #62687c;
        --line: #262a37;
        --line-strong: #373c4f;
        --panel: #16181f;
        --panel-soft: #1c1f2b;
        --canvas: #0b0c0e;
        --accent: #6c72f4;
        --accent-strong: #5a60e0;
        --accent-soft: rgba(108, 114, 244, 0.16);
        --warning-bg: rgba(217, 142, 50, 0.14);
        --warning-ink: #d98e32;
        --shadow: 0 24px 64px rgba(0, 0, 0, 0.45);
      }
    }
    * { box-sizing: border-box; }
    html { background: var(--canvas); transition: background-color 200ms ease; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 32px;
      background: var(--canvas);
      color: var(--ink);
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
      background: linear-gradient(180deg, var(--panel-soft) 0%, var(--panel) 100%);
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
      color: var(--ink);
    }
    .brand-mark {
      width: 36px;
      height: 36px;
      display: grid;
      place-items: center;
      border-radius: 11px;
      background: linear-gradient(135deg, var(--accent) 0%, var(--accent-strong) 100%);
      color: #fff;
      font-family: var(--font-mono);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: -0.04em;
      box-shadow: 0 4px 14px rgba(84, 89, 216, 0.3);
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
      color: var(--ink);
    }
    .intro-copy > p:last-child {
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.68;
    }
    .intro-notes {
      display: grid;
      gap: 10px;
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .intro-notes li {
      display: grid;
      gap: 3px;
      padding: 14px 16px;
      border: 1px solid var(--line);
      border-radius: var(--radius-control);
      background: var(--panel);
    }
    .intro-notes strong {
      font-family: var(--font-display);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: -0.01em;
      color: var(--ink);
    }
    .intro-notes span {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
    }
    .login { display: grid; place-items: center; padding: 44px 48px; }
    .form-wrap { width: min(360px, 100%); }
    .form-wrap h2 {
      margin: 0 0 10px;
      font-family: var(--font-display);
      font-size: 28px;
      font-weight: 750;
      line-height: 1.14;
      letter-spacing: -0.04em;
      color: var(--ink);
    }
    .sub { margin: 0 0 26px; color: var(--muted); font-size: 13px; line-height: 1.65; }
    label { display: block; margin: 0 0 10px; font-size: 12px; font-weight: 650; letter-spacing: 0.01em; color: var(--ink); }
    .field { display: grid; gap: 12px; }
    input {
      width: 100%;
      height: var(--control-height);
      padding: 0 16px;
      border: 1px solid var(--line-strong);
      border-radius: var(--radius-control);
      background: var(--panel);
      color: var(--ink);
      outline: none;
      transition: border-color .15s ease, box-shadow .15s ease, background .15s ease;
    }
    input::placeholder { color: var(--quiet); }
    input:hover { border-color: var(--accent); }
    input:focus { border-color: var(--accent); box-shadow: 0 0 0 4px var(--accent-soft); }
    button {
      width: 100%;
      height: var(--control-height);
      margin-top: 6px;
      border: 1px solid transparent;
      border-radius: var(--radius-control);
      background: linear-gradient(135deg, var(--accent) 0%, var(--accent-strong) 100%);
      color: #fff;
      font-weight: 700;
      letter-spacing: -0.01em;
      cursor: pointer;
      box-shadow: 0 4px 14px rgba(84, 89, 216, 0.25);
      transition: background .15s ease, transform .15s ease, box-shadow .15s ease;
    }
    button:hover { box-shadow: 0 8px 22px rgba(84, 89, 216, 0.35); transform: translateY(-1px); }
    button:focus-visible { outline: none; box-shadow: 0 0 0 4px var(--accent-soft); }
    button:active { transform: translateY(1px); }
    .security { display: flex; align-items: flex-start; gap: 9px; margin: 18px 0 0; color: var(--quiet); font-size: 12px; line-height: 1.65; }
    .security svg { width: 15px; height: 15px; flex: 0 0 15px; margin-top: 2px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
    .notice { margin: 0 0 18px; padding: 12px 14px; border: 1px solid var(--warning-ink); border-radius: var(--radius-control); background: var(--warning-bg); color: var(--warning-ink); font-size: 13px; line-height: 1.55; }
    .meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 22px; padding-top: 16px; border-top: 1px solid var(--line); color: var(--quiet); font-size: 11px; }
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


def render_login_page(*, expired: bool = False) -> str:
    notice = (
        '<div class="notice" role="alert">会话已过期，请重新登录。</div>'
        if expired
        else ""
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>登录 · WordYeah</title>
  <style>{_CSS}</style>
  <script>
    (function(){{
      var saved = localStorage.getItem('wy-theme');
      if (saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)) {{
        document.documentElement.setAttribute('data-theme', 'dark');
      }}
    }})();
  </script>
</head>
<body>
  <main class="window">
    <section class="intro" aria-label="Reviewer 访问说明">
      <div class="brand"><span class="brand-mark">wy</span><span>wordyeah</span></div>
      <div class="intro-copy">
        <p class="eyebrow">Restricted access</p>
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
          <div class="field">
            <label for="token">审核令牌</label>
            <input id="token" type="password" name="token" autocomplete="current-password" required autofocus>
          </div>
          <button type="submit">登录工作台</button>
        </form>
        <p class="security"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5l7 3v5.2c0 4.2-2.8 7.5-7 8.8-4.2-1.3-7-4.6-7-8.8V6.5z"></path><path d="M9 12l2 2 4-4"></path></svg>会话受限，原始媒体不会写入浏览器存储。</p>
        <div class="meta"><span>受控 reviewer session</span><code>/review/login</code></div>
      </div>
    </section>
  </main>
</body>
</html>"""


__all__ = ["render_login_page"]
