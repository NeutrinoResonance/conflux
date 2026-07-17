"""Control-plane dashboard (SPEC §7.1): a single self-contained HTML page
served at `/`. Polls /admin endpoints; posts steering changes to
/admin/control. No build step, no external assets.
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>llm-super control plane</title>
<style>
:root {
  color-scheme: light;
  --page:      #f9f9f7;
  --surface:   #fcfcfb;
  --ink:       #0b0b0b;
  --ink-2:     #52514e;
  --muted:     #898781;
  --grid:      #e1e0d9;
  --baseline:  #c3c2b7;
  --border:    rgba(11,11,11,0.10);
  --seq:       #2a78d6;   /* single-hue magnitude (score bars) */
  --seq-track: #e1e0d9;
  --good:      #0ca30c;
  --good-text: #006300;
  --warning:   #fab219;
  --serious:   #ec835a;
  --critical:  #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page:      #0d0d0d;
    --surface:   #1a1a19;
    --ink:       #ffffff;
    --ink-2:     #c3c2b7;
    --muted:     #898781;
    --grid:      #2c2c2a;
    --baseline:  #383835;
    --border:    rgba(255,255,255,0.10);
    --seq:       #3987e5;
    --seq-track: #2c2c2a;
    --good-text: #0ca30c;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page:      #0d0d0d;
  --surface:   #1a1a19;
  --ink:       #ffffff;
  --ink-2:     #c3c2b7;
  --muted:     #898781;
  --grid:      #2c2c2a;
  --baseline:  #383835;
  --border:    rgba(255,255,255,0.10);
  --seq:       #3987e5;
  --seq-track: #2c2c2a;
  --good-text: #0ca30c;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--page); color: var(--ink);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
}
/* wide cap: the conversation tree needs the room on big displays */
main { max-width: 1560px; margin: 0 auto; padding: 20px 20px 60px; }
h1 { font-size: 18px; margin: 0 0 2px; }
.sub { color: var(--muted); font-size: 12px; margin-bottom: 16px; }
section { margin-top: 22px; }
h2 { font-size: 13px; color: var(--ink-2); text-transform: uppercase;
     letter-spacing: .04em; margin: 0 0 8px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px,1fr)); gap: 8px; }
.tile { background: var(--surface); border: 1px solid var(--border);
        border-radius: 8px; padding: 10px 12px; }
.tile .k { font-size: 11px; color: var(--muted); }
.tile .v { font-size: 20px; margin-top: 2px; }
.tile .v small { font-size: 12px; color: var(--ink-2); }
.controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
            background: var(--surface); border: 1px solid var(--border);
            border-radius: 8px; padding: 10px 12px; }
.controls label { font-size: 12px; color: var(--ink-2); display: flex;
                  gap: 6px; align-items: center; }
select, input[type=number] {
  font: inherit; color: var(--ink); background: var(--page);
  border: 1px solid var(--baseline); border-radius: 6px; padding: 4px 6px;
}
input[type=number] { width: 80px; }
button {
  font: inherit; padding: 5px 14px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--baseline); background: var(--surface); color: var(--ink);
}
button.primary { background: var(--seq); border-color: var(--seq); color: #fff; }
button.danger  { background: var(--critical); border-color: var(--critical); color: #fff; }
.badge { display: inline-flex; align-items: center; gap: 4px; font-size: 11px;
         padding: 1px 8px; border-radius: 999px; border: 1px solid var(--border);
         color: var(--ink-2); background: var(--surface); white-space: nowrap; }
.badge.fm       { border-color: var(--serious);  }
.badge.crit     { border-color: var(--critical); }
.badge.ok       { border-color: var(--good);     }
.card { background: var(--surface); border: 1px solid var(--border);
        border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; }
.scorebar { display: inline-flex; align-items: center; gap: 6px; }
.scorebar .track { width: 90px; height: 6px; border-radius: 4px;
                   background: var(--seq-track); overflow: hidden; }
.scorebar .fill { display: block; height: 100%; border-radius: 4px; background: var(--seq); }
.scorebar .n { font-variant-numeric: tabular-nums; font-size: 12px; color: var(--ink-2); }
/* ---- goal timeline ---- */
details.turn { background: var(--surface); border: 1px solid var(--border);
               border-radius: 8px; margin-bottom: 10px; }
details.turn > summary { list-style: none; cursor: pointer; padding: 10px 14px;
  display: flex; flex-wrap: wrap; gap: 10px; align-items: baseline; }
details.turn > summary::-webkit-details-marker { display: none; }
details.turn > summary::before { content: "▸"; color: var(--muted); font-size: 12px; }
details.turn[open] > summary::before { content: "▾"; }
.goal { font-size: 13.5px; color: var(--ink); flex: 1 1 320px; }
.goal::before { content: "“"; color: var(--muted); }
.goal::after  { content: "”"; color: var(--muted); }
.gid { font-family: ui-monospace, monospace; font-size: 11px; color: var(--muted); }
.gcost { font-variant-numeric: tabular-nums; font-size: 12px; color: var(--muted); }
.tl { border-top: 1px solid var(--grid); padding: 10px 14px 12px; }
.node, details.node { position: relative; margin-left: 8px; padding: 3px 0 3px 20px;
  border-left: 2px solid var(--grid); font-size: 12.5px; color: var(--ink-2); }
.node::before, details.node::before { content: ""; position: absolute; left: -5px;
  top: 11px; width: 8px; height: 8px; border-radius: 50%;
  background: var(--baseline); }
.node.fm::before, details.node.fm::before   { background: var(--serious); }
.node.ok::before, details.node.ok::before   { background: var(--good); }
.node.err::before, details.node.err::before { background: var(--critical); }
details.node > summary { list-style: none; cursor: pointer; }
details.node > summary::-webkit-details-marker { display: none; }
details.node > summary .more { color: var(--seq); font-size: 11px; }
.node .t, details.node .t { font-family: ui-monospace, monospace; font-size: 10.5px;
  color: var(--muted); margin-right: 6px; }
.node b, details.node b { color: var(--ink); font-weight: 600; }
.payload { margin: 4px 0 6px 14px; padding: 6px 10px; background: var(--page);
  border: 1px solid var(--grid); border-radius: 6px; font-size: 12px;
  white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto; }
details.unit { margin-left: 8px; border-left: 2px solid var(--seq);
  padding: 3px 0 3px 20px; position: relative; font-size: 12.5px; }
details.unit::before { content: ""; position: absolute; left: -5px; top: 11px;
  width: 8px; height: 8px; border-radius: 50%; background: var(--seq); }
details.unit > summary { list-style: none; cursor: pointer; color: var(--ink); }
details.unit > summary::-webkit-details-marker { display: none; }
details.unit .subtl { margin: 4px 0 4px 4px; }
.esc { margin-top: 8px; font-size: 13px; color: var(--ink); }
.esc::before { content: "⛔ "; }
.msgbtn { font-size: 11px; padding: 2px 10px; margin-left: auto; }
.msgview { border-top: 1px solid var(--grid); padding: 10px 14px; }
.msg { margin-bottom: 8px; }
.msg .mh { font-size: 11px; color: var(--muted); margin-bottom: 2px;
           font-family: ui-monospace, monospace; }
.msg .role { display: inline-block; min-width: 70px; font-weight: 600;
             color: var(--ink); }
.msg pre { margin: 0 0 4px; padding: 6px 10px; background: var(--page);
           border: 1px solid var(--grid); border-radius: 6px; font-size: 11.5px;
           white-space: pre-wrap; word-break: break-word; max-height: 300px;
           overflow: auto; }
.note { margin-top: 6px; font-size: 12px; color: var(--ink-2); }
.note::before { content: "↩ "; color: var(--muted); }
table { width: 100%; border-collapse: collapse; background: var(--surface);
        border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
th, td { text-align: left; font-size: 12.5px; padding: 6px 10px;
         border-bottom: 1px solid var(--grid); }
th { color: var(--muted); font-weight: 500; }
td.num { font-variant-numeric: tabular-nums; text-align: right; }
th.num { text-align: right; }
tr:last-child td { border-bottom: none; }
.evk { font-family: ui-monospace, monospace; font-size: 11.5px; }
#flash { position: fixed; top: 12px; right: 12px; background: var(--surface);
         border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px;
         font-size: 12px; display: none; }
.paused-banner { display: none; margin-bottom: 14px; padding: 8px 12px;
  border: 1px solid var(--warning); border-radius: 8px; background: var(--surface);
  font-size: 13px; }
.paused-banner::before { content: "⏸ "; }
/* ---- layout: sidebar + content ---- */
.layout { display: flex; gap: 18px; align-items: flex-start; }
.sidebar { flex: 0 0 240px; position: sticky; top: 12px; }
.content { flex: 1 1 auto; min-width: 0; }
@media (max-width: 820px) { .layout { flex-direction: column; }
  .sidebar { position: static; flex-basis: auto; width: 100%; } }
.proj { background: var(--surface); border: 1px solid var(--border);
        border-radius: 8px; margin-bottom: 8px; }
.proj > .ph { display: flex; align-items: center; gap: 6px; padding: 8px 10px;
  cursor: pointer; font-size: 13px; }
.proj > .ph.sel { background: var(--page); border-radius: 8px 8px 0 0;
  box-shadow: inset 3px 0 0 var(--seq); }
.proj > .ph .pname { font-weight: 600; flex: 1; }
.proj > .ph .pcount { font-size: 11px; color: var(--muted); }
.slist { padding: 2px 6px 8px; }
.sitem { display: flex; align-items: center; gap: 6px; padding: 4px 8px;
  border-radius: 6px; cursor: pointer; font-size: 12.5px; color: var(--ink-2); }
.sitem:hover { background: var(--page); }
.sitem.sel { background: var(--page); color: var(--ink); box-shadow: inset 2px 0 0 var(--seq); }
.sitem .st { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sitem .sx { color: var(--muted); font-size: 12px; visibility: hidden; }
.sitem:hover .sx { visibility: visible; }
.iconbtn { background: none; border: none; cursor: pointer; padding: 0 3px;
  color: var(--muted); font-size: 13px; }
.iconbtn:hover { color: var(--ink); }
.miniadd { width: 100%; margin-top: 4px; font-size: 12px; padding: 5px; }
/* ---- library / settings ---- */
.settings-grid { display: grid; grid-template-columns: 150px 1fr auto auto; gap: 6px 10px;
  align-items: center; background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 14px; }
.settings-grid .fname { font-size: 12.5px; color: var(--ink-2); }
.settings-grid .fval input, .settings-grid .fval select { width: 100%; }
.src { font-size: 10.5px; padding: 1px 7px; border-radius: 999px; border: 1px solid var(--border); }
.src.default { color: var(--muted); }
.src.project { color: var(--seq); border-color: var(--seq); }
.reset { font-size: 11px; padding: 2px 8px; visibility: hidden; }
.src.project ~ .reset, .reset.show { visibility: visible; }
.exportbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  margin-top: 10px; }
.exportbar input { min-width: 160px; }
.export-result { font-size: 12px; color: var(--good-text); margin-top: 6px;
  font-family: ui-monospace, monospace; word-break: break-all; }
</style>
</head>
<body>
<main>
  <h1>llm-super</h1>
  <div class="sub">control plane — <span id="clock">…</span> · auto-refresh 2s</div>
  <div class="paused-banner" id="pausedBanner">Supervision is paused — new turns will not execute until resumed.</div>

  <div class="tiles" id="tiles"></div>

  <div class="layout">
    <aside class="sidebar">
      <h2>Conversations</h2>
      <div id="projects"></div>
      <button class="miniadd" onclick="newProject()">＋ New project</button>
    </aside>
    <div class="content">

  <section>
    <h2>Steering</h2>
    <div class="controls">
      <button id="pauseBtn" class="primary">Pause</button>
      <label>executor
        <select id="executorSel"><option value="">auto</option></select>
      </label>
      <label>budget $
        <input id="budgetInp" type="number" step="0.05" min="0" placeholder="default">
      </label>
      <label>checklist
        <select id="checklistSel">
          <option value="on">on</option><option value="off">off</option>
          <option value="skip">skip next turn</option>
        </select>
      </label>
      <label>sandbox
        <select id="sandboxSel">
          <option value="auto">auto</option><option value="local">local</option>
          <option value="gcloud">gcloud</option><option value="off">off</option>
        </select>
      </label>
      <label>plan
        <select id="planSel">
          <option value="auto">auto</option><option value="on">on</option>
          <option value="off">off</option>
        </select>
      </label>
      <label>ensemble
        <select id="ensembleSel" title="best-of-N model families + verified fusion; ~N+1x cost">
          <option value="0">off</option><option value="2">2</option>
          <option value="3">3</option><option value="4">4</option>
        </select>
      </label>
    </div>
    <div class="controls" style="margin-top:8px">
      <label>breakpoint
        <input id="breakInp" type="text" size="18"
               placeholder="fm:FM-X.3 · budget:0.4 · escalation">
      </label>
      <button onclick="addBreak()">Add</button>
      <span id="breakList" style="font-size:12px"></span>
    </div>
  </section>

  <section>
    <h2>Routing <span style="color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0">— runtime overrides; edit models.yaml to persist</span></h2>
    <div id="routing"></div>
  </section>

  <section>
    <h2 id="tasksHeading">Tasks</h2>
    <div id="edits"></div>
    <div id="tasks"></div>
  </section>

  <section>
    <h2>Extraction settings <span id="settingsScope" style="color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0"></span></h2>
    <div id="settings"></div>
    <div class="exportbar" id="exportbar"></div>
    <div class="export-result" id="exportResult"></div>
  </section>

  <section>
    <h2>Retention <span style="color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0">— global; 0 days = keep forever</span></h2>
    <div id="retention"></div>
  </section>

  <section>
    <h2>Model outcomes</h2>
    <div id="stats"></div>
  </section>

  <section>
    <h2>Load balancing <span style="color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0">— window usage vs provider limits; nominal prices for subscription channels</span></h2>
    <div id="balance"></div>
  </section>

  <section>
    <h2>Efficiency <span style="color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0">— last 30 days; SPEC §8 KPIs</span></h2>
    <div id="efficiency"></div>
  </section>

  <section>
    <h2>Event feed</h2>
    <div id="events"></div>
  </section>
    </div><!-- .content -->
  </div><!-- .layout -->
</main>
<div id="flash"></div>
<script>
// ?theme=light|dark overrides the OS preference (also used for screenshots)
{
  const t = new URLSearchParams(location.search).get("theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
}
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

let models = [];

async function post(field, value) {
  await fetch("/admin/control", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({field, value})});
  flash(field + " → " + (value === "" ? "auto" : value));
  refresh();
}
function flash(msg) {
  const f = $("#flash"); f.textContent = msg; f.style.display = "block";
  clearTimeout(f._t); f._t = setTimeout(() => f.style.display = "none", 1800);
}

async function addBreak() {
  const rule = $("#breakInp").value.trim();
  if (!rule) return;
  const r = await fetch("/admin/control", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({field: "break_add", value: rule})});
  if (!r.ok) { flash("✗ " + ((await r.json()).error || r.status)); return; }
  $("#breakInp").value = "";
  flash("breakpoint set: " + rule);
  refresh();
}
function clearBreak(rule) { post("break_clear", rule); }

$("#pauseBtn").onclick = () => post("paused", $("#pauseBtn").dataset.paused !== "true");
$("#executorSel").onchange = e => post("executor", e.target.value);
$("#budgetInp").onchange = e => post("budget", e.target.value);
$("#checklistSel").onchange = e => post("checklist", e.target.value);
$("#sandboxSel").onchange = e => post("sandbox", e.target.value);
$("#planSel").onchange = e => post("plan", e.target.value);
$("#ensembleSel").onchange = e => post("ensemble", e.target.value);

function tile(k, v, small) {
  return `<div class="tile"><div class="k">${esc(k)}</div>
          <div class="v">${v}${small ? ` <small>${esc(small)}</small>` : ""}</div></div>`;
}
function scorebar(score) {
  if (score == null) return "";
  const pct = Math.round(score * 100);
  return `<span class="scorebar"><span class="track">
          <span class="fill" style="width:${pct}%"></span></span>
          <span class="n">${score.toFixed(2)}</span></span>`;
}
function fmBadge(id) { return `<span class="badge fm">⚠ ${esc(id)}</span>`; }

function renderStatus(st, cfgModels) {
  const paused = !!st.paused;
  $("#pauseBtn").textContent = paused ? "Resume" : "Pause";
  $("#pauseBtn").dataset.paused = paused;
  $("#pauseBtn").className = paused ? "danger" : "primary";
  $("#pausedBanner").style.display = paused ? "block" : "none";
  if (models.join() !== cfgModels.join()) {
    models = cfgModels;
    $("#executorSel").innerHTML = '<option value="">auto</option>' +
      models.map(m => `<option>${esc(m)}</option>`).join("");
  }
  $("#executorSel").value = st.forced_executor || "";
  if (document.activeElement !== $("#budgetInp"))
    $("#budgetInp").value = st.budget_usd ?? "";
  $("#checklistSel").value = st.checklist || "on";
  $("#sandboxSel").value = st.sandbox || "auto";
  $("#planSel").value = st.plan || "auto";
  $("#ensembleSel").value = String(st.ensemble || 0);
  $("#breakList").innerHTML = (st.breakpoints || []).length
    ? st.breakpoints.map(b =>
        `<span class="badge">${esc(b)} <a href="#" style="text-decoration:none"
           onclick="clearBreak('${esc(b)}');return false">×</a></span>`).join(" ")
    : '<span style="color:var(--muted)">none — pauses the supervisor when a rule matches</span>';
  $("#tiles").innerHTML =
    tile("state", paused ? "⏸ paused" : "▶ running") +
    tile("executor", esc(st.forced_executor || "auto")) +
    tile("budget / task", st.budget_usd != null ? "$" + Number(st.budget_usd).toFixed(2) : "default") +
    tile("spent (recent)", "$" + (st.recent_spend ?? 0).toFixed(3)) +
    tile("checklist", esc(st.checklist || "on")) +
    tile("sandbox", esc(st.sandbox || "auto")) +
    tile("plan", esc(st.plan || "auto"));
}

// expand/collapse state survives the 2s re-render
const openNodes = new Set();
document.addEventListener("toggle", e => {
  const id = e.target.dataset && e.target.dataset.nid;
  if (!id) return;
  if (e.target.open) openNodes.add(id); else openNodes.delete(id);
}, true);

function hhmmss(ts) { return new Date(ts * 1000).toLocaleTimeString(); }

// One timeline node. body!=null → expandable <details>.
function node(nid, cls, ts, html, body) {
  const t = `<span class="t">${hhmmss(ts)}</span>`;
  if (!body) return `<div class="node ${cls}">${t}${html}</div>`;
  return `<details class="node ${cls}" data-nid="${nid}"${openNodes.has(nid) ? " open" : ""}>
    <summary>${t}${html} <span class="more">details</span></summary>
    <div class="payload">${body}</div></details>`;
}

// Translate a trace event into a human-readable timeline node.
function nodeFor(task, e, idx) {
  const d = e.data || {};
  const nid = `${task}:${idx}:${e.kind}`;
  const model = e.model ? ` <b>${esc(e.model)}</b>` : "";
  const cost = e.cost_usd ? ` · $${e.cost_usd.toFixed(4)}` : "";
  const toks = (e.tokens_in || e.tokens_out)
    ? ` · ${(e.tokens_in||0)+(e.tokens_out||0)} tok` : "";
  switch (e.kind) {
    case "turn_start":  return node(nid, "", e.ts, `goal started —${model} routing=${esc(d.routed||"static")}`);
    case "agent_turn":  return node(nid, "", e.ts, `agent goal started —${model} (${d.n_messages||"?"} msgs in conversation)`);
    case "contract":    return node(nid, "", e.ts, `☑ checklist extracted — <b>${(d.constraints||[]).length} constraints</b>${cost}`,
                                    (d.constraints||[]).map(c => "• " + esc(c)).join("\n") || null);
    case "contract_skipped": return node(nid, "", e.ts, "☑ checklist skipped (user setting)");
    case "contract_failed":  return node(nid, "err", e.ts, "☑ checklist extraction failed (provider) — continuing without");
    case "plan":        return node(nid, "", e.ts, `⧉ plan — <b>${(d.units||[]).length ? (d.units||[]).length + " units" : "single pass"}</b>${cost}`,
                                    (d.units||[]).map((u,i) => `${i+1}. ${esc(u)}`).join("\n") || null);
    case "resume":      return node(nid, "ok", e.ts, `↻ resumed from checkpoint — units done: ${(d.completed||[]).map(x=>x+1).join(", ") || "none"} (prior spend $${(d.prior_spent||0).toFixed(4)})`);
    case "wave_start":  return node(nid, "", e.ts, `∥ wave ${d.wave} started — units ${(d.units||[]).join(", ")} in parallel`);
    case "execute":     return node(nid, "", e.ts, `⚙ attempt ${d.attempt||1} —${model}${toks}${cost}`);
    case "execute_code":return node(nid, d.ok ? "ok" : "err", e.ts,
                                    `⏵ sandbox ${d.ok ? "passed" : "FAILED"} — ${esc(d.backend)} · exit ${d.exit_code} · ${d.duration_s}s`,
                                    d.stderr ? esc(d.stderr) : null);
    case "fm_event":    return node(nid, "fm", e.ts,
                                    `⚠ <b>${esc(e.fm_id || d.fm_id)}</b>${d.scope === "session" ? " (cross-turn)" : ""} · confidence ${d.confidence ?? "?"}`,
                                    esc(d.evidence || ""));
    case "verify":      return node(nid, d.passed ? "ok" : "err", e.ts,
                                    `${d.passed ? "✓" : "✗"} verified by${model} — score <b>${(d.score ?? 0).toFixed(2)}</b>${d.stage ? " ("+esc(d.stage)+")" : ""}${cost}`,
                                    d.criteria ? Object.entries(d.criteria).map(([k,v]) => `${k}: ${v}`).join("\n") : null);
    case "verify_error":return node(nid, "err", e.ts, `✗ verification unavailable — ${esc(d.error||"")}`);
    case "executor_error":    return node(nid, "err", e.ts, `⚙ executor failed —${model}`, esc(d.error||""));
    case "executor_fallback": return node(nid, "", e.ts, `⇄ failed over to <b>${esc(e.model)}</b>`);
    case "budget_stop": return node(nid, "err", e.ts, `$ budget stop — $${(d.spent||0).toFixed(3)} of $${(d.budget||0).toFixed(2)}`);
    case "synthesis":   return node(nid, "", e.ts, `Σ assembled final answer —${model}${toks}${cost}`);
    case "tool_step":   return node(nid, "", e.ts, `🔧 agent tool step —${model} · ${d.n_calls||1} call(s)${cost}`);
    case "unit_done":   return null; // rendered as the unit group summary
    case "turn_end": case "agent_end":
      return node(nid, d.escalated ? "err" : "ok", e.ts,
                  `${d.escalated ? "⛔" : "✓"} finished${d.score != null ? ` — score <b>${Number(d.score).toFixed(2)}</b>` : ""}${d.spent != null ? ` · spent $${d.spent.toFixed(4)}` : ""}`,
                  d.answer_preview ? "→ " + esc(d.answer_preview) : null);
    default:            return node(nid, "", e.ts, esc(e.kind) + model + cost);
  }
}

function renderTasks(events) {
  lastEvents = events;
  const proj = library.projects.find(p => p.id === sel.project);
  const projSessions = new Set(library.sessions
    .filter(s => s.project_id === sel.project).map(s => s.session));
  $("#tasksHeading").textContent = sel.session
    ? "Tasks — this conversation"
    : `Tasks — ${proj ? proj.name : "all"}`;
  const byTask = new Map();
  for (const e of events) {
    if (e.task === "-") continue;
    // filter to the selected session, or all sessions in the selected project
    if (sel.session) { if (e.session !== sel.session) continue; }
    else if (library.sessions.length && !projSessions.has(e.session)) continue;
    if (!byTask.has(e.task)) byTask.set(e.task, []);
    byTask.get(e.task).push(e);
  }
  const cards = [];
  let n = 0;
  for (const [task, evs] of byTask) {
    if (++n > 10) break;
    evs.sort((a, b) => a.ts - b.ts);
    const end = evs.find(e => e.kind === "turn_end" || e.kind === "agent_end");
    const verifies = evs.filter(e => e.kind === "verify");
    const lastScore = verifies.length ? verifies[verifies.length-1].data?.score : null;
    const cost = evs.reduce((s, e) => s + (e.cost_usd || 0), 0);
    const fms = [...new Set(evs.filter(e => e.kind === "fm_event").map(e => e.fm_id || e.data?.fm_id))];
    const escalated = end?.data?.escalated;
    const preview = evs.find(e => e.data?.task_preview)?.data?.task_preview;
    const planUnits = evs.find(e => e.kind === "plan")?.data?.units || [];
    const agentic = evs.some(e => e.kind === "agent_turn" || e.kind === "tool_step");
    const status = end
      ? (escalated ? `<span class="badge crit">⛔ needs input</span>`
                   : `<span class="badge ok">✓ done</span>`)
      : (agentic && !verifies.length
         ? `<span class="badge">🔧 agent tool step</span>`
         : `<span class="badge">… running</span>`);

    // Build the timeline: unit-tagged events fold into per-unit groups,
    // inserted at the position of the unit's first event.
    const rows = [];
    const unitRendered = new Set();
    evs.forEach((e, idx) => {
      const u = e.data?.unit;
      if (u == null || e.kind === "wave_start") {
        const r = nodeFor(task, e, idx);
        if (r) rows.push(r);
        return;
      }
      if (unitRendered.has(u)) return;
      unitRendered.add(u);
      const unitEvs = evs.map((x, i) => [x, i]).filter(([x]) => x.data?.unit === u);
      const done = unitEvs.map(([x]) => x).find(x => x.kind === "unit_done");
      const desc = planUnits[u-1] ? esc(String(planUnits[u-1]).slice(0, 100)) : "";
      const uScore = done?.data?.score;
      const nid = `${task}:unit:${u}`;
      rows.push(`<details class="unit" data-nid="${nid}"${openNodes.has(nid) ? " open" : ""}>
        <summary><b>unit ${u}</b>${desc ? " — " + desc : ""}${
          uScore != null ? ` · score <b>${Number(uScore).toFixed(2)}</b>` : ""}${
          done?.data?.escalated ? " · ⛔ " + esc(done.data.escalated) : ""} <span class="more">expand</span></summary>
        <div class="subtl">${unitEvs.filter(([x]) => x.kind !== "unit_done")
          .map(([x, i]) => nodeFor(task, x, i)).filter(Boolean).join("")}</div>
      </details>`);
    });

    const tnid = `${task}:turn`;
    const open = openNodes.has(tnid) || n === 1;  // newest goal starts expanded
    cards.push(`<details class="turn" data-nid="${tnid}"${open ? " open" : ""}>
      <summary>
        ${status}
        <span class="goal" title="${esc(preview || "")}">${esc((preview || "(no prompt recorded)").slice(0, 150))}</span>
        ${scorebar(lastScore)}
        <span class="gcost">$${cost.toFixed(4)}</span>
        ${fms.map(fmBadge).join(" ")}
        <span class="gid">${esc(task)}</span>
        <button class="msgbtn" onclick="toggleMessages(event, '${esc(task)}')">messages</button>
        <button class="msgbtn" onclick="copyRequest(event, '${esc(task)}')"
          title="copy the exact request text — search for it in OpenCode/Hermes to edit that message, or resend it to resume from checkpoint (!rewind <unit#> first to redo a unit)">⧉ request</button>
      </summary>
      <div class="tl">${rows.join("")}
        ${escalated ? `<div class="esc">${esc(escalated)}</div>` : ""}
      </div>
      <div class="msgview" id="msg-${esc(task)}" style="display:none"></div>
    </details>`);
  }
  $("#tasks").innerHTML = cards.join("") ||
    `<div class="card" style="color:var(--muted)">no supervised turns yet — point a client at /v1 with model "super"</div>`;
  // restore message views wiped by the re-render
  for (const task of msgShown) {
    const el = document.getElementById("msg-" + task);
    if (el && msgCache.has(task)) {
      el.style.display = "block";
      el.innerHTML = msgCache.get(task);
    }
  }
}

// Edit history: divergences of the conversation prefix — each one forked a
// branch; the superseded branch's turns remain in the task list below.
function renderEdits(rows) {
  if (!rows || !rows.length) { $("#edits").innerHTML = ""; return; }
  const items = rows.map(r => {
    const when = new Date(r.ts * 1000).toLocaleTimeString();
    const what = r.kind === "edit"
      ? `message ${r.position + 1} (${esc(r.role)}) edited:
         <s title="${esc(r.old_text)}">${esc((r.old_text || "").slice(0, 70))}</s>
         → <span title="${esc(r.new_text)}">${esc((r.new_text || "").slice(0, 70))}</span>`
      : `rewound to before message ${r.position + 1}
         (dropped: <s title="${esc(r.old_text)}">${esc((r.old_text || "").slice(0, 70))}</s>)`;
    return `<div class="node"><span class="t">${when}</span>
      ✏️ <b>branch ${r.branch}</b> · ${what}</div>`;
  }).join("");
  $("#edits").innerHTML = `<div class="card">
    <div style="font-size:12px;color:var(--muted);margin-bottom:6px">
      edit history — each divergence forked a branch; superseded turns stay listed below (!edits in-band)</div>
    ${items}</div>`;
}

function renderStats(rows) {
  if (!rows.length) { $("#stats").innerHTML = ""; return; }
  $("#stats").innerHTML = `<table><thead><tr>
    <th>model</th><th class="num">turns</th><th class="num">avg score</th>
    <th class="num">avg attempts</th><th class="num">failure modes / turn</th>
    </tr></thead><tbody>` + rows.map(r => `<tr>
      <td>${esc(r.model)}</td><td class="num">${r.turns}</td>
      <td class="num">${r.avg_score ?? "—"}</td>
      <td class="num">${r.avg_attempts ?? "—"}</td>
      <td class="num">${r.fm_per_turn ?? "—"}</td></tr>`).join("") +
    "</tbody></table>";
}

function meter(pct) {
  if (pct == null) return "";
  const color = pct >= 90 ? "var(--critical)" : pct >= 60 ? "var(--serious)" : "var(--seq)";
  return `<span class="scorebar"><span class="track"><span class="fill"
    style="width:${Math.min(100, pct)}%;background:${color}"></span></span>
    <span class="n">${pct}%</span></span>`;
}

function renderBalance(b) {
  const provs = Object.entries(b.providers || {});
  if (!provs.length) { $("#balance").innerHTML = ""; return; }
  const br = b.breakers || {providers: {}, models: {}};
  const rows = [];
  for (const [name, p] of provs) {
    const hasLimits = Object.keys(p.limits || {}).length > 0;
    const anyUse = Object.values(p.windows).some(w => w.requests);
    if (!hasLimits && !anyUse) continue;   // idle provider with no declared caps
    const circuit = br.providers[name];
    const circuitTxt = circuit && circuit.open_for_s > 0
      ? `<span class="badge crit">⛔ cooling ${Math.ceil(circuit.open_for_s)}s</span>`
      : (circuit && (circuit.fails || circuit.limit_hits)
         ? `<span class="badge fm">⚠ ${circuit.limit_hits ? "limit hits: " + circuit.limit_hits : "fails: " + circuit.fails}</span>`
         : `<span class="badge ok">✓ ok</span>`);
    const cells = Object.entries(p.windows).map(([wname, w]) => {
      const unitTok = "limit_tokens_in" in w;
      const used = unitTok
        ? `${(w.tokens_in / 1e6).toFixed(2)}M in-tok`
        : `$${w.nominal_usd.toFixed(2)}`;
      const cap = unitTok ? (w.limit_tokens_in != null ? ` / ${(w.limit_tokens_in / 1e6).toFixed(0)}M` : "")
                          : (w.limit_usd != null ? ` / $${w.limit_usd}` : "");
      const est = w.est_requests_left != null
        ? `<div style="color:var(--muted);font-size:11px">≈ ${w.est_requests_left.toLocaleString()} req left</div>` : "";
      return `<td class="num">${w.requests} req · ${used}${cap}
        ${meter(w.used_pct)}${est}</td>`;
    }).join("");
    rows.push(`<tr><td>${esc(name)}<br>${circuitTxt}</td>${cells}</tr>`);
  }
  const modelBr = Object.entries(br.models || {})
    .filter(([, v]) => v.open_for_s > 0)
    .map(([m, v]) => `<span class="badge fm">⚠ ${esc(m)} cooling ${Math.ceil(v.open_for_s)}s</span>`)
    .join(" ");
  $("#balance").innerHTML = (rows.length
    ? `<table><thead><tr><th>provider</th><th class="num">5h window</th>
       <th class="num">week</th><th class="num">month</th></tr></thead>
       <tbody>${rows.join("")}</tbody></table>`
    : `<div class="card" style="color:var(--muted)">no provider traffic yet</div>`)
    + (modelBr ? `<div style="margin-top:8px">model-level limit cooldowns: ${modelBr}</div>` : "");
}

function renderEfficiency(r) {
  const k = r.kpi || {};
  const pct = v => v == null ? "—" : v + "%";
  const roles = Object.entries(r.by_role || {})
    .filter(([, v]) => v.cost_usd || v.tokens);
  const kpis =
    tile("supervision overhead", pct(k.overhead_pct_tokens), "of tokens · target <15%") +
    tile("repair spend", pct(k.repair_pct_of_executor), "of executor spend") +
    tile("total (30d)", "$" + (r.total_cost_usd ?? 0).toFixed(3),
         (r.total_tokens ?? 0).toLocaleString() + " tok");
  const roleRows = roles.map(([b, v]) => `<tr><td>${esc(b)}</td>
      <td class="num">$${v.cost_usd.toFixed(4)}</td>
      <td class="num">${v.tokens.toLocaleString()}</td></tr>`).join("");
  const repairs = (r.repair_stats || []).slice(0, 12).map(x =>
    `<tr><td>${esc(x.model)}</td><td>${esc(x.fm_id)}</td>
     <td class="num">${x.attempts}</td>
     <td class="num">${Math.round(x.success_rate * 100)}%</td></tr>`).join("");
  $("#efficiency").innerHTML =
    `<div class="tiles" style="margin-bottom:10px">${kpis}</div>` +
    (roleRows ? `<table><thead><tr><th>role</th><th class="num">$</th>
       <th class="num">tokens</th></tr></thead><tbody>${roleRows}</tbody></table>` : "") +
    (repairs ? `<div style="margin-top:10px"><table><thead><tr>
       <th>repair priors: model</th><th>failure mode</th>
       <th class="num">attempts</th><th class="num">success</th>
       </tr></thead><tbody>${repairs}</tbody></table></div>` : "");
}

function renderEvents(events) {
  $("#events").innerHTML = `<table><thead><tr>
    <th>time</th><th>task</th><th>event</th><th>model</th><th>fm</th>
    <th class="num">tokens</th><th class="num">$</th></tr></thead><tbody>` +
    events.slice(0, 40).map(e => {
      const t = new Date(e.ts * 1000).toLocaleTimeString();
      const fm = e.fm_id || e.data?.fm_id || "";
      return `<tr><td class="evk">${t}</td><td class="evk">${esc(e.task)}</td>
        <td class="evk">${esc(e.kind)}</td><td class="evk">${esc(e.model || "")}</td>
        <td>${fm ? fmBadge(fm) : ""}</td>
        <td class="num">${(e.tokens_in||0)+(e.tokens_out||0) || ""}</td>
        <td class="num">${e.cost_usd ? e.cost_usd.toFixed(4) : ""}</td></tr>`;
    }).join("") + "</tbody></table>";
}

// ---- conversation library: projects, sessions, settings, export ----
let library = { projects: [], sessions: [], default_settings: {} };
let sel = { project: "default", session: null };   // what the content pane shows
const expandedProjects = new Set(["default"]);

async function libPost(body) {
  const r = await fetch("/admin/library", {method: "POST",
    headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  return r.json();
}
async function newProject() {
  const name = prompt("New project name:");
  if (name) { await libPost({action: "create_project", name}); flash("project created"); refresh(); }
}
async function renameProject(pid, cur) {
  const name = prompt("Rename project:", cur);
  if (name) { await libPost({action: "rename_project", id: pid, name}); refresh(); }
}
async function deleteProject(pid) {
  if (confirm("Delete this project? Its conversations move to Default.")) {
    await libPost({action: "delete_project", id: pid});
    if (sel.project === pid) sel = {project: "default", session: null};
    refresh();
  }
}
async function deleteSession(sid) {
  if (confirm("Delete this conversation and all its messages? This cannot be undone.")) {
    await libPost({action: "delete_session", session: sid});
    if (sel.session === sid) sel.session = null;
    refresh();
  }
}
async function renameSession(sid, cur) {
  const title = prompt("Rename conversation:", cur || "");
  if (title != null) { await libPost({action: "rename_session", session: sid, title}); refresh(); }
}
async function assignSession(sid, pid) {
  await libPost({action: "assign_session", session: sid, project_id: pid}); refresh();
}
function selectProject(pid) { sel = {project: pid, session: null}; renderSidebar(); renderLibrary(); renderTasks(lastEvents); }
function selectSession(sid, pid) { sel = {project: pid, session: sid}; renderSidebar(); renderTasks(lastEvents); }

function renderSidebar() {
  const byProj = new Map(library.projects.map(p => [p.id, []]));
  for (const s of library.sessions) {
    (byProj.get(s.project_id) || byProj.get("default")).push(s);
  }
  const html = library.projects.map(p => {
    const ss = byProj.get(p.id) || [];
    const open = expandedProjects.has(p.id);
    const selP = sel.project === p.id && !sel.session;
    const projOpts = library.projects.map(x =>
      `<option value="${esc(x.id)}"${x.id===p.id?" selected":""}>${esc(x.name)}</option>`).join("");
    return `<div class="proj">
      <div class="ph ${selP?"sel":""}">
        <span class="iconbtn" onclick="toggleProj('${esc(p.id)}')">${open?"▾":"▸"}</span>
        <span class="pname" onclick="selectProject('${esc(p.id)}')">${esc(p.name)}</span>
        <span class="pcount">${ss.length}</span>
        ${p.id!=="default" ? `<span class="iconbtn" title="rename" onclick="renameProject('${esc(p.id)}','${esc(p.name)}')">✎</span>
          <span class="iconbtn" title="delete" onclick="deleteProject('${esc(p.id)}')">🗑</span>` : ""}
      </div>
      ${open ? `<div class="slist">${ss.length ? ss.map(s => `
        <div class="sitem ${sel.session===s.session?"sel":""}">
          <span class="st" title="${esc(s.title||s.session)}" onclick="selectSession('${esc(s.session)}','${esc(p.id)}')">${esc(s.title||"(untitled)")}</span>
          <select class="sx" title="move to project" onchange="assignSession('${esc(s.session)}',this.value)">${projOpts}</select>
          <span class="sx iconbtn" title="rename" onclick="renameSession('${esc(s.session)}','${esc(s.title||"")}')">✎</span>
          <span class="sx iconbtn" title="delete" onclick="deleteSession('${esc(s.session)}')">🗑</span>
        </div>`).join("") : '<div class="sitem" style="color:var(--muted)">no conversations</div>'}</div>` : ""}
    </div>`;
  }).join("");
  $("#projects").innerHTML = html;
}
function toggleProj(pid) {
  if (expandedProjects.has(pid)) expandedProjects.delete(pid); else expandedProjects.add(pid);
  renderSidebar();
}

// setting field types for rendering the right control
const SETTING_FIELDS = {
  compression: ["select", ["xz","gzip","none"]],
  compression_level: ["number", null],
  encryption: ["select", ["none","passphrase","publickey"]],
  kdf: ["select", ["scrypt","argon2id","pbkdf2"]],
  public_key: ["text", null],
  destination: ["select", ["dir","command"]],
  directory: ["text", null],
  command: ["text", null],
  include_upstream: ["bool", null],
};

async function renderLibrary() {
  // don't yank focus / reset a field the user is editing during the 2s poll
  const af = document.activeElement;
  if (af && (af.closest("#settings") || af.closest("#exportbar"))) return;
  const pid = sel.project;
  const proj = library.projects.find(p => p.id === pid);
  $("#settingsScope").textContent = proj ? `— ${proj.name}${pid==="default"?" (global default)":""}` : "";
  let resolved;
  if (pid === "default") {
    // editing the default itself: everything is "default", edits set the global default
    resolved = {};
    for (const [k, v] of Object.entries(library.default_settings))
      resolved[k] = {value: v, source: "default"};
  } else {
    resolved = await fetch(`/admin/project/${pid}/settings`).then(r => r.json());
  }
  const rows = Object.keys(SETTING_FIELDS).map(key => {
    const info = resolved[key] || {value: library.default_settings[key], source: "default"};
    const [kind, opts] = SETTING_FIELDS[key];
    const v = info.value;
    let control;
    if (kind === "select")
      control = `<select onchange="setSetting('${key}',this.value)">${opts.map(o =>
        `<option${String(v)===o?" selected":""}>${o}</option>`).join("")}</select>`;
    else if (kind === "bool")
      control = `<select onchange="setSetting('${key}',this.value==='true')">
        <option value="true"${v?" selected":""}>true</option>
        <option value="false"${!v?" selected":""}>false</option></select>`;
    else if (kind === "number")
      control = `<input type="number" value="${esc(v)}" onchange="setSetting('${key}',Number(this.value))">`;
    else
      control = `<input type="text" value="${esc(v)}" placeholder="${key==='public_key'?'X25519 base64 or RSA PEM':''}" onchange="setSetting('${key}',this.value)">`;
    const isDefaultProj = pid === "default";
    const badge = isDefaultProj ? "" :
      `<span class="src ${info.source}">${info.source==="project"?"overridden":"inherited"}</span>`;
    const reset = (!isDefaultProj && info.source === "project")
      ? `<button class="reset show" onclick="resetSetting('${key}')">reset</button>` : "<span></span>";
    return `<div class="fname">${key}</div><div class="fval">${control}</div>${badge||"<span></span>"}${reset}`;
  }).join("");
  $("#settings").innerHTML = `<div class="settings-grid">${rows}</div>`;

  const eff = {}; for (const k in resolved) eff[k] = resolved[k].value;
  const needsPass = eff.encryption === "passphrase";
  $("#exportbar").innerHTML =
    (sel.session
      ? `<button class="primary" onclick="doExport('session')">Export this conversation</button>`
      : "") +
    `<button onclick="doExport('project')">Export whole project</button>` +
    (needsPass ? `<input type="password" id="exportPass" placeholder="passphrase">` : "") +
    `<span style="color:var(--muted);font-size:12px">→ ${esc(eff.destination==="command"?"command":eff.directory)} · ${esc(eff.encryption)} · ${esc(eff.compression)}</span>`;
}

async function setSetting(key, value) {
  if (sel.project === "default")
    await libPost({action: "set_default", patch: {[key]: value}});
  else
    await libPost({action: "set_project_override", id: sel.project, key, value});
  flash(key + " set");
  const lib = await fetch("/admin/library").then(r => r.json());
  library = lib; renderLibrary();
}
async function resetSetting(key) {
  await libPost({action: "clear_project_override", id: sel.project, key});
  renderLibrary();
}
async function doExport(scope) {
  const body = scope === "session" ? {session: sel.session} : {project_id: sel.project};
  const passEl = document.getElementById("exportPass");
  if (passEl) body.passphrase = passEl.value;
  $("#exportResult").textContent = "exporting…";
  const r = await fetch("/admin/export", {method: "POST",
    headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)}).then(r => r.json());
  $("#exportResult").textContent = r.error
    ? "✗ " + r.error
    : `✓ ${r.name} — ${(r.bytes/1024).toFixed(1)}KB from ${(r.raw_bytes/1024).toFixed(1)}KB (${Math.round(100*r.bytes/r.raw_bytes)}%) · ${r.encryption} · ${r.location}`;
}

// ---- routing ----
const ROUTING_LABELS = {
  default_executor: "default executor",
  utility: "utility (contract / planner)",
  referee: "referee (repair strategy)",
  trivial_executor: "trivial-tier executor",
  learned_routing: "learned routing",
  min_routing_samples: "min samples to route",
  verifier_pool: "verifier pool (ordered)",
};
function renderRouting(r) {
  const af = document.activeElement;
  if (af && af.closest("#routing")) return;  // don't clobber live edits
  const s = r.settings;
  const names = Object.keys(r.models);
  const executors = names.filter(m => r.models[m].roles.includes("executor"));
  const modelSel = (k, v, pool, blank) =>
    `<select onchange="setRouting('${k}', this.value)">` +
    (blank ? `<option value=""${!v ? " selected" : ""}>(none)</option>` : "") +
    pool.map(m => `<option${m === v ? " selected" : ""}>${m}</option>`).join("") +
    `</select>`;
  const controls = {
    default_executor: modelSel("default_executor", s.default_executor, executors),
    utility: modelSel("utility", s.utility, names),
    referee: modelSel("referee", s.referee, names, true),
    trivial_executor: modelSel("trivial_executor", s.trivial_executor, names, true),
    learned_routing:
      `<select onchange="setRouting('learned_routing', this.value === 'true')">
         <option value="true"${s.learned_routing ? " selected" : ""}>on</option>
         <option value="false"${!s.learned_routing ? " selected" : ""}>off</option></select>`,
    min_routing_samples:
      `<input type="number" min="1" step="1" value="${esc(s.min_routing_samples)}"
        onchange="setRouting('min_routing_samples', Number(this.value))">`,
    verifier_pool:
      `<input type="text" style="width:100%" value="${esc(s.verifier_pool.join(", "))}"
        onchange="setRouting('verifier_pool', this.value)">`,
  };
  $("#routing").innerHTML = `<div class="settings-grid">` +
    Object.keys(ROUTING_LABELS).map(k =>
      `<div class="fname">${ROUTING_LABELS[k]}</div><div class="fval">${controls[k]}</div><span></span><span></span>`
    ).join("") + `</div>`;
}
async function setRouting(key, value) {
  if (key === "verifier_pool")
    value = value.split(",").map(s => s.trim()).filter(Boolean);
  const resp = await fetch("/admin/routing", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({patch: {[key]: value}})});
  if (!resp.ok) {
    const e = await resp.json();
    flash("routing: ✗ " + (e.error || resp.status));
    renderRouting(await fetch("/admin/routing").then(r => r.json()));
    return;
  }
  flash("routing: " + key + " set (runtime only)");
}

// ---- retention ----
const RETENTION_LABELS = {
  exchanges_days: "message payloads (days)",
  events_days: "trace events (days)",
  turns_days: "turn history (days)",
  vacuum: "reclaim disk space (VACUUM)",
};
function renderRetention(r) {
  const af = document.activeElement;
  if (af && af.closest("#retention")) return;  // don't clobber live edits
  const s = r.settings, st = r.stats;
  const fields = Object.keys(RETENTION_LABELS).map(k => {
    const v = s[k];
    const control = k === "vacuum"
      ? `<select onchange="setRetention('${k}',this.value==='true')">
           <option value="true"${v?" selected":""}>true</option>
           <option value="false"${!v?" selected":""}>false</option></select>`
      : `<input type="number" min="0" step="1" value="${esc(v)}"
           onchange="setRetention('${k}',Number(this.value))">`;
    return `<div class="fname">${RETENTION_LABELS[k]}</div><div class="fval">${control}</div><span></span><span></span>`;
  }).join("");
  const tbl = Object.entries(st.tables).map(([t, v]) =>
    `${t}: ${v.rows} rows${v.oldest_days ? ` (oldest ${v.oldest_days}d)` : ""}`).join(" · ");
  $("#retention").innerHTML = `<div class="settings-grid">${fields}</div>
    <div class="exportbar">
      <button onclick="pruneNow()">Prune now</button>
      <span style="color:var(--muted);font-size:12px">
        db ${(st.db_bytes/1048576).toFixed(1)}MB · ${tbl} · auto-prunes hourly</span>
    </div>
    <div class="export-result" id="pruneResult"></div>`;
}
async function setRetention(key, value) {
  await fetch("/admin/retention", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({patch: {[key]: value}})});
  flash("retention: " + key + " set");
}
async function pruneNow() {
  $("#pruneResult").textContent = "pruning…";
  const r = await fetch("/admin/prune", {method: "POST"}).then(r => r.json());
  const d = r.deleted || {};
  $("#pruneResult").textContent =
    `✓ deleted ${Object.entries(d).map(([t,n]) => `${t}:${n}`).join(" ")} · ` +
    `reclaimed ${(r.reclaimed_bytes/1024).toFixed(0)}KB` +
    (r.vacuumed === false ? " (vacuum deferred: db busy)" : "");
}

// Quick-copy the exact request text for a task. It is both the locator
// (search your client's history for it to edit/rewind to that message) and
// the resume key (resending the identical text continues from checkpoint).
// Copied verbatim — any decoration would break the checkpoint key match.
async function copyRequest(e, task) {
  e.preventDefault(); e.stopPropagation();
  const msgs = await fetch(`/admin/messages?task=${encodeURIComponent(task)}&n=20`)
    .then(r => r.json());
  const req = msgs.find(m => m.kind === "client_request");
  let text = "";
  const mlist = (req && req.payload && req.payload.messages) || [];
  for (let i = mlist.length - 1; i >= 0; i--) {
    if (mlist[i].role === "user") {
      const c = mlist[i].content;
      text = typeof c === "string" ? c
        : (c || []).map(p => p && p.text || "").join(" ");
      break;
    }
  }
  if (!text) { flash("no recorded request for this task"); return; }
  try {
    await navigator.clipboard.writeText(text);
    flash("request copied — paste in your client to edit/rewind, or resend to resume");
  } catch (err) {
    flash("clipboard blocked by the browser (" + err + ")");
  }
}

// Full-payload viewer: fetched on demand, never polled.
const msgShown = new Set();
const msgCache = new Map();
let lastEvents = [];
function fmtContent(c) {
  if (c == null) return "";
  if (Array.isArray(c)) return c.map(p => p.text || JSON.stringify(p)).join("\n");
  return typeof c === "string" ? c : JSON.stringify(c, null, 1);
}
function renderMessage(m, i) {
  const rows = [];
  const add = (role, text) =>
    rows.push(`<div><span class="role">${esc(role)}</span></div><pre>${esc(text)}</pre>`);
  if (m.kind === "client_request") {
    for (const msg of (m.payload.messages || [])) {
      let t = fmtContent(msg.content);
      if (msg.tool_calls) t += "\n[tool_calls] " + JSON.stringify(msg.tool_calls, null, 1);
      add(msg.role, t);
    }
  } else if (m.kind === "upstream") {
    for (const msg of ((m.payload.request || {}).messages || []).slice(-2))
      add(msg.role, fmtContent(msg.content));
    const rmsg = (((m.payload.response || {}).choices || [])[0] || {}).message || {};
    let t = fmtContent(rmsg.content);
    if (rmsg.tool_calls) t += "\n[tool_calls] " + JSON.stringify(rmsg.tool_calls, null, 1);
    add("↳ " + (m.model || "model"), t);
  } else {  // client_response
    const p = m.payload;
    const rmsg = ((p.choices || [])[0] || {}).message;
    let t = rmsg ? fmtContent(rmsg.content) : fmtContent(p.text);
    if (rmsg && rmsg.tool_calls) t += "\n[tool_calls] " + JSON.stringify(rmsg.tool_calls, null, 1);
    add("→ client", t);
  }
  return `<div class="msg"><div class="mh">#${i + 1} ${esc(m.kind)}${
    m.model ? " · " + esc(m.model) : ""} · ${hhmmss(m.ts)}</div>${rows.join("")}</div>`;
}
async function toggleMessages(ev, task) {
  ev.preventDefault(); ev.stopPropagation();
  const el = document.getElementById("msg-" + task);
  if (!el) return;
  if (msgShown.has(task)) {
    msgShown.delete(task); el.style.display = "none"; return;
  }
  msgShown.add(task);
  el.style.display = "block";
  el.innerHTML = '<span style="color:var(--muted)">loading…</span>';
  const ms = await fetch(`/admin/messages?task=${encodeURIComponent(task)}&n=200`)
    .then(r => r.json()).catch(() => []);
  const html = ms.length
    ? `<div class="mh" style="margin-bottom:8px;color:var(--muted)">
         ${ms.length} exchanges (client ↔ proxy ↔ providers) — newest last</div>`
      + ms.map(renderMessage).join("")
    : '<span style="color:var(--muted)">no recorded exchanges for this task (predates message recording?)</span>';
  msgCache.set(task, html);
  el.innerHTML = html;
}

let libraryRendered = false;
async function refresh() {
  try {
    const [st, evs, stats, lib, ret, rt, eff, bal] = await Promise.all([
      fetch("/admin/status").then(r => r.json()),
      fetch("/admin/events?n=300").then(r => r.json()),
      fetch("/admin/stats").then(r => r.json()),
      fetch("/admin/library").then(r => r.json()),
      fetch("/admin/retention").then(r => r.json()),
      fetch("/admin/routing").then(r => r.json()),
      fetch("/admin/report").then(r => r.json()),
      fetch("/admin/balance").then(r => r.json()),
    ]);
    library = lib;
    if (!library.projects.find(p => p.id === sel.project)) sel = {project: "default", session: null};
    renderStatus(st, st.models || []);
    renderSidebar();
    renderLibrary();
    renderRetention(ret);
    renderRouting(rt);
    renderEdits(sel.session
      ? await fetch(`/admin/edits?session=${encodeURIComponent(sel.session)}`)
          .then(r => r.json())
      : []);
    renderTasks(evs);
    renderStats(stats);
    renderEfficiency(eff);
    renderBalance(bal);
    renderEvents(evs);
    $("#clock").textContent = new Date().toLocaleTimeString();
  } catch (e) {
    $("#clock").textContent = "proxy unreachable";
  }
}
refresh().then(() => {
  const q = new URLSearchParams(location.search);
  const p = q.get("project");
  if (p) { sel = {project: p, session: null}; expandedProjects.add(p); renderSidebar(); renderLibrary(); renderTasks(lastEvents); }
  const t = q.get("msg");
  if (t) toggleMessages(new Event("click"), t);
});
setInterval(refresh, 2000);
</script>
</body>
</html>
"""
