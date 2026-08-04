from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from typing import Iterable
from urllib.parse import urlencode

from wy_review.store import ReviewEvent, ReviewItem

LANE_ORDER: tuple[str, ...] = ("auto-approve", "auto-reject", "escalate", "error")
RISK_ORDER: tuple[str, ...] = ("low", "guarded", "elevated", "critical")


CSS = """
:root {
  color-scheme: light;
  --page: #f3f4f7;
  --page-wash: #f8f9fc;
  --app: #ffffff;
  --sidebar: #f8f9fc;
  --panel: #ffffff;
  --panel-soft: #f8f9fc;
  --panel-muted: #f1f2f7;
  --line: #e7e9f0;
  --line-strong: #cfd3df;
  --text: #20222d;
  --muted: #6f7483;
  --quiet: #9ba1b0;
  --accent: #5f63df;
  --accent-soft: rgba(95, 99, 223, 0.09);
  --green: #16a34a;
  --green-soft: rgba(22, 163, 74, 0.08);
  --amber: #d97706;
  --amber-soft: rgba(217, 119, 6, 0.08);
  --red: #dc2626;
  --red-soft: rgba(220, 38, 38, 0.08);
  --shadow-sm: 0 1px 3px rgba(15, 23, 42, 0.05);
  --shadow-md: 0 4px 16px rgba(15, 23, 42, 0.07);
  --shadow-app: 0 24px 64px rgba(15, 23, 42, 0.08);
  --shadow-sticky: 0 8px 22px rgba(15, 23, 42, 0.08);
  --shadow-floating: 0 12px 30px rgba(15, 23, 42, 0.16);
  --shadow-overlay: 0 28px 72px rgba(0, 0, 0, 0.28);
  --radius-app: 24px;
  --radius-panel: 14px;
  --radius-card: 12px;
  --radius-control: 10px;
  --space-3xs: 2px;
  --space-2xs: 4px;
  --space-xs: 8px;
  --space-sm: 12px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;
  --space-2xl: 48px;
  --font-display: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  --font: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  --font-body: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  --mono: "SF Mono", "JetBrains Mono", "Fira Code", ui-monospace, Menlo, Monaco, Consolas, monospace;
}

:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #090a0f;
  --page-wash: #0e1017;
  --app: #12141d;
  --sidebar: #0e1018;
  --panel: #161824;
  --panel-soft: #1b1e2e;
  --panel-muted: #222638;
  --line: #222638;
  --line-strong: #333852;
  --text: #f8fafc;
  --muted: #94a3b8;
  --quiet: #64748b;
  --accent: #6f74ff;
  --accent-soft: rgba(111, 116, 255, 0.16);
  --green: #4ade80;
  --green-soft: rgba(74, 222, 128, 0.14);
  --amber: #fbbf24;
  --amber-soft: rgba(251, 191, 36, 0.14);
  --red: #f87171;
  --red-soft: rgba(248, 113, 113, 0.14);
  --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.3);
  --shadow-md: 0 4px 16px rgba(0, 0, 0, 0.35);
  --shadow-app: 0 24px 64px rgba(0, 0, 0, 0.5);
  --shadow-sticky: 0 8px 22px rgba(0, 0, 0, 0.28);
  --shadow-floating: 0 12px 30px rgba(0, 0, 0, 0.38);
  --shadow-overlay: 0 28px 72px rgba(0, 0, 0, 0.56);
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; background: var(--page); }
body {
  min-width: 320px;
  min-height: 100vh;
  margin: 0;
  background: var(--page);
  color: var(--text);
  font-family: var(--font);
  font-size: 14px;
  line-height: 1.55;
  font-feature-settings: "kern" 1, "liga" 1;
  text-rendering: optimizeLegibility;
}

a { color: inherit; }
button, input, textarea, select { font: inherit; color: var(--text); }
img { display: block; max-width: 100%; }
code, .mono { font-family: var(--mono); }
.brand, h1, h2, h3, button, .page-tabs, .view-switch { font-family: var(--font-display); }
.tabular { font-variant-numeric: tabular-nums; }
button, a { -webkit-tap-highlight-color: transparent; }

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.skip-link {
  position: fixed;
  z-index: 20;
  top: 16px;
  left: 16px;
  padding: 9px 13px;
  border-radius: 10px;
  background: var(--text);
  color: var(--panel);
  transform: translateY(-180%);
  text-decoration: none;
  font-weight: 700;
}
.skip-link:focus { transform: translateY(0); }

.app-frame {
  width: 100%;
  min-height: 100vh;
  margin: 0;
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  border: 0;
  border-radius: 0;
  background: var(--app);
  box-shadow: none;
  isolation: isolate;
  transition: width 200ms ease, margin 200ms ease, border-radius 200ms ease, box-shadow 200ms ease;
}

:root[data-layout="boxed"] .app-frame {
  width: min(1360px, calc(100vw - 48px));
  min-height: calc(100vh - 48px);
  margin: 24px auto;
  overflow: clip;
  border: 1px solid var(--line);
  border-radius: var(--radius-app);
  box-shadow: var(--shadow-app);
}

:root[data-layout="boxed"] .queue-list[data-view="grid"] {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.side-nav {
  display: flex;
  min-height: 100%;
  flex-direction: column;
  gap: var(--space-lg);
  padding: 24px 16px 20px;
  background: var(--sidebar);
  border-right: 1px solid var(--line);
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 6px;
  color: var(--text);
  text-decoration: none;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.035em;
}

.brand-mark {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border-radius: 10px;
  background: var(--accent);
  color: #ffffff;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: -0.06em;
}

.nav-section {
  display: grid;
  gap: 4px;
}

.nav-scroll {
  display: grid;
  gap: 20px;
}

.nav-label {
  margin: 0 8px 6px;
  color: var(--quiet);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.nav-item {
  display: flex;
  min-height: 38px;
  align-items: center;
  gap: 10px;
  padding: 7px 12px;
  border-radius: var(--radius-control);
  color: var(--muted);
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  transition: background 140ms ease, color 140ms ease;
}

.nav-item:hover,
.nav-item:focus-visible {
  background: var(--panel-soft);
  color: var(--text);
}

.nav-item.is-active {
  background: var(--panel);
  color: var(--accent);
  font-weight: 600;
}

.nav-icon {
  display: grid;
  width: 18px;
  height: 18px;
  place-items: center;
  flex: 0 0 18px;
  color: currentColor;
}

.nav-icon svg,
.top-icon svg {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.6;
}

.nav-count {
  min-width: 24px;
  margin-left: auto;
  padding: 2px 7px;
  border-radius: 999px;
  background: var(--panel-muted);
  color: var(--text);
  font-size: 11px;
  text-align: center;
}

.nav-spacer { flex: 1; }

.usage-card {
  display: grid;
  gap: 12px;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: var(--panel);
  box-shadow: none;
}

.usage-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.usage-card-head strong {
  font-size: 13px;
  font-weight: 750;
  letter-spacing: -0.02em;
}

.usage-card p {
  margin: -4px 0 2px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}

.usage-icon {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 9px;
  background: var(--accent-soft);
  color: var(--accent);
}

.usage-icon svg {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
}

.usage-line,
.usage-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: var(--muted);
  font-size: 12px;
}

.usage-line strong { color: var(--text); font-family: var(--mono); font-size: 11px; }

.usage-bar {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--panel-muted);
}

.usage-bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
}

.usage-upgrade-btn {
  display: inline-flex;
  min-height: 32px;
  align-items: center;
  justify-content: center;
  width: 100%;
  margin-top: 4px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-soft);
  color: var(--text);
  font-size: 12px;
  font-weight: 680;
  text-decoration: none;
  transition: background-color 140ms ease, border-color 140ms ease;
}
.usage-upgrade-btn:hover {
  background: var(--panel);
  border-color: var(--line-strong);
}

.status-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  border-radius: 50%;
  background: var(--green);
}
.status-dot.is-danger { background: var(--red); }

.theme-toggle-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--muted);
  font-size: 13px;
  cursor: pointer;
  transition: background-color 140ms ease, border-color 140ms ease;
}
.theme-toggle-btn:hover { background: var(--panel-soft); color: var(--text); }
:root[data-theme="dark"] .theme-icon-moon { display: none; }
:root[data-theme="dark"] .theme-icon-sun { display: inline; }
:root:not([data-theme="dark"]) .theme-icon-sun { display: none; }
:root:not([data-theme="dark"]) .theme-icon-moon { display: inline; }
.theme-icon-sun,
.theme-icon-moon {
  width: 18px;
  height: 18px;
  place-items: center;
  line-height: 0;
}
:root[data-theme="dark"] .theme-icon-sun,
:root:not([data-theme="dark"]) .theme-icon-moon { display: grid; }

.consumer-switcher {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 10px 0;
  border-top: 1px solid var(--line);
  cursor: pointer;
}

.consumer-avatar {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border-radius: 50%;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  font-weight: 800;
}

.consumer-copy {
  display: grid;
  min-width: 0;
}

.consumer-copy strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.consumer-copy small {
  color: var(--quiet);
  font-size: 11px;
}

.chevron {
  margin-left: auto;
  color: var(--quiet);
  font-size: 13px;
}

.app-main {
  min-width: 0;
  background: var(--app);
}

.topbar {
  min-height: 72px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 28px;
  border-bottom: 1px solid var(--line);
  background: var(--app);
}

.toolbar-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

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

.toolbar-title span {
  color: var(--quiet);
  font-size: 12px;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.topbar-icon {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--muted);
  text-decoration: none;
}
.topbar-icon:hover,
.topbar-icon:focus-visible { background: var(--panel-soft); color: var(--accent); }
.topbar-icon svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.topbar-icon[data-tone="danger"] { color: var(--red); }

.pipeline-chip,
.toolbar-chip,
.toolbar-link,
.toolbar-logout button {
  display: inline-flex;
  min-height: 36px;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--panel);
  color: var(--muted);
  font-size: 12px;
  font-weight: 650;
  text-decoration: none;
}

.pipeline-chip[data-tone="ready"] {
  border-color: var(--line);
  background: var(--accent-soft);
  color: var(--accent);
}

.pipeline-chip[data-tone="danger"] {
  border-color: var(--line);
  background: var(--red-soft);
  color: var(--red);
}

.toolbar-chip {
  background: var(--panel-soft);
  color: var(--text);
}

.toolbar-link:hover,
.toolbar-link:focus-visible,
.toolbar-logout button:hover,
.toolbar-logout button:focus-visible {
  color: var(--text);
  border-color: var(--line-strong);
}

.toolbar-logout { margin: 0; }
.toolbar-logout button { cursor: pointer; }

.account-menu { position: relative; }
.account-menu summary {
  display: flex;
  min-height: 42px;
  align-items: center;
  gap: 10px;
  padding: 4px 7px 4px 5px;
  border-radius: 999px;
  color: var(--text);
  cursor: pointer;
  list-style: none;
  font-size: 13px;
  font-weight: 620;
}
.account-menu summary::-webkit-details-marker { display: none; }
.reviewer-avatar {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border-radius: 50%;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  font-weight: 750;
}
.account-popover {
  position: absolute;
  z-index: 10;
  top: calc(100% + 9px);
  right: 0;
  width: 210px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--panel);
  box-shadow: var(--shadow-floating);
}
.account-popover p { margin: 0 0 10px; color: var(--muted); font-size: 12px; }
.account-popover .toolbar-logout button { width: 100%; justify-content: center; border-radius: 10px; }

.shell {
  max-width: 1260px;
  margin: 0 auto;
  padding: 32px 36px 48px;
}

.shell.shell-focus {
  max-width: 1320px;
  padding-top: 16px;
}

.page-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
}

.page-heading-copy { max-width: 720px; }

.support-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--line);
}
.support-hero-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.support-hero h1 {
  margin: 0;
  color: var(--text);
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.2;
}
.header-count-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
}

.status-dot-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--panel);
  color: var(--muted);
  font-size: 11px;
  font-weight: 600;
}
.status-dot-pill .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--green);
}
.status-dot-pill[data-tone="danger"] .dot {
  background: var(--red);
}
.status-pill[data-tone="success"] {
  border-color: var(--line);
  background: var(--green-soft);
  color: var(--green);
}
.status-pill[data-tone="danger"] {
  border-color: var(--line);
  background: var(--red-soft);
  color: var(--red);
}

.intent-note {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--quiet);
  font-size: 11px;
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--accent);
  font-size: 10px;
  font-weight: 850;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.page-heading h1 {
  margin: 0;
  font-size: clamp(28px, 2.8vw, 36px);
  font-weight: 700;
  letter-spacing: -0.05em;
  line-height: 1.1;
}

.page-heading p:not(.eyebrow) {
  margin: 12px 0 0;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.6;
}

.heading-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.button {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0 16px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--panel);
  color: var(--text);
  text-decoration: none;
  font-size: 13px;
  font-weight: 700;
}

.button:hover,
.button:focus-visible { border-color: var(--line-strong); }

.button.primary {
  border-color: var(--text);
  background: var(--text);
  color: var(--panel);
}

.context-line {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 24px;
}

.context-pill {
  display: inline-flex;
  min-height: 34px;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  border-radius: 999px;
  background: var(--panel-soft);
  color: var(--muted);
  font-size: 12px;
}

.context-pill strong { color: var(--text); font-weight: 720; }

.agent-note {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  margin-top: 24px;
  padding: 18px 20px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: var(--panel-soft);
}

.agent-badge {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  flex: 0 0 32px;
  border-radius: 11px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
  font-weight: 900;
}

.agent-note-copy {
  display: grid;
  gap: 4px;
}

.agent-note-copy strong {
  font-size: 14px;
  letter-spacing: -0.02em;
}

.agent-note-copy span {
  color: var(--muted);
  font-size: 13px;
}

.queue-section { margin-top: 16px; }
.queue-section.is-primary { margin-top: 0; }

.queue-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.queue-head h2 {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.04em;
}

.queue-head p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.queue-count {
  display: grid;
  justify-items: end;
  gap: 2px;
  min-width: 120px;
}

.queue-count strong {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.05em;
}

.queue-count span {
  color: var(--quiet);
  font-size: 12px;
}

.page-tabs {
  display: flex;
  align-items: center;
  gap: 26px;
  margin-top: 16px;
  padding-bottom: 2px;
  border-bottom: 1px solid var(--line);
}

.page-tabs a {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  color: var(--muted);
  text-decoration: none;
  font-size: 13px;
  font-weight: 650;
}

.page-tabs a:hover,
.page-tabs a.is-active { color: var(--text); }

.page-tabs a.is-active::after {
  position: absolute;
  right: 0;
  bottom: -3px;
  left: 0;
  height: 2px;
  border-radius: 2px;
  background: var(--accent);
  content: "";
}

.page-tabs span {
  min-width: 22px;
  padding: 2px 7px;
  border-radius: 999px;
  background: var(--panel-muted);
  color: var(--quiet);
  font-size: 11px;
  text-align: center;
}

.page-tabs a.is-active span {
  background: var(--panel);
  color: var(--text);
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.search-control,
.filter-control,
.filter-submit {
  min-height: 36px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
  color: var(--text);
  font-size: 13px;
}

.search-control {
  display: flex;
  min-width: min(360px, 100%);
  flex: 1 1 320px;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
}

.search-control svg {
  width: 15px;
  height: 15px;
  flex: 0 0 15px;
  color: var(--quiet);
}

.search-control input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text);
}

.search-control input::placeholder { color: var(--quiet); }

.filter-control {
  min-width: 138px;
  padding: 0 34px 0 12px;
  color: var(--text);
  appearance: none;
  background: var(--panel);
}

.filter-submit {
  padding: 0 16px;
  color: var(--text);
  font-weight: 700;
  cursor: pointer;
}

.filter-submit:hover,
.filter-submit:focus-visible {
  border-color: var(--line-strong);
  background: var(--panel-soft);
}

.queue-list-head { display: none; }

.queue-list {
  overflow: hidden;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: var(--app);
}

.queue-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 28px;
  margin: 12px 0 4px;
}

.queue-tool-note { color: var(--quiet); font-size: 11px; }

.view-switch {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--panel-soft);
}

.view-switch a {
  display: inline-flex;
  min-height: 34px;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  border-radius: 8px;
  color: var(--muted);
  text-decoration: none;
  font-size: 12px;
  font-weight: 680;
}

.view-switch a:hover,
.view-switch a.is-active {
  background: var(--panel);
  color: var(--text);
}

.batch-toggle {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel);
  color: var(--muted);
  text-decoration: none;
  font-size: 12px;
  font-weight: 680;
}

.batch-toggle:hover,
.batch-toggle.is-active { border-color: var(--line-strong); background: var(--panel-muted); color: var(--text); }

.batch-bar {
  position: sticky;
  z-index: 6;
  top: 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin: 12px 0;
  padding: 10px 12px;
  border: 1px solid var(--line-strong);
  border-radius: 13px;
  background: var(--panel-soft);
  box-shadow: var(--shadow-sticky);
  backdrop-filter: blur(12px);
}

.batch-summary { display: flex; align-items: center; gap: 10px; color: var(--muted); font-size: 12px; }
.batch-summary strong { color: var(--accent); font-size: 13px; }
.batch-actions { display: flex; flex-wrap: wrap; gap: 7px; }
.batch-actions button {
  min-height: 32px;
  padding: 0 11px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--panel);
  color: var(--text);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.batch-actions button[value="approve"] { color: var(--green); }
.batch-actions button[value="reject"] { color: var(--amber); }
.batch-actions button[value="blacklist"] { color: var(--red); }
.batch-actions button[value="hold"] { color: var(--amber); }

.filtered-count {
  color: var(--quiet);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.batch-result {
  margin-top: 12px;
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--panel-soft);
  color: var(--muted);
  font-size: 12px;
}

.review-card.is-batch {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  align-items: stretch;
}

.batch-check {
  display: grid;
  place-items: center;
  border-right: 1px solid var(--line);
  background: var(--panel-soft);
  cursor: pointer;
  border-top-left-radius: 16px;
  border-bottom-left-radius: 16px;
}
.batch-check input { width: 16px; height: 16px; accent-color: var(--accent); }

.review-card {
  margin-bottom: 8px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
  transition: background-color 120ms ease, border-color 120ms ease;
}

.review-card:hover {
  background: var(--panel-soft);
  border-color: var(--line-strong);
}

.review-card.is-focused {
  border-color: var(--line-strong);
  border-left-width: 3px;
  background: var(--panel-soft);
}

.row-identity { display: grid; gap: 2px; }
.row-id-tag {
  display: inline-block;
  width: fit-content;
  padding: 2px 6px;
  margin-bottom: 2px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel-soft);
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 11px;
}

.review-row-link {
  display: grid;
  grid-template-columns: 64px minmax(160px, 1.2fr) minmax(200px, 2fr) minmax(130px, 1fr) 28px;
  gap: 14px;
  align-items: center;
  min-height: 80px;
  padding: 10px 16px;
  color: inherit;
  text-decoration: none;
}

.row-preview {
  position: relative;
  width: 58px;
  height: 58px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel-muted);
  flex: 0 0 58px;
}

.row-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.queue-list[data-view="grid"] {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  padding: 8px 0;
  border-bottom: 0;
  background: transparent;
}
@media (max-width: 1150px) {
  .queue-list[data-view="grid"] { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 800px) {
  .queue-list[data-view="grid"] { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

.queue-list[data-view="grid"] .review-card {
  margin-bottom: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--panel);
}

.queue-list[data-view="grid"] .review-card.is-batch { grid-template-columns: 1fr; }
.queue-list[data-view="grid"] .batch-check { min-height: 36px; border-right: 0; border-bottom: 1px solid var(--line); border-radius: 0; place-items: center start; padding: 0 12px; }
.queue-list[data-view="grid"] .review-row-link {
  display: grid;
  grid-template-columns: 1fr 24px;
  gap: 12px;
  min-height: 0;
  padding: 14px;
}
.queue-list[data-view="grid"] .row-preview { grid-column: 1 / -1; width: 100%; height: auto; aspect-ratio: 4 / 3; border-radius: var(--radius-control); }
.queue-list[data-view="grid"] .row-identity,
.queue-list[data-view="grid"] .row-ai { grid-column: 1 / -1; }
.queue-list[data-view="grid"] .row-ai > span { display: none; }
.queue-list[data-view="grid"] .row-decision { grid-column: 1; grid-row: auto; display: flex; align-items: center; justify-content: space-between; }
.queue-list[data-view="grid"] .row-open { grid-column: 2; align-self: center; }

.focus-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.focus-nav-group { display: flex; gap: 8px; }
.focus-nav a {
  display: inline-flex;
  min-height: 34px;
  align-items: center;
  padding: 0 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel);
  color: var(--muted);
  text-decoration: none;
  font-size: 12px;
  font-weight: 680;
}
.focus-shortcuts { color: var(--quiet); font-size: 11px; }

.row-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.media-fallback {
  display: grid;
  width: 100%;
  height: 100%;
  place-items: center;
  color: var(--quiet);
  background: var(--panel-muted);
  font-size: 12px;
  text-align: center;
}

.media-fallback span {
  padding: 6px 10px;
  border-radius: 7px;
  background: transparent;
}

.avatar-state {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--panel-muted);
}
.avatar-state img { width: 100%; height: 100%; object-fit: cover; }
.avatar-state.is-blocked img { opacity: 1; }

.row-risk-dot {
  position: absolute;
  right: 8px;
  bottom: 8px;
  width: 10px;
  height: 10px;
  border: 2px solid var(--panel);
  border-radius: 50%;
  background: var(--green);
}
.row-risk-dot.risk-guarded { background: var(--accent); }
.row-risk-dot.risk-elevated { background: var(--amber); }
.row-risk-dot.risk-critical { background: var(--red); }

.row-identity,
.row-ai,
.row-decision {
  display: grid;
  min-width: 0;
  gap: 5px;
}

.row-identity strong,
.row-ai strong,
.row-decision strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 720;
}

.row-id,
.row-time,
.row-ai > span:not(.column-label) {
  overflow: hidden;
  color: var(--muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-id {
  color: var(--quiet);
  font-family: var(--mono);
}

.column-label {
  color: var(--quiet);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}

.row-identity .column-label,
.row-ai .column-label { display: none; }

.row-decision {
  display: flex;
  align-items: center;
  gap: 10px;
}

.row-decision small {
  color: var(--muted);
  font-size: 11px;
  white-space: nowrap;
}

.status-pill {
  display: inline-flex;
  width: max-content;
  min-height: 24px;
  align-items: center;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 800;
}

.status-pill.status-pending { background: var(--accent-soft); color: var(--accent); }
.status-pill.status-held { background: var(--amber-soft); color: var(--amber); }
.status-pill.status-approved { background: var(--green-soft); color: var(--green); }
.status-pill.status-rejected { background: var(--red-soft); color: var(--red); }

.risk-label {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  padding: 0 8px;
  border-radius: 6px;
  background: var(--panel-muted);
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
}
.risk-label.risk-low { background: var(--green-soft); color: var(--green); }
.risk-label.risk-guarded { background: var(--accent-soft); color: var(--accent); }
.risk-label.risk-elevated { background: var(--amber-soft); color: var(--amber); }
.risk-label.risk-critical { background: var(--red-soft); color: var(--red); }

.row-confidence strong { font-size: 16px; letter-spacing: -0.04em; }

.row-open {
  display: grid;
  width: 20px;
  height: 20px;
  place-items: center;
  color: var(--quiet);
}
.row-open svg { width: 16px; height: 16px; }
.review-row-link:hover .row-open { color: var(--text); }

.detail-return {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 0;
  color: var(--muted);
  font-size: 12px;
}
.detail-return a { color: var(--text); font-weight: 700; text-decoration: none; }

.review-detail {
  margin-top: 16px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--panel);
}

.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 28px 30px 22px;
  border-bottom: 1px solid var(--line);
}

.detail-kicker {
  margin: 0 0 6px;
  color: var(--accent);
  font-size: 11px;
  font-weight: 720;
}

.detail-header h2 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.045em;
}

.detail-header p:not(.detail-kicker) {
  margin: 8px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.detail-close {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border-radius: 10px;
  color: var(--quiet);
}
.detail-close svg {
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  stroke-width: 1.8;
}

.detail-close:hover,
.detail-close:focus-visible {
  background: var(--panel-soft);
  color: var(--text);
}

.detail-layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 0;
}

.detail-sidebar {
  display: grid;
  align-content: start;
  gap: 18px;
  padding: 28px;
  border-right: 1px solid var(--line);
  background: var(--panel-soft);
}

.sidebar-section {
  padding-bottom: 16px;
  border-bottom: 1px solid var(--line);
}
.sidebar-section:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.sidebar-section h3,
.detail-stage h3 {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 740;
  letter-spacing: -0.02em;
}

.metadata-details > summary {
  cursor: pointer;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  list-style: none;
}
.metadata-details > summary::-webkit-details-marker { display: none; }
.metadata-details > summary::after { content: "＋"; float: right; color: var(--quiet); }
.metadata-details[open] > summary::after { content: "−"; }
.metadata-details .detail-facts { margin-top: 14px; }

.sidebar-note {
  color: var(--muted);
  font-size: 12px;
}

.detail-facts {
  display: grid;
  gap: 12px;
}

.detail-facts.summary-facts {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 12px;
}

.detail-fact {
  display: grid;
  gap: 4px;
}

.detail-fact .label {
  color: var(--quiet);
  font-size: 11px;
  font-weight: 650;
}

.detail-fact .value {
  overflow: hidden;
  color: var(--text);
  font-size: 13px;
  text-overflow: ellipsis;
  word-break: break-word;
}

.detail-stage {
  display: grid;
  gap: 22px;
  padding: 28px 30px 32px;
}

.preview-panel {
  display: grid;
  gap: 14px;
}

.detail-section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.detail-chip {
  display: inline-flex;
  min-height: 30px;
  align-items: center;
  padding: 0 11px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--panel-soft);
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
}

.media-preview {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-muted);
}

.preview-wrapper {
  position: relative;
  overflow: hidden;
  display: flex;
  justify-content: center;
  align-items: center;
}

.preview-image-button {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: zoom-in;
}

.preview-image-button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -3px;
}

.media-preview img {
  width: 100%;
  max-height: clamp(280px, calc(100vh - 580px), 380px);
  object-fit: contain;
  background: transparent;
  transition: filter 200ms ease;
}

.media-preview.is-sensitive-blur img {
  filter: blur(18px) scale(1.05);
}

.preview-unblur-toggle {
  position: absolute;
  z-index: 5;
  top: 14px;
  right: 14px;
  padding: 6px 12px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--panel-soft);
  color: var(--text);
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  backdrop-filter: blur(8px);
  box-shadow: none;
}

.preview-unblur-toggle:hover {
  background: var(--panel);
}

.score-bar-track {
  width: 100%;
  height: 5px;
  margin: 6px 0;
  border-radius: 999px;
  background: var(--panel-muted);
  overflow: hidden;
}

.score-bar-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  transition: width 300ms ease;
}

.score-bar-fill.tone-green { background: var(--green); }
.score-bar-fill.tone-amber { background: var(--amber); }
.score-bar-fill.tone-danger { background: var(--red); }

.inline-analytics-strip {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 16px;
  padding: 8px 14px;
  border-radius: 10px;
  background: var(--panel-soft);
  color: var(--muted);
  font-size: 12px;
}

.inline-analytics-strip .stat-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.inline-analytics-strip .lbl { color: var(--muted); font-size: 12px; }
.inline-analytics-strip .val { color: var(--text); font-weight: 750; font-variant-numeric: tabular-nums; }
.inline-analytics-strip .sep { color: var(--line-strong); opacity: 0.6; }

.control-dock {
  display: grid;
  gap: 16px;
  margin-bottom: 0;
}
.control-dock > .page-tabs { margin: 0; }

.control-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.control-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
}

.control-dock .filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
}

.search-box {
  position: relative;
  display: flex;
  align-items: center;
}
.search-box svg {
  position: absolute;
  left: 10px;
  width: 14px;
  height: 14px;
  color: var(--quiet);
  pointer-events: none;
}
.search-box input {
  min-height: 40px;
  width: 224px;
  padding: 0 28px 0 30px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  color: var(--text);
  font-size: 12px;
  outline: 0;
  transition: border-color 140ms ease, width 140ms ease;
}
.search-box input:focus {
  border-color: var(--line-strong);
  width: 248px;
}
.search-kbd {
  position: absolute;
  right: 8px;
  padding: 1px 5px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--panel-muted);
  color: var(--quiet);
  font-family: var(--mono);
  font-size: 10px;
  pointer-events: none;
}

.select-pill {
  min-height: 40px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  color: var(--text);
  font-size: 12px;
  font-weight: 550;
  outline: 0;
  cursor: pointer;
}
.select-pill:hover { border-color: var(--line-strong); }

.finding-badge {
  display: inline-flex;
  padding: 2px 7px;
  margin-left: 6px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 750;
}

.finding-badge.badge-divergence {
  background: var(--amber-soft);
  color: var(--amber);
  border: 1px solid var(--line);
}

.preview-header-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--panel-soft);
}

.bg-mode-bar {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
}

.bg-mode-bar button {
  padding: 2px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.bg-mode-bar button:hover { color: var(--text); background: var(--panel-muted); }
.bg-mode-bar button.is-active {
  background: var(--panel-muted);
  color: var(--text);
  outline: 1px solid var(--line-strong);
  outline-offset: -1px;
}

.lightbox-trigger {
  display: inline-flex;
  min-height: 30px;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  color: var(--text);
  font-size: 11px;
  font-weight: 650;
  cursor: pointer;
}

.media-preview.bg-grid .preview-wrapper {
  background-color: #ffffff;
  background-image: repeating-conic-gradient(#eef1f5 0 25%, #ffffff 0 50%);
  background-position: 50%;
  background-size: 16px 16px;
}
.media-preview.bg-white .preview-wrapper { background: #ffffff; }
.media-preview.bg-black .preview-wrapper { background: #090a0f; }

.lightbox-modal {
  position: fixed;
  z-index: 200;
  inset: 0;
  display: none;
  place-items: center;
  padding: 24px;
  background: rgba(9, 10, 15, 0.78);
  backdrop-filter: blur(8px);
}
.lightbox-modal.is-open { display: grid; }
.lightbox-content {
  width: min(1180px, calc(100vw - 48px));
  height: min(820px, calc(100vh - 48px));
  display: grid;
  grid-template-rows: 52px minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: var(--panel);
  box-shadow: var(--shadow-overlay);
}
.lightbox-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 12px 0 18px;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
}
.lightbox-toolbar strong { font-size: 13px; font-weight: 700; }
.lightbox-zoom-hint { margin-left: 8px; color: var(--quiet); font-size: 11px; font-weight: 500; }
.lightbox-toolbar-actions { display: flex; align-items: center; gap: 4px; }
.lightbox-toolbar button {
  min-width: 34px;
  height: 34px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  color: var(--muted);
  cursor: pointer;
}
.lightbox-toolbar button:hover { background: var(--panel-muted); color: var(--text); }
.lightbox-close { font-size: 18px; line-height: 1; }
.lightbox-stage {
  position: relative;
  min-width: 0;
  min-height: 0;
  display: grid;
  place-items: center;
  overflow: auto;
  padding: 28px;
  background-color: var(--panel-muted);
}
.lightbox-stage.is-blocked::after {
  position: absolute;
  inset: 16px 16px auto auto;
  display: inline-flex;
  height: 26px;
  align-items: center;
  padding: 0 9px;
  border: 1px solid rgba(255, 255, 255, .72);
  border-radius: 7px;
  background: var(--red);
  color: #ffffff;
  content: "Cravatar 已屏蔽";
  font-size: 11px;
  font-weight: 700;
  line-height: 24px;
}
.lightbox-stage.is-blocked img { opacity: 1; }
.lightbox-stage img {
  display: block;
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  transform-origin: center center;
  transition: transform 120ms ease;
  box-shadow: none;
}

.keyboard-help-popover { position: relative; display: inline-block; }
.keyboard-help-btn {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  color: var(--muted);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  list-style: none;
  transition: all 140ms ease;
}
.keyboard-help-btn svg,
.view-switch a svg {
  width: 14px;
  height: 14px;
  stroke: currentColor;
  flex: 0 0 14px;
}
.theme-toggle-btn svg {
  width: 18px;
  height: 18px;
  stroke: currentColor;
  flex: 0 0 18px;
}
.keyboard-help-btn::-webkit-details-marker { display: none; }
.keyboard-help-btn:hover { border-color: var(--line-strong); color: var(--text); background: var(--panel-muted); }

.keyboard-popover-content {
  position: absolute;
  z-index: 50;
  top: calc(100% + 8px);
  bottom: auto;
  right: 0;
  width: 230px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--panel);
  backdrop-filter: blur(16px);
  box-shadow: var(--shadow-floating);
}
.keyboard-popover-content strong { display: block; margin-bottom: 8px; font-size: 12px; color: var(--text); }
.keyboard-popover-content ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 6px; }
.keyboard-popover-content li { display: flex; align-items: center; justify-content: space-between; font-size: 11px; color: var(--muted); }
.keyboard-popover-content kbd {
  padding: 1px 5px;
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  background: var(--panel-muted);
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text);
}

.var-tag,
.replacement-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border-radius: 6px;
  background: var(--panel-muted);
  color: var(--accent);
  border: 1px solid var(--line);
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.replacement-badge[data-type="purple"] {
  background: rgba(108, 114, 244, 0.12);
  color: var(--accent);
  border-color: var(--line);
}
.replacement-badge[data-type="pink"] {
  background: rgba(224, 91, 109, 0.12);
  color: var(--red);
  border-color: var(--line);
}
.replacement-badge[data-type="amber"] {
  background: rgba(217, 142, 50, 0.12);
  color: var(--amber);
  border-color: var(--line);
}

.floating-status-dock {
  position: fixed;
  z-index: 100;
  bottom: 24px;
  right: 24px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border: 1px solid var(--line-strong);
  border-radius: 14px;
  background: var(--panel);
  box-shadow: var(--shadow-floating);
  backdrop-filter: blur(16px);
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
  animation: floatDockSlideIn 300ms cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes floatDockSlideIn {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

.dock-progress-ring {
  position: relative;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  font-family: var(--mono);
  font-size: 9px;
  font-weight: 800;
  color: var(--accent);
}

.dock-progress-ring svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}

.dock-progress-ring circle {
  fill: none;
  stroke-width: 2.5;
  stroke-linecap: round;
}

.dock-progress-ring .bg { stroke: var(--panel-muted); }
.dock-progress-ring .meter {
  stroke: var(--accent);
  stroke-dasharray: 63;
  stroke-dashoffset: 20;
  transition: stroke-dashoffset 300ms ease;
}

.dock-copy { display: grid; gap: 2px; }
.dock-copy strong { font-size: 12px; color: var(--text); }
.dock-copy small { font-size: 10.5px; color: var(--quiet); }

.dock-actions { display: flex; align-items: center; gap: 6px; margin-left: 6px; }
.dock-actions button,
.dock-actions a {
  padding: 4px 9px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--panel-soft);
  color: var(--muted);
  font-size: 11px;
  font-weight: 650;
  cursor: pointer;
  text-decoration: none;
}
.dock-actions button:hover,
.dock-actions a:hover { color: var(--text); background: var(--panel-muted); }

.action-form {
  position: sticky;
  z-index: 4;
  bottom: 16px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px 14px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-panel);
  background: var(--panel);
  box-shadow: none;
}

.action-form label {
  grid-column: 1;
  grid-row: 1;
  color: var(--quiet);
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0;
}

.action-form input[type="text"] {
  grid-column: 1 / -1;
  grid-row: 2;
  width: 100%;
  min-height: 42px;
  padding: 0 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  outline: 0;
  background: var(--panel-soft);
  color: var(--text);
}

.action-form input[type="text"]:focus {
  border-color: var(--line-strong);
  box-shadow: 0 0 0 3px var(--panel-muted);
}

.action-caption {
  grid-column: 2;
  grid-row: 1;
  text-align: right;
  color: var(--muted);
  font-size: 12px;
}

.action-buttons {
  grid-column: 1 / -1;
  grid-row: 3;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr)) 40px 40px;
  gap: 8px;
}

.action-buttons button {
  width: 100%;
  min-height: 40px;
  padding: 0 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: var(--panel);
  color: var(--text);
  font-size: 13px;
  font-weight: 720;
  cursor: pointer;
}

.action-buttons button:hover,
.action-buttons button:focus-visible { border-color: var(--line-strong); }

.action-buttons .is-icon-only {
  padding: 0;
}

.action-buttons .is-icon-only svg {
  width: 17px;
  height: 17px;
}

.action-buttons button[data-action="approve"] {
  border-color: transparent;
  background: var(--green);
  color: white;
}

.action-buttons button[data-action="reject"] {
  border-color: var(--line);
  background: var(--panel-soft);
  color: var(--amber);
}

.action-buttons button[data-action="blacklist"] {
  border-color: color-mix(in srgb, var(--red) 42%, var(--line));
  background: var(--panel);
  color: var(--red);
}

.action-buttons button[data-action="hold"] {
  border-color: var(--line);
  background: var(--panel-soft);
  color: var(--muted);
}

.evidence-block.detail-findings {
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}
.detail-findings .finding-list {
  gap: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 10px;
}
.detail-findings .finding-item {
  border: 0;
  border-bottom: 1px solid var(--line);
  border-radius: 0;
}
.detail-findings .finding-item:last-child { border-bottom: 0; }

.completed-state {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--panel-soft);
  color: var(--muted);
  font-size: 13px;
}

.queue-intro { margin: 5px 0 0; color: var(--muted); font-size: 13px; }
.preview-header-tools svg,
.preview-unblur-toggle svg { width: 15px; height: 15px; }
.lightbox-trigger kbd { margin-left: 3px; }

.action-buttons button[data-action="retry"] {
  grid-column: 1 / -1;
  border-color: var(--line);
  background: var(--panel-muted);
  color: var(--text);
}

.evidence-block {
  padding: 20px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-soft);
}

.finding-list,
.event-list {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.finding-item,
.event-item {
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
}

.finding-item .top,
.event-item .top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.finding-item .top strong,
.event-item .top strong { font-size: 13px; }

.finding-item .sub,
.event-item .sub,
.evidence-summary {
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
}

.audit-log,
.guide {
  margin-top: 24px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel);
}

.detail-audit {
  margin-top: 0;
  overflow: hidden;
}

.detail-audit > summary {
  display: flex;
  min-height: 46px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 14px;
  color: var(--text);
  cursor: pointer;
  font-size: 12px;
  font-weight: 650;
  list-style: none;
}

.detail-audit > summary::-webkit-details-marker { display: none; }
.audit-summary-main { display: inline-flex; align-items: center; gap: 8px; }
.audit-summary-main svg {
  width: 14px;
  height: 14px;
  flex: 0 0 14px;
  color: var(--quiet);
  transition: transform 140ms ease;
}
.detail-audit[open] .audit-summary-main svg { transform: rotate(90deg); }
.detail-audit .quiet { color: var(--quiet); font-size: 11px; font-weight: 500; }
.audit-summary-meta {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  padding-left: 12px;
  border-left: 1px solid var(--line);
  white-space: nowrap;
}
.audit-log-body { padding: 0 14px 14px; border-top: 1px solid var(--line); }
.detail-audit .event-list { gap: 0; }
.detail-audit .event-item {
  padding: 12px 0;
  border: 0;
  border-bottom: 1px solid var(--line);
  border-radius: 0;
}
.detail-audit .event-item:last-child { border-bottom: 0; }

@media (max-width: 980px) {
  .app-frame { grid-template-columns: 1fr; }
  .side-nav {
    position: sticky;
    z-index: 12;
    top: 0;
    min-height: 0;
    padding: 10px 14px;
    flex-direction: row;
    align-items: center;
    gap: 14px;
    border-right: 0;
    border-bottom: 1px solid var(--line);
    width: 100%;
    max-width: 100vw;
    min-width: 0;
    overflow: hidden;
  }
  .brand { flex: 0 0 auto; }
  .nav-scroll { display: flex; flex: 1 1 0; width: 0; min-width: 0; gap: 8px; overflow-x: auto; }
  .nav-scroll .nav-section { display: flex; gap: 4px; }
  .nav-label, .nav-spacer, .consumer-switcher { display: none; }
  .nav-item { flex: 0 0 auto; }
  .nav-count { display: none; }
  .shell { padding-inline: 24px; }
  .control-row { align-items: flex-start; flex-direction: column; }
  .control-actions { width: 100%; justify-content: space-between; }
}

@media (max-width: 760px) {
  .side-nav { position: static; padding: 8px 12px; }
  .brand span:last-child { display: none; }
  .brand { padding: 0; }
  .brand-mark { width: 30px; height: 30px; }
  .nav-scroll .nav-section:nth-child(2) { display: none; }
  .nav-scroll .nav-section {
    flex: 0 0 auto;
    overflow: visible;
  }

  .nav-label,
  .nav-spacer,
  .consumer-switcher { display: none; }

  .nav-item { flex: 0 0 auto; }
  .nav-count { display: none; }

  .topbar {
    min-height: 60px;
    padding: 12px 16px;
    align-items: flex-start;
    flex-direction: column;
  }

  .toolbar-actions { width: 100%; justify-content: flex-start; }
  .toolbar-actions .topbar-icon { display: none; }
  .shell { padding: 18px 16px 28px; }
  .page-heading,
  .queue-head,
  .detail-header { flex-direction: column; }
  .heading-actions { width: 100%; }
  .heading-actions .button { flex: 1; }
  .filter-bar { flex-wrap: wrap; align-items: stretch; }
  .search-control { flex-basis: 100%; }
  .filter-control, .filter-submit { flex: 1; min-width: 0; }
  .page-tabs { gap: 16px; overflow-x: auto; }
  .control-dock {
    gap: 12px;
  }
  .control-row { gap: 10px; }
  .control-dock .filter-bar { display: grid; grid-template-columns: minmax(0, 1fr) auto; width: 100%; }
  .control-dock .search-box,
  .control-dock .search-box input { width: 100%; min-width: 0; }
  .control-actions { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 6px; }
  .control-actions > .view-switch { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .control-actions > .view-switch a { justify-content: center; padding-inline: 7px; }
  .keyboard-help-btn span { display: none; }
  .queue-tool-note { display: none; }
  .queue-list-head { display: none; }
  .queue-list { overflow: visible; }
  .review-row-link {
    position: relative;
    min-width: 0;
    grid-template-columns: 72px minmax(0, 1fr) 20px;
    gap: 12px;
    padding: 12px;
  }
  .row-preview { width: 72px; height: 58px; }
  .row-ai { display: none; }
  .row-decision { grid-column: 2 / -1; display: flex; align-items: center; gap: 10px; }
  .row-open { position: absolute; right: 16px; top: 20px; }
  .detail-layout { grid-template-columns: 1fr; }
  .detail-stage { order: 1; }
  .detail-sidebar {
    order: 2;
    padding: 22px 20px;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .detail-stage { padding: 22px 20px 24px; }
  .media-preview img { max-height: 220px; }
  .detail-header { position: relative; padding-right: 64px; }
  .detail-header p:not(.detail-kicker) { overflow-wrap: anywhere; }
  .detail-close { position: absolute; top: 14px; right: 14px; }
  .review-detail { overflow: hidden; }
  .focus-nav { align-items: flex-start; flex-wrap: wrap; }
  .focus-shortcuts, .detail-return span { display: none; }
  .action-form {
    position: fixed;
    z-index: 30;
    right: 12px;
    bottom: max(6px, env(safe-area-inset-bottom));
    left: 12px;
    display: block;
    padding: 5px;
    border-radius: 10px;
    box-shadow: 0 -8px 26px rgba(15, 23, 42, 0.12);
  }
  .action-form > label,
  .action-form > input[type="text"],
  .action-form > .action-caption { display: none; }
  .action-buttons { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)) 38px 38px; gap: 8px; }
  .action-buttons button { min-width: 0; min-height: 34px; padding-inline: 6px; font-size: 12px; }
  .lightbox-modal { padding: 8px; }
  .lightbox-content { width: calc(100vw - 16px); height: calc(100vh - 16px); border-radius: 14px; }
  .lightbox-toolbar { padding-left: 12px; }
  .lightbox-toolbar strong { display: none; }
  .lightbox-stage { padding: 12px; }
}

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after {
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
"""


WORKBENCH_JS = r"""
(() => {
  // Toast notifications
  window.showToast = (message, tone = 'info') => {
    let container = document.querySelector('.toast-container');
    if (!container) {
      container = document.createElement('div');
      container.className = 'toast-container';
      document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `toast-item tone-${tone}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
      toast.classList.add('is-show');
    }, 10);
    setTimeout(() => {
      toast.classList.remove('is-show');
      setTimeout(() => toast.remove(), 250);
    }, 3000);
  };

  // Toggle layout and theme handlers
  document.addEventListener('click', (e) => {
    const layoutBtn = e.target.closest('[data-action="toggle-layout"]');
    if (layoutBtn) {
      e.preventDefault();
      const current = document.documentElement.getAttribute('data-layout') || 'fluid';
      const next = current === 'boxed' ? 'fluid' : 'boxed';
      if (next === 'boxed') {
        document.documentElement.setAttribute('data-layout', 'boxed');
      } else {
        document.documentElement.removeAttribute('data-layout');
      }
      localStorage.setItem('wy-layout', next);
      return;
    }
    const themeBtn = e.target.closest('[data-action="toggle-theme"]');
    if (themeBtn) {
      e.preventDefault();
      const current = document.documentElement.getAttribute('data-theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      const next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('wy-theme', next);
      return;
    }
  });

  // Batch Form handling (Single, clean initialization)
  const form = document.querySelector('[data-batch-form]');
  if (form) {
    let lastChecked = null;
    const boxes = [...form.querySelectorAll('input[name="selected"]')];
    const all = form.querySelector('[data-select-all]');
    const count = form.querySelector('[data-selected-count]');
    const sync = () => {
      const selected = boxes.filter((box) => box.checked).length;
      if (count) count.textContent = String(selected);
      if (all) {
        all.checked = boxes.length > 0 && selected === boxes.length;
        all.indeterminate = selected > 0 && selected < boxes.length;
      }
    };

    if (all) {
      all.addEventListener('change', () => {
        boxes.forEach((box) => { box.checked = all.checked; });
        sync();
      });
    }

    boxes.forEach((box, index) => {
      box.addEventListener('click', (e) => {
        if (e.shiftKey && lastChecked !== null && lastChecked !== index) {
          const start = Math.min(lastChecked, index);
          const end = Math.max(lastChecked, index);
          for (let i = start; i <= end; i++) {
            boxes[i].checked = box.checked;
          }
        }
        lastChecked = index;
        sync();
      });
    });

    form.addEventListener('submit', (event) => {
      const selected = boxes.filter((box) => box.checked).length;
      if (!selected) {
        event.preventDefault();
        window.showToast('请先选择审核项目。', 'warning');
        return;
      }
      const action = event.submitter?.value || '处理';
      if (!window.confirm(`确认对 ${selected} 个项目执行 ${action}？每项会独立写入审核记录。`)) {
        event.preventDefault();
      }
    });
    sync();
  }

  window.setPreviewBackground = (button, mode) => {
    const preview = button?.closest('.media-preview');
    if (!preview || !['grid', 'white', 'black'].includes(mode)) return;
    preview.classList.remove('bg-grid', 'bg-white', 'bg-black');
    preview.classList.add(`bg-${mode}`);
    preview.querySelectorAll('[data-preview-background]').forEach((entry) => {
      const active = entry === button;
      entry.classList.toggle('is-active', active);
      entry.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  };

  window.lightboxScale = 1;
  let lightboxBaseWidth = 0;

  window.setLightboxScale = (nextScale) => {
    const img = document.querySelector('#lightbox-img');
    if (!img) return;
    window.lightboxScale = Math.min(4, Math.max(0.5, Number(nextScale) || 1));
    if (!lightboxBaseWidth) lightboxBaseWidth = img.getBoundingClientRect().width || img.naturalWidth;
    img.style.maxWidth = 'none';
    img.style.maxHeight = 'none';
    img.style.width = `${Math.round(lightboxBaseWidth * window.lightboxScale)}px`;
    img.style.height = 'auto';
    const label = document.querySelector('[data-lightbox-scale]');
    if (label) label.textContent = `${Math.round(window.lightboxScale * 100)}%`;
  };

  window.zoomLightboxAtPoint = (nextScale, clientX, clientY) => {
    const stage = document.querySelector('.lightbox-stage');
    const img = document.querySelector('#lightbox-img');
    if (!stage || !img) return;
    const previousScale = window.lightboxScale || 1;
    const rect = stage.getBoundingClientRect();
    const pointX = clientX - rect.left + stage.scrollLeft;
    const pointY = clientY - rect.top + stage.scrollTop;
    window.setLightboxScale(nextScale);
    const ratio = window.lightboxScale / previousScale;
    stage.scrollLeft = pointX * ratio - (clientX - rect.left);
    stage.scrollTop = pointY * ratio - (clientY - rect.top);
  };

  window.resetLightboxScale = () => {
    const img = document.querySelector('#lightbox-img');
    if (!img) return;
    window.lightboxScale = 1;
    img.style.width = '';
    img.style.height = '';
    img.style.maxWidth = '100%';
    img.style.maxHeight = '100%';
    requestAnimationFrame(() => {
      lightboxBaseWidth = img.getBoundingClientRect().width || img.naturalWidth;
      const label = document.querySelector('[data-lightbox-scale]');
      if (label) label.textContent = '适应';
    });
  };

  // Controlled media lightbox
  window.openLightbox = (src, blocked = false) => {
    let modal = document.querySelector('.lightbox-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.className = 'lightbox-modal';
      modal.innerHTML = `
        <div class="lightbox-content">
          <div class="lightbox-toolbar">
            <strong>受控大图预览<span class="lightbox-zoom-hint">滚轮缩放</span></strong>
            <div class="lightbox-toolbar-actions">
              <button type="button" onclick="window.setLightboxScale(window.lightboxScale - .25)" aria-label="缩小">−</button>
              <button type="button" data-lightbox-scale onclick="window.resetLightboxScale()" aria-label="适应窗口">适应</button>
              <button type="button" onclick="window.setLightboxScale(window.lightboxScale + .25)" aria-label="放大">＋</button>
              <button type="button" class="lightbox-close" onclick="window.closeLightbox()" aria-label="关闭预览">×</button>
            </div>
          </div>
          <div class="lightbox-stage"><img src="" alt="大图放大预览" id="lightbox-img"></div>
        </div>`;
      document.body.appendChild(modal);
      modal.addEventListener('click', (e) => {
        if (e.target === modal) window.closeLightbox();
      });
      const lightboxStage = modal.querySelector('.lightbox-stage');
      lightboxStage?.addEventListener('wheel', (event) => {
        event.preventDefault();
        const direction = event.deltaY < 0 ? 1 : -1;
        window.zoomLightboxAtPoint(window.lightboxScale + direction * .2, event.clientX, event.clientY);
      }, { passive: false });
    }
    const img = modal.querySelector('#lightbox-img');
    const stage = modal.querySelector('.lightbox-stage');
    if (stage) stage.classList.toggle('is-blocked', Boolean(blocked));
    if (img && src) {
      img.onload = () => window.resetLightboxScale();
      img.src = src;
      if (img.complete) window.resetLightboxScale();
    }
    modal.classList.add('is-open');
    document.body.style.overflow = 'hidden';
  };

  window.closeLightbox = () => {
    const modal = document.querySelector('.lightbox-modal');
    if (modal) modal.classList.remove('is-open');
    document.body.style.overflow = '';
  };

  // Keyboard navigation & Shortcuts
  let kbIndex = -1;
  const actionForm = document.querySelector('.action-form');

  const updateKbFocus = (items, index) => {
    items.forEach((el, i) => {
      if (i === index) {
        el.classList.add('is-kb-focused');
        el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      } else {
        el.classList.remove('is-kb-focused');
      }
    });
  };

  document.addEventListener('keydown', (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const target = event.target;
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return;
    const key = event.key.toLowerCase();

    if (event.key === 'Escape') {
      window.closeLightbox();
      const kbItems = document.querySelectorAll('.review-row-link, .queue-card');
      kbItems.forEach(el => el.classList.remove('is-kb-focused'));
      kbIndex = -1;
      return;
    }

    if (event.key === ' ' || key === 'space') {
      event.preventDefault();
      const modal = document.querySelector('.lightbox-modal');
      if (modal && modal.classList.contains('is-open')) {
        window.closeLightbox();
        return;
      }
      let currentPreview = document.querySelector('#preview-img-target') || document.querySelector('.row-preview img');
      const focusedEl = document.querySelector('.is-kb-focused .row-preview img, .is-kb-focused .card-preview img');
      if (focusedEl) currentPreview = focusedEl;
      if (currentPreview && currentPreview.src) {
        window.openLightbox(currentPreview.src, Boolean(currentPreview.closest('.avatar-state.is-blocked')));
      }
      return;
    }

    if (key === '/') {
      const searchInput = document.querySelector('.search-control input, .search-box input');
      if (searchInput) {
        event.preventDefault();
        searchInput.focus();
        return;
      }
    }

    // J / K Navigation
    const nextBtn = document.querySelector('[data-focus-next]');
    const prevBtn = document.querySelector('[data-focus-previous]');

    if (key === 'arrowdown' || key === 'j') {
      if (nextBtn) {
        event.preventDefault();
        nextBtn.click();
        return;
      }
      const items = [...document.querySelectorAll('.review-row-link, .queue-card')];
      if (items.length) {
        event.preventDefault();
        kbIndex = Math.min(kbIndex + 1, items.length - 1);
        updateKbFocus(items, kbIndex);
      }
      return;
    }

    if (key === 'arrowup' || key === 'k') {
      if (prevBtn) {
        event.preventDefault();
        prevBtn.click();
        return;
      }
      const items = [...document.querySelectorAll('.review-row-link, .queue-card')];
      if (items.length) {
        event.preventDefault();
        kbIndex = Math.max(kbIndex - 1, 0);
        updateKbFocus(items, kbIndex);
      }
      return;
    }

    if (event.key === 'Enter' && kbIndex >= 0) {
      const items = [...document.querySelectorAll('.review-row-link, .queue-card')];
      if (items[kbIndex]) {
        event.preventDefault();
        const link = items[kbIndex].tagName === 'A' ? items[kbIndex] : items[kbIndex].querySelector('a');
        if (link) link.click();
      }
      return;
    }

    if (actionForm) {
      const shortcut = {a: 'approve', r: 'reject', h: 'hold', x: 'retry'}[key];
      if (shortcut) {
        event.preventDefault();
        actionForm.querySelector(`[data-action="${shortcut}"]`)?.click();
      }
    }
  });
})();
"""


@dataclass(frozen=True)
class ReviewQueueItem:
    item: ReviewItem
    lane: str
    risk_band: str
    confidence: float | None
    model_split: float | None
    focused: bool


@dataclass(frozen=True)
class ReviewSummary:
    queue_items: tuple[ReviewQueueItem, ...]
    lane_items: dict[str, tuple[ReviewQueueItem, ...]]
    risk_counts: Counter[str]
    metrics: dict[str, float | int]
    total_items: int
    pending_items: int
    held_items: int
    reviewed_items: int
    divergence_items: int
    focus_item: ReviewItem | None
    focus_events: tuple[ReviewEvent, ...]
    recent_events: tuple[ReviewEvent, ...]


def render_review_workbench(
    *,
    items: Iterable[ReviewItem],
    events: Iterable[ReviewEvent],
    csrf_token: str,
    consumer_id: str,
    reviewer_id: str = "Reviewer",
    policy_profile: str,
    service_ready: bool,
    service_error: str | None,
    focus_item_id: str | None = None,
    metrics: dict[str, float | int] | None = None,
    search_query: str = "",
    status_filter: str = "pending",
    risk_filter: str = "all",
    view_mode: str = "list",
    batch_mode: bool = False,
    batch_result: str = "",
) -> str:
    all_items = list(items)
    view_value = view_mode if view_mode in {"list", "grid", "focus"} else "list"
    filtered_items = _filter_items(
        all_items,
        search_query=search_query,
        status_filter=status_filter,
        risk_filter=risk_filter,
    )
    if view_value == "focus" and not focus_item_id and filtered_items:
        focus_item_id = filtered_items[0].item_id
    item_list = filtered_items
    if focus_item_id:
        item_list = all_items
    pending_count = sum(1 for item in all_items if _requires_human_review(item))
    held_count = sum(1 for item in all_items if item.status == "held")
    reviewed_count = sum(1 for item in all_items if item.status in {"approved", "rejected"})
    total_count = len(all_items)
    event_list = list(events)
    summary = _summarise(
        item_list,
        event_list,
        focus_item_id=focus_item_id,
        metrics=metrics or {},
    )
    current_ts = datetime.now(timezone.utc)
    page_title = "WordYeah · 图像审核"
    ready_tone = "ready" if service_ready else "danger"
    status_value = _status_filter_value(status_filter)
    risk_value = _risk_filter_value(risk_filter)
    queue_cards = "".join(
        _review_card(
            view,
            href=_review_href(
                status=status_filter,
                risk=risk_filter,
                query=search_query,
                view="focus",
                focus=view.item.item_id,
            ),
            batch_mode=batch_mode,
        )
        for view in summary.queue_items
    )
    if not queue_cards:
        queue_cards = (
            '<div class="empty-state">'
            "<strong>当前没有需要人工接手的例外项</strong>"
            "AI Agent 已自动处理常规项目；新的异常、低置信度或分歧内容会出现在这里。"
            "</div>"
        )

    detail_html = ""
    if focus_item_id:
        focus_ids = [item.item_id for item in filtered_items]
        try:
            focus_index = focus_ids.index(focus_item_id)
        except ValueError:
            focus_index = -1
        previous_id = focus_ids[focus_index - 1] if focus_index > 0 else None
        next_id = focus_ids[focus_index + 1] if 0 <= focus_index < len(focus_ids) - 1 else None
        detail_html = _detail_panel(
            summary.focus_item,
            summary.focus_events,
            csrf_token,
            current_ts,
            previous_href=_review_href(status=status_filter, risk=risk_filter, query=search_query, view="focus", focus=previous_id) if previous_id else None,
            next_href=_review_href(status=status_filter, risk=risk_filter, query=search_query, view="focus", focus=next_id) if next_id else None,
            close_href=_review_href(status=status_filter, risk=risk_filter, query=search_query, view="list"),
        )

    queue_list = f'<div class="queue-list" data-view="{escape(view_value if view_value != "focus" else "list")}">{queue_cards}</div>'
    if batch_mode:
        queue_body = f'''
        <form class="batch-form" method="post" action="/review/batch" data-batch-form>
          <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
          <input type="hidden" name="return_to" value="{escape(_review_href(status=status_filter, risk=risk_filter, query=search_query, view=view_value, batch=True))}">
          <div class="batch-bar">
            <label class="batch-summary"><input type="checkbox" data-select-all> <strong><span data-selected-count>0</span> 项已选</strong><span>单次最多 50 项，后端逐项写审计事件</span></label>
            <div class="batch-actions">
              <button type="submit" name="action" value="approve">批量通过</button>
              <button type="submit" name="action" value="reject">批量替换默认头像</button>
              <button type="submit" name="action" value="blacklist">批量加入黑名单</button>
              <button type="submit" name="action" value="hold">批量留置</button>
            </div>
          </div>
          {queue_list}
        </form>'''
    else:
        queue_body = queue_list

    active_tab = {
        "pending": "pending",
        "held": "held",
        "approved": "reviewed",
        "rejected": "reviewed",
        "reviewed": "reviewed",
        "all": "all",
    }.get(status_value, "pending")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <meta name="color-scheme" content="light dark">
  <title>{escape(page_title)}</title>
  {THEME_INIT_JS}
  <style>{CSS}</style>
</head>
<body>
  <a class="skip-link" href="#review-queue">跳到待审核图片</a>
  <div class="app-frame">
    <aside class="side-nav" aria-label="审核导航">
      <a class="brand" href="/review/overview" aria-label="WordYeah 图像审核">
        <span class="brand-mark">wy</span><span>wordyeah</span>
      </a>

      <div class="nav-scroll">
      <nav class="nav-section" aria-label="工作区">
        <p class="nav-label">Workspace</p>
        <a class="nav-item" href="/review/overview">
          <span class="nav-icon" aria-hidden="true">{_nav_icon("overview")}</span><span>概览</span>
        </a>
        <a class="nav-item is-active" href="/review#review-queue" aria-current="page">
          <span class="nav-icon" aria-hidden="true">{_nav_icon("queue")}</span>
          <span>审核队列</span><span class="nav-count">{pending_count}</span>
        </a>
        <a class="nav-item" href="/review/agents">
          <span class="nav-icon" aria-hidden="true">{_nav_icon("agents")}</span><span>AI 任务</span>
        </a>
        <a class="nav-item" href="/review/history">
          <span class="nav-icon" aria-hidden="true">{_nav_icon("log")}</span><span>操作记录</span>
        </a>
      </nav>

      <nav class="nav-section" aria-label="设置">
        <p class="nav-label">Settings</p>
        <a class="nav-item" href="/review/policies">
          <span class="nav-icon" aria-hidden="true">{_nav_icon("policy")}</span><span>审核策略</span>
        </a>
        <a class="nav-item" href="/review/quality">
          <span class="nav-icon" aria-hidden="true">{_nav_icon("quality")}</span><span>质量与仲裁</span>
        </a>
        <a class="nav-item" href="/review/health">
          <span class="nav-icon" aria-hidden="true">{_nav_icon("health")}</span><span>系统健康</span>
        </a>
        <a class="nav-item" href="/review/account">
          <span class="nav-icon" aria-hidden="true">{_nav_icon("account")}</span><span>账户</span>
        </a>
        <a class="nav-item" href="/review/guide">
          <span class="nav-icon" aria-hidden="true">{_nav_icon("guide")}</span><span>审核说明</span>
        </a>
      </nav>
      </div>

      <div class="nav-spacer"></div>
      <div class="consumer-switcher">
        <span class="consumer-avatar">{escape(consumer_id[:1].upper() or 'W')}</span>
        <span class="consumer-copy"><strong>{escape(consumer_id)}</strong><small>Consumer workspace</small></span>
        <span class="chevron" aria-hidden="true">⌄</span>
      </div>
    </aside>

    <div class="app-main">
      <header class="topbar">
        <div class="toolbar-title">
          <nav class="topbar-breadcrumbs" aria-label="面包屑">
            <a href="/review/overview">WordYeah</a>
            <span class="divider" aria-hidden="true">/</span>
            {f'<a href="/review#review-queue">审核队列</a><span class="divider" aria-hidden="true">/</span><span class="current-crumb">{escape(summary.focus_item.item_id[:12])}</span>' if focus_item_id and summary.focus_item else '<span class="current-crumb">审核队列</span>'}
          </nav>
        </div>
        <div class="toolbar-actions">
          <button class="theme-toggle-btn" type="button" data-action="toggle-layout" title="切换全宽/盒装居中" aria-label="切换全宽/盒装居中">
            {_top_icon('layout')}
          </button>
          <button class="theme-toggle-btn" type="button" data-action="toggle-theme" title="切换深色/浅色模式" aria-label="切换深色/浅色模式">
            <span class="theme-icon-sun">{_top_icon('sun')}</span>
            <span class="theme-icon-moon">{_top_icon('moon')}</span>
          </button>
          <span class="topbar-icon" data-tone="{ready_tone}" title="{'AI 正常运行' if service_ready else 'AI 服务异常'}" aria-label="{'AI 正常运行' if service_ready else 'AI 服务异常'}">{_top_icon('spark')}</span>
          <a class="topbar-icon" href="/review/guide" title="审核说明" aria-label="审核说明">{_top_icon('help')}</a>
          <details class="account-menu">
            <summary><span class="reviewer-avatar">{escape(reviewer_id[:1].upper() or 'R')}</span><span>{escape(reviewer_id)}</span><span aria-hidden="true">⌄</span></summary>
            <div class="account-popover">
              <p>{escape(consumer_id)} · 受限审核会话</p>
              <form class="toolbar-logout" method="post" action="/review/logout">
                <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
                <button type="submit">退出审核台</button>
              </form>
            </div>
          </details>
        </div>
      </header>

      <main class="shell{' shell-focus' if focus_item_id else ''}" id="main-workbench">
        {f'''
        {detail_html}
        ''' if focus_item_id else f'''
        <section class="queue-section is-primary" id="review-queue" aria-labelledby="queue-title">
          <header class="support-hero">
            <div class="support-hero-left">
              <div><h1 id="queue-title">审核队列</h1><p class="queue-intro">人工例外 {pending_count} · AI 已处理 {reviewed_count}</p></div>
            </div>
            <span class="status-dot-pill" data-tone="{ready_tone}">
              <span class="dot"></span>
              {'Pipeline Active' if service_ready else 'Pipeline Blocked'}
            </span>
          </header>

          <div class="control-dock">
            <nav class="page-tabs" aria-label="审核状态">
              <a class="{'is-active' if active_tab == 'pending' else ''}" href="{escape(_review_href(status='pending', risk=risk_filter, query=search_query, view=view_value, batch=batch_mode))}#review-queue">待审核 <span>{pending_count}</span></a>
              <a class="{'is-active' if active_tab == 'held' else ''}" href="{escape(_review_href(status='held', risk=risk_filter, query=search_query, view=view_value, batch=batch_mode))}#review-queue">已留置 <span>{held_count}</span></a>
              <a class="{'is-active' if active_tab == 'reviewed' else ''}" href="{escape(_review_href(status='reviewed', risk=risk_filter, query=search_query, view=view_value, batch=batch_mode))}#review-queue">已处理 <span>{reviewed_count}</span></a>
              <a class="{'is-active' if active_tab == 'all' else ''}" href="{escape(_review_href(status='all', risk=risk_filter, query=search_query, view=view_value, batch=batch_mode))}#review-queue">全部 <span>{total_count}</span></a>
            </nav>

            <div class="control-row">
              <form class="filter-bar" method="get" action="/review">
                <input type="hidden" name="status" value="{escape(status_value)}">
                <input type="hidden" name="view" value="{escape(view_value if view_value != 'focus' else 'list')}">
                {'<input type="hidden" name="batch" value="1">' if batch_mode else ''}
                <div class="search-box">
                  {_top_icon("search")}
                  <input name="q" type="search" value="{escape(search_query)}" placeholder="搜索 ID / 内容...">
                  <kbd class="search-kbd">/</kbd>
                </div>
                <select class="select-pill" name="risk" onchange="this.form.submit()">
                  {_filter_option("all", "全部风险", risk_value)}
                  {_filter_option("low", "低风险", risk_value)}
                  {_filter_option("guarded", "需确认", risk_value)}
                  {_filter_option("elevated", "高风险", risk_value)}
                  {_filter_option("critical", "严重风险", risk_value)}
                </select>
              </form>
              <div class="control-actions">
                <nav class="view-switch" aria-label="队列视图">
                  <a class="{'is-active' if view_value == 'grid' else ''}" href="{escape(_review_href(status=status_filter, risk=risk_filter, query=search_query, view='grid', batch=batch_mode))}" title="视觉网格">{_top_icon('grid')}<span>网格</span></a>
                  <a class="{'is-active' if view_value == 'list' else ''}" href="{escape(_review_href(status=status_filter, risk=risk_filter, query=search_query, view='list', batch=batch_mode))}" title="紧凑列表">{_top_icon('list')}<span>列表</span></a>
                  <a class="{'is-active' if view_value == 'focus' else ''}" href="{escape(_review_href(status=status_filter, risk=risk_filter, query=search_query, view='focus'))}" title="沉浸标记">{_top_icon('zap')}<span>沉浸</span></a>
                </nav>
              <details class="keyboard-help-popover">
                <summary class="keyboard-help-btn" title="查看键盘快捷键说明">{_top_icon('keyboard')}<span>快捷键说明</span></summary>
                <div class="keyboard-popover-content">
                  <strong>极速审核快捷键</strong>
                  <ul>
                    <li><span>通过 (Approve)</span><kbd>A</kbd></li>
                    <li><span>拒绝 (Reject)</span><kbd>R</kbd></li>
                    <li><span>留置 (Hold)</span><kbd>H</kbd></li>
                    <li><span>重试 (Retry)</span><kbd>X</kbd></li>
                    <li><span>切换卡片</span><kbd>J</kbd> / <kbd>K</kbd> / <kbd>↑</kbd> / <kbd>↓</kbd></li>
                    <li><span>放大预览</span><kbd>Space</kbd></li>
                    <li><span>搜索框</span><kbd>/</kbd></li>
                    <li><span>关闭弹窗</span><kbd>Esc</kbd></li>
                  </ul>
                </div>
              </details>
              <a class="batch-toggle{' is-active' if batch_mode else ''}" href="{escape(_review_href(status=status_filter, risk=risk_filter, query=search_query, view=view_value if view_value != 'focus' else 'list', batch=not batch_mode))}">{'退出批量模式' if batch_mode else '批量模式'}</a>
              </div>
            </div>
          </div>

          <div class="queue-tools">
            <span class="filtered-count">当前显示 {len(filtered_items)} 项</span>
            <span class="queue-tool-note">按风险筛选后进入单项审核，或开启批量模式集中处理。</span>
          </div>

          {f'<div class="batch-result">{escape(batch_result)}</div>' if batch_result else ''}

          {queue_body}
        </section>
        '''}
      </main>
    </div>
  </div>
  <script src="/review/assets/workbench.js" defer></script>
</body>
</html>"""


THEME_INIT_JS = """
  <script>
    (function() {
      var savedTheme = localStorage.getItem('wy-theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      document.documentElement.setAttribute('data-theme', savedTheme);
      var savedLayout = localStorage.getItem('wy-layout') || 'fluid';
      if (savedLayout === 'boxed') {
        document.documentElement.setAttribute('data-layout', 'boxed');
      }
    })();
    window.toggleTheme = function() {
      var current = document.documentElement.getAttribute('data-theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      var next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('wy-theme', next);
    };
    window.toggleLayout = function() {
      var current = document.documentElement.getAttribute('data-layout') || 'fluid';
      var next = current === 'boxed' ? 'fluid' : 'boxed';
      if (next === 'boxed') {
        document.documentElement.setAttribute('data-layout', 'boxed');
      } else {
        document.documentElement.removeAttribute('data-layout');
      }
      localStorage.setItem('wy-layout', next);
    };
  </script>
"""


def _review_href(
    *,
    status: str,
    risk: str,
    query: str,
    view: str,
    focus: str | None = None,
    batch: bool = False,
) -> str:
    values: dict[str, str] = {"status": status, "risk": risk, "view": view}
    if query:
        values["q"] = query
    if focus:
        values["focus"] = focus
    if batch:
        values["batch"] = "1"
    return f"/review?{urlencode(values)}"

def _filter_items(
    items: list[ReviewItem],
    *,
    search_query: str,
    status_filter: str,
    risk_filter: str,
) -> list[ReviewItem]:
    query = search_query.strip().lower()
    status_value = _status_filter_value(status_filter)
    risk_value = _risk_filter_value(risk_filter)
    filtered: list[ReviewItem] = []
    for item in items:
        if status_value == "reviewed":
            if item.status not in {"approved", "rejected"}:
                continue
        elif status_value == "pending":
            if not _requires_human_review(item):
                continue
        elif status_value != "all" and item.status != status_value:
            continue
        if risk_value != "all" and _risk_band(item) != risk_value:
            continue
        if query:
            haystack = " ".join(
                [
                    item.item_id,
                    item.content_sha256,
                    item.media_ref,
                    item.decision_hint,
                    item.policy_version,
                    *item.reasons,
                    *(str(finding.get("label", "")) for finding in item.findings),
                ]
            ).lower()
            if query not in haystack:
                continue
        filtered.append(item)
    return filtered


def _requires_human_review(item: ReviewItem) -> bool:
    """Return only pending cases the automated review chain has escalated."""
    return item.status == "pending" and (
        item.stage == "human_required"
        or item.quality_sample
        or item.arbitration_required
    )


def _summarise(
    items: list[ReviewItem],
    events: list[ReviewEvent],
    *,
    focus_item_id: str | None,
    metrics: dict[str, float | int],
) -> ReviewSummary:
    queue_items = list(items)
    reviewed_items = sum(1 for item in items if item.status in {"approved", "rejected"})
    held_items = sum(1 for item in items if item.status == "held")
    pending_items = sum(1 for item in items if item.status == "pending")

    queue_views: list[ReviewQueueItem] = []
    lane_items: dict[str, list[ReviewQueueItem]] = {lane: [] for lane in LANE_ORDER}
    risk_counts: Counter[str] = Counter()
    divergence_items = 0

    for item in queue_items:
        lane = _lane_for_item(item)
        risk_band = _risk_band(item)
        confidence = _confidence(item)
        model_split = _model_split(item)
        focused = item.item_id == focus_item_id
        view = ReviewQueueItem(
            item=item,
            lane=lane,
            risk_band=risk_band,
            confidence=confidence,
            model_split=model_split,
            focused=focused,
        )
        queue_views.append(view)
        lane_items[lane].append(view)
        if risk_band in RISK_ORDER:
            risk_counts[risk_band] += 1
        if model_split is not None and model_split < 0.2:
            divergence_items += 1

    for lane in lane_items:
        lane_items[lane].sort(key=lambda entry: entry.item.created_at, reverse=True)
    queue_views.sort(
        key=lambda entry: (
            {"critical": 0, "elevated": 1, "guarded": 2, "low": 3}.get(entry.risk_band, 4),
            entry.item.created_at,
        )
    )

    focus_item = _resolve_focus_item(items, focus_item_id)
    focus_events = tuple(
        event for event in events if focus_item is not None and event.item_id == focus_item.item_id
    )
    focus_events = tuple(sorted(focus_events, key=lambda entry: entry.created_at, reverse=True))
    recent_events = tuple(sorted(events, key=lambda entry: entry.created_at, reverse=True)[:24])

    return ReviewSummary(
        queue_items=tuple(queue_views),
        lane_items={lane: tuple(entries) for lane, entries in lane_items.items()},
        risk_counts=risk_counts,
        metrics=metrics,
        total_items=len(items),
        pending_items=pending_items,
        held_items=held_items,
        reviewed_items=reviewed_items,
        divergence_items=divergence_items,
        focus_item=focus_item,
        focus_events=focus_events,
        recent_events=recent_events,
    )


def _resolve_focus_item(items: list[ReviewItem], focus_item_id: str | None) -> ReviewItem | None:
    if not focus_item_id:
        return None
    for item in items:
        if item.item_id == focus_item_id:
            return item
    return None


def _lane_for_item(item: ReviewItem) -> str:
    if item.status == "held" or item.decision_hint == "error":
        return "error"
    if item.decision_hint == "block":
        return "auto-reject"
    if item.decision_hint == "allow":
        return "auto-approve"
    return "escalate"


def _review_card(
    view: ReviewQueueItem,
    *,
    href: str,
    batch_mode: bool,
) -> str:
    item = view.item
    confidence = "—" if view.confidence is None else f"{view.confidence * 100:.0f}%"
    focus_class = " is-focused" if view.focused else ""
    batch_class = " is-batch" if batch_mode else ""
    batch_check = (
        f'<label class="batch-check" title="选择此项目"><input type="checkbox" name="selected" '
        f'value="{escape(item.item_id)}:{item.version}" aria-label="选择 {escape(item.item_id)}"></label>'
        if batch_mode else ""
    )
    divergence_badge = (
        '<span class="finding-badge badge-divergence">模型分歧</span>'
        if view.model_split is not None and view.model_split < 0.2
        else ""
    )
    return f"""
    <article class="review-card{focus_class}{batch_class}" data-risk="{escape(view.risk_band)}" data-lane="{escape(view.lane)}" id="{escape(item.item_id)}">
      {batch_check}
      <a class="review-row-link" href="{escape(href)}" aria-label="查看 {escape(item.item_id)}">
        <div class="row-preview">
          {_media_thumbnail(item)}
          <span class="row-risk-dot risk-{escape(view.risk_band)}" aria-label="{escape(_risk_label(view.risk_band))}"></span>
        </div>
        <div class="row-identity">
          <strong>{escape(_product_reason(item))}</strong>
          <small>{escape(item.item_id[:12])} · {escape(confidence)} 置信度</small>
        </div>
        <div class="row-ai">
          <span class="row-intent-label">{escape(_decision_label(item.decision_hint))}{divergence_badge}</span>
        </div>
        <div class="row-decision">
          <span class="status-pill status-{escape(item.status)}">{escape(_status_label(item.status))}</span>
          <small>等待 {escape(_time_text(item.created_at).replace(' 前', ''))}</small>
        </div>
        <span class="row-open" aria-hidden="true">{_top_icon("arrow")}</span>
      </a>
    </article>
    """


def _detail_panel(
    item: ReviewItem | None,
    events: tuple[ReviewEvent, ...],
    csrf_token: str,
    current_ts: datetime,
    previous_href: str | None = None,
    next_href: str | None = None,
    close_href: str = "/review",
) -> str:
    if item is None:
        return """
        <section class="review-detail" id="review-detail">
          <div class="focus-hint">
            <h2>没有找到这张图片</h2>
            <p>该审核项目可能已被处理，或不属于当前 consumer。</p>
          </div>
        </section>
        """

    risk_band = _risk_band(item)
    confidence = _confidence(item)
    confidence_text = "—" if confidence is None else f"{confidence * 100:.1f}%"
    findings = _finding_rows(item)
    timeline = _detail_events(events, current_ts)
    buttons = _manual_actions(item, csrf_token)
    return_href = next_href or close_href
    previous_link = (
        f'<a href="{escape(previous_href)}" data-focus-previous>← 上一条 <span class="mono">K</span></a>'
        if previous_href else ""
    )
    next_link = (
        f'<a href="{escape(next_href)}" data-focus-next>下一条 <span class="mono">J</span> →</a>'
        if next_href else ""
    )
    return_link = f'<a class="focus-return" href="{escape(close_href)}#review-queue">← 返回队列</a>'
    return f"""
    <div class="focus-nav">
      <div class="focus-nav-group">{return_link}{previous_link}{next_link}</div>
      <span class="focus-shortcuts">A 通过 · R 替换默认头像 · H 留置 · J/K 切换</span>
    </div>
    <section class="review-detail" id="review-detail" aria-labelledby="detail-title">
      <header class="detail-header">
        <div>
          <p class="detail-kicker">{'待审核 · AI 已升级' if _requires_human_review(item) else '审核记录'}</p>
          <h2 id="detail-title">{'人工确认' if buttons else '处理结果'}</h2>
          <p>{escape(item.item_id)} · {escape(_product_reason(item))}</p>
        </div>
        <a class="detail-close" href="{escape(close_href)}#review-queue" aria-label="关闭详情">{_top_icon("close")}</a>
      </header>

      <div class="detail-layout">
        <aside class="detail-sidebar">
          <section class="sidebar-section">
            <h3>案件摘要</h3>
            <div class="detail-facts summary-facts">
              <div class="detail-fact"><div class="label">审核状态</div><div class="value"><span class="status-pill status-{escape(item.status)}">{escape(_status_label(item.status))}</span></div></div>
              <div class="detail-fact"><div class="label">AI 建议</div><div class="value">{escape(_decision_label(item.decision_hint))}</div></div>
              <div class="detail-fact"><div class="label">风险等级</div><div class="value"><span class="risk-label risk-{escape(risk_band)}">{escape(_risk_label(risk_band))}</span></div></div>
              <div class="detail-fact"><div class="label">模型置信度</div><div class="value">{escape(confidence_text)}</div></div>
              <div class="detail-fact"><div class="label">头像处置</div><div class="value">{escape(_avatar_action_label(_effective_avatar_action(item)))}</div></div>
            </div>
          </section>

          <details class="sidebar-section metadata-details">
            <summary>证据与元数据</summary>
            <div class="detail-facts">
              <div class="detail-fact"><div class="label">进入人工原因</div><div class="value">{escape(_reason_summary(item))}</div></div>
              <div class="detail-fact"><div class="label">策略版本</div><div class="value mono">{escape(item.policy_version)}</div></div>
              <div class="detail-fact"><div class="label">媒体类型</div><div class="value">{escape(item.media_type)}</div></div>
              <div class="detail-fact"><div class="label">创建时间</div><div class="value">{escape(_time_text(item.created_at, current_ts))}</div></div>
              <div class="detail-fact"><div class="label">记录版本</div><div class="value">{item.version}</div></div>
              <div class="detail-fact"><div class="label">SHA-256</div><div class="value mono">{escape(item.content_sha256[:20])}…</div></div>
              <div class="detail-fact"><div class="label">参与模型</div><div class="value">{_render_model_versions(item)}</div></div>
            </div>
          </details>
        </aside>

        <div class="detail-stage">
          <section class="preview-panel">
            <div class="detail-section-heading">
              <h3>受控图片预览<span class="sr-only">Controlled media preview</span></h3>
              <span class="detail-chip mono">{escape(item.item_id[:12])}</span>
            </div>
            {_media_preview(item)}
          </section>

          {f'''<form method="post" class="action-form">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
            <input type="hidden" name="version" value="{item.version}">
            <input type="hidden" name="return_to" value="{escape(return_href)}">
            <label for="note-{escape(item.item_id)}">审核备注</label>
            <input id="note-{escape(item.item_id)}" name="note" type="text" maxlength="2000" placeholder="记录人工判断依据（可选）">
            <div class="action-caption">选择明确结论；证据不足时留置复核。</div>
            <div class="action-buttons">{buttons}</div>
          </form>''' if buttons else f'''<div class="completed-state"><span class="status-pill status-{escape(item.status)}">{escape(_status_label(item.status))}</span><span>该项目已完成处理，详情保留用于追溯。</span></div>'''}

          <section class="evidence-block detail-findings">
            <h3>模型判断摘要<span class="sr-only">Model finding summary</span></h3>
            <ul class="finding-list">{findings}</ul>
          </section>

          <details class="audit-log detail-audit">
            <summary><span class="audit-summary-main">{_top_icon("arrow")}<span>这张图片的操作记录</span></span><span class="quiet audit-summary-meta">AI 自动记录<span class="sr-only">Agent action log</span></span></summary>
            <div class="audit-log-body">
              <ul class="event-list">{timeline}</ul>
            </div>
          </details>
        </div>
      </div>
    </section>
    """


def _media_thumbnail(item: ReviewItem) -> str:
    avatar_action = _effective_avatar_action(item)
    if avatar_action == "blacklist":
        blocked_source = _cravatar_preview_url(item, size=160) or _blocked_avatar_url()
        return _avatar_state("blocked", size=160, source=blocked_source)
    if avatar_action == "replace_default":
        return _avatar_state("default", size=160)
    cravatar_url = _cravatar_preview_url(item, size=160)
    if cravatar_url is not None:
        return (
            f'<img src="{escape(cravatar_url)}" '
            f'alt="Cravatar 头像预览 {escape(item.item_id)}" loading="lazy" decoding="async">'
        )
    if item.media_type == "image" and item.media_ref.startswith("media://"):
        return (
            f'<img src="/review/items/{escape(item.item_id)}/media" '
            f'alt="受控图片预览 {escape(item.item_id)}" loading="lazy" decoding="async">'
        )
    return _avatar_state("default", size=160)


def _media_preview(item: ReviewItem) -> str:
    risk_band = _risk_band(item)
    blur_class = " is-sensitive-blur" if risk_band in {"elevated", "critical"} else ""
    toggle_button = (
        f'<button type="button" class="preview-unblur-toggle" onclick="this.closest(\'.media-preview\').classList.toggle(\'is-sensitive-blur\')">{_top_icon("eye")}<span>切换防护遮罩</span></button>'
        if risk_band in {"elevated", "critical"} else ""
    )
    bg_switch = """
    <div class="bg-mode-bar" aria-label="切换背景颜色">
      <button type="button" class="is-active" data-preview-background title="透明棋盘网格" aria-pressed="true" onclick="setPreviewBackground(this, 'grid')">棋盘</button>
      <button type="button" data-preview-background title="纯白背景" aria-pressed="false" onclick="setPreviewBackground(this, 'white')">纯白</button>
      <button type="button" data-preview-background title="纯黑背景" aria-pressed="false" onclick="setPreviewBackground(this, 'black')">纯黑</button>
    </div>
    """
    avatar_action = _effective_avatar_action(item)
    blocked = avatar_action == "blacklist"
    replaced = avatar_action == "replace_default"
    cravatar_url = _cravatar_preview_url(item, size=512)
    if item.media_type != "image" and cravatar_url is None:
        return (
            '<div class="media-preview"><div class="media-fallback">'
            "<span>暂无受控本地预览</span></div></div>"
        )
    img_src = (
        escape(cravatar_url or _blocked_avatar_url())
        if blocked
        else escape(_default_avatar_url(size=512))
        if replaced
        else escape(cravatar_url)
        if cravatar_url is not None
        else f"/review/items/{escape(item.item_id)}/media"
    )
    note_text = "黑名单头像显示 Cravatar 源站 ban 状态图，不再展示原始恶意头像。" if blocked else "一般违规头像已替换为 Cravatar 默认头像，不再展示原图。" if replaced else "预览按 Cravatar 官方 API 生成 <code>cn.cravatar.com/avatar/&lt;hash&gt;</code> 地址，仅允许尺寸与 404 默认图参数。" if cravatar_url is not None else "预览通过 reviewer session 和 allowlisted <code>media://</code> 引用提供；浏览器不会收到原始存储路径。"
    preview_image = (
        f'<div class="avatar-state is-blocked"><img src="{img_src}" alt="已屏蔽头像" loading="eager" decoding="async" id="preview-img-target"></div>'
        if blocked
        else f'<img src="{img_src}" alt="受控头像预览" loading="eager" decoding="async" id="preview-img-target">'
    )

    return f"""
    <div class="media-preview{blur_class} bg-grid">
      <div class="preview-header-tools">
        {bg_switch}
        <button type="button" class="lightbox-trigger" onclick="openLightbox('{img_src}', {str(blocked).lower()})">{_top_icon("zoom")}<span>放大预览</span><kbd>Space</kbd></button>
      </div>
      <div class="preview-wrapper">
        <button type="button" class="preview-image-button" aria-label="打开大图预览" onclick="openLightbox('{img_src}', {str(blocked).lower()})">
          {preview_image}
        </button>
        {toggle_button}
      </div>
      <p class="sr-only">{note_text}</p>
    </div>
    """


def _avatar_state(state: str, *, size: int, source: str | None = None) -> str:
    source = source or (_blocked_avatar_url() if state == "blocked" else _default_avatar_url(size=size))
    state_class = " is-blocked" if state == "blocked" else ""
    label = "已屏蔽头像" if state == "blocked" else "默认头像"
    return f'<div class="avatar-state{state_class}"><img src="{source}" alt="{label}" loading="lazy" decoding="async"></div>'


def _default_avatar_url(*, size: int) -> str:
    bounded_size = min(max(size, 16), 1024)
    return f"https://cn.cravatar.com/avatar/{'0' * 32}?s={bounded_size}&f=y"


def _blocked_avatar_url() -> str:
    return "/review/assets/cravatar-ban.png"


def _cravatar_preview_url(item: ReviewItem, *, size: int) -> str | None:
    if item.media_type != "image" or not item.media_ref.startswith("cravatar://"):
        return None
    avatar_hash = item.media_ref.removeprefix("cravatar://").strip().lower()
    if len(avatar_hash) not in {32, 64} or any(character not in "0123456789abcdef" for character in avatar_hash):
        return None
    bounded_size = min(max(size, 16), 1024)
    return f"https://cn.cravatar.com/avatar/{avatar_hash}?s={bounded_size}&d=404"


def _manual_actions(item: ReviewItem, csrf_token: str) -> str:
    if item.status in {"held", "rejected"}:
        return _action_button(item, "retry", "retry", "重新检查")
    if not _requires_human_review(item):
        return ""
    return "".join(
        [
            _action_button(item, "approve", "approve", "通过"),
            _action_button(item, "reject", "reject", "拒绝"),
            _action_button(item, "blacklist", "blacklist", "", icon="ban"),
            _action_button(item, "hold", "hold", "", icon="pause"),
        ]
    )


def _action_button(
    item: ReviewItem,
    action: str,
    data_action: str,
    label: str,
    *,
    icon: str | None = None,
) -> str:
    accessible_label = {
        "approve": "通过并保留原头像",
        "reject": "拒绝并替换为默认头像",
        "blacklist": "加入 Cravatar 全网黑名单",
        "hold": "留置人工复核",
        "retry": "重新检查",
    }.get(action, label)
    button_class = ' class="is-icon-only"' if icon else ""
    content = _top_icon(icon) if icon else escape(label)
    return (
        f'<button type="submit"{button_class} formaction="/review/items/{escape(item.item_id)}/{action}" '
        f'data-action="{escape(data_action)}" aria-label="{escape(accessible_label)}" '
        f'title="{escape(accessible_label)}">{content}</button>'
    )


def _detail_events(events: tuple[ReviewEvent, ...], current_ts: datetime) -> str:
    if not events:
        return "<li class='event-item'><div class='sub'>这张图片还没有记录过审核动作。</div></li>"
    rows = []
    for event in events:
        avatar_transition = ""
        if event.before_avatar_action != event.after_avatar_action:
            avatar_transition = (
                '<div class="sub">头像处置：'
                f'{escape(_avatar_action_label(event.before_avatar_action))} → '
                f'{escape(_avatar_action_label(event.after_avatar_action))}</div>'
            )
        rows.append(
            f"""<li class="event-item">
              <div class="top">
                <strong class="event-action" data-action="{escape(_event_tone(event.action))}">{escape(event.action)}</strong>
                <span class="sub">{escape(_time_text(event.created_at, current_ts))}</span>
              </div>
              <div class="sub">审核员：{escape(event.reviewer)} · request <code>{escape(event.request_id or "—")}</code></div>
              <div class="sub">{escape(event.before_status or "—")} → {escape(event.after_status or "—")}</div>
              {avatar_transition}
              {f'<div class="sub">备注：{escape(event.note)}</div>' if event.note else ""}
            </li>"""
        )
    return "".join(rows)


def _score_bar(score: float | int | None) -> str:
    if score is None:
        return ""
    val = float(score)
    pct = round(min(max(val * 100, 0.0), 100.0), 1)
    tone = "danger" if val >= 0.85 else ("amber" if val >= 0.5 else "green")
    return f'<div class="score-bar-track" title="置信度 {pct}%"><span class="score-bar-fill tone-{tone}" style="width:{pct}%;"></span></div>'


def _finding_rows(item: ReviewItem) -> str:
    if not item.findings:
        return "<li class='finding-item'><div class='sub'>没有记录到模型 finding。</div></li>"
    rows = []
    split = _model_split(item)
    has_divergence = split is not None and split < 0.2
    for finding in item.findings:
        category = escape(str(finding.get("category", "unknown")))
        label = escape(str(finding.get("label", "unknown")))
        score = finding.get("score")
        source = escape(str(finding.get("source", "unknown")))
        score_val = score if isinstance(score, (float, int)) else None
        score_text = _score_text(score_val)
        bar_html = _score_bar(score_val)
        div_badge = '<span class="finding-badge badge-divergence">模型分歧</span>' if (has_divergence and label.lower() in {"nsfw", "normal"}) else ""
        badge_type = "pink" if "nsfw" in label.lower() or "risk" in category.lower() else ("amber" if has_divergence else "purple")
        rows.append(
            f"""<li class="finding-item">
              <div class="top">
                <div>
                  <span class="replacement-badge" data-type="{badge_type}">{category}</span>
                  <span class="replacement-badge" data-type="purple">{label}</span>
                  {div_badge}
                </div>
                <span class="sub val">{escape(score_text)}</span>
              </div>
              {bar_html}
              <div class="sub">source model: <code class="var-tag">{source}</code></div>
            </li>"""
        )
    return "".join(rows)


def _event_row(event: ReviewEvent, current_ts: datetime) -> str:
    action_tone = _event_tone(event.action)
    return f"""<tr>
      <td><span class="mono">{escape(_time_text(event.created_at, current_ts))}</span></td>
      <td><code>{escape(event.item_id[:14])}</code></td>
      <td><span class="event-action" data-action="{escape(action_tone)}">{escape(event.action)}</span></td>
      <td>{escape(event.reviewer)}</td>
      <td>{escape(event.note or "—")}</td>
      <td><code>{escape(event.request_id or "—")}</code></td>
    </tr>"""


def _render_model_versions(item: ReviewItem) -> str:
    if not item.model_versions:
        return "unknown"
    return " · ".join(
        f"{escape(key)} {escape(value)}" for key, value in item.model_versions.items()
    )


def _reason_summary(item: ReviewItem) -> str:
    if not item.reasons:
        return "未发现明确原因"
    return " · ".join(item.reasons[:2])


def _product_reason(item: ReviewItem) -> str:
    reasons = {reason.lower() for reason in item.reasons}
    if "nsfw_score_at_or_above_review_threshold" in reasons:
        return "敏感内容置信度接近审核阈值"
    if item.decision_hint == "error":
        return "模型未能完成可靠判断"
    if item.decision_hint == "block":
        return "高风险内容等待最终确认"
    if item.decision_hint == "allow":
        return "质量抽检需要人工确认"
    return "模型置信度不足，需要人工确认"


def _findings_summary(item: ReviewItem) -> str:
    if not item.findings:
        return "未记录模型 finding"
    parts = []
    for finding in item.findings[:2]:
        label = str(finding.get("label", "unknown"))
        score = finding.get("score")
        score_text = _score_text(score if isinstance(score, (float, int)) else None)
        parts.append(f"{label} {score_text}")
    if len(item.findings) > 2:
        parts.append(f"+{len(item.findings) - 2}")
    return " · ".join(parts)


def _split_summary(item: ReviewItem) -> str:
    split = _model_split(item)
    if split is None:
        return "无模型分歧"
    if split < 0.2:
        return f"分歧 {split * 100:.0f}%"
    return f"差异 {split * 100:.0f}%"


def _model_split(item: ReviewItem) -> float | None:
    nsfw = None
    normal = None
    for finding in item.findings:
        label = str(finding.get("label", "")).lower()
        score = finding.get("score")
        if not isinstance(score, (float, int)):
            continue
        if label == "nsfw":
            nsfw = float(score)
        elif label == "normal":
            normal = float(score)
    if nsfw is None or normal is None:
        return None
    return abs(nsfw - normal)


def _confidence(item: ReviewItem) -> float | None:
    if item.top_score is None:
        return None
    score = float(item.top_score)
    return max(score, 1.0 - score)


def _risk_band(item: ReviewItem) -> str:
    if item.status == "held" or item.decision_hint == "error":
        return "critical"
    if item.top_score is None:
        return "guarded"
    score = float(item.top_score)
    if score >= 0.85:
        return "critical"
    if score >= 0.65:
        return "elevated"
    if score >= 0.35:
        return "guarded"
    return "low"


def _score_text(score: float | int | None) -> str:
    if score is None:
        return "—"
    return f"{float(score) * 100:.1f}%"


def _time_text(iso_text: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
    except ValueError:
        return iso_text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    seconds = int((now - parsed.astimezone(timezone.utc)).total_seconds())
    if seconds < 60:
        return f"{max(seconds, 0)}s 前"
    if seconds < 3600:
        return f"{seconds // 60}m 前"
    if seconds < 86400:
        return f"{seconds // 3600}h 前"
    return f"{seconds // 86400}d 前"


def _event_tone(action: str) -> str:
    return action if action in {"approve", "reject", "blacklist", "hold", "retry"} else "noop"


def _effective_avatar_action(item: ReviewItem) -> str | None:
    if item.avatar_action is not None:
        return item.avatar_action
    if item.status == "rejected":
        return "replace_default"
    return "keep" if item.status == "approved" else None


def _avatar_action_label(action: str | None) -> str:
    return {
        "keep": "保留原头像",
        "replace_default": "替换默认头像",
        "blacklist": "Cravatar 全网黑名单",
        None: "待决定",
    }.get(action, str(action))


def _status_label(status: str) -> str:
    return {
        "pending": "待审核",
        "held": "已留置",
        "approved": "已通过",
        "rejected": "已拒绝",
    }.get(status, status)


def _decision_label(decision: str) -> str:
    return {
        "allow": "建议通过",
        "block": "建议拒绝",
        "review": "需要确认",
        "error": "检测异常",
    }.get(decision, decision)


def _risk_label(risk: str) -> str:
    return {
        "low": "低风险",
        "guarded": "需确认",
        "elevated": "高风险",
        "critical": "严重风险",
    }.get(risk, risk)


def _percent(part: int | float, total: int | float) -> float:
    if not total:
        return 0.0
    return round(min(max(float(part) / float(total) * 100.0, 0.0), 100.0), 1)


def _risk_summary(counts: Counter[str]) -> str:
    total = sum(counts.values())
    if not total:
        return "暂无信号"
    critical = counts.get("critical", 0)
    elevated = counts.get("elevated", 0)
    if critical:
        return f"{critical} 项严重风险"
    if elevated:
        return f"{elevated} 项高风险"
    return f"{total} 项已评分"


def _risk_class_label(counts: Counter[str]) -> str:
    if counts.get("critical", 0):
        return "critical"
    if counts.get("elevated", 0):
        return "elevated"
    if counts.get("guarded", 0):
        return "guarded"
    return "low"


def _status_filter_value(value: str) -> str:
    return value if value in {"all", "pending", "held", "reviewed", "approved", "rejected"} else "all"


def _risk_filter_value(value: str) -> str:
    return value if value in set(RISK_ORDER) | {"all"} else "all"


def _filter_option(value: str, label: str, selected: str) -> str:
    mark = " selected" if value == selected else ""
    return f'<option value="{escape(value)}"{mark}>{escape(label)}</option>'


def _nav_icon(name: str) -> str:
    paths = {
        "overview": '<path d="M4 13h6V4H4zM14 20h6v-9h-6zM4 20h6v-3H4zM14 7h6V4h-6z"></path>',
        "queue": '<rect x="4" y="4" width="16" height="16" rx="3"></rect><path d="M8 9h8M8 12h6M8 15h4"></path>',
        "agents": '<path d="M8 8h8v8H8zM12 3v3M12 18v3M3 12h3M18 12h3"></path><circle cx="10.5" cy="11" r=".7"></circle><circle cx="13.5" cy="11" r=".7"></circle><path d="M10 14h4"></path>',
        "guide": '<circle cx="12" cy="12" r="8.5"></circle><path d="M12 10v5M12 7.5h.01"></path>',
        "log": '<path d="M6 4.5h12v15H6z"></path><path d="M9 8h6M9 11.5h6M9 15h4"></path>',
        "policy": '<path d="M12 3.5l7 3v5.2c0 4.2-2.8 7.5-7 8.8-4.2-1.3-7-4.6-7-8.8V6.5z"></path><path d="M9 12l2 2 4-4"></path>',
        "quality": '<circle cx="12" cy="12" r="8.5"></circle><path d="m8.5 12 2.2 2.2 4.8-5"></path>',
        "health": '<path d="M3.5 12h4l1.8-4.5 3.2 9 2.1-4.5h5.9"></path>',
        "account": '<circle cx="12" cy="8" r="3.5"></circle><path d="M5.5 20c.7-4 3-6 6.5-6s5.8 2 6.5 6"></path>',
    }
    return f'<svg viewBox="0 0 24 24" aria-hidden="true">{paths.get(name, paths["guide"])}</svg>'


def _top_icon(name: str) -> str:
    paths = {
        "spark": '<path d="M12 3l1.4 4.1 4.1 1.4-4.1 1.4L12 14l-1.4-4.1-4.1-1.4 4.1-1.4z"></path><path d="M18 14l.8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8z"></path>',
        "bell": '<path d="M18 9a6 6 0 0 0-12 0c0 6.5-2.5 7-2.5 8.5h17C20.5 16 18 15.5 18 9"></path><path d="M10 20h4"></path>',
        "help": '<circle cx="12" cy="12" r="8.5"></circle><path d="M9.8 9.2a2.5 2.5 0 1 1 4.4 1.7c-.8.9-2.2 1.2-2.2 2.7M12 17h.01"></path>',
        "search": '<circle cx="10.7" cy="10.7" r="5.7"></circle><path d="M15 15l4 4"></path>',
        "settings": '<path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"></path><path d="m19.4 15 .1.1a1.8 1.8 0 0 1-2.5 2.5l-.1-.1a1.8 1.8 0 0 0-3.1 1.3v.2a1.8 1.8 0 0 1-3.6 0v-.2a1.8 1.8 0 0 0-3.1-1.3l-.1.1a1.8 1.8 0 1 1-2.5-2.5l.1-.1a1.8 1.8 0 0 0-1.3-3.1h-.2a1.8 1.8 0 0 1 0-3.6h.2a1.8 1.8 0 0 0 1.3-3.1l-.1-.1a1.8 1.8 0 1 1 2.5-2.5l.1.1a1.8 1.8 0 0 0 3.1-1.3V1.2a1.8 1.8 0 0 1 3.6 0v.2a1.8 1.8 0 0 0 3.1 1.3l.1-.1a1.8 1.8 0 0 1 2.5 2.5l-.1.1a1.8 1.8 0 0 0 1.3 3.1h.2a1.8 1.8 0 0 1 0 3.6h-.2a1.8 1.8 0 0 0-1.3 3.1Z"></path>',
        "grip": '<circle cx="8" cy="8" r="1"></circle><circle cx="16" cy="8" r="1"></circle><circle cx="8" cy="12" r="1"></circle><circle cx="16" cy="12" r="1"></circle><circle cx="8" cy="16" r="1"></circle><circle cx="16" cy="16" r="1"></circle>',
        "logout": '<path d="M10 17l5-5-5-5"></path><path d="M15 12H3"></path><path d="M21 19V5a2 2 0 0 0-2-2h-5"></path>',
        "close": '<path d="m6 6 12 12M18 6 6 18"></path>',
        "arrow": '<path d="m9 18 6-6-6-6"></path>',
        "guide": '<circle cx="12" cy="12" r="8.5"></circle><path d="M12 10v5M12 7.5h.01"></path>',
        "grid": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/>',
        "list": '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
        "zap": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
        "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
        "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
        "layout": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/>',
        "keyboard": '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M6 12h.01M10 12h.01M14 12h.01M18 12h.01M7 16h10"/>',
        "eye": '<path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.5"/>',
        "zoom": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4M10.5 7.5v6M7.5 10.5h6"/>',
        "ban": '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
        "pause": '<path d="M9 5v14M15 5v14"/>',
    }
    return f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths.get(name, paths["help"])}</svg>'
