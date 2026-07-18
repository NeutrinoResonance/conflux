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
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🛰️</text></svg>">
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
.node.sub { margin-left: 26px; }
/* provenance convention: every expansion block is labeled. Model-generated
   text gets the accent border + tint; system-computed data gets the plain
   border. They must never be confusable. */
/* identity hues: every task and conversation carries a stable accent */
.sitem .cdot { flex: 0 0 8px; width: 8px; height: 8px; border-radius: 50%; }
details.turn { border-left: 3px solid var(--task-hue, var(--border)); }
.pipeline { border-left: 3px solid var(--task-hue, var(--border)); }
#graph svg.flash .gnode rect { animation: gflash 1.2s ease-out 2; }
@keyframes gflash { 0% { stroke-width: 4; } 100% { stroke-width: 1.2; } }
/* probability strip for the score math */
.crit { display: grid; grid-template-columns: 130px 1fr 84px; gap: 10px;
  align-items: center; margin: 4px 0; }
.crit .cname { font-size: 11.5px; color: var(--ink-2); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.pstrip { display: flex; gap: 2px; height: 14px; border-radius: 4px; overflow: hidden; }
.pstrip .seg { min-width: 2px; border-radius: 3px; position: relative; }
.pstrip .seg .sl { position: absolute; inset: 0; display: flex; align-items: center;
  justify-content: center; font-size: 9.5px; color: var(--ink); }
.crit .ev { font-size: 11px; color: var(--ink); text-align: right;
  font-family: ui-monospace, monospace; }
.scorehelp { font-size: 11px; color: var(--muted); margin-top: 6px; }
.scorehelp summary { cursor: pointer; }
.payload .cap { font-size: 10px; letter-spacing: .08em; text-transform: uppercase;
  color: var(--muted); margin: 8px 0 3px; font-family: inherit; }
.payload .cap.mdl { color: var(--seq); }
.payload pre.blk { margin: 0; white-space: pre-wrap; font-size: 11.5px;
  max-height: 280px; overflow-y: auto; font-family: ui-monospace, monospace; }
.payload pre.blk.mdl { border-left: 3px solid var(--seq); padding-left: 8px; }
.payload pre.blk.sys { border-left: 3px solid var(--grid); padding-left: 8px;
  color: var(--ink-2); }
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
/* min-width:0 everywhere: without it, long nowrap conversation titles set
   the flex min-content floor and blow the sidebar out past its basis,
   squeezing .content into a strip */
.sidebar { flex: 0 0 260px; min-width: 0; max-width: 260px;
  position: sticky; top: 12px; }
.content { flex: 1; min-width: 0; }
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
.sitem .st { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sitem .sx { color: var(--muted); font-size: 12px; visibility: hidden; }
.sitem:hover .sx { visibility: visible; }
.iconbtn { background: none; border: none; cursor: pointer; padding: 0 3px;
  color: var(--muted); font-size: 13px; }
.iconbtn:hover { color: var(--ink); }
.miniadd { width: 100%; margin-top: 4px; font-size: 12px; padding: 5px; }
/* ---- pipeline graph ---- */
.pipeline { background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 10px 12px; overflow-x: auto; }
.pipeline .phead { display: flex; gap: 10px; align-items: center;
  font-size: 12px; color: var(--ink-2); margin-bottom: 4px; }
.pipeline svg { display: block; }
.gnode rect { fill: var(--page); stroke: var(--grid); stroke-width: 1.2;
  rx: 8; transition: stroke .4s, fill .4s, opacity .4s; }
.gnode text { fill: var(--ink); font-size: 11.5px; font-weight: 600; }
.gnode text.gsub { fill: var(--ink-2); font-size: 10px; font-weight: 400; }
.gnode.ok rect { stroke: var(--ok, #3fb950); }
.gnode.err rect { stroke: var(--crit, #f85149); }
.gnode.cancelled { opacity: .38; }
.gnode.cancelled rect { stroke-dasharray: 4 3; }
.gnode.pending { opacity: .55; }
.gnode.running rect { stroke: var(--seq); animation: gpulse 1.4s ease-in-out infinite; }
@keyframes gpulse {
  0%, 100% { stroke-width: 1.2; stroke-opacity: 1; }
  50%      { stroke-width: 3;   stroke-opacity: .55; }
}
.gnode.fresh { animation: gin .5s ease-out; }
@keyframes gin { from { opacity: 0; transform: translateY(6px); }
                 to   { opacity: 1; transform: none; } }
.gedge { fill: none; stroke: var(--grid); stroke-width: 1.4;
  transition: stroke .4s; }
.gedge.ok { stroke: var(--ok, #3fb950); stroke-opacity: .65; }
.gedge.active { stroke: var(--seq); stroke-dasharray: 6 5;
  animation: gflow 1s linear infinite; }
@keyframes gflow { to { stroke-dashoffset: -11; } }
.gscore { font-size: 10px; fill: var(--ink-2); }
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
      <label>strategy
        <select id="strategySel" title="how answers are produced: one routed model / the history-ranked best / top-of-N candidates / set-union merge of N / synthesized fusion of N">
          <option value="single">single</option>
          <option value="exploit">exploit (ranking best)</option>
          <option value="best">best-of-N</option>
          <option value="union">union-of-N</option>
          <option value="fuse">fuse-of-N</option>
        </select>
      </label>
      <label>N
        <select id="ensembleSel" title="candidates for best/union/fuse; ~Nx-N+1x cost">
          <option value="2">2</option>
          <option value="3">3</option><option value="4">4</option>
        </select>
      </label>
      <label>cutoff
        <input id="cutoffInp" type="number" step="0.05" min="0.05" max="1"
               placeholder="off" style="width:60px"
               title="short-circuit: first candidate the verifier scores ≥ this wins immediately; others are cancelled">
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
    <h2>Pipeline <span style="color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0">— live turn graph</span></h2>
    <div class="pipeline">
      <div class="phead">
        <label style="display:flex;gap:5px;align-items:center">
          <input type="checkbox" id="gFollow" checked> follow latest</label>
        <select id="gTaskSel" style="font-size:12px"></select>
        <span id="gStatus"></span>
      </div>
      <div id="graph"></div>
    </div>
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
$("#gFollow").onchange = () => renderGraph(lastEvents);
$("#gTaskSel").onchange = e => {
  $("#gFollow").checked = false;
  gSel.task = e.target.value;
  renderGraph(lastEvents);
};
$("#strategySel").onchange = e => post("strategy", e.target.value);
$("#ensembleSel").onchange = e => post("ensemble", e.target.value);
$("#cutoffInp").onchange = e => post("cutoff", e.target.value);

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
// Failure-mode taxonomy (SPEC §3/§5) — every badge explains itself.
const FM_INFO = {
  "FM-X.1": ["incomplete work", "The answer contains stubs/placeholders or defers work back to the user instead of doing it.", "The repair loop demands the full implementation; recurring hits lower the model's routing stats."],
  "FM-X.2": ["breadth thrash", "Many rapid, mutually dissimilar turns — the driving agent is skimming across subtasks without finishing any (cross-turn monitor).", "Advisory: consider !plan on, or steering the client to finish one thread."],
  "FM-X.3": ["execution failure", "Code extracted from the answer was RUN in the sandbox and failed (non-zero exit).", "The failing transcript is fed back to the executor; unresolved failures block a pass."],
  "FM-X.4": ["unevidenced claim", "The answer claims success (e.g. 'tests pass') without showing evidence.", "The verifier is told to trust execution evidence over claims; the repair prompt demands proof or removal."],
  "FM-X.6": ["token starvation", "The model spent its entire output budget on internal reasoning and returned an EMPTY answer.", "Auto-retried with feedback to answer directly; raise supervision.max_output_tokens if it recurs."],
  "FM-1.3": ["step repetition", "A step/attempt is nearly identical to the previous one — feedback is not being incorporated (in-turn: repair loop; cross-turn: the driving agent).", "Forces the referee to make a structural change (switch model / escalate / decompose) instead of another retry."],
  "FM-1.4": ["context loss", "The conversation sent by the client SHRANK versus what was seen before — history was trimmed or compacted.", "Advisory: earlier constraints may be gone; consider re-stating them or !attach-ing the original conversation."],
  "FM-2.1": ["context loss", "Prior conversation content is missing from the current request.", "Advisory: re-state dropped requirements."],
  "FM-2.3": ["progress stall", "Verifier scores are flat or declining across several turns — the task is not converging.", "Advisory: change approach (!use <model>, !plan on) or intervene."],
  "FM-2.6": ["reasoning–action gap", "The answer ENDS by announcing an action it never performs ('Next, I will…').", "Repair demands performing the action or removing the announcement."],
  "FM-3.1": ["premature termination", "The answer is far shorter than the task warrants — it stopped before completing the objective.", "Repair demands the complete deliverable."],
};
function fmTitle(id) {
  const i = FM_INFO[id];
  return i ? `${id} — ${i[0]}: ${i[1]}` : `${id} — failure-mode monitor hit (see docs/observability-and-conversations.md)`;
}
function fmBadge(id) { return `<span class="badge fm" title="${esc(fmTitle(id))}">⚠ ${esc(id)}</span>`; }

// Stable identity hue for a task / conversation id.
function hueFor(id) {
  let h = 0;
  for (const ch of String(id)) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${h} 60% 52%)`;
}

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
  $("#strategySel").value = st.strategy || "single";
  const multi = ["best", "union", "fuse"].includes(st.strategy);
  $("#ensembleSel").disabled = !multi;
  $("#ensembleSel").value = String(multi ? (st.ensemble || 3) : 2);
  $("#cutoffInp").disabled = !multi;
  if (document.activeElement !== $("#cutoffInp"))
    $("#cutoffInp").value = st.cutoff ?? "";
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
    tile("plan", esc(st.plan || "auto")) +
    tile("strategy", esc((st.strategy || "single") + (multi ? " ×" + st.ensemble : "")),
         st.cutoff != null && multi ? "cutoff " + st.cutoff : "");
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

// Provenance-labeled expansion blocks: model text vs system-computed data
// must never be confusable (accent border + MODEL caption vs plain SYSTEM).
function mdlBlk(label, text) {
  return `<div class="cap mdl">🤖 ${label}</div><pre class="blk mdl">${text}</pre>`;
}
function sysBlk(label, text) {
  return `<div class="cap">⚙ ${label} — computed by llm-super</div><pre class="blk sys">${text}</pre>`;
}

// The verifier's score math, from the criteria_detail logged per verify:
// per criterion the letter distribution at the <score> position, its
// expectation, then the combination formula (SPEC §6 / arXiv:2607.05391).
function scoreMath(d) {
  if (!d.criteria_detail || !d.criteria_detail.length)
    return d.criteria
      ? sysBlk("per-criterion expected scores",
               Object.entries(d.criteria).map(([k, v]) => `${k}: ${v}`).join("\n"))
      : null;
  const scale = d.scale || 20;
  const strips = d.criteria_detail.map(c => {
    const entries = Object.entries(c.dist || {});
    const total = entries.reduce((sum, [, pr]) => sum + pr, 0) || 1;
    let mid;
    if (c.continuous && entries.length) {
      const segs = entries.map(([L, pr]) => {
        const pct = 100 * pr / total;
        const val = L.charCodeAt(0) - 64;
        return `<span class="seg" style="flex:${pct.toFixed(2)} 0 0;` +
          `background:var(--seq);opacity:${(0.2 + 0.8 * val / scale).toFixed(2)}"` +
          ` title="P(${L}) = ${(100 * pr / total).toFixed(1)}% · letter value ${val}/${scale}">` +
          `${pct > 14 ? `<span class="sl">${L} · ${(100 * pr / total).toFixed(0)}%</span>` : ""}</span>`;
      }).join("");
      mid = `<div class="pstrip" title="token probabilities at the score position (darker = higher letter)">${segs}</div>`;
    } else {
      mid = `<span class="cname" style="font-style:italic">discrete read — letter ` +
        `${String.fromCharCode(64 + (c.point || 1))} (no usable logprobs this call)</span>`;
    }
    return `<div class="crit"><span class="cname" title="${esc(c.criterion)}">${esc(c.criterion)}</span>` +
      `${mid}<span class="ev">E = ${c.expected}/${scale}</span></div>`;
  }).join("");
  const mean = d.criteria_detail.reduce((sum, c) => sum + c.expected, 0)
    / d.criteria_detail.length;
  const formula = `score = (mean(E) − 1) / (scale − 1) = (${mean.toFixed(2)} − 1) / ${scale - 1}` +
    ` = <b>${((mean - 1) / (scale - 1)).toFixed(4)}</b>`;
  const help = `<details class="scorehelp"><summary>？ how this score works</summary>` +
    `The cross-family reviewer analyzes the answer against each criterion and ends with a ` +
    `single letter grade in &lt;score&gt; tags (A=1 … ${String.fromCharCode(64 + scale)}=${scale}; ` +
    `letters because multi-digit numbers split into several tokens on some tokenizers and ` +
    `corrupt the read). Instead of trusting that one letter, llm-super reads the top-5 token ` +
    `probabilities AT the letter position — the bars above, darker = higher letter — and takes ` +
    `the expectation E = Σ letter·P(letter): a continuous score that keeps the reviewer's ` +
    `uncertainty. Criteria are averaged and normalized to [0,1]; the turn passes at ` +
    `supervision.pass_threshold (default 0.70). A bar pinned at one letter with 100% means the ` +
    `reviewer had no doubt — many of those in a row is verifier saturation, worth noticing.</details>`;
  return `<div class="cap">⚙ score math (from the verifier's logged logprobs) — computed by llm-super</div>` +
    strips + `<div class="ev" style="text-align:left;margin-top:6px">${formula}</div>` + help;
}

// Inline output loading: find the upstream payload matching a timeline node
// (nth non-reviewer call to that model) and show the response text in place.
const outCache = new Map();
const ioLoaded = new Map();   // elId -> rendered html; survives re-renders
async function loadOut(ev, task, model, nth, kind, elId) {
  ev.preventDefault(); ev.stopPropagation();
  const el = document.getElementById(elId);
  if (!el) return;
  el.innerHTML = "loading…";
  if (!outCache.has(task))
    outCache.set(task, await fetch(`/admin/messages?task=${encodeURIComponent(task)}&n=300`)
      .then(r => r.json()).catch(() => []));
  const rows = outCache.get(task)
    .filter(r => r.kind === "upstream" && r.model === model)
    .sort((a, b) => (a.ts || 0) - (b.ts || 0))
    .map(r => r.payload || {});
  const lastMsg = p => (((p.request || {}).messages) || []).slice(-1)[0] || {};
  const lastTxt = p => { const c = lastMsg(p).content; return typeof c === "string" ? c : JSON.stringify(c); };
  const isReview = p => (lastTxt(p) || "").includes("expert reviewer verifying");
  const isMerge = p => (lastTxt(p) || "").includes("independent solutions to the same task")
    || (lastTxt(p) || "").includes("Assemble them into one");
  let pool = rows.filter(p => !isReview(p));
  pool = kind === "synthesis" ? pool.filter(isMerge) : pool.filter(p => !isMerge(p));
  const p = pool[nth] ?? pool[pool.length - 1];
  let html;
  if (!p) {
    html = sysBlk("payload lookup", "no recorded payload — pruned by retention, or a different server instance wrote it");
  } else {
    let outTxt = "(empty answer)";
    try { outTxt = p.response.choices[0].message.content || "(empty answer)"; } catch (e) {}
    html = mdlBlk(`input — prompt sent to ${esc(model)} (assembled by llm-super; may embed task, feedback, or candidate texts)`,
                  esc(lastTxt(p).slice(0, 4000)))
         + mdlBlk(`output — ${esc(model)}'s response, verbatim`, esc(outTxt.slice(0, 6000)));
  }
  ioLoaded.set(elId, html);
  el.innerHTML = html;
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
                                    (d.constraints||[]).length ? mdlBlk("checklist extracted by the utility model", (d.constraints||[]).map(c => "• " + esc(c)).join("\n")) : null);
    case "contract_skipped": return node(nid, "", e.ts, "☑ checklist skipped (user setting)");
    case "contract_failed":  return node(nid, "err", e.ts, "☑ checklist extraction failed (provider) — continuing without");
    case "plan":        return node(nid, "", e.ts, `⧉ plan — <b>${(d.units||[]).length ? (d.units||[]).length + " units" : "single pass"}</b>${cost}`,
                                    (d.units||[]).length ? mdlBlk("decomposition proposed by the planner model", (d.units||[]).map((u,i) => `${i+1}. ${esc(u)}`).join("\n")) : null);
    case "resume":      return node(nid, "ok", e.ts, `↻ resumed from checkpoint — units done: ${(d.completed||[]).map(x=>x+1).join(", ") || "none"} (prior spend $${(d.prior_spent||0).toFixed(4)})`);
    case "wave_start":  return node(nid, "", e.ts, `∥ wave ${d.wave} started — units ${(d.units||[]).join(", ")} in parallel`);
    case "execute":     return node(nid, "", e.ts, `⚙ attempt ${d.attempt||1} —${model}${toks}${cost}`,
                                    `<button class="msgbtn" onclick="loadOut(event,'${esc(task)}','${esc(e.model||"")}',${d._nth||0},'execute','io_${nid.replace(/[^a-zA-Z0-9]/g,"_")}')">load model output</button><div class="ioout" id="io_${nid.replace(/[^a-zA-Z0-9]/g,"_")}"></div>`);
    case "execute_code":return node(nid, d.ok ? "ok" : "err", e.ts,
                                    `⏵ sandbox ${d.ok ? "passed" : "FAILED"} — extracted code ran via ${esc(d.backend)} · exit ${d.exit_code} · ${d.duration_s}s${e.model ? " · " + esc(e.model) + "'s answer" : ""}`,
                                    [d.stdout ? sysBlk("sandbox stdout (what the extracted code printed when run)", esc(d.stdout)) : null,
                                     d.stderr ? sysBlk("sandbox stderr", esc(d.stderr)) : null,
                                     `<div class="cap">handed to the verifier as execution evidence</div>`]
                                      .filter(Boolean).join(""));
    case "fm_event":    return node(nid, "fm", e.ts,
                                    `⚠ <b>${esc(e.fm_id || d.fm_id)}</b>${d.scope === "session" ? " (cross-turn)" : ""} · confidence ${d.confidence ?? "?"}`,
                                    (() => { const i = FM_INFO[e.fm_id || d.fm_id];
                                      return (d.evidence ? sysBlk("monitor evidence (may quote model text)", esc(d.evidence)) : "")
                                        + (i ? sysBlk(`what ${esc(e.fm_id || d.fm_id)} (“${i[0]}”) means`, esc(i[1]) + "\n\nWhat the supervisor does: " + esc(i[2])) : "");
                                    })() || null);
    case "verify":      return node(nid, d.passed ? "ok" : "err", e.ts,
                                    `${d.passed ? "✓" : "✗"} verified by${model} — score <b>${(d.score ?? 0).toFixed(2)}</b>${d.tier && d.tier !== "standard" ? " · " + esc(d.tier) + " tier" : ""}${d.stage ? " ("+esc(d.stage)+")" : ""}${cost}`,
                                    scoreMath(d));
    case "verify_error":return node(nid, "err", e.ts, `✗ verification unavailable — ${esc(d.error||"")}`);
    case "executor_error":    return node(nid, "err", e.ts, `⚙ executor failed —${model}`, esc(d.error||""));
    case "executor_fallback": return node(nid, "", e.ts, `⇄ failed over to <b>${esc(e.model)}</b>`);
    case "budget_stop": return node(nid, "err", e.ts, `$ budget stop — $${(d.spent||0).toFixed(3)} of $${(d.budget||0).toFixed(2)}`);
    case "synthesis":   return node(nid, "", e.ts,
                                    `Σ merge/assembly call —${model}${toks}${cost} · candidate outputs (with reviewer scores) become the prompt; the result must out-score the best input to win`,
                                    `<button class="msgbtn" onclick="loadOut(event,'${esc(task)}','${esc(e.model||"")}',${d._nth||0},'synthesis','io_${nid.replace(/[^a-zA-Z0-9]/g,"_")}')">load merged output</button><div class="ioout" id="io_${nid.replace(/[^a-zA-Z0-9]/g,"_")}"></div>`);
    case "ensemble_start": return node(nid, "", e.ts,
                                    `⑂ <b>${esc(d.mode||"ensemble")}</b> strategy — ${(d.models||[]).length} candidates in parallel: ${(d.models||[]).map(esc).join(", ")}${d.cutoff ? ` · short-circuit cutoff ${d.cutoff}` : ""} (indented events below belong to this fan-out)`);
    case "ensemble_candidate": return node(nid, "", e.ts,
                                    `◇ candidate verified —${model} · score <b>${(d.score ?? 0).toFixed(2)}</b> by ${esc(d.verifier||"?")}${cost}`,
                                    scoreMath(d));
    case "short_circuit": return node(nid, "ok", e.ts,
                                    `⚡ short-circuit —${model} reached cutoff ${d.cutoff} · ${d.cancelled} pending candidate(s) cancelled`);
    case "ensemble_winner": return node(nid, "ok", e.ts,
                                    `★ fan-out winner — <b>${esc(d.model || e.model || "")}</b> · score ${(d.score ?? 0).toFixed(2)} (${esc(d.mode||"")})`,
                                    d.candidates ? sysBlk("candidate scoreboard", Object.entries(d.candidates).map(([m, sc]) => `${m}: ${sc}`).join("\n")) : null);
    case "ensemble_fusion_rejected": return node(nid, "err", e.ts,
                                    `✂ merge rejected — scored ${(d.fusion_score ?? 0).toFixed(2)}, below best candidate ${(d.score ?? 0).toFixed(2)} — best candidate returned instead`);
    case "ensemble_degraded": return node(nid, "err", e.ts, `⑂ fan-out degraded to single supervised attempt — ${esc(d.reason||"")}`);
    case "referee":     return node(nid, d.strategy === "ask_user" ? "err" : "", e.ts,
                                    `↻ referee after failed attempt ${d.attempt} — decision: <b>${esc((d.strategy||"").replace(/_/g, " "))}</b>${d.target ? " → <b>" + esc(d.target) + "</b>" : ""} · ${d.source === "rule" ? "rule (free retries left)" : "LLM referee"}${cost}`,
                                    d.rationale ? mdlBlk("referee rationale (model-generated)", esc(d.rationale)) : null);
    case "gate":        return node(nid, "", e.ts, `🚪 new-conversation gate — warned, nothing spent`, esc(d.preview || "") || null);
    case "tool_step":   return node(nid, "", e.ts, `🔧 agent tool step —${model} · ${d.n_calls||1} call(s)${cost}`);
    case "unit_done":   return null; // rendered as the unit group summary
    case "turn_end": case "agent_end":
      return node(nid, d.escalated ? "err" : "ok", e.ts,
                  `${d.escalated ? "⛔" : "✓"} finished${d.score != null ? ` — score <b>${Number(d.score).toFixed(2)}</b>` : ""}${d.spent != null ? ` · spent $${d.spent.toFixed(4)}` : ""}`,
                  d.answer_preview ? mdlBlk("answer preview (model output)", esc(d.answer_preview)) : null);
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
      ? (escalated ? `<span class="badge crit" style="cursor:pointer"
             title="NEEDS INPUT: the supervisor stopped WITHOUT a verified answer — its reason/question is the ⛔ line inside this card (and the red result node in the graph; click this badge to jump there). To resolve: reply in this conversation (!attach it from your client), adjust the request, or !rewind and resend."
             onclick="focusGraph(event, '${esc(task)}')">⛔ needs input</span>`
                   : `<span class="badge ok">✓ done</span>`)
      : (agentic && !verifies.length
         ? `<span class="badge">🔧 agent tool step</span>`
         : `<span class="badge">… running</span>`);

    // Annotate per-model call ordinals so inline "load output" can find the
    // matching upstream payload later.
    const ord = {};
    for (const e of evs) {
      if (e.kind === "execute" || e.kind === "synthesis") {
        const key = e.kind + ":" + (e.model || "");
        e.data = e.data || {};
        e.data._nth = ord[key] = (ord[key] ?? -1) + 1;
      }
    }
    // Build the timeline: unit-tagged events fold into per-unit groups,
    // inserted at the position of the unit's first event; events inside an
    // ensemble fan-out are indented under their ensemble_start.
    const rows = [];
    const unitRendered = new Set();
    let inEns = false;
    evs.forEach((e, idx) => {
      if (e.kind === "ensemble_start") inEns = true;
      const ensChild = inEns && (
        ["execute", "execute_code", "ensemble_candidate", "short_circuit",
         "synthesis", "fm_event", "executor_error", "executor_fallback",
         "verify_error"].includes(e.kind)
        || (e.kind === "verify" && e.data?.stage === "ensemble-fusion"));
      if (e.kind === "ensemble_winner" || e.kind === "ensemble_degraded") inEns = false;
      const u = e.data?.unit;
      if (u == null || e.kind === "wave_start") {
        let r = nodeFor(task, e, idx);
        if (r && ensChild) r = r.replace('class="node', 'class="node sub');
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
    cards.push(`<details class="turn" data-nid="${tnid}"${open ? " open" : ""} style="--task-hue:${hueFor(task)}">
      <summary>
        ${status}
        <span class="goal" title="${esc(preview || "")}">${esc((preview || "(no prompt recorded)").slice(0, 150))}</span>
        ${scorebar(lastScore)}
        <span class="gcost">$${cost.toFixed(4)}</span>
        ${fms.map(fmBadge).join(" ")}
        <span class="gid">${esc(task)}</span>
        <button class="msgbtn" onclick="toggleMessages(event, '${esc(task)}')">messages</button>
        <button class="msgbtn" onclick="copyRequest(event, '${esc(task)}')"
          title="copy the exact request text — for LOCATING this message in your client (edit/rewind). To continue the conversation, prefer !attach <session-prefix> from the client: no re-run, context preserved. Resending this text re-runs the turn (completed units resume from checkpoint; a single turn's repair progress does not carry over).">⧉ request</button>
        <button class="msgbtn" onclick="focusGraph(event, '${esc(task)}')"
          title="show this turn in the pipeline graph">⛓ graph</button>
      </summary>
      <div class="tl">${rows.join("")}
        ${escalated ? `<div class="esc"><div class="cap">⛔ needs input — the supervisor stopped without a verified answer. Reply in this conversation to resolve:</div>${esc(escalated)}</div>` : ""}
      </div>
      <div class="msgview" id="msg-${esc(task)}" style="display:none"></div>
    </details>`);
  }
  $("#tasks").innerHTML = cards.join("") ||
    `<div class="card" style="color:var(--muted)">no supervised turns yet — point a client at /v1 with model "super"</div>`;
  // restore inline model-output loads wiped by the re-render
  for (const [elId, html] of ioLoaded) {
    const el = document.getElementById(elId);
    if (el) el.innerHTML = html;
  }
  // restore message views wiped by the re-render
  for (const task of msgShown) {
    const el = document.getElementById("msg-" + task);
    if (el && msgCache.has(task)) {
      el.style.display = "block";
      el.innerHTML = msgCache.get(task);
    }
  }
}

// ---- pipeline graph: live turn DAG built from trace events ----
// Reconciled in place every refresh: existing nodes transition their state
// via CSS, new nodes animate in, the newest stage of an unfinished turn
// pulses. No re-render flicker.
const gSel = {task: null};
const gDone = new Set();   // node ids already rendered for gSel.task

function graphModel(evs) {
  const N = [], E = [];
  const add = (id, label, sub, state, col, row) =>
    N.push({id, label, sub, state, col, row});
  const done = evs.find(e => e.kind === "turn_end" || e.kind === "agent_end");
  const dd = done ? done.data : {};
  const score = s => s == null ? "" : Number(s).toFixed(2);

  const startEv = evs.find(e => e.kind === "turn_start" || e.kind === "agent_turn");
  add("start", "goal", (startEv?.data?.task_preview || "").slice(0, 24),
      "ok", 0, 0);
  const c = evs.find(e =>
    ["contract", "contract_skipped", "contract_failed"].includes(e.kind));
  add("contract", "contract",
      !c ? "…" : c.kind === "contract"
        ? `${(c.data.constraints || []).length} constraints · ${c.data.difficulty || ""}`
        : c.kind === "contract_skipped" ? "skipped" : "failed",
      !c ? (done ? "ok" : "running")
         : c.kind === "contract_failed" ? "err" : "ok", 1, 0);
  E.push(["start", "contract"]);

  const ens = evs.find(e => e.kind === "ensemble_start");
  const plan = evs.find(e => e.kind === "plan" && (e.data.units || []).length);

  if (ens) {                                   // best / union / fuse
    const models = ens.data.models || [];
    const mode = ens.data.mode || "fuse";
    const sc = evs.find(e => e.kind === "short_circuit");
    const winner = evs.find(e => e.kind === "ensemble_winner");
    const midRow = (models.length - 1) / 2;
    models.forEach((m, i) => {
      const ex = evs.find(e => e.kind === "execute" && e.model === m);
      const code = evs.find(e => e.kind === "execute_code" && e.model === m);
      const cand = evs.find(e => e.kind === "ensemble_candidate" && e.model === m);
      let state, sub;
      if (cand) { state = "ok"; sub = `score ${score(cand.data.score)}`; }
      else if (sc || winner || done) { state = "cancelled"; sub = "cancelled"; }
      else if (ex) { state = "running"; sub = "verifying…"; }
      else { state = "running"; sub = "generating…"; }
      if (code) sub += code.data.ok ? " · ▶✓" : " · ▶✗";
      add("cand:" + m, m, sub, state, 2, i);
      E.push(["contract", "cand:" + m]);
    });
    const syn = evs.find(e => e.kind === "synthesis");
    const fver = evs.find(e => e.kind === "verify" && e.data.stage === "ensemble-fusion");
    const rejected = evs.find(e => e.kind === "ensemble_fusion_rejected");
    let hasMerge = mode !== "best" && !sc;
    if (hasMerge) {
      // the synthesis event lands only AFTER the merge call returns, so the
      // merge is "running" from the moment every candidate has verified
      const candsDone = models.every(m =>
        evs.some(e => e.kind === "ensemble_candidate" && e.model === m));
      add("merge", mode === "union" ? "union merge" : "fusion",
          fver ? `score ${score(fver.data.score)}${rejected ? " · rejected" : ""}`
               : syn ? "verifying…" : candsDone && !done ? "merging…"
               : done ? "" : "…",
          fver ? (rejected ? "err" : "ok")
               : done ? "cancelled"
               : (syn || candsDone) ? "running" : "pending",
          3, midRow);
      models.forEach(m => E.push(["cand:" + m, "merge"]));
    }
    const wsub = winner
      ? `${winner.model}${winner.data.score != null ? " · " + score(winner.data.score) : ""}` : "";
    add("end", done ? (dd.escalated ? "⛔ result" : "✓ result") : "result",
        done ? `${wsub}${dd.spent != null ? ` · $${dd.spent.toFixed(3)}` : ""}` : wsub || "…",
        done ? (dd.escalated ? "err" : "ok") : "pending",
        hasMerge ? 4 : 3, sc ? 0 : midRow);
    if (sc) E.push(["cand:" + sc.model, "end"]);
    else if (hasMerge) E.push(["merge", "end"]);
    else models.forEach(m => E.push(["cand:" + m, "end"]));
  } else if (plan) {                           // decomposed turn: unit DAG
    const units = plan.data.units || [];
    add("plan", "plan", `${units.length} units`, "ok", 2, 0);
    E.push(["contract", "plan"]);
    const midRow = (units.length - 1) / 2;
    units.forEach((u, i) => {
      const uev = evs.filter(e => e.data?.unit === i + 1);
      const uver = uev.filter(e => e.kind === "verify").pop();
      add("unit:" + i, `unit ${i + 1}`,
          uver ? `score ${score(uver.data.score)}` : String(u).slice(0, 24),
          uver ? (uver.data.passed ? "ok" : "err")
               : uev.length ? "running" : done ? "cancelled" : "pending",
          3, i);
      E.push(["plan", "unit:" + i]);
    });
    const sver = evs.filter(e => e.kind === "verify" && e.data.stage === "synthesis").pop();
    const syn = evs.find(e => e.kind === "synthesis" && e.data?.unit == null);
    add("synth", "synthesis",
        sver ? `score ${score(sver.data.score)}` : syn ? "verifying…" : "…",
        sver ? "ok" : syn ? "running" : done ? "cancelled" : "pending",
        4, midRow);
    units.forEach((u, i) => E.push(["unit:" + i, "synth"]));
    add("end", done ? (dd.escalated ? "⛔ result" : "✓ result") : "result",
        done ? `$${(dd.spent ?? 0).toFixed(3)}` : "…",
        done ? (dd.escalated ? "err" : "ok") : "pending", 5, midRow);
    E.push(["synth", "end"]);
  } else {                                     // single path: attempt chain
    const exs = evs.filter(e => e.kind === "execute");
    const vers = evs.filter(e => e.kind === "verify" && !e.data.stage);
    const codes = evs.filter(e => e.kind === "execute_code");
    const referee = evs.find(e => e.kind === "referee");
    const n = Math.max(exs.length, 1);
    for (let i = 0; i < n; i++) {
      const ex = exs[i], ver = vers[i], code = codes[i];
      let sub = ver ? `score ${score(ver.data.score)}`
                    : ex ? "verifying…" : "generating…";
      if (code) sub += code.data.ok ? " · ▶✓" : " · ▶✗";
      add("att:" + i, (ex?.model || "executor") + (i ? ` · try ${i + 1}` : ""),
          sub,
          ver ? (ver.data.passed ? "ok" : "err") : done ? "ok" : "running",
          2 + i, 0);
      E.push([i ? "att:" + (i - 1) : "contract", "att:" + i]);
    }
    if (referee) {
      add("referee", "referee",
          (referee.data.strategy || "").replace("_", " "), "ok", 2 + n, 0.9);
      E.push(["att:" + (n - 1), "referee"]);
    }
    add("end", done ? (dd.escalated ? "⛔ result" : "✓ result") : "result",
        done ? `score ${score(dd.score)} · $${(dd.spent ?? 0).toFixed(3)}` : "…",
        done ? (dd.escalated ? "err" : "ok") : "pending", 2 + n + (referee ? 1 : 0), 0);
    E.push(["att:" + (n - 1), "end"]);
  }
  return {nodes: N, edges: E};
}

const GW = 168, GH = 46, GX = 46, GY = 14, GPAD = 8;
const svgNS = "http://www.w3.org/2000/svg";
function gpos(n) {
  return [GPAD + n.col * (GW + GX), GPAD + n.row * (GH + GY)];
}
function gtrim(s, n) { s = String(s ?? ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; }

function renderGraph(events) {
  // candidate tasks, newest first, honoring the sidebar selection
  const tasks = [], seen = new Set();
  for (const e of events) {
    if (e.task === "-" || seen.has(e.task)) continue;
    if (sel.session && e.session !== sel.session) continue;
    seen.add(e.task);
    tasks.push(e.task);
    if (tasks.length >= 10) break;
  }
  const selEl = $("#gTaskSel");
  const opts = tasks.map(t => {
    const p = events.find(e => e.task === t && e.data?.task_preview)?.data.task_preview;
    return `<option value="${esc(t)}">${esc(t)} — ${esc((p || "").slice(0, 40))}</option>`;
  }).join("");
  if (selEl.innerHTML !== opts) selEl.innerHTML = opts;
  if ($("#gFollow").checked || !gSel.task || !tasks.includes(gSel.task))
    gSel.task = tasks[0] || null;
  selEl.value = gSel.task || "";
  const box = $("#graph");
  if (!gSel.task) {
    box.innerHTML = `<div style="color:var(--muted);font-size:12px">no turns yet</div>`;
    gDone.clear();
    return;
  }
  document.querySelector(".pipeline").style.setProperty("--task-hue", hueFor(gSel.task));
  const evs = events.filter(e => e.task === gSel.task).sort((a, b) => a.ts - b.ts);
  const model = graphModel(evs);
  const running = !evs.some(e => e.kind === "turn_end" || e.kind === "agent_end");
  $("#gStatus").innerHTML = `<span class="badge${running ? "" : " ok"}">` +
    `${running ? "● live" : "✓ complete"}</span>`;

  let svg = box.querySelector("svg");
  if (svg && svg.dataset.task !== gSel.task) { box.innerHTML = ""; svg = null; gDone.clear(); }
  const cols = Math.max(...model.nodes.map(n => n.col)) + 1;
  const rows = Math.max(...model.nodes.map(n => n.row)) + 1;
  const w = GPAD * 2 + cols * GW + (cols - 1) * GX;
  const h = GPAD * 2 + rows * GH + (rows - 1) * GY + 8;
  if (!svg) {
    svg = document.createElementNS(svgNS, "svg");
    svg.dataset.task = gSel.task;
    svg.innerHTML = `<g class="gedges"></g><g class="gnodes"></g>`;
    box.appendChild(svg);
  }
  // Fit-to-width: the graph scales down to the panel instead of forcing a
  // horizontal scroll; small graphs stay at natural size (maxWidth).
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.style.width = "100%";
  svg.style.maxWidth = w + "px";
  svg.style.height = "auto";

  const byId = new Map(model.nodes.map(n => [n.id, n]));
  const eg = svg.querySelector(".gedges");
  for (const [a, b] of model.edges) {
    const na = byId.get(a), nb = byId.get(b);
    if (!na || !nb) continue;
    const [ax, ay] = gpos(na), [bx, by] = gpos(nb);
    const x1 = ax + GW, y1 = ay + GH / 2, x2 = bx, y2 = by + GH / 2;
    const mx = (x1 + x2) / 2;
    const d = `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
    const cls = "gedge" + (nb.state === "running" ? " active"
      : (na.state === "ok" && (nb.state === "ok" || nb.state === "err")) ? " ok" : "");
    const id = `ge:${a}>${b}`;
    let p = svg.getElementById(id);
    if (!p) {
      p = document.createElementNS(svgNS, "path");
      p.id = id; eg.appendChild(p);
    }
    if (p.getAttribute("d") !== d) p.setAttribute("d", d);
    if (p.getAttribute("class") !== cls) p.setAttribute("class", cls);
  }
  const ng = svg.querySelector(".gnodes");
  for (const n of model.nodes) {
    const [x, y] = gpos(n);
    const id = `gn:${n.id}`;
    let g = svg.getElementById(id);
    if (!g) {
      g = document.createElementNS(svgNS, "g");
      g.id = id;
      g.innerHTML = `<rect width="${GW}" height="${GH}" rx="8"></rect>` +
        `<text x="10" y="19" class="glabel"></text>` +
        `<text x="10" y="35" class="gsub"></text>`;
      ng.appendChild(g);
      g.setAttribute("class", `gnode fresh ${n.state}`);
      setTimeout(() => g.classList.remove("fresh"), 600);
    } else {
      const cls = `gnode ${n.state}`;
      if (g.getAttribute("class") !== cls && !g.classList.contains("fresh"))
        g.setAttribute("class", cls);
    }
    g.setAttribute("transform", `translate(${x},${y})`);
    const [lab, sub] = [gtrim(n.label, 24), gtrim(n.sub, 30)];
    const tl = g.querySelector(".glabel"), ts = g.querySelector(".gsub");
    if (tl.textContent !== lab) tl.textContent = lab;
    if (ts.textContent !== sub) ts.textContent = sub;
  }
}

function focusGraph(e, task) {
  e.stopPropagation(); e.preventDefault();
  $("#gFollow").checked = false;
  gSel.task = task;
  renderGraph(lastEvents);
  document.querySelector(".pipeline").scrollIntoView({behavior: "smooth", block: "center"});
  const svg = $("#graph").querySelector("svg");
  if (svg) { svg.classList.add("flash"); setTimeout(() => svg.classList.remove("flash"), 2600); }
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
          <span class="cdot" style="background:${hueFor(s.session)}"></span>
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
  routingData = r;
  const chip = (m, name, i, len) =>
    `<span class="badge" title="${esc(r.models[name] ? r.models[name].provider : "?")}">` +
    `${esc(name)} <small>${esc(r.models[name] ? r.models[name].provider : "?")}</small>` +
    (i > 1 ? ` <a href="#" onclick="chainMove('${m}',${i - 1},-1);return false" title="try earlier">◀</a>` : "") +
    (i < len - 1 ? ` <a href="#" onclick="chainMove('${m}',${i - 1},1);return false" title="try later">▶</a>` : "") +
    ` <a href="#" onclick="chainDrop('${m}',${i - 1});return false" title="remove">×</a></span>`;
  const chainRows = names.map(m => {
    const fb = r.models[m].fallbacks || [];
    const chain = [m, ...fb];
    const addable = names.filter(n => n !== m && !fb.includes(n));
    return `<div class="fname">${esc(m)}</div><div class="fval">` +
      `<span class="badge" title="primary — always tried first">` +
      `${esc(m)} <small>${esc(r.models[m].provider)}</small></span>` +
      chain.slice(1).map((n, i) => " → " + chip(m, n, i + 1, chain.length)).join("") +
      ` <select onchange="chainAdd('${m}', this.value); this.value=''">` +
      `<option value="">+ fallback…</option>` +
      addable.map(n => `<option>${esc(n)}</option>`).join("") +
      `</select></div><span></span><span></span>`;
  }).join("");
  $("#routing").innerHTML = `<div class="settings-grid">` +
    Object.keys(ROUTING_LABELS).map(k =>
      `<div class="fname">${ROUTING_LABELS[k]}</div><div class="fval">${controls[k]}</div><span></span><span></span>`
    ).join("") + `</div>` +
    `<details id="chainsBox"${chainsOpen ? " open" : ""}
       ontoggle="chainsOpen = this.open">
      <summary style="cursor:pointer;color:var(--muted);margin-top:8px">
        provider rotation — per-model failover order (first entry always runs first)</summary>
      <div class="settings-grid" style="margin-top:6px">${chainRows}</div>
    </details>`;
}
let routingData = null;
let chainsOpen = false;
async function chainSet(model, chain) {
  if (document.activeElement) document.activeElement.blur();
  const resp = await fetch("/admin/routing", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({patch: {fallbacks: {[model]: chain}}})});
  if (!resp.ok) flash("chain: ✗ " + ((await resp.json()).error || resp.status));
  else flash("rotation for " + model + " updated (runtime only)");
  renderRouting(await fetch("/admin/routing").then(r => r.json()));
}
function chainMove(model, i, d) {
  const c = (routingData.models[model].fallbacks || []).slice();
  const j = i + d;
  if (j < 0 || j >= c.length) return;
  [c[i], c[j]] = [c[j], c[i]];
  chainSet(model, c);
}
function chainDrop(model, i) {
  const c = (routingData.models[model].fallbacks || []).slice();
  c.splice(i, 1);
  chainSet(model, c);
}
function chainAdd(model, name) {
  if (!name) return;
  chainSet(model, (routingData.models[model].fallbacks || []).concat([name]));
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
    // Scroll anchoring: live growth above the viewport (graph rows, new
    // timeline events) must not shove what the user is reading. Anchor on
    // the section nearest the viewport top (section shells are stable
    // across re-renders) and compensate any height delta afterwards.
    const anchor = [...document.querySelectorAll("main section, .layout")]
      .filter(el => el.getBoundingClientRect().top <= 120)
      .pop();
    const anchorTop = anchor ? anchor.getBoundingClientRect().top : null;
    renderTasks(evs);
    renderGraph(evs);
    if (anchor && anchorTop !== null) {
      const delta = anchor.getBoundingClientRect().top - anchorTop;
      if (Math.abs(delta) > 1) window.scrollBy(0, delta);
    }
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
