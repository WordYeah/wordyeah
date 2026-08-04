"""Reviewer login document for the WordYeah workbench."""

from __future__ import annotations


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
  <meta name="color-scheme" content="light">
  <title>登录 · WordYeah</title>
  <style>
    :root{{--font-display:'seravek','Lato',"Source Han Sans SC","Noto Sans CJK SC","PingFang SC",-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;--font-body:'seravek','Lato',"Source Han Sans SC","Noto Sans CJK SC","PingFang SC",-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;--font-mono:'wenfeng-ibmps',"JetBrains Mono","SFMono-Regular","SFMono",ui-monospace,Menlo,Consolas,monospace;--ink:#171923;--muted:#676d79;--quiet:#8d93a1;--line:#e5e8ef;--line-strong:#d6dbe6;--panel:#fff;--panel-soft:#fafbfc;--canvas:#f3f4f7;--accent:#5d61d5;--accent-strong:#4c51bc;--accent-soft:#eef0ff;--warning-bg:#fff5e8;--warning-ink:#875f23;--shadow:0 18px 56px rgba(19,23,34,.08);--radius-app:24px;--radius-panel:18px;--radius-control:12px}}
    *{{box-sizing:border-box}}
    html{{background:var(--canvas)}}
    body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:32px;background:var(--canvas);color:var(--ink);font:14px/1.58 var(--font-body);letter-spacing:-.01em;-webkit-font-smoothing:antialiased}}
    button,input{{font:inherit}}
    .window{{width:min(1080px,100%);min-height:680px;display:grid;grid-template-columns:minmax(320px,43%) minmax(0,57%);overflow:hidden;border:1px solid var(--line);border-radius:var(--radius-app);background:var(--panel);box-shadow:var(--shadow)}}
    .intro{{display:flex;flex-direction:column;justify-content:space-between;gap:28px;padding:42px;background:linear-gradient(180deg,#fbfbfd 0%,#f6f7fb 100%);border-right:1px solid var(--line)}}
    .brand{{display:inline-flex;align-items:center;gap:12px;font:600 20px/1.1 var(--font-display);letter-spacing:-.03em}}
    .brand-mark{{width:38px;height:38px;display:grid;place-items:center;border-radius:11px;background:var(--accent);color:#fff;font:700 13px/1 var(--font-mono);letter-spacing:-.04em}}
    .intro-copy{{display:grid;gap:14px;max-width:360px}}
    .eyebrow{{margin:0;color:var(--quiet);font-size:11px;font-weight:600;letter-spacing:.11em;text-transform:uppercase}}
    h1{{margin:0;font:600 38px/1.12 var(--font-display);letter-spacing:-.045em}}
    .intro-copy>p:last-child{{margin:0;color:var(--muted);font-size:15px;line-height:1.7}}
    .intro-grid{{display:grid;gap:12px}}
    .info-card{{padding:16px 18px;border:1px solid var(--line);border-radius:var(--radius-panel);background:#fff}}
    .info-card strong{{display:block;margin:0 0 6px;font:600 13px/1.35 var(--font-display);letter-spacing:-.01em}}
    .info-card p{{margin:0;color:var(--muted);font-size:12px;line-height:1.65}}
    .login{{display:grid;place-items:center;padding:52px 56px}}
    .form-wrap{{width:min(388px,100%)}}
    .form-wrap h2{{margin:0 0 10px;font:600 30px/1.14 var(--font-display);letter-spacing:-.04em}}
    .sub{{margin:0 0 30px;color:var(--muted);font-size:14px;line-height:1.65}}
    label{{display:block;margin:0 0 10px;font-size:12px;font-weight:600;letter-spacing:.01em}}
    .field{{display:grid;gap:12px}}
    input{{width:100%;height:52px;padding:0 15px;border:1px solid var(--line-strong);border-radius:var(--radius-control);background:#fff;color:var(--ink);outline:none;transition:border-color .15s ease,box-shadow .15s ease,background .15s ease}}
    input::placeholder{{color:#a0a6b4}}
    input:hover{{border-color:#c9cfdb}}
    input:focus{{border-color:var(--accent);box-shadow:0 0 0 4px var(--accent-soft)}}
    button{{width:100%;height:52px;margin-top:4px;border:1px solid transparent;border-radius:var(--radius-control);background:var(--accent);color:#fff;font-weight:600;letter-spacing:-.01em;cursor:pointer;transition:background .15s ease,transform .15s ease,box-shadow .15s ease}}
    button:hover{{background:var(--accent-strong);box-shadow:0 10px 22px rgba(93,97,213,.16)}}
    button:focus-visible{{outline:none;box-shadow:0 0 0 4px var(--accent-soft)}}
    button:active{{transform:translateY(1px)}}
    .security{{display:flex;align-items:flex-start;gap:9px;margin:18px 0 0;color:var(--quiet);font-size:12px;line-height:1.65}}
    .security svg{{width:15px;height:15px;flex:0 0 15px;margin-top:2px;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}}
    .notice{{margin:0 0 18px;padding:12px 14px;border:1px solid #eedfc2;border-radius:var(--radius-control);background:var(--warning-bg);color:var(--warning-ink);font-size:13px;line-height:1.55}}
    .meta{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:22px;padding-top:16px;border-top:1px solid var(--line);color:var(--quiet);font-size:11px}}
    .meta code{{font:12px/1 var(--font-mono);color:var(--muted)}}
    @media(max-width:920px){{.window{{grid-template-columns:1fr}}.intro{{padding:34px;border-right:0;border-bottom:1px solid var(--line)}}.login{{padding:42px 34px}}}}
    @media(max-width:720px){{body{{padding:0;background:#fff}}.window{{min-height:100vh;border:0;border-radius:0;box-shadow:none}}.intro{{gap:22px;padding:28px 24px;background:#f8f9fb}}.intro-copy{{max-width:none}}h1{{font-size:30px}}.login{{padding:28px 24px 32px}}.form-wrap h2{{font-size:28px}}.meta{{display:grid;justify-content:stretch}}}}
  </style>
</head>
<body>
  <main class="window">
    <section class="intro" aria-label="WordYeah 图像审核">
      <div class="brand"><span class="brand-mark">wy</span><span>wordyeah</span></div>
      <div class="intro-copy">
        <p class="eyebrow">Review operations</p>
        <h1>审核工作台</h1>
        <p>登录页只提供会话验证、访问控制与工作台入口。自动审核流水线继续在后台运行，人工处理范围保持可追踪。</p>
      </div>
      <div class="intro-grid">
        <div class="info-card">
          <strong>会话范围</strong>
          <p>登录后仅展示需要人工接手的异常、分歧与仲裁结果，不重复展示自动通过的正常流量。</p>
        </div>
        <div class="info-card">
          <strong>访问约束</strong>
          <p>审核令牌与会话状态单独校验；原始媒体与敏感记录不会写入浏览器持久存储。</p>
        </div>
      </div>
    </section>
    <section class="login">
      <div class="form-wrap">
        <h2>进入审核工作台</h2>
        <p class="sub">使用审核凭据访问受控图片与决策记录。</p>
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
