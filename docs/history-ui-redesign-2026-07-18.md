# History UI redesign — evidence-backed specification (2026-07-18)

Status: **proposal only**. This document does not change the running UI. It
defines the smallest architecture that makes long agent histories readable,
auditable, and performant.

Companion evidence:

- [Forensic NetBSD/AArch64 endeavor report](./netbsd-arm64-endeavor-forensic-report-2026-07-18.md)
- [Exact agent tool-call ledger](./netbsd-arm64-agent-tool-ledger-2026-07-18.md)
- [Trace acceptance queries](./agentic-trace-audit.sql)

## 1. Decision

The history experience should stop treating every transport request as a
top-level human task and stop rendering cumulative raw transcripts inline.

The default history unit must be an **endeavor**: one user objective across
credential retries, interrupted clients, proxy restarts, recovery prompts,
model repairs, long-running jobs, and final acceptance. Within an endeavor,
the UI should show only state changes, errors, recovery chains, evidence, and
final outcomes by default. Polls, repeated prompt prefixes, duplicate
client/proxy/provider copies, logprobs, and raw payloads remain available but
collapsed.

The navigation should be split into four top-level views:

1. **Live** — current controls, active work, blockers, and latest state changes.
2. **History** — endeavors, runs/recovery epochs, phases, and steps.
3. **Analytics** — cost, latency, reliability, model/tool aggregates.
4. **Settings** — routing, retention, projects, and control defaults.

This removes unrelated control-plane content from the reading path without
removing any capability.

## 2. What was inspected

### MCP browser inspection

Chrome DevTools MCP was used against `http://127.0.0.1:8055/`. Its first
connection failed because an abandoned MCP-owned Chrome held
`~/.cache/chrome-devtools-mcp/chrome-profile`. After resolving and terminating
only that exact MCP bridge/Chrome process tree, Chrome DevTools MCP connected.
The llm-super listener and normal user browser were not touched.

Through MCP we:

- captured the page's accessibility tree;
- captured 1440×1000 screenshots;
- selected conversation `a7ac14a9f48f`;
- queried the live admin API from the page;
- opened the messages for task `517f1024`;
- measured the rendered DOM and scroll height.

The separate Browser Tools MCP was unavailable because it had no browser
connector. The measurements below come from the successful Chrome DevTools MCP
session, direct read-only API queries, and `traces.db`.

### Visible result

The dashboard is one long page. Status, conversations, steering, routing,
graph, and tasks compete for the same vertical flow; Tasks begins below the
first viewport. Extraction, retention, analytics, and the event feed continue
farther down.

For `a7ac14a9f48f`:

- API: 138 events, 69 task IDs, 69 `agent_turn`, 69 `tool_step`;
- UI: only 10 task cards and 40 event rows were visible;
- the missing 59 task cards had no hidden-count or pagination indication.

For late task `517f1024`, opening “messages” created:

| Measurement | Result |
|---|---:|
| exchange blocks | 3 |
| `pre` nodes | 142 |
| visible characters | 149,989 |
| HTML characters | 157,845 |
| message-view height | 29,720 px |
| full-page height | about 34,605 px |
| viewport height | 1,000 px |

The first screen was dominated by the repeated Hermes system prompt, followed
by cumulative message/tool history. This is why cosmetic spacing alone cannot
solve the problem.

## 3. Root causes

### 3.1 Wrong hierarchy

The current implicit hierarchy is:

```text
project -> session -> request-derived task card -> raw event/message
```

The user actually reasons about:

```text
project
  -> endeavor / objective
    -> run or recovery epoch
      -> operational phase
        -> logical model/tool step
          -> raw event or exchange
```

One NetBSD endeavor was fragmented into 8 sessions, 114 task IDs, 245 events,
and 356 exchanges. There are zero aliases, checkpoints, or edit records joining
those sessions.

### 3.2 Transport turns masquerade as work units

`run_tool_turn()` generates a new UUID for every HTTP tool-loop request and
repeats the same task preview. One user objective therefore appears as 69
separate tasks in `a7ac14a9f48f`. Each card says only “agent tool step” because
the event records call count but not durable step/run/phase identity.

### 3.3 Cumulative payloads are rendered as transcripts

Each Hermes request contains the full message prefix. Across the endeavor:

| Measure | Cumulative requests | Terminal snapshots | Repeated prefix |
|---|---:|---:|---:|
| message instances | 5,727 | 225 | 5,502 / 96.1% |
| message JSON bytes | 7,597,192 | 300,594 | 7,296,598 / 96.0% |

For 106 tool-loop tasks, client messages/tools are duplicated again in the
upstream request, and the returned client response is JSON-identical to the
upstream response. The UI presents boundary copies instead of one logical
exchange.

### 3.4 Polling is first-class noise

After four setup actions, `a7ac14a9f48f` contains 65 polling/wait decisions:

- 13 delayed polls;
- 4 process waits;
- 28 status checks;
- 20 log tails.

Median gap was 12.021 seconds; 53 of 64 gaps were at most 15 seconds. Polling
consumed 2,164,450 input tokens and `$0.613652`, 99.1% of that session's input.
The same locale warning appears 128 times across 82 tool results.

### 3.5 Raw diagnostics overwhelm useful content

Raw upstream rows contain 1,997,915 bytes of `logprobs`. The largest exchange
is 260,571 bytes, of which 209,344 bytes are logprobs. These fields are useful
for forensic debugging, not normal history reading.

### 3.6 Silent caps and global polling hide truth

Relevant current behavior:

- `renderTasks()` stops after 10 cards without showing how many were omitted;
- `/admin/events?n=300` is global and the browser filters after download;
- `toggleMessages()` fetches up to 200 full exchanges and renders all messages;
- eight endpoints are refetched every two seconds;
- the page re-renders large sections even when nothing material changed;
- task rendering skips `task='-'`, hiding control/restart milestones;
- `turns.response` truncates at 2,000 characters, so valid JSON may become an
  invalid prefix.

The eight polling endpoints transfer about 108 KB every two seconds in the
observed database state, roughly 194 MB/hour uncompressed for an idle open tab.

## 4. Proposed information architecture

### History list

Default to one row per endeavor, newest first:

```text
✓ NetBSD ARM64 acceptance
  1h 46m · 8 sessions · 114 steps · 6 provider errors, all recovered
  2.72M input · 76.6K output · $0.814018
  x86_64 GCE host -> NetBSD evbarm/aarch64 -> QEMU TCG
```

Each row shows:

- terminal state: active, paused, blocked, failed, interrupted, or accepted;
- objective/title;
- start, last activity, duration;
- run/session and step counts;
- unrecovered and recovered error counts;
- cost and token totals;
- target/resource badges;
- last meaningful state change;
- owner/project/tags.

Do not show prompt content or raw model text until the row is opened.

### Endeavor detail

Use five tabs:

1. **Overview**
   - objective and acceptance contract;
   - current/final state;
   - target boundary;
   - phase progress;
   - outcome/evidence;
   - cost/time summary;
   - unresolved deficiencies.
2. **Timeline**
   - state-changing steps, grouped recovery chains, restart markers;
   - polls collapsed by default;
   - wall-clock gaps represented as time, not blank vertical space.
3. **Prompts & commands**
   - exact initial/recovery prompts;
   - logical tool commands and results;
   - duplicate transport copies folded;
   - copy/export actions.
4. **Evidence**
   - artifact paths, hashes, exit files, validation markers;
   - verifier decisions and target corroboration;
   - provenance of each claim.
5. **Raw**
   - paginated events/exchanges;
   - explicit opt-in to messages, tools, logprobs, reasoning, and provider
     envelopes;
   - export without mounting all payloads into the DOM.

### Suggested desktop layout

```text
┌ History ─ search ─ filters ─ saved view ─ export ┐
│ Endeavor header: status · duration · cost · target│
├ Overview | Timeline | Prompts & commands | Evidence | Raw ┤
│ Phase rail              │ Selected phase/run summary      │
│ ✓ provision             │ Durable release                 │
│ ✓ cross-tools           │ 69 cycles · 69 tools            │
│ ✓ kernel                │ 65 polls collapsed              │
│ ✓ release               │ 1 interruption · recovered      │
│ ✓ image                 │ $0.619384 · 25m trace window     │
│ ✓ QEMU + acceptance     │ [show 65 routine steps]          │
├─────────────────────────┴──────────────────────────────────┤
│ 07:00 Auth chain: Nous 401 -> Go 400 -> refresh -> success │
│ 07:14 Wrong MACHINE -> corrected evbarm/aarch64            │
│ 07:30 Durable job started PID 266335, PPID 1               │
│ 07:55 Client interrupted; remote job survived              │
│ 08:19 Release exit 0                                       │
│ 08:35 Guest evidence accepted                              │
└────────────────────────────────────────────────────────────┘
```

On narrow screens the phase rail becomes a dropdown and the detail pane remains
a single virtualized column.

## 5. Timeline semantics

### Stable states

Every run and step must end in exactly one explicit state:

- `queued`
- `running`
- `waiting_external`
- `paused`
- `blocked`
- `succeeded`
- `failed`
- `interrupted`
- `cancelled`
- `unknown`

“Running” requires a live lease/heartbeat or an explicit currently active
process. A session that ends on an unmatched tool call is `interrupted` or
`unknown`, never permanently running.

For the legacy NetBSD data:

| Session | Correct display state |
|---|---|
| `a7508c77800d` | failed |
| `a20239db146e` | interrupted/incomplete |
| `c0904cb7dd7d` | interrupted/incomplete |
| `a7ac14a9f48f` | interrupted/incomplete; remote child later recovered |
| `a7cfccda0288` | complete |
| `dd8af54b87b2` | complete |
| `3e90d8f1cf59` | complete |
| `91f5e1ddd105` | complete |

The endeavor itself is accepted because later target evidence and verified
runs satisfy the contract.

### Recovery chains

Group causally related attempts, never hide their errors:

```text
Authorization — recovered
  attempt 1: Nous 401
             fallback Go 400
  attempt 2: Nous 401
             fallback Go 400
  attempt 3: Nous 401
             fallback Go 400
  intervention: forced Hermes OAuth import
  next probe: success
```

A recovery group shows first/last time, attempts, models/providers, total cost,
intervention, and final state. Expanding reveals each raw event.

### Poll folding

Render the 69-step release run initially as:

```text
69 cycles · 69 tools · 65 polls collapsed · 1 interrupted client
remote job survived · release exit 0 · $0.619384
```

Inside the collapsed poll group show:

- interval and duration;
- category counts;
- first observation;
- latest changed observation;
- number of identical results/warnings;
- token/cost total;
- any timeout, error, disappearance, exit transition, or artifact appearance.

Always show these events even when “hide routine” is active:

- errors and retries;
- new or disappeared process;
- exit-file transition;
- artifact creation/hash change;
- state-changing command;
- security boundary violation;
- pause/restart/resume;
- verifier rejection;
- final evidence;
- unmatched tool request/result.

### Delta transcript

A step should show only messages appended since the preceding request in the
same run. A late cumulative request becomes:

```text
Client request · 138 total messages · 165,491 bytes
Delta since prior step: 2 messages
  assistant -> terminal tail command
  tool -> 2 output lines
[show cumulative snapshot] [show raw]
```

System prompts and tool schemas appear once per run with a hash and “unchanged
for N steps” badge. If content changes, show a semantic diff.

### Duplicate boundary folding

One logical exchange gets boundary tabs:

```text
Decision: inspect release status
  Request delta | Model response | Tool result
  Raw copies: client request · upstream request · upstream response · client response
```

If copies are byte/JSON-identical, say so and store/render one logical content
object. Raw tabs remain addressable for forensic use.

### Warning deduplication

Repeated identical non-error lines become a badge:

```text
⚠ locale warning ×128 across 82 results
[first] [last] [show all]
```

Never deduplicate distinct exit codes, paths, PIDs, hashes, security identities,
or error messages merely because their prefixes match.

## 6. Search and filters

History must support server-side combinations of:

- endeavor/run/session ID;
- status;
- severity;
- recovered versus unrecovered;
- active versus historical;
- restart/interruption;
- model/provider;
- tool;
- target/resource;
- phase;
- event/exchange kind;
- time range;
- duration;
- cost or token spike;
- verifier score;
- full-text prompt/command/result search;
- “only changes”;
- “hide routine”;
- “collapse polling.”

Show active filter chips and a result count. Saved views should be shareable by
URL. Search results must deep-link to the endeavor/run/step and highlight the
matching field without expanding unrelated raw payloads.

## 7. Proposed data model

Add explicit durable entities:

### `endeavors`

- `id`
- `project_id`
- `title`
- `objective`
- `contract_json`
- `status`
- `created_ts`, `last_ts`, `completed_ts`
- `target_json`
- `tags_json`
- `metadata_json`

### `endeavor_members`

Maps existing sessions and later explicit conversations into one endeavor:

- `endeavor_id`
- `session`
- `ordinal`
- `relationship`: initial, continuation, retry, recovery, audit
- `attached_by`: explicit API, UI, heuristic, migration
- `attached_ts`

### `runs`

A process/client recovery epoch:

- `id`, `endeavor_id`, `session`
- `parent_run_id`
- `client_name`, `client_version`
- `server_instance_id`
- `executor`
- `status`
- `start_ts`, `end_ts`
- `interruption_reason`
- `resume_from_run_id`
- `prompt_hash`, `tool_schema_hash`

### `phases` and `steps`

- stable IDs and parent IDs;
- ordinal;
- phase/kind;
- summary;
- status/severity;
- start/end timestamps;
- tokens/cost;
- tool/model/target;
- input/output/evidence references;
- recovered_by_step_id;
- routine/dedup group;
- unmatched-request/result flags.

### `tool_calls`

- `id` and provider tool-call ID;
- `step_id`;
- name;
- canonical arguments;
- client executor argv/provenance;
- target identity;
- start/end/timeout;
- exit code;
- result reference;
- durable job ID.

### Event and exchange changes

Give `events` a monotonic primary key and add:

- `endeavor_id`
- `run_id`
- `phase_id`
- `step_id`
- `severity`
- `exchange_id`
- `parent_event_id`
- `dedup_key`

Record explicit lifecycle events:

- `process_start`
- `run_interrupted`
- `run_resumed`
- `step_start`
- `step_end`
- `tool_start`
- `tool_end`
- `external_job_started`
- `external_job_heartbeat`
- `external_job_finished`
- `server_start` and `server_stop`
- `control_changed`

Store repeated messages and schemas by content hash. An exchange snapshot can
reference ordered message object IDs instead of copying the full JSON prefix.
Retain original raw payloads under the configured retention policy, but do not
make them the query path for summaries.

Add indexes on:

- events by endeavor/run/step/id/time/severity;
- exchanges by session/task/time/kind;
- steps by endeavor/status/time/tool/model;
- tool calls by step/name/status;
- FTS over prompt, command, summary, result excerpt, and evidence labels.

## 8. API design

Replace global fixed-size fetches with scoped cursor APIs:

```text
GET /admin/endeavors?project=&status=&q=&cursor=&limit=
GET /admin/endeavors/{id}
GET /admin/endeavors/{id}/timeline?after_id=&cursor=&limit=&routine=
GET /admin/runs/{id}/steps?cursor=&limit=&kind=&severity=
GET /admin/steps/{id}
GET /admin/steps/{id}/exchange?view=delta
GET /admin/exchanges/{id}/raw?include=messages,tools
GET /admin/search?q=&endeavor_id=&cursor=&limit=
```

List responses use:

```json
{
  "items": [],
  "total": 69,
  "next_cursor": "opaque",
  "summary": {}
}
```

The UI must always say “showing X of Y.” No silent caps.

Summary endpoints must omit:

- raw payloads;
- cumulative message arrays;
- logprobs;
- reasoning details;
- full tool schemas;
- duplicate provider envelopes.

Fetch raw fields only after an explicit user action. Enforce a maximum raw
response size with downloadable/exportable continuation rather than silently
truncating valid JSON.

For Live, use server-sent events or a cursor `after_id` endpoint. Apply
incremental changes; do not refetch and rerender eight unrelated resources
every two seconds.

## 9. Rendering and performance requirements

- Virtualize timeline and raw-event rows.
- Paginate on the server; default 50 logical steps.
- Mount at most one raw payload drawer at a time.
- Keep collapsed payloads out of the DOM.
- Preserve scroll anchor when new live events arrive.
- Abort stale requests when selection changes.
- Cache summaries by endeavor/run and invalidate by event ID.
- Syntax-highlight only visible command/JSON blocks.
- Never put multi-megabyte logprobs or reasoning into the DOM by default.
- Compute deltas/dedup groups on ingestion or server query, not repeatedly in
  the browser.
- Keep first useful History content inside the initial viewport.
- Define a DOM budget and a response-size budget in automated tests.

For the NetBSD fixture, opening the endeavor overview should transfer under
200 KB, mount under 500 semantic rows, and never render the 14.2 MB cumulative
Hermes payload. Opening one raw exchange is an explicit exception.

## 10. Visual and accessibility rules

Use calm hierarchy rather than a unique color for every event:

- neutral background and borders;
- one stable accent per endeavor/run;
- status communicated by icon + text + color;
- red reserved for unrecovered/error states;
- amber for warning/recovered-with-caveat;
- green for proven terminal success;
- monospace only for IDs, commands, paths, hashes, and raw payloads.

Accessibility requirements:

- keyboard traversal for list, timeline, tabs, and drawers;
- semantic buttons, headings, tables, and disclosure controls;
- visible focus;
- status text that does not rely on color;
- screen-reader labels including collapsed counts;
- honor `prefers-reduced-motion`;
- no animated two-second full-page refresh;
- user-selectable density and wrapping for commands;
- sticky endeavor header, not a sticky wall of controls.

## 11. Legacy migration for this endeavor

Because the current database has no explicit lineage, create one manual
endeavor mapping for the fixture:

```text
NetBSD ARM64 acceptance
  1 a7508c77800d  initial/auth failure
  2 a20239db146e  credential-refreshed continuation
  3 c0904cb7dd7d  broken resume
  4 a7ac14a9f48f  hardened durable release
  5 a7cfccda0288  monitoring decision
  6 dd8af54b87b2  QEMU plan/repair
  7 3e90d8f1cf59  acceptance judgment
  8 91f5e1ddd105  fixed-target smoke
```

Attach the seven control events as endeavor milestones, including the two
post-restart `!gate off` commands. Do not claim heuristic certainty for future
legacy grouping; expose proposed groupings for confirmation.

Duration must use the maximum event/exchange time, not only turn rows. The
`dd8` run, for example, lasts 303.926 seconds rather than zero.

When rendering final responses, use the complete exchange content. The `dd8`
response is valid 5,527-character JSON in `exchanges` but an invalid
2,000-character prefix in `turns.response`.

## 12. Delivery phases

### Phase 0 — stop the worst behavior

- separate Live and History routes;
- add explicit hidden counts and pagination;
- scope event queries server-side;
- default message view to delta/summary;
- collapse system prompt/tool schema;
- fold duplicate boundary copies;
- hide logprobs/reasoning from summaries;
- stop full-page two-second rerenders;
- fix terminal status for unmatched calls;
- surface control/restart events.

This can work against the existing schema with derived grouping.

### Phase 1 — first-class endeavors and runs

- add endeavor/member/run/phase/step/tool-call entities;
- accept explicit endeavor/conversation IDs at API ingress;
- record client/server/restart provenance;
- record durable external jobs;
- migrate the NetBSD fixture;
- add recovery-chain and poll-group summaries.

### Phase 2 — scalable history

- content-address repeated messages/tool schemas;
- add indexes and FTS;
- use incremental event delivery;
- add saved searches and exports;
- enforce retention tiers for raw provider diagnostics;
- measure UI payload/DOM/interaction budgets in CI.

## 13. Acceptance criteria

The redesign is acceptable only when all of these pass against a copy of the
current database:

1. One NetBSD endeavor contains all 8 sessions and 114 task IDs.
2. The endeavor list shows duration, cost, errors/recovery, target, and final
   acceptance without opening raw data.
3. `a7ac14a9f48f` initially renders one run summary:
   `69 cycles · 69 tools · 65 polls collapsed · 1 interrupted client ·
   missing final agent result · $0.619384`.
4. Expanding the poll group shows category counts, first/last time, latest
   change, errors, and cost; raw 65 rows are paginated or virtualized.
5. The late request shows `138 messages · 165,491 bytes` and only its appended
   delta by default.
6. Duplicate client/upstream/request/response copies render as one logical
   exchange with explicit raw tabs.
7. The three auth failures render as one recovery chain while preserving every
   Nous 401 and Go 400.
8. The 128 identical locale warnings render as one count badge; no errors,
   target changes, exits, or evidence are suppressed.
9. Session states match the table in section 5; none remains falsely running.
10. Exact initial prompts and exact tool commands are reachable within two
    interactions.
11. The complete 5,527-character `dd8` response is available and valid; the
    truncated History copy is not used.
12. All seven control events are visible as configuration/restart milestones.
13. APIs return `items`, `total`, and `next_cursor`; the UI always states
    “showing X of Y.”
14. Endeavor summary responses contain no cumulative messages, logprobs,
    reasoning details, or full raw payloads.
15. Opening Overview transfers under 200 KB and does not mount more than 500
    semantic rows.
16. Live updates preserve scroll/focus and update only changed components.
17. Keyboard, screen-reader, contrast, reduced-motion, and narrow-screen tests
    pass.
18. Raw export remains lossless and every summarized item links to its source
    event/exchange IDs.

## 14. Recommended first implementation slice

The most valuable reviewable slice is:

1. add a `/history` route and move existing controls to `/live`;
2. introduce a derived endeavor fixture joining the eight NetBSD sessions;
3. add scoped cursor endpoints for endeavor timeline and steps;
4. compute logical step deltas and polling groups server-side;
5. render Overview/Timeline with raw payloads absent;
6. add a single on-demand raw drawer;
7. test against the NetBSD database copy and the exact acceptance criteria
   above.

That slice directly removes the nausea-inducing behavior while preserving a
clear path to the durable schema. It should land before visual polishing or
new analytics widgets.

