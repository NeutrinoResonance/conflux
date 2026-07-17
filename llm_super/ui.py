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
main { max-width: 1100px; margin: 0 auto; padding: 20px 16px 60px; }
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
.card .head { display: flex; flex-wrap: wrap; gap: 10px; align-items: baseline; }
.card .head .id { font-family: ui-monospace, monospace; font-size: 12px; color: var(--muted); }
.scorebar { display: inline-flex; align-items: center; gap: 6px; }
.scorebar .track { width: 90px; height: 6px; border-radius: 4px;
                   background: var(--seq-track); overflow: hidden; }
.scorebar .fill { display: block; height: 100%; border-radius: 4px; background: var(--seq); }
.scorebar .n { font-variant-numeric: tabular-nums; font-size: 12px; color: var(--ink-2); }
.steps { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; }
.esc { margin-top: 8px; font-size: 13px; color: var(--ink); }
.esc::before { content: "⛔ "; }
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
</style>
</head>
<body>
<main>
  <h1>llm-super</h1>
  <div class="sub">control plane — <span id="clock">…</span> · auto-refresh 2s</div>
  <div class="paused-banner" id="pausedBanner">Supervision is paused — new turns will not execute until resumed.</div>

  <div class="tiles" id="tiles"></div>

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
    </div>
  </section>

  <section>
    <h2>Tasks</h2>
    <div id="tasks"></div>
  </section>

  <section>
    <h2>Model outcomes</h2>
    <div id="stats"></div>
  </section>

  <section>
    <h2>Event feed</h2>
    <div id="events"></div>
  </section>
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

$("#pauseBtn").onclick = () => post("paused", $("#pauseBtn").dataset.paused !== "true");
$("#executorSel").onchange = e => post("executor", e.target.value);
$("#budgetInp").onchange = e => post("budget", e.target.value);
$("#checklistSel").onchange = e => post("checklist", e.target.value);
$("#sandboxSel").onchange = e => post("sandbox", e.target.value);
$("#planSel").onchange = e => post("plan", e.target.value);

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
  $("#tiles").innerHTML =
    tile("state", paused ? "⏸ paused" : "▶ running") +
    tile("executor", esc(st.forced_executor || "auto")) +
    tile("budget / task", st.budget_usd != null ? "$" + Number(st.budget_usd).toFixed(2) : "default") +
    tile("spent (recent)", "$" + (st.recent_spend ?? 0).toFixed(3)) +
    tile("checklist", esc(st.checklist || "on")) +
    tile("sandbox", esc(st.sandbox || "auto")) +
    tile("plan", esc(st.plan || "auto"));
}

function renderTasks(events) {
  const byTask = new Map();
  for (const e of events) {
    if (e.task === "-") continue;
    if (!byTask.has(e.task)) byTask.set(e.task, []);
    byTask.get(e.task).push(e);
  }
  const cards = [];
  let n = 0;
  for (const [task, evs] of byTask) {
    if (++n > 8) break;
    evs.sort((a, b) => a.ts - b.ts);
    const end = evs.find(e => e.kind === "turn_end");
    const verifies = evs.filter(e => e.kind === "verify");
    const lastScore = verifies.length ? verifies[verifies.length-1].data?.score : null;
    const cost = evs.reduce((s, e) => s + (e.cost_usd || 0), 0);
    const fms = [...new Set(evs.filter(e => e.kind === "fm_event").map(e => e.fm_id || e.data?.fm_id))];
    const escalated = end?.data?.escalated;
    const sessionNotes = evs.filter(e => e.kind === "fm_event" && e.data?.scope === "session");
    const units = end?.data?.units;
    const steps = evs.map(e =>
      `<span class="badge ${e.kind === "fm_event" ? "fm" : ""}">${esc(e.kind)}${
        e.model ? " · " + esc(e.model) : ""}</span>`).join("");
    const status = end
      ? (escalated ? `<span class="badge crit">⛔ needs input</span>`
                   : `<span class="badge ok">✓ done</span>`)
      : `<span class="badge">… running</span>`;
    cards.push(`<div class="card">
      <div class="head">
        <span class="id">${esc(task)}</span> ${status}
        ${units ? `<span class="badge">${units} units</span>` : ""}
        ${scorebar(lastScore)}
        <span class="n" style="color:var(--muted);font-size:12px">$${cost.toFixed(4)}</span>
        ${fms.map(fmBadge).join(" ")}
      </div>
      ${sessionNotes.map(e => `<div class="note">${esc(e.data?.evidence || "")}</div>`).join("")}
      ${escalated ? `<div class="esc">${esc(escalated)}</div>` : ""}
      <div class="steps">${steps}</div>
    </div>`);
  }
  $("#tasks").innerHTML = cards.join("") ||
    `<div class="card" style="color:var(--muted)">no supervised turns yet — point a client at /v1 with model "super"</div>`;
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

async function refresh() {
  try {
    const [st, evs, stats] = await Promise.all([
      fetch("/admin/status").then(r => r.json()),
      fetch("/admin/events?n=200").then(r => r.json()),
      fetch("/admin/stats").then(r => r.json()),
    ]);
    renderStatus(st, st.models || []);
    renderTasks(evs);
    renderStats(stats);
    renderEvents(evs);
    $("#clock").textContent = new Date().toLocaleTimeString();
  } catch (e) {
    $("#clock").textContent = "proxy unreachable";
  }
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""
