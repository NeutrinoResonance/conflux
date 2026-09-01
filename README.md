# Conflux

Conflux is an OpenAI-compatible proxy built on one working assumption: model output is wrong until
it survives checking. Anyone who has run these things for real already operates this way.

The goal is to push open-weight and local models to frontier (read: Fable) reliability by refusing
to believe them. You point any OpenAI client at a virtual model called `super`, and every turn
gets:

- **A contract** — a checklist of what "done" means, extracted up front.
- **A workflow** — a graph of supervising agents (executor, governor, critic) plus their settings,
  matched from the flows declared in [`agent_flows.yaml`](agent_flows.yaml) or synthesized for
  that message and deterministically checked. The fixed `Orchestrator` pipeline still drives
  execution.
- **An executor** — the model that does the work, chosen through learned routing, defaults, and
  fallbacks.
- **Deterministic monitors** — run over the answer before anyone believes it.
- **Real execution** — produced code runs in a sandbox instead of being trusted.
- **A grade from a *different* model family** — because a model grading its own homework grades
  generously.
- **Bounded repair** — failed work gets a fixed number of fixes; endless retries are how a $0.003
  task becomes a cloud bill.

The other half of the design: nothing is stored as one big transcript string, because transcript
strings are where information goes to die. Instead:

- Every user message, context block, store operation, and checkpoint is a row in
  `workspace_nodes`; every relationship between them is a row in `workspace_edges`.
- Every reply is an *assistant node* — the one node that computes. Born `queued`, it owns a
  private workflow instance, runs the turn, and receives the result.
- That instance is a `workspace_workflows` row whose `graph_json` holds a private copy of a
  declared flow from [`agent_flows.yaml`](agent_flows.yaml) — a second graph, with its own nodes
  and edges, living inside the first.
- Edit a node and its dependents are marked stale and recomputed in order; the exact rules,
  including which edits don't count and which nodes are shielded, are below.

Like a build system, except the compiler is a pile of open-weight models that lie sometimes.

A quick naming note before the graph editor:

> [!NOTE]
> This project uses both *workflow* and *flow*, so it is easy to mix up the drawn graph with the scheduler.
> The drawing visualizes the run, and node settings affect behavior, but the fixed `Orchestrator` pipeline decides what runs; [the execution trace doc](docs/graph-node-execution-trace.md) explains how.

And this is a research prototype in the literal sense: its central claim (supervision beats an
equally-funded unsupervised model) has **no controlled benchmark behind it yet**. The
[technical report](docs/paper/conflux-technical-report-2026-08-22.md) is honest about this. Read
it before you form opinions.

## How a message gets in

Messages enter through three doors. All three land on the same engine.

1. **The workspace** — `POST /admin/workspace/conversations/{session}/messages`. The product
   path. The server owns the conversation as a graph; you send only the new text.
2. **`/v1/chat/completions` without tools** — one stateless supervised turn dressed up as a
   model. You own the conversation and resend the history every request, like every other OpenAI
   client on the planet.
3. **`/v1/chat/completions` with tools** — your agent (OpenCode, Hermes, whatever) drives the
   turn, and every tool call it proposes goes through the action governor before release. On
   `super`, that is — raw model names skip all of it, see the warning below.

Talk is cheap, so here is door 1, all the way through. You submit `Return the first 10 primes.`
on conversation `conv_1`:

```http
POST /admin/workspace/conversations/conv_1/messages
Content-Type: application/json

{"content":"Return the first 10 primes.","flow_id":"auto"}
```

You get HTTP 202 back. Before that 202, `send()` has picked a flow — a keyword gate
(`heuristic_match()`), no model call, so the queued message has a real graph immediately — and
`create_message_pair()` has committed, in one transaction:

1. A user `message` row in `workspace_nodes`, status `complete`.
2. If the conversation has a last node: a `depends_on` edge from it to the new user node,
   labeled `next message`.
3. An assistant `message` row, status `queued`, output empty.
4. A `depends_on` edge from user to assistant, labeled `responds`.
5. A fresh `workspace_workflows` row holding a private copy of the chosen flow's graph — for
   this prompt, `supervised_tool_turn`.

Then `send()` creates a `workspace_jobs` row for the UI to poll and schedules the asyncio task
that does the actual work.

That task first finishes the flow decision: in `auto` mode, one cheap utility-model call may
overrule the keyword gate and retarget the instance to a better declared flow. In `synthesize`
mode, the utility model proposes a one-off graph as JSON and a deterministic validator accepts or
rejects it — on garbage, the default flow runs and the failure is recorded in `flow_decision`,
not hidden. Only then does the assistant node flip to `running`, and if the graph contains an
unsatisfied `human_input` node, it parks at `awaiting_input` instead — **nothing is spent** until
a human answers.

Then the prompt is assembled from the graph (`prompt_messages()`): walk the structural ancestors
in creation order — messages as their roles, context nodes as `system` — then splice in each
direct `feeds` source as a labeled system block before the last user message. A `feeds` wire
imports the source's *output text only*, not its ancestry. That's the whole point of a wire.
`store_read` nodes prepend their retrieved records. Then `Orchestrator.run_turn()` gets called,
and for a boring single-unit text turn you can watch the cursor move:

```text
turn_start -> contract -> execute -> verify -> turn_end
```

When the report comes back, the assistant row gets its output, a `run_id`, and
`config.task_id` / `executor` / `score` / `cost_usd` / `attempts`. Status becomes `complete` — or
`awaiting_approval`, `failed`, or `needs_attention` if the turn earned it. The full per-event
evidence stays in the trace and exchange ledgers;
`GET /admin/workspace/workflows/{instance_id}/execution` joins it back onto the graph, exact
provider payloads included (loaded only when you expand the run — payloads are heavy).

One wart you should hear from me instead of discovering: `/v1/chat/completions` does **not** go
through `WorkspaceService.send()`. It runs the engine directly and writes trace rows; the
workspace imports those later via `import_trace_conversation()`. Watch live work in `/workspace`;
point clients at `/v1`. Two paths, both on purpose. Don't file a bug about it.

## Inside the engine, where the money goes

`run_turn()` starts by putting a price on the turn: a `Budget` with a hard USD cap. Then one
cheap contract call turns the request into a checklist and a difficulty rating — trivial turns
get lite verification. From there, one of three paths: a single supervised unit (the common
case), a multi-candidate ensemble when the workflow asks for one (N candidates, then a verified
merge), or a planned set of units for big or multipart tasks. Planned units run in dependency
waves, and every completed unit is checkpointed immediately — if the turn dies from a crash, a
pause, or a budget stop, resending the same request resumes from the checkpoint instead of
paying twice.

Each unit runs the supervised loop:

1. **Execute.** The routed model answers; provider fallback happens inside this step. An empty
   answer (a reasoning model that burned its whole token budget thinking — common) costs one
   attempt and skips straight to feedback.
2. **Monitor.** Five deterministic checks, no model calls: stub text where work should be,
   success claims without evidence, deferring the work back to you, endings that announce actions
   never taken, and big requests answered in three lines. A retry that's basically the previous
   attempt gets flagged too — feedback that isn't incorporated is its own failure mode.
3. **Run the code.** If the answer contains Python and the sandbox is on, the code runs — local
   subprocess or an ephemeral GCE VM — and a failing transcript becomes repair feedback.
   Execution evidence beats model confidence every single time.
4. **Verify.** A model from a different family scores the answer against the contract, reading
   letter-grade token logprobs. Pass with no monitor events: done.
5. **Repair or escalate.** The first `max_repairs` failures (two, as checked in) get a
   rule-driven retry with targeted feedback — no referee spend. After that, a referee model must
   change something structural: switch to an untried model family, escalate verification,
   decompose into units, or ask you. The turn always returns its best attempt.

Failures have names — every monitor is keyed to an ID in the
[failure taxonomy](docs/failure-taxonomy.md) — and outages are survivable by design: if every
verifier provider is down, you get the best attempt marked UNVERIFIED instead of a dead turn. A
supervisor outage should not delete the work it was supervising.

## Getting it running

Python 3.11+, developed on 3.12:

```bash
uv venv --python 3.12
uv pip install -e .
source .venv/bin/activate
```

Run `conflux` from the repo root. The config default is a CWD-relative `models.yaml`, resolved
against whatever directory you happen to be standing in. Pass `--config /absolute/path/models.yaml`
if that offends you.

### Keys

[`models.yaml`](models.yaml) holds providers, models, roles, prices, fallbacks, and key-source
*names*. No secrets — keys resolve at request time. As checked in, two providers are actually
used:

- `nous` → `key_source: hermes:nous` → `~/.hermes/auth.json`
- `opencode-go` → `key_source: opencode:opencode-go` → `~/.local/share/opencode/auth.json`

Don't have those tools? Set `key_source: env:MY_API_KEY` and export the variable. The `nanogpt`
and `ollama-cloud` blocks exist in the registry but no checked-in model uses them.

Then:

```bash
conflux probe
```

`probe` fires real requests at every model, three samples each, because providers will happily
accept a `logprobs` parameter and return nothing, and their documentation is a work of
aspirational fiction. The verifier depends on this data. Probe first.

### Run it

```bash
conflux demo                     # one supervised turn, report printed
conflux serve                    # proxy on 127.0.0.1:8055
```

> [!IMPORTANT]
> The checked-in config sets `execution.backend: gce` and locks it there. If a turn produces
> Python, Conflux will try to start a real Compute Engine VM in the configured `gcloud` project —
> which is not *your* project. Set `execution.backend: off` unless you've pointed
> `execution.gcloud_*` at infrastructure you own and authenticated. Supervision still works
> without it; you just lose execution evidence. A model message cannot retarget the backend.
> That's deliberate.

```bash
curl http://127.0.0.1:8055/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "super", "messages": [{"role": "user", "content": "Return the first 10 primes."}]}'
```

Any OpenAI-compatible client works: base URL `http://127.0.0.1:8055/v1`, model `super`. Hermes
users register a custom provider named `conflux` and run `hermes --provider custom:conflux -m
super`.

> [!WARNING]
> The raw names under `models:` are **unsupervised passthrough**. Straight to the provider — no
> governor, no verifier, nothing, tools included. They exist for comparison and plumbing. If you
> wanted supervision and typed a raw model name, that's between you and your shell history. Use
> `super`.

The `/v1` endpoint is stateless by default: no explicit ID means a fresh `oneshot_<hex>` session
per request, and even with `X-Conflux-Conversation` it only groups trace identity — it does not
reconstruct history for you. Send your own message history. The old stateful mode
(`supervision.stateful_chat_endpoint: true`), with in-band `!pause` / `!budget` / `!use`
commands, exists for legacy clients and is off by default; a `!command` sent in stateless mode
gets a short retirement notice and costs nothing.

## The two graphs, precisely

The full walkthroughs are [message-arrival-trace](docs/message-arrival-trace.md) and
[graph-node-execution-trace](docs/graph-node-execution-trace.md). Read them before inventing a
third interpretation.

### Vocabulary before machinery

- **Workflow** — the reusable definition: a recipe for how work should move, rather than any
  particular run of it.
  - BPMN, LangGraph, and n8n use different names for these ideas, but the definition/run split is
    the same.
  - In Conflux, [`agent_flows.yaml`](agent_flows.yaml) holds the workflow definitions.
- **Workflow instance** — one use of a workflow definition, with its own runtime state.
  - Instances are independent: changes to instance 47 do not change instance 48.
  - One definition can have zero instances or thousands.
  - In Conflux, `workspace_workflows.graph_json` holds the instance for an assistant message.
- **Node kind** — a verb: the work or control point a node represents.
  - Common kinds: trigger (starts an instance), task (does the work), decision (picks the next
    edge), fork/join (splits into parallel branches, then waits for them), wait (pauses for time
    or an event), sub-workflow (runs another workflow as one step), and terminal (ends the
    instance).
  - Conflux has five conversation node kinds and eighteen workflow node types.
- **Edge kind** — a travel rule: how work or data moves between nodes.
  - Common kinds: sequence (source finished, go to target), conditional (taken only when its
    condition is true), default (taken when no conditional edge matched), error (a recovery path
    when the source fails), and data (carries values between steps instead of deciding order).
  - Conflux has two conversation edge kinds.

Here, the workflow graph shows the run and supplies settings; the fixed `Orchestrator` pipeline
still decides what runs.

### The conversation graph

`workspace_nodes` + `workspace_edges`, scoped to a conversation. Exactly five node kinds, enforced
as a closed whitelist:

| Kind | What it actually does |
|---|---|
| `message` | User rows carry prompt text; assistant rows own a workflow instance and receive the result. |
| `context` | Created `complete`; rendered as a `system` message when it's in structural ancestry. |
| `store_read` | `config.store_id`, `top_k`, `query_prompt` pull bounded records into the prompt as a system block. |
| `store_write` | After a real, non-held result, copies the report text into `workspace_store_records` with full provenance. |
| `checkpoint` | A marker in the outer graph. The planner's unit checkpoints are a separate store. Don't confuse them. |

An *assistant node* is the `kind=message`, `role=assistant` case. It is the only conversation-graph
node that runs. It is born `queued` in the same transaction as its user node, owns that message's
workflow instance, and on completion receives `output_text` plus the audit trail: `task_id`,
`executor`, `score`, `cost_usd`, and `attempts`. Descendants consume its output through structural
lineage or `feeds` wires. Do not confuse it with workflow node type `agent`; that lives in the
other graph.

Two edge kinds. Two.

- `depends_on` — the control/sequence edge: structural lineage, prompt ancestry, and invalidation.
  Only message creation makes these. You don't get to create or delete them.
- `feeds` — the data edge: a user-created wire carrying the source's output text only, with no
  ancestry, into the target's prompt. Creating or deleting one marks the target stale. Created
  via `POST /admin/workspace/conversations/{session}/edges`; self-edges, duplicates,
  cross-conversation endpoints, and cycles are rejected at the API.

Conflux keeps control flow and data flow separate, and the split is load-bearing: the two edges
have different prompt and lineage semantics.

### The workflow graph

A *flow* is the static recipe: a named supervision graph declared in
[`agent_flows.yaml`](agent_flows.yaml), such as `supervised_tool_turn`. `FlowRegistry.load()` loads
it, and `FlowSpec.validate()` hard-rejects unknown types or agents, undeclared capabilities,
unreachable nodes, missing terminals, duplicate edges, and undeclared loops — a cycle must carry
both `loop: true` and a positive `budgets.max_iterations`. A flow never runs itself. Nothing at
send time writes to it; global changes go through `workspace_workflow_overrides`, explicitly.

A *workflow instance* is one assistant message's private, literal copy of that graph, serialized
into `workspace_workflows.graph_json`. Generic workflow engines often share one definition and
vary only the runtime state. Conflux does not: because this is a copy, it may diverge structurally
from its source. Edit it, retarget it, or replace it through `synthesize`; the registry and every
other message remain untouched. There is one instance per assistant message, and instances are
independent.

The instance does not execute. Before the run, its enabled-node settings are summarized into a
plan that the fixed Python `Orchestrator` pipeline reads. During the run, engine events are
projected back onto the instance as the moving `runtime_status` cursor. It is a control surface
plus a display; no little interpreter hides in that JSON column.

Its eighteen node types are a settings-and-projection vocabulary rather than dispatch targets:

```text
ingress agent policy critic probe approval tool postcheck checker
verifier router checkpoint terminal ensemble context store_read
store_write human_input
```

For people arriving from BPMN, Temporal, or LangGraph: `ingress` is roughly start; `terminal`, end;
`agent` and `tool`, tasks; `router`, a decision; `human_input` and `approval`, wait-for-a-human;
`ensemble`, fork/join; and `verifier`, `checker`, `critic`, and `postcheck`, review tasks. A node's
type determines which pipeline events light it up and which settings the engine reads. It does
not mean "what happens when execution reaches it," because execution never reaches it.

Put the two graphs together and the line is sharp. The conversation graph is real dataflow:
outputs travel and edits cascade. The workflow graph is a control surface plus a display. Nothing
anywhere walks a graph dispatching on kind. The engine pipeline is fixed Python, and even
conversation-graph recalculation runs in creation order (`ordinal`); edges decide what goes stale
and what enters the prompt, while `ordinal` decides the visit order.

### What `supervised_tool_turn` actually declares

```text
ingress -> executor
  no tool calls -> final_verifier -> completed (one bounded repair loop on failure)
  tool calls -> policy_gate
    invalid/forbidden -> blocked
    low risk -> action_released
    medium/high -> action_critic -> released | blocked | preflight | human_approval
    action_released -> client_tool -> postcheck -> soundness checks -> executor
```

Capabilities are granted to named agents: the executor can *propose* but not *release*; the
deterministic governor owns risk classification and release; critic and verifier can't execute
anything; the operator is the only identity that approves unresolved high-risk actions. A held
action is a durable `human_pending` row. On the `/v1` tool surface, an approved action is
released *byte-for-byte* from the stored proposal, rather than regenerated by a model that might
helpfully produce something different. In the workspace, approval flips the durable row and
re-runs the assistant node from its graph inputs. Either way, the model saying "approved!" in
prose is worth exactly what model prose is worth: nothing.

## Edits, staleness, recalculation

Conversation nodes hold one durable status:
`draft queued running awaiting_input awaiting_approval paused complete stale failed
needs_attention cancelled`. Workflow-graph nodes carry a separate `runtime_status` cursor inside
`graph_json` — the live projection; the durable state stays on the conversation node.

The edit cascade is one flow, and it's worth knowing cold:

1. `PATCH /admin/workspace/nodes/{node_id}` on content writes the old input/output/config to
   `workspace_node_revisions` first — the undo and audit ledger — then increments the revision.
2. Every downstream node is marked `stale` by following outgoing edges (500 levels deep,
   skipping `paused` and `cancelled` — pausing a node shields it from upstream churn), and their
   workflow cursors are cleared. `feeds` wires participate fully: creating or deleting one stales
   the target just like editing its parent would.
3. A stale node keeps its old `output_text` until recalculation overwrites it, so the UI can
   show the previous answer while the new one is pending. Stale simply means "the inputs that
   produced this have changed."
4. Recalculation runs the stale set ordered by `(ordinal, node_id)`, serialized by one asyncio
   lock per conversation, and stops at the first node that comes out `awaiting_input`,
   `awaiting_approval`, `failed`, or `needs_attention`. Later nodes stay stale until the blocker
   clears.

A patch that only touches `position_x`/`position_y` moves the picture: no revision, no
invalidation, no model call. Layout is not data.

And the known hole, stated here instead of a commit message: recalculation order is creation
order, **not** a topological sort. For ordinary message lineage those coincide. But a
later-created node feeding an earlier-created consumer on a sibling branch can recompute *after*
its consumer, which then reads stale output for that pass. Real limitation, documented.

Pause and resume, because "cancel" is never as simple as people want: `pause` cancels the node's
asyncio task at an await point — it does not recall a provider call already in flight, un-send a
released tool call, or stop sandbox work already launched. `resume` re-executes the node from its
graph inputs; it does not resurrect a Python stack frame. An approval decision
(`POST /admin/workspace/actions/{action_id}/decision`) flips the durable action row and resumes
the message automatically.

## Knowledge stores

The built-in `sqlite-vector` adapter hashes tokens into a deterministic 96-dimensional vector,
scans at most 2,000 recent records by cosine, returns 1–20 results, and truncates the rendered
block at 20,000 characters. Deliberately dumb and bounded, which beats cleverly unbounded.
`external-vector` rows hold an operator-owned `connection_ref` and nothing else — the graph
stores zero credentials — and the adapter refuses to run until an operator wires one up. A held
proposal never reaches `store_write`; only real terminal output enters a store.

## Durable jobs

Long work goes through the declared `durable_locked_job` flow: an execution lock on the exact
adapter and target fingerprint (or `job_blocked`), durable job IDs, heartbeats, byte cursors,
exact process-group signals, and evidence collection with artifact manifests. The backend is
pinned by operator config. A model asking nicely for a different backend gets nowhere, which is
the correct amount of nowhere.

## Export, retention

Everything lives in `traces.db`. `conflux sessions | export | prune --dry-run | report`.

Export encryption is decided by *project settings*, not by which flags you waved at the CLI.
Default is `compression: xz`, `encryption: none` → `.json.xz`. Set the project's
`encryption: passphrase` and you get AES-256-GCM in an `.llmx` container, and *then*
`--passphrase` supplies the key. Passing `--passphrase` at a project with `encryption: none`
encrypts nothing. Flags are not settings.

## The warnings you will skip and regret

> [!WARNING]
> **Admin auth is off by default.** Empty `admin.token` means every `/admin/*` endpoint —
> approvals, workflow edits, routing, exports, deletion — is open to whoever reaches the port.
> Fine on localhost. Spectacularly not fine anywhere else.

```bash
CONFLUX_ADMIN_TOKEN=$(openssl rand -hex 24) conflux serve
```

`Authorization: Bearer <token>` or `X-Conflux-Token`; browsers can do a one-time `?token=` for
the `conflux_admin` cookie. This gates `/admin/*` only. `/v1` ingress is not behind it.

> [!WARNING]
> **Supervision costs real money by design.** Contract, executor attempts, verification, repair,
> synthesis, sandbox — one turn can pay for all of them. The default cap is `$0.50` per task,
> checked at loop and wave boundaries, not reserved per call. One in-flight attempt can blow past
> the cap, and a cancelled provider request may still bill. `conflux report` exists. Use it.

The governor's schemas and risk heuristics reduce accidents. They are **not** a security
boundary, and anyone who tells you their prompt-adjacent heuristics are a security boundary is
selling something. And hosted `logprobs` can vanish without an error at any time, so `probe`
isn't optional hygiene — it's load-bearing.

## Docs

- [Technical report](docs/paper/conflux-technical-report-2026-08-22.md) — the honest audit. Start
  here.
- [SPEC.md](SPEC.md) — full supervision policy, costs, intervention design.
- [What happens when a message arrives](docs/message-arrival-trace.md) — every function on the
  ingress paths, every special case.
- [Executing the graph](docs/graph-node-execution-trace.md) — status machine, recalculation,
  evidence projection.
- [Failure taxonomy](docs/failure-taxonomy.md) — the failure-mode IDs monitors tag.
- [Observability](docs/observability-and-conversations.md) — score math, identity, dashboards.
- [Mini-paper](docs/mini-paper.md) — early progress report, historical.

Field logs and reproducibility artifacts: [`docs/`](docs/), [`artifacts/`](artifacts/).

Field evidence rather than a benchmark: one supervised long-running
[NetBSD/AArch64 agent exercise](docs/field-report-2026-07-18-netbsd-arm64.md) cross-compiled
NetBSD for AArch64 on an x86_64 GCE host and booted the image under `qemu-system-aarch64` with
TCG. The accepted run has a
[full forensic report](docs/netbsd-arm64-endeavor-forensic-report-2026-07-18.md) and an
[exact 113-call tool ledger](docs/netbsd-arm64-agent-tool-ledger-2026-07-18.md). A
[follow-up session](docs/netbsd-optee-driver-2026-07-19.md) used the preserved VM disk to build an
OP-TEE driver continuation; its honest status is **agent-reported complete; repository
verification unavailable**.

## Status

Implemented and running: the proxy, the fixed supervised loop, cross-family verification, the
action governor, durable jobs, the conversation graph with invalidation and recalculation,
workflow instances, stores, export, retention. Known limits, stated where you can see them:
drawn edges don't schedule; cross-branch recalculation is ordinal, not topological; verifier
calibration needs real evidence; hosted logprobs regress silently; heuristics aren't security;
budget caps can be overrun by in-flight work.

No benchmark theater. When the controlled comparison exists, it'll be in the report. Until then
the claims are exactly as strong as the evidence, which is how this is supposed to work.

## License

MIT. See [LICENSE](LICENSE).
