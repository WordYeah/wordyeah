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
  --page: #eceef1;
  --page-wash: #f4f5f7;
  --app: #ffffff;
  --sidebar: #f7f7f8;
  --panel: #ffffff;
  --panel-soft: #fafafa;
  --panel-muted: #f2f3f5;
  --line: #e2e4e8;
  --line-strong: #d6d9df;
  --text: #202128;
  --muted: #747684;
  --quiet: #999ba7;
  --accent: #5b61d6;
  --accent-soft: #efefff;
  --green: #2e9d6a;
  --green-soft: #edf8f2;
  --amber: #ba7a2b;
  --amber-soft: #fff7eb;
  --red: #cd5867;
  --red-soft: #fff1f4;
  --shadow-app: 0 24px 70px rgba(22, 24, 29, 0.08);
  --radius-app: 24px;
  --radius-card: 16px;
  --radius-control: 12px;
  --font-display: "Seravek", "Lato", "Source Han Sans SC", "Noto Sans CJK SC", "Noto Sans SC", "PingFang SC", system-ui, -apple-system, sans-serif;
  --font: "Source Han Sans SC", "Noto Sans CJK SC", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", system-ui, -apple-system, sans-serif;
  --mono: "wenfeng-ibmps", "JetBrains Mono", "SFMono-Regular", "Menlo", "Consolas", monospace;
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
button, input, textarea, select { font: inherit; }
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
  color: #fff;
  transform: translateY(-180%);
  text-decoration: none;
  font-weight: 700;
}
.skip-link:focus { transform: translateY(0); }

.app-frame {
  width: min(1520px, calc(100vw - 112px));
  min-height: calc(100vh - 72px);
  margin: 36px auto;
  display: grid;
  grid-template-columns: 224px minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid rgba(215, 218, 223, 0.95);
  border-radius: var(--radius-app);
  background: var(--app);
  box-shadow: var(--shadow-app);
}

.side-nav {
  display: flex;
  min-height: 100%;
  flex-direction: column;
  gap: 28px;
  padding: 26px 16px 16px;
  background: var(--sidebar);
  border-right: 1px solid var(--line);
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 8px;
  color: var(--text);
  text-decoration: none;
  font-size: 18px;
  font-weight: 720;
  letter-spacing: -0.04em;
}

.brand-mark {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border-radius: 11px;
  background: var(--accent);
  color: #fff;
  font-size: 11px;
  font-weight: 850;
  letter-spacing: -0.08em;
}

.nav-section {
  display: grid;
  gap: 7px;
}

.nav-scroll {
  display: grid;
  gap: 28px;
}

.nav-label {
  margin: 0 8px 8px;
  color: var(--quiet);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.nav-item {
  display: flex;
  min-height: 44px;
  align-items: center;
  gap: 11px;
  padding: 9px 12px;
  border-radius: 12px;
  color: var(--muted);
  text-decoration: none;
  font-size: 13px;
  font-weight: 560;
  transition: background 140ms ease, color 140ms ease;
}

.nav-item:hover,
.nav-item:focus-visible {
  background: rgba(255, 255, 255, 0.8);
  color: var(--text);
}

.nav-item.is-active {
  background: #ffffff;
  color: var(--text);
  box-shadow: 0 3px 10px rgba(35, 36, 50, 0.045);
  font-weight: 650;
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
  gap: 10px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: #fff;
}

.usage-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.usage-card-head strong {
  font-size: 14px;
  letter-spacing: -0.03em;
}

.usage-card p {
  margin: -2px 0 2px;
  color: var(--muted);
  font-size: 12px;
}

.usage-icon {
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  border-radius: 9px;
  background: var(--accent-soft);
  color: var(--accent);
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

.usage-line strong { color: var(--text); }
.usage-bar {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: #eceef2;
}
.usage-bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--accent) 0%, #897dff 100%);
}

.status-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  border-radius: 50%;
  background: var(--green);
}
.status-dot.is-danger { background: var(--red); }

.consumer-switcher {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 10px 0;
  border-top: 1px solid var(--line);
}

.consumer-avatar {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border-radius: 50%;
  background: #dfdefb;
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
  background: rgba(255, 255, 255, 0.96);
}

.toolbar-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.toolbar-title strong {
  font-size: 14px;
  font-weight: 650;
  letter-spacing: -0.02em;
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
  background: #fff;
  color: var(--muted);
  font-size: 12px;
  font-weight: 650;
  text-decoration: none;
}

.pipeline-chip[data-tone="ready"] {
  border-color: #dedffd;
  background: #f7f7ff;
  color: var(--accent);
}

.pipeline-chip[data-tone="danger"] {
  border-color: #f1d5db;
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
  background: #fff;
  box-shadow: 0 18px 48px rgba(30, 31, 42, .12);
}
.account-popover p { margin: 0 0 10px; color: var(--muted); font-size: 12px; }
.account-popover .toolbar-logout button { width: 100%; justify-content: center; border-radius: 10px; }

.shell {
  max-width: 1260px;
  margin: 0 auto;
  padding: 34px 48px 40px;
}

.shell.shell-focus {
  max-width: 1320px;
  padding-top: 16px;
}

.page-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 28px;
}

.page-heading-copy { max-width: 720px; }

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
  font-size: clamp(30px, 3vw, 38px);
  font-weight: 700;
  letter-spacing: -0.055em;
  line-height: 1.08;
}

.page-heading p:not(.eyebrow) {
  margin: 14px 0 0;
  color: var(--muted);
  font-size: 15px;
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
  background: #fff;
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
  color: #fff;
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
  background: linear-gradient(180deg, #fdfdff 0%, #fafaff 100%);
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

.queue-section { margin-top: 12px; }
.queue-section.is-primary { margin-top: 0; }

.queue-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.queue-head h2 {
  margin: 0;
  font-size: 30px;
  font-weight: 680;
  letter-spacing: -0.04em;
}

.queue-head p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 12px;
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
  gap: 22px;
  margin-top: 18px;
  padding-bottom: 2px;
  border-bottom: 1px solid var(--line);
}

.page-tabs a {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  color: var(--muted);
  text-decoration: none;
  font-size: 13px;
  font-weight: 680;
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
  background: var(--accent-soft);
  color: var(--accent);
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
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
  background: #fff;
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
  background:
    linear-gradient(45deg, transparent 50%, var(--quiet) 50%) calc(100% - 18px) 16px / 5px 5px no-repeat,
    linear-gradient(135deg, var(--quiet) 50%, transparent 50%) calc(100% - 13px) 16px / 5px 5px no-repeat,
    #fff;
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
  border-top: 1px solid #eff0f3;
  border-bottom: 1px solid #eff0f3;
  background: #fff;
}

.queue-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 12px;
}

.queue-tool-meta { display: flex; align-items: center; gap: 10px; }

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
  min-height: 30px;
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
  background: #fff;
  color: var(--text);
  box-shadow: 0 1px 3px rgba(22, 24, 29, 0.07);
}

.batch-toggle {
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
  color: var(--muted);
  text-decoration: none;
  font-size: 12px;
  font-weight: 680;
}

.batch-toggle:hover,
.batch-toggle.is-active { border-color: #dcdafd; background: var(--accent-soft); color: var(--accent); }

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
  border: 1px solid #d7d4ff;
  border-radius: 13px;
  background: rgba(246, 246, 255, 0.97);
  box-shadow: 0 8px 24px rgba(46, 43, 108, 0.07);
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
  background: #fff;
  color: var(--text);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.batch-actions button[value="approve"] { color: var(--green); }
.batch-actions button[value="reject"] { color: var(--red); }
.batch-actions button[value="hold"] { color: var(--amber); }

.filtered-count {
  color: var(--quiet);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.batch-result {
  margin-top: 12px;
  padding: 9px 12px;
  border: 1px solid #dfe4ea;
  border-radius: 11px;
  background: var(--panel-soft);
  color: var(--muted);
  font-size: 12px;
}

.review-card.is-batch { display: grid; grid-template-columns: 34px minmax(0, 1fr); align-items: stretch; }
.batch-check { display: grid; place-items: center; border-right: 1px solid #eff0f3; cursor: pointer; }
.batch-check input { width: 16px; height: 16px; accent-color: var(--accent); }

.review-card {
  border-bottom: 1px solid #eff0f3;
  background: #fff;
}
.review-card:last-child { border-bottom: 0; }
.review-card.is-focused { background: #fbfbff; }

.review-row-link {
  display: grid;
  grid-template-columns: 76px 190px minmax(280px, 1fr) 170px 22px;
  gap: 14px;
  align-items: center;
  min-height: 82px;
  padding: 13px 8px;
  color: inherit;
  text-decoration: none;
}

.review-row-link:hover { background: #fcfcfd; }

.row-preview {
  position: relative;
  width: 76px;
  height: 52px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #f1f2f4;
}

.queue-list[data-view="grid"] {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  padding: 14px 0;
  border-bottom: 0;
  background: transparent;
}
.queue-list[data-view="grid"] .review-card {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: #fff;
}
.queue-list[data-view="grid"] .review-card.is-batch { grid-template-columns: 1fr; }
.queue-list[data-view="grid"] .batch-check { min-height: 34px; border-right: 0; border-bottom: 1px solid var(--line); place-items: center start; padding: 0 10px; }
.queue-list[data-view="grid"] .review-row-link {
  display: grid;
  grid-template-columns: 1fr 22px;
  gap: 10px;
  min-height: 0;
  padding: 10px;
}
.queue-list[data-view="grid"] .row-preview { grid-column: 1 / -1; width: 100%; height: 148px; border-radius: 10px; }
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
  background: #fff;
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
  background:
    linear-gradient(135deg, #f6f7f9 25%, transparent 25%) 0 0 / 18px 18px,
    linear-gradient(315deg, #f6f7f9 25%, #eef0f3 25%) 0 0 / 18px 18px;
  font-size: 12px;
  text-align: center;
}

.media-fallback span {
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
}

.row-risk-dot {
  position: absolute;
  right: 8px;
  bottom: 8px;
  width: 10px;
  height: 10px;
  border: 2px solid #fff;
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
  border-radius: 24px;
  background: #fff;
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
  border-radius: 999px;
  background: var(--panel-soft);
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
}

.media-preview {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: #f2f3f5;
}

.media-preview img {
  width: 100%;
  max-height: clamp(250px, calc(100vh - 640px), 430px);
  object-fit: contain;
  background: #f2f3f5;
}

.media-preview .mini-note {
  margin: 0;
  padding: 12px 14px;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 11px;
}

.action-form {
  position: sticky;
  z-index: 4;
  bottom: 16px;
  display: grid;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 14px 34px rgba(25, 27, 35, 0.08);
}

.action-form label {
  color: var(--quiet);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.action-form input[type="text"] {
  width: 100%;
  min-height: 42px;
  padding: 0 14px;
  border: 1px solid var(--line);
  border-radius: 12px;
  outline: 0;
  background: #fff;
  color: var(--text);
}

.action-form input[type="text"]:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(97, 89, 216, 0.08);
}

.action-caption {
  color: var(--muted);
  font-size: 12px;
}

.action-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.action-buttons button {
  min-height: 40px;
  padding: 0 16px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #fff;
  color: var(--text);
  font-size: 13px;
  font-weight: 720;
  cursor: pointer;
}

.action-buttons button:hover,
.action-buttons button:focus-visible { border-color: var(--line-strong); }

.action-buttons button[data-action="approve"] {
  border-color: #d3eadc;
  background: var(--green-soft);
  color: var(--green);
}

.action-buttons button[data-action="reject"] {
  border-color: #f1d7dd;
  background: var(--red-soft);
  color: var(--red);
}

.action-buttons button[data-action="hold"] {
  border-color: #f0dec2;
  background: var(--amber-soft);
  color: var(--amber);
}

.action-buttons button[data-action="retry"] {
  border-color: #e0ddff;
  background: var(--accent-soft);
  color: var(--accent);
}

.evidence-block {
  padding: 20px;
  border: 1px solid var(--line);
  border-radius: 20px;
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
  border-radius: 14px;
  background: #fff;
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
  border-radius: 20px;
  background: #fff;
}

.audit-log summary,
.guide summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px;
  cursor: pointer;
  list-style: none;
  font-size: 13px;
  font-weight: 720;
}

.audit-log summary::-webkit-details-marker,
.guide summary::-webkit-details-marker { display: none; }

.audit-log summary::after,
.guide summary::after {
  content: "+";
  color: var(--quiet);
  font-size: 18px;
  font-weight: 400;
}

.audit-log[open] summary::after,
.guide[open] summary::after { content: "−"; }

.guide-body,
.audit-log-body { padding: 0 18px 18px; }
.audit-log-body { overflow-x: auto; }

.audit-log table {
  width: 100%;
  border-collapse: collapse;
  color: var(--muted);
  font-size: 12px;
  text-align: left;
}

.audit-log th,
.audit-log td {
  padding: 12px 8px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
}

.audit-log th {
  color: var(--quiet);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.audit-log tr:last-child td { border-bottom: 0; }

.empty-state {
  grid-column: 1 / -1;
  padding: 56px 28px;
  border: 1px dashed var(--line-strong);
  border-radius: 18px;
  color: var(--muted);
  background: var(--panel-soft);
  text-align: center;
}

.empty-state strong {
  display: block;
  margin-bottom: 6px;
  color: var(--text);
  font-size: 16px;
  font-weight: 740;
}

.footer-note {
  margin: 26px 0 0;
  color: var(--quiet);
  font-size: 11px;
}

.focus-hint {
  margin-top: 32px;
  padding: 24px 26px;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: var(--panel-soft);
}

.focus-hint h2 {
  margin: 0;
  font-size: 18px;
  letter-spacing: -0.03em;
}

.focus-hint p {
  margin: 8px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.quiet { color: var(--quiet); }
.event-action[data-action="approve"] { color: var(--green); }
.event-action[data-action="reject"] { color: var(--red); }
.event-action[data-action="hold"] { color: var(--amber); }
.event-action[data-action="retry"] { color: var(--accent); }

@media (max-width: 1160px) {
  .queue-list[data-view="grid"] { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .app-frame {
    width: min(calc(100vw - 40px), 1520px);
    grid-template-columns: 208px minmax(0, 1fr);
  }

  .shell { padding-right: 34px; padding-left: 34px; }
  .topbar { padding-right: 24px; padding-left: 24px; }
  .queue-list-head,
  .review-row-link { min-width: 860px; }
  .detail-layout { grid-template-columns: 292px minmax(0, 1fr); }
}

@media (max-width: 760px) {
  .queue-tools, .batch-bar { align-items: stretch; flex-direction: column; }
  .view-switch { overflow-x: auto; }
  .queue-list[data-view="grid"] { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
  .queue-list[data-view="grid"] .row-preview { height: 120px; }
  .app-frame {
    width: 100%;
    min-height: 100vh;
    margin: 0;
    display: block;
    border: 0;
    border-radius: 0;
    box-shadow: none;
  }

  .side-nav {
    min-height: auto;
    gap: 14px;
    padding: 16px 12px 10px;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .nav-section {
    display: flex;
    gap: 4px;
    overflow-x: auto;
  }

  .nav-scroll {
    display: flex;
    gap: 4px;
    overflow-x: auto;
  }

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
  .queue-list-head { display: none; }
  .queue-list { overflow: visible; }
  .review-row-link {
    position: relative;
    min-width: 0;
    grid-template-columns: 72px minmax(0, 1fr) 20px;
    gap: 12px;
    padding: 16px;
  }
  .row-preview { width: 72px; height: 58px; }
  .row-ai,
  .row-decision { grid-column: 2 / -1; }
  .row-open { position: absolute; right: 16px; top: 20px; }
  .detail-layout { grid-template-columns: 1fr; }
  .detail-sidebar {
    padding: 22px 20px;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .detail-stage { padding: 22px 20px 24px; }
  .media-preview img { max-height: 320px; }
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
  const form = document.querySelector('[data-batch-form]');
  if (form) {
    const boxes = [...form.querySelectorAll('input[name="selected"]')];
    const all = form.querySelector('[data-select-all]');
    const count = form.querySelector('[data-selected-count]');
    const sync = () => {
      const selected = boxes.filter((box) => box.checked).length;
      count.textContent = String(selected);
      all.checked = boxes.length > 0 && selected === boxes.length;
      all.indeterminate = selected > 0 && selected < boxes.length;
    };
    all.addEventListener('change', () => {
      boxes.forEach((box) => { box.checked = all.checked; });
      sync();
    });
    boxes.forEach((box) => box.addEventListener('change', sync));
    form.addEventListener('submit', (event) => {
      const selected = boxes.filter((box) => box.checked).length;
      if (!selected) {
        event.preventDefault();
        window.alert('请先选择审核项目。');
        return;
      }
      const action = event.submitter?.value || '处理';
      if (!window.confirm(`确认对 ${selected} 个项目执行 ${action}？每项会独立写入审核记录。`)) {
        event.preventDefault();
      }
    });
    sync();
  }

  const actionForm = document.querySelector('.action-form');
  if (actionForm) {
    document.addEventListener('keydown', (event) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return;
      const key = event.key.toLowerCase();
      const shortcut = {a: 'approve', r: 'reject', h: 'hold'}[key];
      if (shortcut) {
        event.preventDefault();
        actionForm.querySelector(`[data-action="${shortcut}"]`)?.click();
      }
      if (key === 'j') document.querySelector('[data-focus-next]')?.click();
      if (key === 'k') document.querySelector('[data-focus-previous]')?.click();
    });
  }
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
    pending_count = sum(1 for item in all_items if item.status == "pending")
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
              <button type="submit" name="action" value="reject">批量拒绝</button>
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
  <meta name="color-scheme" content="light">
  <title>{escape(page_title)}</title>
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
          <span>WordYeah / 图像审核</span>
        </div>
        <div class="toolbar-actions">
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
        <div class="detail-return">
          <a href="{escape(_review_href(status=status_filter, risk=risk_filter, query=search_query, view='list'))}#review-queue">← 返回审核队列</a>
          <span>{escape(consumer_id)} · {escape(policy_profile)}</span>
        </div>
        {detail_html}
        ''' if focus_item_id else f'''
        <section class="queue-section is-primary" id="review-queue" aria-labelledby="queue-title">
          <div class="queue-head">
            <div>
              <h2 id="queue-title">审核队列</h2>
              <p>{'AI 自动处理已完成，仅展示例外项。' if service_ready else escape(service_error or '审核服务未就绪，当前例外项保持 fail-closed。')}</p>
            </div>
          </div>

          <nav class="page-tabs" aria-label="审核状态">
            <a class="{'is-active' if active_tab == 'pending' else ''}" href="/review?status=pending#review-queue">待审核 <span>{pending_count}</span></a>
            <a class="{'is-active' if active_tab == 'held' else ''}" href="/review?status=held#review-queue">已留置 <span>{held_count}</span></a>
            <a class="{'is-active' if active_tab == 'reviewed' else ''}" href="/review?status=reviewed#review-queue">已处理 <span>{reviewed_count}</span></a>
            <a class="{'is-active' if active_tab == 'all' else ''}" href="/review?status=all#review-queue">全部 <span>{total_count}</span></a>
          </nav>

          <form class="filter-bar" method="get" action="/review">
            <input type="hidden" name="view" value="{escape(view_value if view_value != 'focus' else 'list')}">
            {'<input type="hidden" name="batch" value="1">' if batch_mode else ''}
            <label class="search-control">
              {_top_icon("search")}
              <span class="sr-only">搜索图片或 ID</span>
              <input name="q" type="search" value="{escape(search_query)}" placeholder="搜索图片、ID 或哈希">
            </label>
            <label>
              <span class="sr-only">审核状态</span>
              <select class="filter-control" name="status">
                {_filter_option("all", "全部状态", status_value)}
                {_filter_option("pending", "待审核", status_value)}
                {_filter_option("held", "已留置", status_value)}
                {_filter_option("reviewed", "已处理", status_value)}
                {_filter_option("approved", "已通过", status_value)}
                {_filter_option("rejected", "已拒绝", status_value)}
              </select>
            </label>
            <label>
              <span class="sr-only">风险等级</span>
              <select class="filter-control" name="risk">
                {_filter_option("all", "全部风险", risk_value)}
                {_filter_option("low", "低风险", risk_value)}
                {_filter_option("guarded", "需确认", risk_value)}
                {_filter_option("elevated", "高风险", risk_value)}
                {_filter_option("critical", "严重风险", risk_value)}
              </select>
            </label>
            <button class="filter-submit" type="submit">筛选</button>
          </form>

          <div class="queue-tools">
            <nav class="view-switch" aria-label="队列视图">
              <a class="{'is-active' if view_value == 'list' else ''}" href="{escape(_review_href(status=status_filter, risk=risk_filter, query=search_query, view='list', batch=batch_mode))}">紧凑列表</a>
              <a class="{'is-active' if view_value == 'grid' else ''}" href="{escape(_review_href(status=status_filter, risk=risk_filter, query=search_query, view='grid', batch=batch_mode))}">视觉网格</a>
              <a class="{'is-active' if view_value == 'focus' else ''}" href="{escape(_review_href(status=status_filter, risk=risk_filter, query=search_query, view='focus'))}">快速标记</a>
            </nav>
            <div class="queue-tool-meta">
              <span class="filtered-count">当前显示 {len(filtered_items)} 项</span>
              <a class="batch-toggle{' is-active' if batch_mode else ''}" href="{escape(_review_href(status=status_filter, risk=risk_filter, query=search_query, view=view_value if view_value != 'focus' else 'list', batch=not batch_mode))}">{'退出批量模式' if batch_mode else '批量模式'}</a>
            </div>
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
    return f"""
    <article class="review-card{focus_class}{batch_class}" data-risk="{escape(view.risk_band)}" data-lane="{escape(view.lane)}" id="{escape(item.item_id)}">
      {batch_check}
      <a class="review-row-link" href="{escape(href)}" aria-label="查看 {escape(item.item_id)}">
        <div class="row-preview">
          {_media_thumbnail(item)}
          <span class="row-risk-dot risk-{escape(view.risk_band)}" aria-label="{escape(_risk_label(view.risk_band))}"></span>
        </div>
        <div class="row-identity">
          <strong>{escape(_decision_label(item.decision_hint))}</strong>
          <span class="row-time">等待 {escape(_time_text(item.created_at).replace(' 前', ''))}</span>
          <span class="sr-only">{escape(item.item_id)}</span>
        </div>
        <div class="row-ai">
          <strong>{escape(_product_reason(item))}</strong>
        </div>
        <div class="row-decision">
          <span class="status-pill status-{escape(item.status)}">{escape(_status_label(item.status))}</span>
          <small>{escape(confidence)} 置信度</small>
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
    previous_link = (
        f'<a href="{escape(previous_href)}" data-focus-previous>← 上一条 <span class="mono">K</span></a>'
        if previous_href else ""
    )
    next_link = (
        f'<a href="{escape(next_href)}" data-focus-next>下一条 <span class="mono">J</span> →</a>'
        if next_href else ""
    )
    return f"""
    <div class="focus-nav">
      <div class="focus-nav-group">{previous_link}{next_link}</div>
      <span class="focus-shortcuts">A 通过 · R 拒绝 · H 留置 · J/K 切换</span>
    </div>
    <section class="review-detail" id="review-detail" aria-labelledby="detail-title">
      <header class="detail-header">
        <div>
          <p class="detail-kicker">AI 无法确定 · 需要人工判断</p>
          <h2 id="detail-title">人工确认</h2>
          <p>{escape(item.item_id)} · {escape(_product_reason(item))}</p>
        </div>
        <a class="detail-close" href="/review#review-queue" aria-label="关闭详情">{_top_icon("close")}</a>
      </header>

      <div class="detail-layout">
        <aside class="detail-sidebar">
          <section class="sidebar-section">
            <h3>案件摘要</h3>
            <div class="detail-facts summary-facts">
              <div class="detail-fact"><div class="label">审核状态</div><div class="value"><span class="status-pill status-{escape(item.status)}">{escape(_status_label(item.status))}</span></div></div>
              <div class="detail-fact"><div class="label">AI 建议</div><div class="value">{escape(_decision_label(item.decision_hint))}</div></div>
              <div class="detail-fact"><div class="label">风险等级</div><div class="value"><span class="risk-{escape(risk_band)}">{escape(_risk_label(risk_band))}</span></div></div>
              <div class="detail-fact"><div class="label">模型置信度</div><div class="value">{escape(confidence_text)}</div></div>
            </div>
          </section>

          <section class="sidebar-section">
            <h3>证据与元数据</h3>
            <div class="detail-facts">
              <div class="detail-fact"><div class="label">进入人工原因</div><div class="value">{escape(_reason_summary(item))}</div></div>
              <div class="detail-fact"><div class="label">策略版本</div><div class="value mono">{escape(item.policy_version)}</div></div>
              <div class="detail-fact"><div class="label">媒体类型</div><div class="value">{escape(item.media_type)}</div></div>
              <div class="detail-fact"><div class="label">创建时间</div><div class="value">{escape(_time_text(item.created_at, current_ts))}</div></div>
              <div class="detail-fact"><div class="label">记录版本</div><div class="value">{item.version}</div></div>
              <div class="detail-fact"><div class="label">SHA-256</div><div class="value mono">{escape(item.content_sha256[:20])}…</div></div>
              <div class="detail-fact"><div class="label">参与模型</div><div class="value">{_render_model_versions(item)}</div></div>
            </div>
          </section>
        </aside>

        <div class="detail-stage">
          <section class="preview-panel">
            <div class="detail-section-heading">
              <h3>受控图片预览<span class="sr-only">Controlled media preview</span></h3>
              <span class="detail-chip mono">{escape(item.item_id[:12])}</span>
            </div>
            {_media_preview(item)}
          </section>

          <form method="post" class="action-form">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
            <input type="hidden" name="version" value="{item.version}">
            <label for="note-{escape(item.item_id)}">审核备注</label>
            <input id="note-{escape(item.item_id)}" name="note" type="text" maxlength="2000" placeholder="记录人工判断依据（可选）">
            <div class="action-caption">选择明确结论；证据不足时留置复核。</div>
            <div class="action-buttons">{buttons}</div>
          </form>

          <section class="evidence-block detail-findings">
            <h3>模型判断摘要<span class="sr-only">Model finding summary</span></h3>
            <ul class="finding-list">{findings}</ul>
          </section>

          <details class="audit-log detail-audit">
            <summary><span>这张图片的操作记录</span><span class="quiet">AI 操作记录<span class="sr-only">Agent action log</span></span></summary>
            <div class="audit-log-body">
              <ul class="event-list">{timeline}</ul>
            </div>
          </details>
        </div>
      </div>
    </section>
    """


def _media_thumbnail(item: ReviewItem) -> str:
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
    return '<div class="media-fallback"><span>暂无受控预览</span></div>'


def _media_preview(item: ReviewItem) -> str:
    cravatar_url = _cravatar_preview_url(item, size=512)
    if cravatar_url is not None:
        return f"""
        <div class="media-preview">
          <img src="{escape(cravatar_url)}" alt="Cravatar 受控头像预览" loading="eager" decoding="async">
          <p class="mini-note">预览地址由 allowlisted <code>cn.cravatar.com/avatar/&lt;md5&gt;</code> 规则生成，不接受任意远程 URL。</p>
        </div>
        """
    if item.media_type != "image" or not item.media_ref.startswith("media://"):
        return (
            '<div class="media-preview"><div class="media-fallback">'
            "<span>暂无受控本地预览</span></div></div>"
        )
    return f"""
    <div class="media-preview">
      <img src="/review/items/{escape(item.item_id)}/media" alt="受控图片预览" loading="lazy" decoding="async">
      <p class="mini-note">预览通过 reviewer session 和 allowlisted <code>media://</code> 引用提供；浏览器不会收到原始存储路径。</p>
    </div>
    """


def _cravatar_preview_url(item: ReviewItem, *, size: int) -> str | None:
    if item.media_type != "image" or not item.media_ref.startswith("cravatar://"):
        return None
    avatar_hash = item.media_ref.removeprefix("cravatar://").strip().lower()
    if len(avatar_hash) != 32 or any(character not in "0123456789abcdef" for character in avatar_hash):
        return None
    bounded_size = min(max(size, 16), 1024)
    return f"https://cn.cravatar.com/avatar/{avatar_hash}?s={bounded_size}&d=404&r=x"


def _manual_actions(item: ReviewItem, csrf_token: str) -> str:
    if item.status in {"held", "rejected"}:
        return _action_button(item, "retry", "retry", "重新检查")
    return "".join(
        [
            _action_button(item, "approve", "approve", "通过"),
            _action_button(item, "reject", "reject", "拒绝"),
            _action_button(item, "hold", "hold", "留置人工复核"),
        ]
    )


def _action_button(item: ReviewItem, action: str, data_action: str, label: str) -> str:
    return (
        f'<button type="submit" formaction="/review/items/{escape(item.item_id)}/{action}" '
        f'data-action="{escape(data_action)}">{escape(label)}</button>'
    )


def _detail_events(events: tuple[ReviewEvent, ...], current_ts: datetime) -> str:
    if not events:
        return "<li class='event-item'><div class='sub'>这张图片还没有记录过审核动作。</div></li>"
    rows = []
    for event in events:
        rows.append(
            f"""<li class="event-item">
              <div class="top">
                <strong class="event-action" data-action="{escape(_event_tone(event.action))}">{escape(event.action)}</strong>
                <span class="sub">{escape(_time_text(event.created_at, current_ts))}</span>
              </div>
              <div class="sub">审核员：{escape(event.reviewer)} · request <code>{escape(event.request_id or "—")}</code></div>
              <div class="sub">{escape(event.before_status or "—")} → {escape(event.after_status or "—")}</div>
              {f'<div class="sub">备注：{escape(event.note)}</div>' if event.note else ""}
            </li>"""
        )
    return "".join(rows)


def _finding_rows(item: ReviewItem) -> str:
    if not item.findings:
        return "<li class='finding-item'><div class='sub'>没有记录到模型 finding。</div></li>"
    rows = []
    for finding in item.findings:
        category = escape(str(finding.get("category", "unknown")))
        label = escape(str(finding.get("label", "unknown")))
        score = finding.get("score")
        source = escape(str(finding.get("source", "unknown")))
        score_text = _score_text(score if isinstance(score, (float, int)) else None)
        rows.append(
            f"""<li class="finding-item">
              <div class="top"><strong>{category} / {label}</strong><span class="sub">{escape(score_text)}</span></div>
              <div class="sub">source: <code>{source}</code></div>
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
    return action if action in {"approve", "reject", "hold", "retry"} else "noop"


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
    }
    return f'<svg viewBox="0 0 24 24" aria-hidden="true">{paths.get(name, paths["help"])}</svg>'
