"""Standalone, low-noise endeavor history page.

The live control plane deliberately remains at `/`.  This page reads only the
scoped `/admin/history/*` projection endpoints and never polls or mounts raw
exchange payloads until the operator explicitly requests one.
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>History · llm-super</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🛰️</text></svg>">
<style>
/*__DESIGN_TOKENS__*/
* { box-sizing: border-box; }
html { min-height: 100%; }
body {
  margin: 0;
  min-height: 100%;
  background: var(--page);
  color: var(--ink);
  font: 14px/1.48 var(--ds-font-ui);
}
button, input, select { font: inherit; }
button, a { -webkit-tap-highlight-color: transparent; }
button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible,
[tabindex]:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--accent) 45%, transparent);
  outline-offset: 2px;
}
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  min-height: 58px;
  display: flex;
  align-items: center;
  gap: 22px;
  padding: 9px clamp(14px, 3vw, 38px);
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface) 92%, transparent);
  backdrop-filter: blur(14px);
}
.brand {
  color: var(--ink);
  text-decoration: none;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -.02em;
  white-space: nowrap;
}
.nav { display: flex; gap: 3px; }
.nav a {
  padding: 6px 10px;
  border-radius: 7px;
  color: var(--ink-2);
  text-decoration: none;
  font-size: 13px;
}
.nav a:hover { background: var(--surface-2); color: var(--ink); }
.nav a[aria-current="page"] {
  color: var(--accent);
  background: var(--accent-soft);
  font-weight: 650;
}
.top-actions { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.organizing-model {
  width: min(1564px, calc(100% - 28px));
  margin: 14px auto 0;
  display: grid;
  grid-template-columns: max-content repeat(7, max-content);
  align-items: center;
  justify-content: center;
  gap: 9px;
  padding: 10px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  box-shadow: var(--shadow);
}
.organizing-model > strong { margin-right: 8px; font-size: 11px; }
.organizing-step { display: grid; gap: 1px; }
.organizing-step b { font-size: 10px; text-transform: uppercase; letter-spacing: .07em; }
.organizing-step span { color: var(--muted); font-size: 9.5px; }
.organizing-arrow { color: var(--accent); font-size: 8px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
button {
  border: 1px solid var(--line-2);
  border-radius: 7px;
  padding: 6px 10px;
  background: var(--surface);
  color: var(--ink);
  cursor: pointer;
}
button:hover { border-color: var(--accent); }
button.primary { background: var(--accent); border-color: var(--accent); color: white; }
button.quiet { border-color: transparent; background: transparent; color: var(--ink-2); }
button:disabled { cursor: default; opacity: .5; }
.shell {
  width: min(1640px, 100%);
  margin: 0 auto;
  padding: 20px clamp(14px, 3vw, 38px) 50px;
  display: grid;
  grid-template-columns: minmax(280px, 370px) minmax(0, 1fr);
  gap: 18px;
}
.sidebar, .detail {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: var(--shadow);
}
.sidebar {
  align-self: start;
  position: sticky;
  top: 78px;
  overflow: hidden;
  max-height: calc(100vh - 98px);
  display: flex;
  flex-direction: column;
}
.sidebar-head { padding: 14px; border-bottom: 1px solid var(--line); }
.eyebrow {
  margin: 0 0 3px;
  color: var(--muted);
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: .11em;
  font-weight: 700;
}
h1, h2, h3, p { margin-top: 0; }
h1 { font-size: clamp(20px, 3vw, 29px); line-height: 1.18; letter-spacing: -.035em; }
h2 { font-size: 16px; letter-spacing: -.015em; }
h3 { font-size: 13px; }
.filters { display: grid; grid-template-columns: 1fr 118px; gap: 7px; margin-top: 11px; }
.filters input, .filters select {
  min-width: 0;
  border: 1px solid var(--line-2);
  border-radius: 7px;
  padding: 7px 9px;
  background: var(--page);
  color: var(--ink);
}
.result-count {
  padding: 8px 14px;
  color: var(--muted);
  border-bottom: 1px solid var(--line);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}
.endeavor-list { overflow: auto; overscroll-behavior: contain; }
.endeavor {
  width: 100%;
  display: block;
  padding: 13px 14px;
  border: 0;
  border-bottom: 1px solid var(--line);
  border-radius: 0;
  background: transparent;
  text-align: left;
}
.e-context {
  display: -webkit-box;
  margin-top: 5px;
  color: var(--ink-2);
  font-size: 11.5px;
  line-height: 1.35;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.endeavor:hover { background: var(--surface-2); }
.endeavor.selected {
  background: var(--accent-soft);
  box-shadow: inset 3px 0 var(--accent);
}
.e-title { display: flex; gap: 8px; align-items: flex-start; font-weight: 680; }
.e-title .text { min-width: 0; flex: 1; }
.meta {
  color: var(--muted);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}
.e-meta { margin: 5px 0 0 24px; }
.loadbar { padding: 10px 14px; text-align: center; }
.status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid currentColor;
  border-radius: 999px;
  padding: 1px 7px;
  font-size: 10.5px;
  line-height: 1.5;
  font-weight: 650;
  white-space: nowrap;
}
.status::before { content: "●"; font-size: 7px; }
.status.accepted, .status.succeeded { color: var(--good); background: var(--good-soft); }
.status.failed { color: var(--bad); background: var(--bad-soft); }
.status.interrupted, .status.warning { color: var(--warn); background: var(--warn-soft); }
.status.unknown { color: var(--unknown); background: var(--surface-2); }
.detail { min-height: calc(100vh - 98px); overflow: clip; }
.empty {
  min-height: 460px;
  display: grid;
  place-items: center;
  padding: 30px;
  color: var(--muted);
  text-align: center;
}
.detail-head { padding: 22px 24px 15px; border-bottom: 1px solid var(--line); }
.detail-title { display: flex; align-items: flex-start; gap: 10px; }
.detail-title h1 { margin-bottom: 5px; }
.detail-title .status { margin-top: 4px; }
.targetline { color: var(--ink-2); font-size: 12px; }
.tabs {
  display: flex;
  gap: 3px;
  padding: 0 20px;
  border-bottom: 1px solid var(--line);
  overflow-x: auto;
}
.tab {
  border: 0;
  border-bottom: 2px solid transparent;
  border-radius: 0;
  padding: 10px 9px 9px;
  color: var(--muted);
  background: transparent;
  white-space: nowrap;
}
.tab[aria-selected="true"] { color: var(--accent); border-bottom-color: var(--accent); }
.panel { padding: 20px 24px 34px; }
.grid { display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 9px; }
.metric {
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 10px 12px;
  background: var(--page);
}
.metric .k { color: var(--muted); font-size: 10.5px; text-transform: uppercase; letter-spacing: .07em; }
.metric .v { margin-top: 3px; font-size: 19px; font-weight: 670; font-variant-numeric: tabular-nums; }
.metric .s { margin-top: 2px; color: var(--muted); font-size: 10.5px; }
.section { margin-top: 21px; }
.section-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
}
.section-head h2 { margin: 0; }
.section-head .meta { margin-left: auto; }
.callout {
  border: 1px solid var(--line);
  border-left: 4px solid var(--accent);
  border-radius: 8px;
  padding: 11px 13px;
  background: var(--accent-soft);
}
.callout.warn { border-left-color: var(--warn); background: var(--warn-soft); }
.callout.bad { border-left-color: var(--bad); background: var(--bad-soft); }
.run-list, .timeline { display: grid; gap: 7px; }
.run, .timeline-item {
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--page);
}
.run { padding: 10px 12px; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 7px 12px; }
.run-title { font-weight: 630; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.run-stats { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 5px 12px; }
.run-context { grid-column: 1 / -1; }
.summary-coverage { margin-top: 7px; }
.timeline-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.timeline-toolbar label { color: var(--ink-2); font-size: 12px; display: flex; gap: 6px; }
.timeline-item { padding: 10px 12px; }
.timeline-item.control { border-left: 4px solid var(--accent); }
.timeline-item.poll_group { border-left: 4px solid var(--warn); }
.timeline-item.failed { border-left: 4px solid var(--bad); }
.timeline-item.interrupted { border-left: 4px solid var(--warn); }
.t-head { display: flex; align-items: flex-start; gap: 8px; }
.t-main { min-width: 0; flex: 1; }
.t-title { font-weight: 640; }
.t-line { display: flex; flex-wrap: wrap; gap: 5px 12px; margin-top: 4px; }
.pill {
  display: inline-flex;
  border: 1px solid var(--line-2);
  border-radius: 999px;
  padding: 1px 7px;
  color: var(--ink-2);
  font-size: 10.5px;
}
.tool-list { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
.summary-stack { display: grid; gap: 6px; margin-top: 9px; }
.message-summary {
  position: relative;
  border-left: 3px solid var(--line-2);
  padding: 4px 0 4px 13px;
  color: var(--ink-2);
}
.message-summary::before { content: ""; position: absolute; left: -6px; top: 9px;
  width: 9px; height: 9px; border-radius: 50%; background: var(--accent);
  box-shadow: 0 0 0 3px var(--surface); }
.message-summary .summary-head { color: var(--ink); font-weight: 640; }
.message-summary .summary-role {
  margin-right: 6px;
  color: var(--accent);
  font-size: 9.5px;
  font-weight: 720;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.message-summary .summary-body { margin-top: 2px; font-size: 12px; }
.message-summary .summary-short { margin-top: 3px; color: var(--ink); font-size: 12px; }
.message-summary .summary-node { display: block; margin-bottom: 2px; font-size: 12.5px;
  color: var(--ink); }
.message-summary details { margin-top: 4px; font-size: 11.5px; }
.message-summary details summary { cursor: pointer; color: var(--accent); }
.conversation-flow { display: grid;
  grid-template-columns: minmax(0,1fr) 26px minmax(0,1fr) 26px minmax(0,1fr);
  align-items: stretch; margin-top: 9px; }
.flow-arrow { display: grid; place-items: center; color: var(--accent); font-size: 17px; }
.flow-stage { min-width: 0; border: 1px solid var(--line); border-radius: 8px;
  padding: 8px 9px; background: var(--surface); }
.flow-stage.active { border-top: 2px solid var(--accent); }
.flow-stage .fk { color: var(--muted); font-size: 9px; font-weight: 720;
  letter-spacing: .08em; text-transform: uppercase; }
.flow-stage .fv { display: -webkit-box; margin-top: 3px; overflow: hidden;
  -webkit-box-orient: vertical; -webkit-line-clamp: 3; color: var(--ink-2); font-size: 11.5px; }
.flow-caption { margin-top: 7px; color: var(--ink-2); font-size: 11.5px; }
.provider-summaries {
  margin-top: 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-2);
}
.provider-summaries > summary {
  cursor: pointer;
  padding: 7px 9px;
  color: var(--ink-2);
  font-size: 11px;
  font-weight: 650;
}
.provider-summaries .summary-stack { margin: 0; padding: 0 9px 9px; }
.warning-list { margin: 8px 0 0; padding: 0; list-style: none; }
.warning-list li { color: var(--warn); font-size: 11.5px; margin-top: 3px; }
.rawlinks { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 5px; }
.rawlinks button { padding: 3px 7px; font-size: 10.5px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.prompt-card { padding: 11px 12px; border: 1px solid var(--line); border-radius: 9px; background: var(--page); }
.prompt-card + .prompt-card { margin-top: 7px; }
.mono { font-family: ui-monospace, "SFMono-Regular", Consolas, monospace; }
.break { overflow-wrap: anywhere; word-break: break-word; }
.error {
  margin: 12px;
  border: 1px solid var(--bad);
  border-radius: 8px;
  padding: 10px 12px;
  color: var(--bad);
  background: var(--bad-soft);
}
.skeleton { color: var(--muted); animation: pulse 1.4s ease-in-out infinite; }
dialog {
  width: min(1060px, calc(100vw - 28px));
  max-height: calc(100vh - 40px);
  padding: 0;
  border: 1px solid var(--line-2);
  border-radius: 12px;
  background: var(--surface);
  color: var(--ink);
  box-shadow: 0 24px 90px rgba(0,0,0,.35);
}
dialog::backdrop { background: rgba(0,0,0,.55); backdrop-filter: blur(2px); }
.dialog-head {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 14px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.dialog-head h2 { margin: 0; flex: 1; }
.rawmeta { padding: 9px 14px; color: var(--muted); font-size: 11px; border-bottom: 1px solid var(--line); }
.view-toggle { display: inline-flex; border: 1px solid var(--line); border-radius: 7px; overflow: hidden; }
.view-toggle button { border: 0; border-radius: 0; padding: 4px 8px; }
.view-toggle button[aria-pressed="true"] { background: var(--accent-soft); color: var(--accent); }
#rawBody { padding: 14px; min-height: 180px; overflow: auto; }
#rawJSON {
  margin: 0;
  padding: 14px;
  min-height: 180px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: 11.5px/1.45 ui-monospace, "SFMono-Regular", Consolas, monospace;
}
.raw-section + .raw-section { margin-top: 14px; }
.raw-section h3 { display: flex; align-items: baseline; gap: 7px; margin-bottom: 7px; }
.chat-thread { display: grid; gap: 8px; }
.chat-message { display: grid; grid-template-columns: 28px minmax(0,1fr); gap: 8px;
  align-items: start; max-width: min(88%, 880px); }
.chat-message.assistant { margin-left: auto; grid-template-columns: minmax(0,1fr) 28px; }
.chat-avatar { width: 28px; height: 28px; display: grid; place-items: center;
  border: 1px solid var(--line); border-radius: 50%; background: var(--surface-2);
  color: var(--ink-2); font-size: 10px; font-weight: 750; }
.chat-message.assistant .chat-avatar { grid-column: 2; background: var(--accent-soft); color: var(--accent); }
.chat-bubble { min-width: 0; padding: 8px 10px; border: 1px solid var(--line);
  border-radius: 4px 11px 11px 11px; background: var(--surface-2); }
.chat-message.assistant .chat-bubble { grid-column: 1; grid-row: 1;
  border-radius: 11px 4px 11px 11px; background: var(--accent-soft); }
.chat-role { margin-bottom: 4px; color: var(--muted); font-size: 9.5px; font-weight: 720;
  letter-spacing: .07em; text-transform: uppercase; }
.chat-content { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
.tool-block { margin-top: 7px; padding: 7px 8px; border: 1px solid var(--line);
  border-radius: 7px; background: var(--surface); font-size: 11px; }
.payload-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(170px,1fr)); gap: 7px; }
.payload-field { min-width: 0; padding: 8px 9px; border: 1px solid var(--line);
  border-radius: 7px; background: var(--surface-2); }
.payload-field .pk { color: var(--muted); font-size: 9.5px; text-transform: uppercase;
  letter-spacing: .06em; }
.payload-field .pv { margin-top: 3px; max-height: 140px; overflow: auto;
  white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11.5px; }
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0;
}
@keyframes pulse { 50% { opacity: .45; } }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; scroll-behavior: auto !important; }
}
@media (max-width: 900px) {
  .shell { grid-template-columns: 1fr; }
  .sidebar { position: static; max-height: 410px; }
  .detail { min-height: 600px; }
  .grid { grid-template-columns: repeat(2, 1fr); }
  .topbar { gap: 8px; }
  .nav a { padding-inline: 7px; }
}
@media (max-width: 560px) {
  .topbar { align-items: flex-start; flex-wrap: wrap; }
  .top-actions { margin-left: 0; }
  .shell { padding-inline: 8px; }
  .detail-head, .panel { padding-inline: 14px; }
  .tabs { padding-inline: 10px; }
  .filters, .two-col { grid-template-columns: 1fr; }
  .grid { grid-template-columns: 1fr 1fr; }
  .conversation-flow { grid-template-columns: 1fr; gap: 5px; }
  .flow-arrow { transform: rotate(90deg); min-height: 18px; }
  .chat-message { max-width: 96%; }
  .organizing-model { grid-template-columns: 1fr; justify-content: stretch; }
  .organizing-model > strong { grid-column: 1 / -1; }
  .organizing-arrow { padding-left: 5px; }
}
</style>
</head>
<body>
<header class="topbar">
  <a class="brand" href="/">llm-super</a>
  <nav class="nav" aria-label="Primary">
    <a href="/workspace">Workspace</a>
    <a href="/">Live</a>
    <a href="/history" aria-current="page">History</a>
    <a href="/graphs">Agent Graphs</a>
    <a href="/#analytics-section">Analytics</a>
    <a href="/#settings-section">Settings</a>
  </nav>
  <div class="top-actions">
    <button id="refreshBtn" type="button" title="Refresh history">Refresh</button>
  </div>
</header>

<section class="organizing-model" aria-label="History containment model">
  <strong>How the records fit together</strong>
  <span class="organizing-step"><b>Endeavor</b><span>broader objective</span></span><span class="organizing-arrow">contains →</span>
  <span class="organizing-step"><b>Conversation</b><span>one chat thread</span></span><span class="organizing-arrow">triggers →</span>
  <span class="organizing-step"><b>Task run</b><span>one workflow execution</span></span><span class="organizing-arrow">records →</span>
  <span class="organizing-step"><b>Decision event</b><span>one recorded step</span></span>
</section>

<main class="shell">
  <aside class="sidebar" aria-label="Endeavors">
    <div class="sidebar-head">
      <p class="eyebrow">History</p>
      <h2 style="margin-bottom:0">Endeavors</h2>
      <p class="meta" style="margin:4px 0 0">An endeavor contains one or more conversations.</p>
      <form id="filterForm" class="filters" role="search">
        <label class="sr-only" for="search">Search history</label>
        <input id="search" name="q" type="search" placeholder="Search title or ID">
        <label class="sr-only" for="statusFilter">Filter status</label>
        <select id="statusFilter" name="status">
          <option value="">All states</option>
          <option value="accepted">Accepted</option>
          <option value="succeeded">Succeeded</option>
          <option value="interrupted">Interrupted</option>
          <option value="failed">Failed</option>
          <option value="unknown">Unknown</option>
        </select>
      </form>
    </div>
    <div id="endeavorCount" class="result-count" aria-live="polite">Loading…</div>
    <div id="endeavorList" class="endeavor-list" role="listbox" aria-label="Endeavor results"></div>
    <div id="endeavorMore" class="loadbar"></div>
  </aside>

  <article id="detail" class="detail" aria-live="polite">
    <div class="empty">
      <div><h1>Choose an endeavor</h1><p>History is summarized by objective, not transport request.</p></div>
    </div>
  </article>
</main>

<dialog id="rawDialog" aria-labelledby="rawTitle">
  <div class="dialog-head">
    <h2 id="rawTitle">Raw exchange</h2>
    <span class="view-toggle" aria-label="Exchange display mode">
      <button id="visualRaw" type="button" aria-pressed="true">Conversation</button>
      <button id="jsonRaw" type="button" aria-pressed="false">JSON</button>
    </span>
    <button id="copyRaw" type="button">Copy JSON</button>
    <button id="closeRaw" type="button" aria-label="Close raw exchange">Close</button>
  </div>
  <div id="rawMeta" class="rawmeta"></div>
  <div id="rawBody">Loading…</div>
  <pre id="rawJSON" hidden></pre>
</dialog>

<div id="announcer" class="sr-only" aria-live="polite"></div>
<script>
const state = {
  endeavors: [], endeavorTotal: 0, endeavorNext: null,
  selected: null, detail: null, runs: [], timeline: [],
  timelineTotal: 0, timelineNext: null, timelineSummary: {},
  timelineLoading: false, timelineError: "",
  collapse: true, tab: "overview", rawText: "", rawItem: null, rawView: "visual", requestSerial: 0,
  detailSerial: 0, timelineSerial: 0, rawSerial: 0,
};
const $ = s => document.querySelector(s);
const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
  "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
})[ch]);
const fmtTime = ts => ts ? new Date(ts * 1000).toLocaleString([], {
  month:"short", day:"numeric", hour:"2-digit", minute:"2-digit", second:"2-digit"
}) : "—";
const fmtDuration = seconds => {
  seconds = Math.max(0, Number(seconds || 0));
  if (seconds < 60) return Math.round(seconds) + "s";
  if (seconds < 3600) return Math.floor(seconds / 60) + "m " + Math.round(seconds % 60) + "s";
  return Math.floor(seconds / 3600) + "h " + Math.round((seconds % 3600) / 60) + "m";
};
const fmtTokens = value => new Intl.NumberFormat(undefined, {
  notation: Number(value) >= 100000 ? "compact" : "standard", maximumFractionDigits: 2
}).format(Number(value || 0));
const fmtBytes = value => new Intl.NumberFormat().format(Number(value || 0)) + " bytes";
const money = value => "$" + Number(value || 0).toFixed(Number(value || 0) < .01 ? 6 : 4);
const statusText = value => ({
  accepted:"accepted", succeeded:"complete", interrupted:"interrupted",
  failed:"failed", unknown:"unknown"
})[value] || value || "unknown";
const statusBadge = value =>
  `<span class="status ${esc(value || "unknown")}">${esc(statusText(value))}</span>`;
const announce = text => { $("#announcer").textContent = text; };

async function api(path) {
  const response = await fetch(path, {headers: {"Accept":"application/json"}});
  let body;
  try { body = await response.json(); } catch (_) { body = null; }
  if (!response.ok) throw new Error(body?.error || body?.detail || `HTTP ${response.status}`);
  return body;
}
function params(values) {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== "" && value !== null && value !== undefined) q.set(key, value);
  }
  return q.toString();
}
function updateURL() {
  const q = new URLSearchParams();
  if (state.selected) q.set("endeavor", state.selected);
  if (state.tab !== "overview") q.set("tab", state.tab);
  history.replaceState(null, "", "/history" + (q.size ? "?" + q : ""));
}
function showError(error) {
  $("#detail").innerHTML = `<div class="error"><strong>History failed to load.</strong><br>${esc(error.message || error)}</div>`;
}

async function loadEndeavors({append=false, preserve=false} = {}) {
  const serial = ++state.requestSerial;
  const query = $("#search").value.trim();
  const status = $("#statusFilter").value;
  const cursor = append ? state.endeavorNext : null;
  if (!append) {
    $("#endeavorCount").textContent = "Loading…";
    $("#endeavorList").innerHTML = '<div class="empty skeleton">Loading history…</div>';
  }
  try {
    const data = await api("/admin/history/endeavors?" + params({
      q: query, status, limit: 50, cursor
    }));
    if (serial !== state.requestSerial) return;
    state.endeavors = append ? state.endeavors.concat(data.items) : data.items;
    state.endeavorTotal = data.total;
    state.endeavorNext = data.next_cursor;
    renderEndeavors();
    if (!preserve && !state.selected && state.endeavors.length) {
      const wanted = new URLSearchParams(location.search).get("endeavor");
      selectEndeavor(
        wanted && state.endeavors.some(item => item.id === wanted)
          ? wanted : state.endeavors[0].id
      );
    } else if (state.selected) {
      renderEndeavors();
    }
  } catch (error) {
    $("#endeavorCount").textContent = "History unavailable";
    $("#endeavorList").innerHTML = `<div class="error">${esc(error.message)}</div>`;
  }
}
function renderEndeavors() {
  const focusedId = document.activeElement?.dataset?.endeavor;
  $("#endeavorCount").textContent =
    `showing ${state.endeavors.length} of ${state.endeavorTotal} endeavors`;
  $("#endeavorList").innerHTML = state.endeavors.length
    ? state.endeavors.map(item => {
      const itemSummary = summaryParts(item);
      const contextHeadline = itemSummary.node || String(item.context_summary?.headline || "").trim();
      const legacyContext = compactContextHTML(item.context_summary);
      const accessibleLabel = [item.status, item.title, contextHeadline].filter(Boolean).join(". ");
      return `
      <button class="endeavor ${item.id === state.selected ? "selected" : ""}"
              type="button" role="option" aria-selected="${item.id === state.selected}"
              aria-label="${esc(accessibleLabel)}"
              data-endeavor="${esc(item.id)}">
        <span class="e-title">${statusBadge(item.status)}
          <span class="text">${esc(item.title)}</span></span>
        <span class="e-meta meta">
          ${item.session_count ?? item.run_count} conversation${(item.session_count ?? item.run_count) === 1 ? "" : "s"} · ${item.task_count} steps ·
          ${fmtDuration(item.duration_seconds)} · ${money(item.cost_usd)}
        </span>
        ${compactContextHTML(item) || legacyContext}
      </button>`;
    }).join("")
    : '<div class="empty">No endeavors match these filters.</div>';
  $("#endeavorMore").innerHTML = state.endeavorNext
    ? '<button type="button" data-action="more-endeavors">Load more</button>' : "";
  if (focusedId) {
    const restored = [...document.querySelectorAll("[data-endeavor]")]
      .find(item => item.dataset.endeavor === focusedId);
    restored?.focus({preventScroll:true});
  }
}
async function selectEndeavor(id) {
  state.selected = id;
  state.detail = null; state.runs = []; state.timeline = [];
  state.timelineNext = null; state.timelineSummary = {};
  state.timelineLoading = false; state.timelineError = "";
  state.timelineSerial++;
  renderEndeavors(); updateURL();
  $("#detail").innerHTML = '<div class="empty skeleton">Building endeavor summary…</div>';
  await loadDetail();
}
async function loadDetail() {
  const id = state.selected;
  const serial = ++state.detailSerial;
  if (!id) return;
  try {
    const [detail, runs] = await Promise.all([
      api("/admin/history/endeavors/" + encodeURIComponent(id)),
      api("/admin/history/endeavors/" + encodeURIComponent(id) + "/runs?limit=200"),
    ]);
    if (id !== state.selected || serial !== state.detailSerial) return;
    state.detail = detail;
    state.runs = runs.items;
    state.timelineLoading = true;
    state.timelineError = "";
    renderDetail();
    announce(`Loaded ${detail.title}; summarizing its timeline`);
  } catch (error) {
    if (id === state.selected && serial === state.detailSerial) showError(error);
    return;
  }
  if (id !== state.selected || serial !== state.detailSerial || !state.detail) return;
  try {
    await loadTimeline({reset:true});
    if (id === state.selected && serial === state.detailSerial) {
      announce(`Loaded ${state.detail.title}`);
    }
  } catch (error) {
    if (id !== state.selected || serial !== state.detailSerial) return;
    state.timelineLoading = false;
    state.timelineError = error.message || String(error);
    renderPanel();
    announce(`Timeline failed to load: ${state.timelineError}`);
  }
}
async function loadTimeline({reset=false, render=true} = {}) {
  if (!state.selected) return;
  const id = state.selected;
  const serial = ++state.timelineSerial;
  const cursor = reset ? null : state.timelineNext;
  state.timelineLoading = true;
  state.timelineError = "";
  if (render && reset) renderPanel();
  const data = await api(
    "/admin/history/endeavors/" + encodeURIComponent(id) +
    "/timeline?" + params({
      limit: 50, cursor, routine: state.collapse ? "collapse" : "all"
    })
  );
  if (id !== state.selected || serial !== state.timelineSerial) return false;
  state.timeline = reset ? data.items : state.timeline.concat(data.items);
  state.timelineTotal = data.total;
  state.timelineNext = data.next_cursor;
  state.timelineSummary = data.summary || {};
  state.timelineLoading = false;
  state.timelineError = "";
  if (render) renderPanel();
  return true;
}
function renderDetail() {
  const d = state.detail;
  if (!d) return;
  const target = d.target || {};
  const conversationCount = d.session_count ?? d.run_count;
  const targetParts = [target.host_arch, target.guest_arch].filter(Boolean);
  $("#detail").innerHTML = `
    <header class="detail-head">
      <p class="eyebrow">Endeavor</p>
      <div class="detail-title">
        ${statusBadge(d.status)}
          <div><h1>${esc(d.title)}</h1>
            <div class="targetline">
            ${conversationCount} conversation${conversationCount === 1 ? "" : "s"} · endeavor <span class="mono">${esc(d.id)}</span>
            ${targetParts.length ? " · " + esc(target.host_arch || "host ?") + " → " + esc(target.guest_arch || "target ?") : ""}
            ${target.emulator ? " · " + esc(target.emulator) : ""}${target.vm ? " · " + esc(target.vm) : ""}
            </div>
        </div>
      </div>
    </header>
    <div class="tabs" role="tablist" aria-label="History views">
      ${["overview","timeline","prompts","evidence","raw"].map((tab, index) => `
        <button class="tab" type="button" role="tab"
          id="tab-${tab}" aria-controls="panel"
          aria-selected="${state.tab === tab}" tabindex="${state.tab === tab ? 0 : -1}"
          data-tab="${tab}">
          ${tab === "prompts" ? "Prompts & commands" : tab[0].toUpperCase() + tab.slice(1)}
        </button>`).join("")}
    </div>
    <div id="panel" class="panel" role="tabpanel" aria-labelledby="tab-${state.tab}"></div>`;
  renderPanel();
}
function renderPanel() {
  const panel = $("#panel");
  if (!panel || !state.detail) return;
  panel.setAttribute("aria-labelledby", "tab-" + state.tab);
  if (state.tab === "overview") panel.innerHTML = overviewHTML();
  if (state.tab === "timeline") panel.innerHTML = timelineHTML();
  if (state.tab === "prompts") panel.innerHTML = promptsHTML();
  if (state.tab === "evidence") panel.innerHTML = evidenceHTML();
  if (state.tab === "raw") panel.innerHTML = rawIndexHTML();
}
function overviewHTML() {
  const d = state.detail;
  const errors = d.errors || {};
  const primary = state.timelineSummary.primary_poll_run;
  const warning = (state.timelineSummary.warning_groups || [])[0];
  const directSummary = summaryParts(d);
  const contextSummary = directSummary.short || directSummary.node
    ? directSummary : summaryParts(d.context_summary);
  const lastStep = [...state.timeline].reverse().find(item => item.type === "step");
  const lastResponse = summaryParts(lastStep?.response_summary || lastStep);
  const legacyObjective = summaryCardHTML(d.context_summary, "Objective");
  return `
    <div class="grid">
      ${metric("Duration", fmtDuration(d.duration_seconds), fmtTime(d.start_ts) + " → " + fmtTime(d.last_ts))}
      ${metric("Conversations", d.session_count ?? d.run_count, d.task_count + " logical steps across their task runs")}
      ${metric("Tokens", fmtTokens(d.tokens_total ?? (d.tokens_in + d.tokens_out)),
        fmtTokens(d.tokens_in) + " input · " + fmtTokens(d.tokens_out) + " output")}
      ${metric("Cost", money(d.cost_usd), (d.provider_errors || 0) + " provider errors · " +
        (errors.unrecovered || 0) + " open failures · " + (d.monitor_findings || 0) + " monitor findings")}
    </div>
    ${(contextSummary.short || contextSummary.node) ? `<section class="section">
      <div class="section-head"><h2>What happened</h2></div>
      <div class="callout">
        ${summaryCardHTML(d, "Objective") || legacyObjective}
        ${conversationFlowHTML({
          prompt: contextSummary.short || contextSummary.node,
          process: `${d.session_count ?? d.run_count} conversation${(d.session_count ?? d.run_count) === 1 ? "" : "s"} · ${d.task_count} logical steps`,
          outcome: lastResponse.short || lastResponse.node || statusText(d.status),
          caption: directSummary.long,
        })}
        ${summaryCoverageHTML(d.message_summary_coverage)}
      </div>
    </section>` : ""}
    ${state.timelineLoading && !primary ? `<section class="section">
      <div class="callout skeleton"><strong>Summarizing timeline…</strong>
        <div class="meta">Folding routine polling and repeated warnings.</div></div>
    </section>` : ""}
    ${state.timelineError ? `<section class="section"><div class="error">
      <strong>Timeline unavailable.</strong><br>${esc(state.timelineError)}</div></section>` : ""}
    ${primary ? `<section class="section">
      <div class="section-head"><h2>Long-running release</h2></div>
      <div class="callout ${primary.unmatched_steps ? "warn" : ""}">
        <strong>${primary.steps} poll decisions summarized</strong> ·
        ${primary.routine_steps} routine collapsed · ${primary.unmatched_steps} unmatched shown ·
        ${money(primary.cost_usd)}
        <div class="meta">${fmtTokens(primary.tokens_in)} input · ${fmtTokens(primary.tokens_out)} output tokens</div>
      </div>
    </section>` : ""}
    ${warning ? `<section class="section">
      <div class="section-head"><h2>Repeated warning folded</h2></div>
      <div class="callout warn"><strong>${esc(warning.text)} ×${warning.count}</strong>
        <div class="meta">across ${warning.results || warning.steps} results</div></div>
    </section>` : ""}
    <section class="section">
      <div class="section-head"><h2>Conversations in this endeavor</h2>
        <span class="meta">showing ${state.runs.length} of ${d.session_count ?? d.run_count} conversation${(d.session_count ?? d.run_count) === 1 ? "" : "s"}</span></div>
      <div class="run-list">${state.runs.map(runHTML).join("")}</div>
    </section>`;
}
function metric(key, value, sub) {
  return `<div class="metric"><div class="k">${esc(key)}</div><div class="v">${esc(value)}</div>
    <div class="s">${esc(sub || "")}</div></div>`;
}
function summaryParts(summary) {
  if (!summary || typeof summary !== "object")
    return {node:"", short:"", long:"", headline:"", body:"", role:""};
  const headline = String(summary.headline || "").trim();
  const body = String(summary.summary || "").trim();
  const node = String(summary.node_label || summary.node_descriptor || headline).trim();
  const short = String(summary.short_summary || body || headline).trim();
  const long = String(summary.long_summary || (body !== short ? body : "")).trim();
  return {node, short, long, headline, body, role:String(summary.role || "").trim()};
}
function compactContextHTML(summary) {
  if (!summary || typeof summary !== "object") return "";
  const headline = String(summary.headline || "").trim();
  const body = String(summary.summary || "").trim();
  const parts = summaryParts(summary);
  if (!parts.node && !parts.short && !parts.long) return "";
  return `<span class="e-context">${parts.node
    ? `<strong>${esc(parts.node)}</strong>` : headline ? `<strong>${esc(headline)}</strong>` : ""}${
    parts.node && parts.short && parts.short !== parts.node ? " — " : ""}${
    parts.short ? esc(parts.short) : (body ? esc(body) : "")}</span>`;
}
function summaryCardHTML(summary, label="") {
  if (!summary || typeof summary !== "object") return "";
  const headline = String(summary.headline || "").trim();
  const body = String(summary.summary || "").trim();
  const parts = summaryParts(summary);
  if (!parts.node && !parts.short && !parts.long) return "";
  const tags = [label, summary.role].map(value => String(value || "").trim())
    .filter((value, index, values) => value && values.indexOf(value) === index);
  const fallbackTitle = `${esc(headline || "Summary")}`;
  return `<div class="message-summary">
    <div class="summary-head">${tags.length
      ? `<span class="summary-role">${esc(tags.join(" · "))}</span>` : ""}
      ${parts.node ? `<span class="summary-node">${esc(parts.node)}</span>` : fallbackTitle}</div>
    ${parts.short && parts.short !== parts.node
      ? `<div class="summary-short">${esc(parts.short)}</div>` : ""}
    ${parts.long && parts.long !== parts.short
      ? `<details><summary>Detailed summary</summary><div class="summary-body">${esc(parts.long)}</div></details>`
      : body && body !== headline && body !== parts.short ? `<div class="summary-body">${body ? esc(body) : ""}</div>` : ""}
  </div>`;
}
function conversationFlowHTML({prompt="", process="", outcome="", caption=""} = {}) {
  return `<div class="conversation-flow" role="img" aria-label="Prompt, LLM activity, and outcome">
    <div class="flow-stage"><div class="fk">① Prompt</div><div class="fv">${esc(prompt || "Prompt summary unavailable")}</div></div>
    <div class="flow-arrow" aria-hidden="true">→</div>
    <div class="flow-stage active"><div class="fk">② LLM activity</div><div class="fv">${esc(process || "Supervised model exchange")}</div></div>
    <div class="flow-arrow" aria-hidden="true">→</div>
    <div class="flow-stage"><div class="fk">③ Outcome</div><div class="fv">${esc(outcome || "Outcome summary unavailable")}</div></div>
  </div>${caption ? `<div class="flow-caption">${esc(caption)}</div>` : ""}`;
}
function itemFlowHTML(item) {
  const parts = summaryParts(item);
  const requestSummaries = (item.message_delta?.summaries || [])
    .filter(summary => String(summary?.role || "").toLowerCase() !== "system");
  const prompt = summaryParts(requestSummaries[0]);
  const response = summaryParts(item.response_summary);
  const tools = (item.tool_calls || []).map(tool => tool.name).filter(Boolean);
  const process = parts.node || (tools.length ? tools.join(" + ") : stepLabel(item));
  return conversationFlowHTML({
    prompt: prompt.short || prompt.node || parts.short,
    process,
    outcome: response.short || response.node || parts.short,
    caption: parts.long,
  });
}
function summaryStackHTML(entries) {
  const cards = (entries || []).map(entry => {
    const wrapped = entry && typeof entry.summary === "object";
    return summaryCardHTML(wrapped ? entry.summary : entry, wrapped ? entry.label : "");
  }).filter(Boolean);
  return cards.length ? `<div class="summary-stack">${cards.join("")}</div>` : "";
}
function summaryCoverageHTML(coverage) {
  if (!coverage || !Number(coverage.unique)) return "";
  const summarized = Number(coverage.summarized || 0).toLocaleString();
  const unique = Number(coverage.unique || 0).toLocaleString();
  const occurrences = Number(coverage.occurrences || 0).toLocaleString();
  const models = Array.isArray(coverage.models) ? coverage.models.filter(Boolean).join(", ") : "";
  const text = `${summarized} of ${unique} distinct messages summarized` +
    (models ? ` by ${models}` : "") + ` · ${occurrences} placements indexed`;
  return `<div class="meta summary-coverage">${esc(text)}</div>`;
}
function runHTML(run) {
  const direct = summaryParts(run);
  const context = direct.short || direct.node ? direct : summaryParts(run.context_summary);
  const legacyRunContext = summaryCardHTML(run.context_summary, "Conversation context");
  return `<div class="run">
    <div class="run-title">Conversation <span class="mono">${esc(run.session_id)}</span> · ${esc(run.relationship)}</div>
    ${statusBadge(run.status)}
    <div class="run-stats meta">
      <span>${run.task_count} steps</span><span>${run.event_count} events</span>
      <span>${fmtDuration(run.duration_seconds)}</span><span>${money(run.cost_usd)}</span>
      <span>${run.provider_errors || 0} provider errors</span>
      <span>${run.monitor_findings || 0} monitor findings</span>
    </div>
    ${(context.short || context.node) ? `<div class="run-context">
      ${summaryCardHTML(run, "Conversation context") || legacyRunContext}
      ${conversationFlowHTML({prompt:context.short || context.node,
        process:`${run.task_count} steps · ${run.event_count} events`,
        outcome:statusText(run.status), caption:direct.long})}
      ${summaryCoverageHTML(run.message_summary_coverage)}
    </div>` : ""}
  </div>`;
}
function timelineHTML() {
  if (state.timelineError) {
    return `<div class="error"><strong>Timeline unavailable.</strong><br>${esc(state.timelineError)}</div>`;
  }
  return `
    <div class="timeline-toolbar">
      <label><input id="collapseToggle" type="checkbox" ${state.collapse ? "checked" : ""}>
        collapse routine polling</label>
      <span class="meta">showing ${state.timeline.length} of ${state.timelineTotal} timeline items
        · ${state.timelineSummary.workload_steps ?? "?"} steps
        · ${state.timelineSummary.control_milestones ?? 0} controls</span>
    </div>
    <div class="timeline">${state.timeline.map(timelineItemHTML).join("") ||
      (state.timelineLoading ? '<div class="timeline-item skeleton">Summarizing timeline…</div>' : "")}</div>
    ${state.timelineNext ? '<div class="loadbar"><button type="button" data-action="more-timeline">Load more</button></div>' : ""}`;
}
function timelineItemHTML(item) {
  if (item.type === "control") {
    return `<div class="timeline-item control">
      <div class="t-head"><div class="t-main"><div class="t-title">Control changed</div>
        <div class="mono break">${esc(item.command)}</div>
        <div class="meta">${fmtTime(item.start_ts)} · curated restart/configuration milestone</div>
      </div></div></div>`;
  }
  if (item.type === "poll_group") {
    const sourceIds = item.source_exchange_ids || [];
    const edgeIds = sourceIds.length > 2
      ? [sourceIds[0], sourceIds[sourceIds.length - 1]] : sourceIds;
    return `<div class="timeline-item poll_group ${esc(item.status)}">
      <div class="t-head"><div class="t-main">
        <div class="t-title">${item.member_count} routine polls collapsed</div>
        <div class="t-line meta">
          <span>${fmtTime(item.start_ts)} → ${fmtTime(item.end_ts)}</span>
          <span>${fmtDuration(item.duration_seconds)}</span>
          <span>${money(item.cost_usd)}</span>
          <span>${fmtTokens(item.tokens_in)} input</span>
        </div>
        <div class="tool-list">${Object.entries(item.poll_categories || {}).map(
          ([name,count]) => `<span class="pill">${esc(name.replaceAll("_"," "))} ×${count}</span>`
        ).join("")}</div>
        ${itemFlowHTML(item)}
        ${summaryStackHTML(pollSummaryEntries(item))}
        ${warningsHTML(item.warning_groups)}
        ${edgeIds.length ? rawLinks(edgeIds, sourceIds.length > 2
          ? "first/latest raw exchange" : "raw exchange") : ""}
      </div>${statusBadge(item.status)}</div></div>`;
  }
  const delta = item.message_delta;
  const tools = item.tool_calls || [];
  const itemSummary = summaryParts(item);
  const legacyStepLabel = esc(stepLabel(item));
  return `<div class="timeline-item ${esc(item.status)}">
    <div class="t-head"><div class="t-main">
      <div class="t-title">${itemSummary.node ? esc(itemSummary.node) : tools.length
        ? tools.map(t => esc(t.name)).join(" + ") : legacyStepLabel}</div>
      <div class="t-line meta">
        <span>${fmtTime(item.start_ts)}</span>
        <span class="mono">${esc(item.session_id)} / ${esc(item.task_id)}</span>
        <span>${money(item.cost_usd)}</span>
        ${delta ? `<span>${delta.total_messages} messages · ${delta.request_chars.toLocaleString()} chars ·
          +${delta.delta_messages} delta</span>` : ""}
      </div>
      <div class="tool-list">
        ${tools.map(tool => `<span class="pill">${esc(tool.name)} · ${tool.arguments_chars} argument chars
          ${tool.matched_result ? "" : " · missing result"}</span>`).join("")}
      </div>
      ${itemFlowHTML(item)}
      ${summaryStackHTML(stepSummaryEntries(item))}
      ${providerSummariesHTML(item)}
      ${warningsHTML(item.warning_groups)}
      ${rawLinks(item.source_exchange_ids, tools.length ? "exact command / exchange" : "raw exchange")}
    </div>${statusBadge(item.status)}</div>
  </div>`;
}
function stepSummaryEntries(item) {
  const entries = [];
  const itemSummary = summaryParts(item);
  if (itemSummary.node || itemSummary.short || itemSummary.long)
    entries.push({summary:item, label:"Conversation step"});
  const delta = item.message_delta;
  for (const summary of (Array.isArray(delta?.summaries) ? delta.summaries : [])) {
    if (String(summary?.role || "").toLowerCase() === "system") continue;
    entries.push({summary, label: "Request message"});
  }
  if (item.response_summary) {
    entries.push({summary: item.response_summary, label: "Agent response"});
  }
  for (const tool of (Array.isArray(item.tool_calls) ? item.tool_calls : [])) {
    if (tool?.result_summary) {
      entries.push({summary: tool.result_summary, label: `${tool.name || "Tool"} result`});
    }
  }
  return entries;
}
function providerSummariesHTML(item) {
  const providers = Array.isArray(item.provider_summaries) ? item.provider_summaries : [];
  if (!providers.length) return "";
  const entries = providers.map((summary, index) => ({
    summary, label: `Provider attempt ${index + 1}`,
  }));
  return `<details class="provider-summaries">
    <summary>${providers.length} provider attempt${providers.length === 1 ? "" : "s"} summarized</summary>
    ${summaryStackHTML(entries)}
  </details>`;
}
function pollSummaryEntries(item) {
  const samples = Array.isArray(item.summary_samples) ? item.summary_samples : [];
  return samples.map((summary, index) => ({
    summary,
    label: samples.length === 1 ? "Poll summary" : (index === 0 ? "Opening poll" : "Closing poll"),
  }));
}
function stepLabel(item) {
  const kinds = Object.keys(item.event_kinds || {});
  return kinds.length ? kinds.join(" + ").replaceAll("_", " ") : "Trace step";
}
function warningsHTML(warnings) {
  return warnings?.length ? `<ul class="warning-list">${warnings.map(w =>
    `<li>⚠ ${esc(w.text)} ×${w.count}</li>`).join("")}</ul>` : "";
}
function rawLinks(ids, label) {
  return ids?.length ? `<div class="rawlinks">${ids.map((id, index) =>
    `<button type="button" data-exchange="${id}">${esc(label)} #${id}${ids.length > 1 ? " · " + (index + 1) + "/" + ids.length : ""}</button>`
  ).join("")}</div>` : "";
}
function promptsHTML() {
  const promptRuns = state.runs.filter(run => run.source_exchange_ids?.length);
  const commandSteps = state.timeline.filter(item => item.type === "step" && item.tool_call_count);
  return `
    <div class="two-col">
      <section>
        <div class="section-head"><h2>Initial and recovery prompts</h2>
          <span class="meta">${promptRuns.length} loaded conversations</span></div>
        ${promptRuns.map(run => `<div class="prompt-card">
          <strong>${esc(run.relationship)}</strong> · <span class="mono">${esc(run.session_id)}</span>
          <div class="meta">${fmtTime(run.start_ts)} · exact payload stays folded</div>
          ${conversationFlowHTML({prompt:summaryParts(run).short || summaryParts(run.context_summary).short,
            process:`${run.task_count} supervised steps`, outcome:statusText(run.status),
            caption:summaryParts(run).long})}
          ${summaryStackHTML((summaryParts(run).short || summaryParts(run).node)
            ? [{summary: run, label: "Prompt context"}]
            : run.context_summary ? [{summary: run.context_summary, label: "Prompt context"}] : [])}
          ${rawLinks(run.source_exchange_ids, "load exact prompt")}
        </div>`).join("") || '<p class="meta">No prompt sources on this page.</p>'}
      </section>
      <section>
        <div class="section-head"><h2>Tool decisions</h2>
          <span class="meta">${commandSteps.length} loaded steps</span></div>
        ${commandSteps.map(item => `<div class="prompt-card">
          <strong>${(item.tool_calls || []).map(t => esc(t.name)).join(" + ")}</strong>
          <div class="meta mono">${esc(item.session_id)} / ${esc(item.task_id)}</div>
          <div class="meta">${(item.tool_calls || []).reduce((n,t) => n + t.arguments_chars, 0)}
            argument chars · exact command on demand</div>
          ${itemFlowHTML(item)}
          ${summaryStackHTML(stepSummaryEntries(item))}
          ${rawLinks(item.source_exchange_ids?.slice(-1), "load exact command")}
        </div>`).join("") || `<p class="meta">${state.timelineLoading
          ? "Summarizing command sources…" : "No command sources on this page."}</p>`}
      </section>
    </div>
    ${state.timelineNext ? '<div class="loadbar"><button type="button" data-action="more-timeline">Load more command sources</button></div>' : ""}`;
}
function evidenceHTML() {
  const d = state.detail;
  const target = d.target || {};
  const evidence = d.metadata?.evidence || null;
  const artifacts = Array.isArray(evidence?.artifacts) ? evidence.artifacts : [];
  const successful = state.runs.filter(run => run.status === "succeeded");
  const finals = state.timeline.filter(item => item.type === "step" &&
    (item.event_kinds?.agent_end || item.event_kinds?.turn_end || item.event_kinds?.verify));
  return `
    <div class="grid">
      ${metric("Host", target.host_arch || "unknown", target.vm || "")}
      ${metric("Guest", target.guest_arch || "unknown", target.emulator || "")}
      ${metric("Successful conversations", successful.length, state.runs.length + " conversation / recovery epochs")}
      ${metric("Provider recovery", (d.errors?.recovered || 0) + " / " + (d.errors?.total || 0),
        (d.errors?.unrecovered || 0) + " unrecovered")}
    </div>
    ${evidence ? `<section class="section">
      <div class="section-head"><h2>Build and boot proof</h2>
        <span class="meta">documented acceptance fixture</span></div>
      <div class="two-col">
        <div class="callout"><strong>Cross-build</strong>
          <div class="meta">${esc(evidence.source_revision)} · ${esc(evidence.build_result)}</div></div>
        <div class="callout"><strong>Emulated guest</strong>
          <div class="meta">${esc(evidence.guest_result)}</div></div>
      </div>
      <div class="meta break" style="margin-top:10px">Evidence root: ${esc(evidence.evidence_root)}</div>
      <div class="timeline" style="margin-top:10px">
        ${artifacts.map(artifact => `<div class="timeline-item">
          <div class="t-title">${esc(artifact.name)}</div>
          <div class="meta">${fmtBytes(artifact.bytes)}</div>
          <div class="meta mono break">sha256 ${esc(artifact.sha256)}</div>
        </div>`).join("")}
      </div>
    </section>` : ""}
    <section class="section">
      <div class="section-head"><h2>Acceptance provenance</h2>
        <span class="meta">${state.timelineLoading ? "summarizing…" : `${finals.length} loaded steps`}</span></div>
      <div class="callout">
        This overview is derived from ${d.event_count} workload events and ${d.exchange_count}
        exchanges. Raw evidence is not embedded here; each final trace step links to its
        source exchange IDs.
      </div>
      <div class="timeline" style="margin-top:10px">
        ${finals.map(timelineItemHTML).join("") || `<div class="timeline-item"><span class="meta">
          ${state.timelineLoading ? "Summarizing verification evidence…" : "No final verification evidence on this page."}
        </span></div>`}
      </div>
      ${state.timelineNext ? '<div class="loadbar"><button type="button" data-action="more-timeline">Load more verification evidence</button></div>' : ""}
    </section>`;
}
function rawIndexHTML() {
  const withRaw = state.timeline.filter(item => item.source_exchange_ids?.length);
  return `
    <div class="callout warn">
      Raw exchanges can contain complete prompts, tool schemas, provider reasoning, and
      cumulative transcripts. Only one payload is fetched and mounted at a time.
    </div>
    <section class="section">
      <div class="section-head"><h2>Source exchange index</h2>
        <span class="meta">showing sources from ${state.timeline.length} of ${state.timelineTotal} timeline items</span></div>
      <div class="timeline">
        ${withRaw.map(item => {
          const ids = item.source_exchange_ids || [];
          const parts = summaryParts(item);
          const shownIds = item.type === "poll_group" && ids.length > 2
            ? [ids[0], ids[ids.length - 1]] : ids;
          return `<div class="timeline-item">
          <div class="t-title">${esc(parts.node || (item.type === "step" ? stepLabel(item) : item.type))}</div>
          <div class="meta mono">${esc(item.session_id || item.run_id || "")}
            ${item.task_id ? " / " + esc(item.task_id) : ""}
            ${shownIds.length < ids.length ? ` · ${ids.length} sources; first/latest shown` : ""}</div>
          ${itemFlowHTML(item)}
          ${summaryStackHTML(parts.short || parts.node ? [{summary:item, label:"Conversation element"}] : [])}
          ${rawLinks(shownIds, "open raw exchange")}
        </div>`; }).join("") || `<p class="meta">${state.timelineLoading
          ? "Summarizing source exchanges…" : "No source exchanges on this page."}</p>`}
      </div>
      ${state.timelineNext ? '<div class="loadbar"><button type="button" data-action="more-timeline">Load more source IDs</button></div>' : ""}
    </section>`;
}
function rawValueText(value, depth=0) {
  if (value == null) return value === null ? "null" : "";
  if (typeof value === "string") return value;
  if (typeof value !== "object") return String(value);
  if (depth > 3) return Array.isArray(value) ? `[${value.length} items]` : "{…}";
  if (Array.isArray(value)) return value.map((part, index) =>
    `${typeof part === "object" ? `${index + 1}. ` : ""}${rawValueText(part, depth + 1)}`).join("\n");
  return Object.entries(value).map(([key, part]) =>
    `${key}: ${rawValueText(part, depth + 1)}`).join("\n");
}
function rawContentText(content) {
  if (Array.isArray(content)) return content.map(part =>
    typeof part?.text === "string" ? part.text : rawValueText(part)).join("\n");
  return rawValueText(content);
}
function toolCallsHTML(calls) {
  return (calls || []).map(call => {
    const fn = call.function || call;
    return `<div class="tool-block"><strong>Tool · ${esc(fn.name || call.type || "call")}</strong>
      <div class="mono break">${esc(rawValueText(fn.arguments || fn.input || fn))}</div></div>`;
  }).join("");
}
function chatMessageHTML(message, label="") {
  if (!message || typeof message !== "object") return "";
  const role = String(message.role || "message");
  const assistant = role === "assistant" || role === "model";
  const content = rawContentText(message.content ?? message.text);
  return `<div class="chat-message ${assistant ? "assistant" : ""}">
    <span class="chat-avatar" aria-hidden="true">${assistant ? "AI" : role === "user" ? "U" : "•"}</span>
    <div class="chat-bubble"><div class="chat-role">${esc(label || role)}</div>
      ${content ? `<div class="chat-content">${esc(content)}</div>` : ""}
      ${toolCallsHTML(message.tool_calls)}</div>
  </div>`;
}
function payloadFieldsHTML(payload, excluded=[]) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return "";
  const skip = new Set(excluded);
  const fields = Object.entries(payload).filter(([key, value]) =>
    !skip.has(key) && value !== undefined && value !== null);
  return fields.length ? `<div class="payload-grid">${fields.map(([key, value]) =>
    `<div class="payload-field"><div class="pk">${esc(key.replaceAll("_", " "))}</div>
      <div class="pv">${esc(rawValueText(value))}</div></div>`).join("")}</div>` : "";
}
function visualRawHTML(item) {
  const payload = item?.payload;
  if (!payload || typeof payload !== "object")
    return `<div class="payload-field"><div class="pk">Payload</div><div class="pv">${esc(rawValueText(payload))}</div></div>`;
  const sections = [];
  const addThread = (title, messages, responseMessage=null, responseLabel="Model response") => {
    const rows = (Array.isArray(messages) ? messages : []).map(message => chatMessageHTML(message)).join("")
      + (responseMessage ? chatMessageHTML(responseMessage, responseLabel) : "");
    if (rows) sections.push(`<section class="raw-section"><h3>${esc(title)}</h3>
      <div class="chat-thread">${rows}</div></section>`);
  };
  if (Array.isArray(payload.messages)) {
    const response = (payload.choices || [])[0]?.message;
    addThread(item.kind === "client_request" ? "Client conversation" : "Conversation",
      payload.messages, response, "Response");
  }
  if (payload.request && typeof payload.request === "object") {
    const response = payload.response?.choices?.[0]?.message;
    addThread(`Request to ${item.model || payload.request.model || "provider"}`,
      payload.request.messages, response, `${item.model || "Model"} response`);
  } else if (!Array.isArray(payload.messages) && Array.isArray(payload.choices)) {
    addThread("Response returned to client", [], payload.choices[0]?.message, "Assistant response");
  }
  if (typeof payload.text === "string" && !sections.length)
    addThread("Response returned to client", [], {role:"assistant", content:payload.text}, "Assistant response");
  const excluded = ["messages", "choices", "request", "response", "text"];
  const fields = payloadFieldsHTML(payload, excluded);
  if (fields) sections.push(`<section class="raw-section"><h3>Exchange metadata</h3>${fields}</section>`);
  if (!sections.length) sections.push(`<section class="raw-section"><h3>Structured payload</h3>
    ${payloadFieldsHTML(payload)}</section>`);
  const summary = summaryCardHTML(item, "Conversation summary");
  return (summary ? `<section class="raw-section">${summary}</section>` : "") + sections.join("");
}
function renderRawDialog() {
  const visual = state.rawView === "visual";
  $("#visualRaw").setAttribute("aria-pressed", visual);
  $("#jsonRaw").setAttribute("aria-pressed", !visual);
  $("#rawBody").hidden = !visual;
  $("#rawJSON").hidden = visual;
  if (visual && state.rawItem) $("#rawBody").innerHTML = visualRawHTML(state.rawItem);
  if (!visual) $("#rawJSON").textContent = state.rawText;
}
async function openRaw(id) {
  const serial = ++state.rawSerial;
  const dialog = $("#rawDialog");
  $("#rawTitle").textContent = "Raw exchange #" + id;
  $("#rawMeta").textContent = "Loading one payload on demand…";
  $("#rawBody").textContent = "Loading…";
  state.rawText = "";
  state.rawItem = null;
  state.rawView = "visual";
  dialog.showModal();
  try {
    const item = await api("/admin/history/exchanges/" + encodeURIComponent(id) + "/raw");
    if (serial !== state.rawSerial || !dialog.open) return;
    state.rawText = JSON.stringify(item.payload, null, 2);
    state.rawItem = item;
    $("#rawMeta").textContent =
      `${item.kind} · ${item.session} / ${item.task} · ${item.payload_chars.toLocaleString()} chars · ${fmtTime(item.ts)}`;
    renderRawDialog();
  } catch (error) {
    if (serial !== state.rawSerial || !dialog.open) return;
    $("#rawBody").textContent = "Failed to load raw exchange: " + error.message;
  }
}

$("#filterForm").addEventListener("submit", event => {
  event.preventDefault(); state.selected = null; loadEndeavors();
});
let searchTimer;
$("#search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.selected = null; loadEndeavors(); }, 250);
});
$("#statusFilter").addEventListener("change", () => {
  state.selected = null; loadEndeavors();
});
$("#refreshBtn").addEventListener("click", async () => {
  const selected = state.selected;
  await loadEndeavors({preserve:true});
  if (selected) await selectEndeavor(selected);
});
$("#closeRaw").addEventListener("click", () => $("#rawDialog").close());
$("#visualRaw").addEventListener("click", () => { state.rawView = "visual"; renderRawDialog(); });
$("#jsonRaw").addEventListener("click", () => { state.rawView = "json"; renderRawDialog(); });
$("#rawDialog").addEventListener("close", () => {
  state.rawSerial++;
  state.rawText = "";
  state.rawItem = null;
  $("#rawMeta").textContent = "";
  $("#rawBody").textContent = "";
  $("#rawJSON").textContent = "";
});
$("#copyRaw").addEventListener("click", async () => {
  if (!state.rawText) return;
  try {
    await navigator.clipboard.writeText(state.rawText);
    announce("Raw exchange copied");
  } catch (_) { announce("Clipboard access was denied"); }
});
document.addEventListener("click", async event => {
  const endeavor = event.target.closest("[data-endeavor]");
  if (endeavor) return selectEndeavor(endeavor.dataset.endeavor);
  const tab = event.target.closest("[data-tab]");
  if (tab) {
    state.tab = tab.dataset.tab;
    document.querySelectorAll(".tab").forEach(button => {
      const active = button.dataset.tab === state.tab;
      button.setAttribute("aria-selected", active);
      button.tabIndex = active ? 0 : -1;
    });
    updateURL(); renderPanel(); return;
  }
  const raw = event.target.closest("[data-exchange]");
  if (raw) return openRaw(raw.dataset.exchange);
  const action = event.target.closest("[data-action]")?.dataset.action;
  if (action === "more-endeavors") return loadEndeavors({append:true, preserve:true});
  if (action === "more-timeline") {
    try { await loadTimeline(); }
    catch (error) {
      state.timelineLoading = false;
      state.timelineError = error.message || String(error);
      renderPanel();
      announce(`Timeline failed to load: ${state.timelineError}`);
    }
    return;
  }
});
document.addEventListener("change", async event => {
  if (event.target.id !== "collapseToggle") return;
  state.collapse = event.target.checked;
  try { await loadTimeline({reset:true}); }
  catch (error) {
    state.timelineLoading = false;
    state.timelineError = error.message || String(error);
    renderPanel();
    announce(`Timeline failed to load: ${state.timelineError}`);
  }
});
document.addEventListener("keydown", event => {
  const option = event.target.closest?.("[data-endeavor]");
  if (option && ["ArrowUp","ArrowDown","Home","End"].includes(event.key)) {
    const options = [...document.querySelectorAll("[data-endeavor]")];
    const index = options.indexOf(option);
    const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? options.length - 1
      : (index + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
    options[nextIndex]?.focus();
    options[nextIndex]?.click();
    event.preventDefault();
    return;
  }
  if (!event.target.matches(".tab") || !["ArrowLeft","ArrowRight"].includes(event.key)) return;
  const tabs = [...document.querySelectorAll(".tab")];
  const direction = event.key === "ArrowRight" ? 1 : -1;
  const next = tabs[(tabs.indexOf(event.target) + direction + tabs.length) % tabs.length];
  next.focus(); next.click(); event.preventDefault();
});
$("#rawDialog").addEventListener("click", event => {
  if (event.target === $("#rawDialog")) $("#rawDialog").close();
});

{
  const q = new URLSearchParams(location.search);
  const tab = q.get("tab");
  const search = q.get("q");
  if (["overview","timeline","prompts","evidence","raw"].includes(tab)) state.tab = tab;
  if (search) $("#search").value = search;
}
loadEndeavors();
</script>
</body>
</html>
"""

from .design_tokens import apply as _apply_design_tokens

PAGE = _apply_design_tokens(PAGE, 'history')
