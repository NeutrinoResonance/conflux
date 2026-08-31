# Conflux — Specification

**An ensemble supervisor for open-source LLMs.** Routes agentic coding work
across an ensemble of OSS models (DeepSeek, GLM, Kimi, Qwen, and small models
like Gemma) and compensates for each model's known deficiencies with
taxonomy-driven runtime monitors, cross-model verification, and
escalation — while keeping the human able to observe, pause, redirect, or kill
the system at any point.

Status: draft v0.1 · 2026-07-15

---

## 1. Thesis

Individual OSS models fail in *characteristic, predictable* ways: DeepSeek
under-delivers and stops early; GLM thrashes across shallow solution attempts;
both skip self-verification; all of them intermittently ignore instructions.
These are not random errors — they are stable failure signatures, which means
they can be **detected cheaply at runtime and corrected structurally**.

The failure catalog is imported from UC Berkeley's MAST taxonomy and extended
with model-level modes: see [`docs/failure-taxonomy.md`](docs/failure-taxonomy.md).
Every mechanism in this spec traces back to a failure-mode ID (FM-x.y) there.

Two findings from the MAST paper shape the whole design:

1. **Self-verification is weak; independent verification works.** Prompting a
   model to check itself yielded marginal gains. Therefore: the verifier is
   always a *different model* than the producer (§6).
2. **41.8% of failures are specification/design failures.** Therefore: the
   system spends cheap tokens up front making the task spec explicit and
   machine-checkable (contract extraction, §5.1) rather than expensive tokens
   later repairing bad output.

Cost efficiency comes from asymmetry: **detection is cheap, generation is
expensive.** A 4–12B model (Gemma-class) can judge "did this output ignore
constraint #3?" far more cheaply than a frontier-class model can produce the
output. So the system wraps expensive generation calls in cheap supervision,
and escalates to expensive models only on detected failure.

---

## 2. System boundary — the first two questions

### 2.1 What provides input? Where does output go?

Three candidate architectures were considered:

**Option A — OpenAI-compatible proxy server ("fake model server").**
The system presents `/v1/chat/completions` (+ streaming, + tool calls) and
registers as a model named e.g. `super/coding`. Any existing OSS client —
OpenCode, Aider, Cline/Roo, Continue, even Claude Code pointed at a custom
base URL — connects unmodified. Internally, one inbound request fans out into
the ensemble pipeline, and the final verified result streams back as if a
single model produced it.

- ✅ Universal client compatibility; zero client maintenance; the ensemble is
  swappable behind a URL.
- ✅ Clean seam for record/replay: every request/response is already
  serialized at the boundary.
- ⚠️ The proxy sees *one completion call at a time*, while failure modes like
  FM-1.3 (step repetition) and FM-X.2 (breadth thrash) are only visible
  *across* calls. Mitigation: session correlation — key requests by client
  connection + conversation-prefix hash to reconstruct the agent trajectory
  server-side. This is well-trodden (LiteLLM/OpenRouter do coarse versions).
- ⚠️ Intervention can't live in the client's UI. Mitigation: a companion
  control-plane UI (§7); the proxy can also inject status lines into the
  assistant stream so the user sees supervisor activity inside their normal
  client.

**Option B — Fork/modify an OSS client (e.g. OpenCode).**
Embed the ensemble logic in the client's agent loop.

- ✅ Full visibility into the loop (tool results, edits, user turns); native
  intervention UI.
- ❌ Married to one client and a fork-maintenance treadmill against an
  upstream that moves weekly.
- ❌ The ensemble logic is not reusable from other clients.

**Option C — Standalone orchestrator that owns the agent loop.**
The system *is* the agent (its own planner/executor/tools), exposed via CLI/TUI.

- ✅ Maximum control; the trajectory is native data, not reconstructed.
- ❌ Rebuilds everything OSS clients already do well (tool harnesses, editor
  integration, sandboxing); slowest path to something usable.

### 2.2 Decision: **A-first, layered so C is reachable**

Build **Option A** (the proxy) as the product boundary, but structure the
internals as a client-agnostic **orchestration core** with two frontends:

```
                         ┌────────────────────────────┐
   OSS client            │  Conflux                 │
 (OpenCode, Aider, …)    │                            │
   │  OpenAI protocol    │  ┌──────────┐  ┌─────────┐ │     ┌─ DeepSeek
   └────────────────────►│  │ Ingress  │─►│ Orchestr│─┼────►├─ GLM / Kimi
                         │  │ (proxy)  │  │  core   │ │     ├─ Qwen
   Control-plane UI ◄────┼──┤          │  │(LangGraph)│     └─ Gemma (judges)
   (web/TUI: pause,      │  └──────────┘  └─────────┘ │
    steer, kill, replay) │        session store, trace│
                         └────────────────────────────┘
```

- The **ingress** speaks OpenAI protocol and does session reconstruction.
- The **orchestration core** never sees HTTP; it sees "here is a task turn,
  here is trajectory history, produce a supervised result." This keeps it
  embeddable in a client later (Option B/C become thin adapters, not rewrites).
- The **control plane** (§7) attaches to the core, not the proxy, so
  intervention works identically regardless of frontend.

Non-goal for v1: being a general-purpose gateway (auth, multi-tenant, billing).
Single user, local-first.

*External validation:* Kwok et al.'s **TurboAgent**
([arXiv:2607.05391](https://arxiv.org/abs/2607.05391)) independently arrived
at the same boundary — a transparent inference-time proxy between OpenAI-API
clients (incl. Claude Code) and providers, with a companion web UI for live
verifier/progress monitoring — and demonstrated it works with unmodified
harnesses, including running whole benchmarks through it.

---

## 3. Roles in the ensemble

| Role | What it does | Model class | Cost posture |
|------|--------------|-------------|--------------|
| **Contract extractor** | Turns the user/task prompt into a checklist of explicit, checkable constraints (targets FM-1.1) | small (Gemma-class) | pennies, every turn |
| **Planner** | Decomposes the task; declares termination criteria up front (FM-1.5, FM-3.1) | mid/large | once per task |
| **Executor** | Produces the actual work (code, edits, tool calls) | large (DeepSeek/GLM/Kimi, routed) | the main spend |
| **Monitors** | Cheap always-on detectors keyed to FM IDs (§5) | small / heuristic (non-LLM where possible) | near-free |
| **Verifier** | Independent check of executor output against the contract; *always a different model family than the executor* (FM-3.2/3.3) | mid | per completed unit |
| **Referee** | On disagreement or detected failure: diagnose, pick a repair strategy (retry-with-feedback, switch model, escalate, split task) | large | rare, on-failure only |
| **Supervisor state** | Persistent per-task ledger: contract, plan, attempts, verdicts, budget | — (data) | — |

Model↔role assignment is **config, not code** (`models.yaml`): per-model cost,
context length, strengths, and known failure priors (e.g.
`deepseek: {priors: [FM-X.1, FM-3.1]}`), so routing can bias verifier choice
toward a model whose failure priors are *uncorrelated* with the executor's.

---

## 4. Task lifecycle

```
turn arrives (proxy) 
  → contract extraction (small model, cached per conversation)
  → route: trivial? ──yes──► single cheap model, verify-lite, return
        │ no
  → plan (or reuse existing plan from session store)
  → execute unit (routed large model)
      ├─ monitors stream-scan output as it generates (§5)
      │    └─ tripwire → cancel generation early (saves tokens), referee
  → verify unit (different model, against contract + evidence)
      ├─ pass → integrate, next unit or finish
      └─ fail → referee → {retry w/ targeted feedback | reroute to other
                 model | escalate tier | decompose | ASK USER}
  → completion gate: contract checklist fully evidenced? (FM-3.1, FM-X.4)
      └─ only then stream final answer to client
```

Retries carry **targeted feedback** ("you produced a stub for `parse_args`;
the contract requires a working implementation — FM-X.1"), not generic
"try again", and the ledger records which feedback worked per model — a local
learning signal for routing.

**Escalation ladder & anti-loop rule:** each unit has a budget (§8). A model
gets at most N=2 repair attempts on the same unit before the referee must
*change something structural* (different model, decomposition, or user
escalation) — this is the system refusing to reproduce FM-1.3/FM-X.2 at the
orchestrator level.

---

## 5. Failure detection (monitors)

Each monitor is small, single-purpose, keyed to FM IDs, and emits
`(fm_id, confidence, evidence_span)` events to the ledger + control plane.
Heuristic before LLM; small-LLM before large.

### 5.1 Contract monitor — FM-1.1, FM-X.5
Contract extractor produces constraint checklist at turn start. After each
executor unit, a small model marks each constraint satisfied / violated /
not-yet-addressed, quoting evidence. "Violated" trips the referee.

### 5.2 Completion monitor — FM-3.1, FM-X.1, FM-X.4
- Heuristics: stub patterns (`TODO`, `pass  #`, `// ... rest`, empty function
  bodies), diff-size vs plan-scope ratio, "claims-tests-pass" assertions with
  no test-run tool call in the trajectory.
- Small-LLM check: "Given plan step 3, is this output a complete
  implementation or a sketch?"

### 5.3 Thrash / repetition monitor — FM-X.2, FM-1.3, FM-2.3
Embed each attempt summary; cosine-similarity against prior attempts detects
loops (FM-1.3) — and *low* similarity across many rapid abandoned attempts
detects breadth thrash (FM-X.2). Tracks "depth per candidate": attempts
abandoned before reaching a testable state.

### 5.4 Reasoning–action monitor — FM-2.6, FM-X.3
Diffs stated intent against emitted actions ("I will edit foo.py" → did a
foo.py edit occur?). Flags asserted tool/file/test state that has no matching
observation in the trajectory (hallucinated environment state).
*Implemented (heuristic first cut):* a response that ENDS by announcing an
action it never performs trips FM-2.6; asserted-but-unevidenced success was
already FM-X.4, and sandbox execution evidence (§5.7) covers the observed-
state half.

### 5.5 Protocol monitor — FM-X.7
Schema validation of tool-call JSON / diff formats. Auto-repair via
constrained re-ask to a small model before bothering the referee.

### 5.6 Progress-curve monitor — FM-X.2, FM-2.3, FM-3.1
The continuous verifier score (§6) evaluated on trajectory *prefixes* acts as
a task-progress estimator: Kwok et al. show verifier scores rise
near-monotonically on successful trajectories (Spearman step-order
correlation 0.848) and stay flat or erratic on failing ones (0.769). Score a
cheap verifier pass every M executor steps and watch the curve:
- flat/declining over a window → stall or thrash (FM-X.2, FM-2.3) → referee
- high plateau near contract completion → supports the completion gate
- the live curve is streamed to the control plane as a per-task progress
  meter — the user's earliest intervention signal (§7.1).
Caution: the paper's success/fail correlation gap is modest (+0.08), so this
monitor triggers *review*, never automatic hard action.

### 5.7 Execution power — evidence-based verification (implemented)
Text-based verification judges what an answer *says*; the execution power
observes what the code *does*. Produced code runs in a sandbox before the
user sees it — **local** (subprocess, temp dir, timeout) or **gcloud**
(ephemeral e2-micro VM ≈ $0.008/h: create → run → delete; verified 57s round
trip) — and the transcript (exit code, stdout/stderr, doctest counts) feeds
the verifier as an added "Errors" criterion plus targeted repair feedback on
failure. The intended workflow for risky changes: test the strategy in the
VM, verify the output, then run on the host for finality — or simply copy
the VM's output back, cross-checked against it. User control: `!sandbox
local|gcloud|off|auto`; config in `models.yaml` `execution:`. The checklist
stage is likewise user-toggleable (`!checklist on|off|skip` — skip affects
only the next turn).

### 5.8 Durability layer (implemented)
Built for intense tasks and hostile conditions; every mechanism below was
validated against a real mid-session Nous outage + credential expiry:

- **Fallback chains** (`models.yaml fallbacks:`): executor, utility
  (contract/planner), and verifier calls all fail over across providers —
  a full primary-provider outage completes turns on the flat-rate channel.
- **Per-provider circuit breaker**: 2 consecutive failures open the circuit
  for 120s; calls skip the dead provider instantly instead of every stage
  independently re-probing it (which multiplied into >10-min stalls).
- **Credential self-healing**: a 401 from a Hermes-sourced provider triggers
  `hermes auth status <provider>` (re-mints the daily agent key), then
  retries — throttled to once per 5 min.
- **Task decomposition**: prompts over a size threshold *or* with visible
  multi-deliverable structure (≥3 enumerated items) are planned into 2–6
  units, each supervised (execute→monitor→sandbox→verify→repair) with unit-
  scoped verification, then synthesized. Weak units are reported, not fatal;
  only pause/budget/outage aborts remaining units.
- **Wave-parallel units**: the planner declares per-unit dependencies;
  independent units run concurrently (bounded at 3), dependent units wait
  only for their declared inputs.
- **Turn checkpointing**: the plan and every completed unit persist to
  SQLite keyed by (session, prompt). A crash, pause, or budget stop keeps
  the checkpoint; resending the identical request resumes from the first
  incomplete unit with prior spend carried in the report. Checkpoints
  delete on success and expire after 24 h. Validated live: budget-stopped
  turn resumed by a fresh orchestrator instance, re-buying nothing.
- **Verified synthesis**: the assembled multi-unit answer is itself
  cross-family verified against the original task and full contract (with
  one repair attempt), and unit-level sandbox transcripts ride along as
  evidence for both the synthesizer and the final verifier.
- **Parallel verification**: criteria are judged concurrently.
- **Turn wall-clock timeout** (default 30 min) and SSE keepalives so clients
  survive long supervised turns.

### 5.9 Cross-turn trajectory monitors (implemented)
The proxy reconstructs the session trajectory (one history row per
supervised turn: task, response, verifier score, failure events, message
count) and runs advisory monitors over it at each turn start:

- **FM-1.3 step repetition** — ≥2 recent turns lexically near-identical to
  the current request: the driving agent is retrying without incorporating
  results.
- **FM-X.2 breadth thrash** — ≥4 rapid, mutually dissimilar, low-scoring
  turns: shallow approach-hopping with no candidate carried to depth.
- **FM-1.4 context loss** — the conversation shrank versus the maximum seen:
  client-side truncation or reset.
- **Progress stall (§5.6 realization)** — verifier scores flat-or-declining
  below threshold across turns. Advisory only, per the paper's modest
  success/fail correlation gap.

These surface as `[Conflux] cross-turn:` trailer lines and trace events —
never as automatic repairs, because the misbehaving party is the *driving*
agent, and correcting it is the user's call (SPEC's intervention principle).

### 5.10 Learned routing (implemented)
Every unit outcome (executor, verifier score, attempts, failure events)
accumulates in per-model stats (`/admin/stats`). With `routing.learned:
true`, the router picks the executor with the best average score once it
has `min_samples` turns; `!use <model>` always overrides; static default
otherwise. The §M4 repair loop is closed: every repair attempt writes a
(model, failure mode, strategy, success) row, and the referee's
switch-model candidate order puts learned repair success on the observed
failure modes ahead of the static failure-prior heuristic — so "which
model actually fixes FM-X.1" is learned from this installation's history.
The efficiency report (§8) exposes whether repair spend trends down.

### 5.11 Session monitors — FM-2.1, FM-1.5 (designed)
On the reconstructed session: sudden context-prefix shrinkage (client
truncation → warn user), conversation restarts, and turn-count/termination
watchdogs.

Monitors run on the **stream**, not just final output — catching FM-X.1 at
token 500 instead of token 8,000 is where much of the cost saving lives.

---

## 6. Cross-model verification policy

Scoring mechanics adopt **LLM-as-a-Verifier** (Kwok et al., Stanford/UC
Berkeley/NVIDIA, [arXiv:2607.05391](https://arxiv.org/abs/2607.05391)):
instead of asking the verifier for a discrete pass/fail or 1–5 score, prompt
it for a score on a 1–20 scale and compute the **expectation over the scoring
token's logprob distribution**, yielding a continuous reward in [0, 1].
Discrete judge scores tie 27% of the time on hard comparisons; the continuous
formulation eliminates ties and raises pairwise verification accuracy
(73.1% → 77.5% on Terminal-Bench in the paper). Logit access constrains
provider choice: **NanoGPT was tested empirically (2026-07-16) and does not
return logprobs** — it accepts `logprobs`/`top_logprobs` without error but
returns `logprobs: null` for DeepSeek V3.2, GLM-4.6, Gemma 3 27B, and Qwen
(Qwen3-235B/32B, Qwen2.5-72B) in both documented parameter styles and on the
legacy completions endpoint — notable because Qwen is the paper's verifier
backbone. Pinning each of DeepSeek V3.2's 15 available upstream providers via
`provider: {only: [...]}` (incl. DeepInfra, Novita, SiliconFlow — vLLM shops
whose own APIs do return logprobs) also yields `logprobs: null` in every
case, so the field is stripped in NanoGPT's response normalization layer, not
by the upstreams. Their docs claim pass-through ("forwards the request to
providers that support returning token-level log probabilities"; response
schema lists `logprobs` "returned where supported") — worth a support ticket,
but do not design against it.

Provider logprobs matrix (tested 2026-07-16 unless noted):

| Backend | logprobs | Notes |
|---|---|---|
| NanoGPT | ✗ | null across 5 model families, 15 pinned providers, both endpoints |
| Ollama Cloud | ✗ | null on OpenAI-compat endpoint; native `/api/chat` has no logprob fields at all (engine limitation) |
| OpenCode Zen (PAYG, `/zen/v1`) | ✓ | full top-20 per generated token; verified end-to-end with the 1–20 scoring recipe on `deepseek-v4-flash-free`. Paid PAYG models blocked (workspace credits at zero) |
| OpenCode Go (subscription, `/zen/go/v1`) | partial, per-model | DeepSeek V4 Pro ✓ (top-5; `top_logprobs: 20` trips a gateway JSON-escaping bug on exotic alt tokens); Qwen 3.7 Plus ✓ (Alibaba upstream caps `top_logprobs` at 5); GLM-5.2 ✗ (chosen-token logprob only, no alternatives); Kimi K2.6 ✗ (empty alts; explicit `top_logprobs` errors upstream); MiniMax M3 ✗ (null) |
| Nous inference API (Hermes subscription, `inference-api.nousresearch.com/v1`) | ✓ best hosted option | 281-model aggregator. Hermes-4-405B ✓ top-20; DeepSeek V4 Pro ✓ top-20 (no escaping bug here); Gemma 4 31B ✓ top-20; Qwen 3.7 Plus ✓ top-5 (Alibaba cap; 400 error above 5); Kimi K2.6 ✓ top-5 (top-20 request returns malformed JSON) — **regressed to ✗ by 2026-07-17**, 0/6 probe samples, dropped from the verifier pool; GLM-5.2 ✗ null (Z.ai upstream, consistent with Go finding) |
| DeepInfra / Novita / SiliconFlow direct | ✓ (docs) | vLLM-based; untested by us |
| Local vLLM / SGLang / llama.cpp | ✓ | reference path for the verifier scoring pass | Therefore NanoGPT-served models are executors
and stage-1 reasoners only; the scoring pass runs on a logprob-exposing
backend (local vLLM/SGLang/llama.cpp, or direct provider APIs that return
logprobs), per the paper's two-stage workaround (Appendix B.6: closed model
writes the reasoning, open model's logits produce the continuous score —
recovers +5.2 pts over the closed model's own discrete scores, zero ties).

Verification effort has three tunable axes ("verification scaling"), which
give the risk tiers concrete knobs:

- **G** — score-token granularity (1–20 scale beats coarse scales)
- **K** — repeated evaluations, averaged (variance ↓ as 1/K)
- **C** — criteria decomposition: score each contract constraint / failure
  dimension separately and ensemble, rather than one monolithic "is it
  correct?" (75.2–76.4% single-criterion → 78.3% ensembled). Our FM-keyed
  contract checklist *is* the decomposition — each constraint and relevant
  FM mode is a criterion.

Policy:

- Verifier model ≠ executor model **family** (uncorrelated failure priors).
  Validated by the paper's SWE-Bench result: a verifier selecting among
  candidates from *different model families* (78.2%) beat every individual
  model in the pool (best: 76.8%).
- Verification is **evidence-based**: verifier receives the contract, the
  output, and trajectory observations (test output, tool results) — and must
  cite evidence for "pass". An unevidenced pass is itself an FM-3.3 event.
- Verification depth is **risk-tiered** to control cost:
  - *lite* — small model, contract checklist only, G=20, K=1
  - *standard* (default) — mid model + evidence citation, G=20, K=3–8,
    C = contract constraints
  - *adversarial* — verifier explicitly prompted to refute; K≥8, full
    criteria decomposition, optionally a second verifier family — for
    high-risk units, prior failures on this task, or user-flagged work.
- Verifier disagreement → referee, never silent acceptance.

### 6.1 Best-of-N across models (un-deferred)

Best-of-N sampling across model families was deferred in v0.0 on cost
grounds; the paper's **Probabilistic Pivot Tournament (PPT)** makes it
tractable: rank N candidates with O(N·k) pairwise verifications instead of
O(N²), using a random ring pass (cancels the verifier's positional bias) to
pick top-k pivots, then comparing all candidates against pivots only.

*Implemented (pointwise variant) as user-selectable answer strategies* —
`!strategy` (dashboard: Steering → strategy). Every plain turn produces its
answer by one of five modes:

- **single** (default): one supervised executor — forced (`!use`) >
  learned routing > static default.
- **exploit**: strictly the best-ranked executor from outcome history
  (`model_stats`), ignoring `min_samples` and the learned toggle — "just
  use the ranking winner".
- **best `<2-4>`**: N model families in parallel (family choice reuses the
  referee's repair-prior ordering), each candidate cross-family verified
  with sandbox execution evidence (produced code runs before scoring, same
  as the unit path); the top-scoring candidate is returned as-is. ~N× cost.
- **union `<2-4>`**: as `best`, then a merge prompt demanding the **set
  union** — every distinct valid element from ANY candidate, deduplicated,
  contradictions resolved toward demonstrable correctness. ~(N+1)× cost.
- **fuse `<2-4>`**: as `best`, then a synthesis prompt keeping the
  strongest elements of each candidate (`!ensemble <2-4>` remains as an
  alias for this original mode). ~(N+1)× cost.

Merged answers (union/fuse) are themselves verified and must out-score the
best candidate to win — otherwise the best candidate is returned and the
rejection is traced. `!cutoff <0-1>` adds a verifier **short-circuit** to
the multi-candidate modes: the first candidate scoring at or above the
cutoff wins immediately and pending candidate tasks are cancelled (note:
already-in-flight provider calls may still bill). Every stage is
budget-gated; total provider outage degrades to the normal supervised
unit. Ranking uses pointwise continuous scores (no ties, so no pairwise
tournament is needed); PPT remains the upgrade path if pairwise comparison
ever proves more discriminating than pointwise at equal cost. This also
answers "can outputs of several models form the next prompt" generally:
unit outputs already feed dependent units and synthesis (§5.8), and the
union/fuse strategies do it for N answers to the *same* task.

---

## 7. Human intervention (primary design constraint)

The user must be able to **see, stop, steer, and rewind** the system. Design
rule: *the orchestrator may not take an irreversible or budget-exceeding step
without a checkpoint the user could have intercepted.*

### 7.1 Control-plane surface
Local web UI (+ CLI equivalents) attached to the orchestration core.
*Implemented (first cut) at `/` on the proxy:* status tiles, steering
controls (pause/resume, executor forcing, budget, checklist, sandbox, plan
mode, answer strategy + N + short-circuit cutoff — same semantics as the
!commands), breakpoint rules (add/clear from the Steering panel or
`!break`), a Routing panel (runtime overrides for
default/utility/referee/trivial executors, learned routing, verifier pool,
and per-model **provider rotation chains** — each model's ordered failover
list, reorderable/editable per model — `/admin/routing`; models.yaml
persists), a Load-balancing panel
(`/admin/balance`: per-provider 5h/week/month window usage vs the limits
declared in `providers.<name>.limits`, with subscription channels re-priced
at nominal twin rates, "≈ N requests left" estimates matching how the Go
docs express limits, and live circuit/cooldown state), a Pipeline panel
(live SVG graph of the followed turn built from trace events — goal →
contract → parallel candidates / unit DAG / attempt chain → merge →
result; nodes reconcile in place each refresh, the current stage pulses,
new nodes animate in, cancelled candidates dim; auto-follows the latest
turn or pins one via its task card's "⛓ graph" button), task cards with
verification score bars, a per-task "⧉ request" quick-copy (the exact
request text — locator for editing/rewinding that message in the client,
and the checkpoint-resume key when resent verbatim), an **edit history**
per conversation (every divergence of the incoming message prefix — a
client-side edit or rewind — is detected against the last recorded
request, stored as a numbered branch with old→new text, and shown above
the task list and via `!edits`; superseded branches' turns and payloads
remain in the trace, so nothing edited away is lost; caveat: sessions are
keyed by the first user message, so editing that one starts a new
session), failure-mode badges
with cross-turn advisories, escalation callouts, per-model outcome stats,
and the raw event feed; 2s polling, light/dark.
Remaining from the full vision below: per-node streaming output and
edit-the-plan steering (rewind is unit-granular, not free-form).

- **Live trace view**: task tree (plan → units → attempts), per-node model,
  tokens, $, FM events with evidence spans; streaming output per node; a
  per-task **progress meter** driven by the continuous verifier score on
  trajectory prefixes (§5.6) — so a stalling task is visible before it burns
  budget or commits broken state.
- **Pause / resume**: global, or scoped to one branch of the task graph.
  Pause points are graph-node boundaries (guaranteed) plus stream
  cancellation (best-effort immediate).
- **Kill**: hard-stop the graph; the proxy returns a clean "interrupted by
  user" completion to the client so the client isn't left hanging.
- **Steer**: edit the contract/plan/next-node prompt before resume; force a
  routing decision ("use Kimi for this unit"); inject a user note the referee
  must honor; skip or re-run a node.
- **Breakpoints** *(implemented)*: user-set rules that force a pause, set
  via `!break fm:<FM-ID> | budget:<usd> | escalation` (or the dashboard).
  A matching rule pauses the supervisor mid-ladder; paid work stays
  checkpointed, and `!resume` + resend continues. The fm rule fires before
  verification spend; budget is a soft threshold under the hard cap;
  escalation fires when the referee picks a structural strategy. (A
  file-write rule awaits workspace-write mediation, which the proxy does
  not have yet.)
- **Rewind / replay** *(implemented, unit-granular)*: `!checkpoints` lists
  this conversation's resumable checkpoints with per-unit status;
  `!rewind <unit#>` forgets one completed unit so resending re-runs it
  (other units stay paid-for); `!rewind all` restarts the turn.

### 7.2 Intervention through the client (no extra window)
Because many users will live in their OSS client, the proxy also supports
**in-band control**: magic user-message prefixes (`!pause`, `!plan`,
`!budget 0.25`, `!use glm`) intercepted at ingress and never forwarded to
models, and supervisor notices injected into the response stream as clearly
delimited status lines (off by default per config).

*New-conversation gate (implemented — `supervision.confirm_new_sessions`,
runtime `!gate on|off`):* the ingress starts every unknown conversation in
"dumb command mode" — in-band `!commands` always work without any model
call, and the first non-command message returns a warning (no model called,
nothing spent) stating the session id, active strategy, and budget, plus
the session-identity rule (conversations are keyed by their first user
message, so clients that rewrite/annotate it fragment into new
conversations). Continuing or resending confirms and runs normally.
Motivated by a live Hermes hookup: agent clients silently spawn new
sessions on every prefix rewrite, and each was getting a full supervised
turn. Explicit passthrough model names are exempt (naming a raw model is
already an explicit choice).

*Conversation navigation (implemented):* `!conversations` lists recent
sessions (id · age · turns · title, current one marked) and
`!attach <id-prefix>` pins the CURRENT client thread onto an existing
conversation via a persistent session-alias table (`!attach off`
detaches). Both are ingress-only — no model call. This is the deliberate
answer to client prefix rewrites: no heuristic session linking; the user
stitches threads explicitly, and checkpoints/edit history/context follow
the attached conversation.

### 7.3 Escalate-to-human as a repair strategy
`ASK USER` is a first-class referee action (targets FM-2.2 — the system
itself must not fail to ask for clarification): the stream returns a concrete
question + options, and the task graph parks at a checkpoint until the reply
turn arrives.

---

## 8. Cost model

- Per-task budget envelope (default, e.g. $0.50) with soft threshold →
  breakpoint, hard threshold → pause. Per-session daily cap.
- Router chooses executor tier by estimated difficulty (small-model
  classifier over the contract) — Gemma-class for mechanical edits,
  mid for routine coding, large only for genuinely hard units.
- Ledger records $/token/latency per node → a `report` view shows spend by
  role, by model, and **spend on repair vs first-pass**, the core efficiency
  KPI: *supervision overhead should be < 15% of tokens; repair spend should
  trend down as routing priors learn.*
- Early stream cancellation on monitor tripwire (§5) is a first-class saving.
- Prompt-prefix caching per provider where available; contract/plan reuse
  across turns in a session.

---

## 9. Implementation notes

- **Orchestration engine: LangGraph** (Python). Chosen because its primitives
  map 1:1 onto hard requirements: `interrupt()` → pause/approval gates and
  breakpoints (§7); **checkpointers** (SQLite for v1) → rewind/replay and
  crash recovery; graph streaming → the live trace view; subgraphs → per-unit
  supervision loops. We write the graphs in code; **LangFlow** is kept as an
  optional visual layer for inspecting/editing flow definitions, not as the
  runtime of record.
- **Auto-generated loops**: the detect→feedback→retry→escalate repair loop is
  a parameterized subgraph *template*, instantiated per failure mode from a
  small spec (`fm_id, detector, feedback_template, max_attempts, escalation`).
  Adding coverage for a new failure mode = adding a row of config + a
  detector, not new graph code. (This is the LangGraph/LangFlow
  "auto-generate loops" idea, made concrete and bounded — generated loops
  always inherit the anti-loop rule and budget gates from §4/§8.)
- **Ingress**: FastAPI, OpenAI-compatible (`/v1/chat/completions`,
  `/v1/models`, streaming SSE, tool calls). Session reconstruction via
  conversation-prefix hashing.
- **Providers**: OpenAI-compatible upstreams (DeepSeek, GLM/Z.ai, Moonshot,
  OpenRouter, local Ollama/vLLM for Gemma-class) behind one thin adapter;
  `models.yaml` holds cost, limits, and failure priors.
- **Trace store**: SQLite; every event is `(task, node, fm_events, tokens, $,
  ts)`; export to JSONL for offline analysis / future MAST-style annotation.
- **Control plane**: FastAPI + small web UI (v1 can be a TUI); talks to the
  core over the same event bus the trace store consumes.

## 10. Milestones

1. **M0 — Pass-through proxy**: OpenAI-compatible ingress → single upstream,
   trace store, session reconstruction. OpenCode/Aider work through it.
2. **M1 — Supervised single-executor**: contract extraction, completion +
   contract monitors (heuristics + Gemma judge), retry-with-feedback loop,
   budget gates. *Measurable goal: catch seeded FM-X.1/FM-1.1 failures.*
3. **M2 — Cross-model verification & referee** *(implemented)*: verifier
   role; referee (`referee.py`) — on verification failure the first
   `max_repairs` retries carry targeted feedback (a rule, no referee spend),
   then a large-model referee must pick a STRUCTURAL strategy: switch to an
   untried model family (candidates ordered by learned repair success on the
   observed failure modes, then uncorrelated failure priors), escalate to
   adversarial verification, decompose into planner units, or ask the user;
   a referee outage falls back to a deterministic reroute. Difficulty
   routing: the contract call also classifies {trivial, routine, hard} —
   trivial goes to `routing.trivial_executor` with lite verification, hard
   is offered to the planner. Verification tiers (§6) implemented: lite /
   standard / adversarial (refute-framed, higher K, contract constraints
   decomposed into criteria). Verifier candidate order is failure-prior
   aware. All routing options are editable at runtime from the dashboard
   Routing panel (`/admin/routing`; in-memory — models.yaml persists).
4. **M3 — Control plane** *(implemented)*: live trace UI, pause/steer/kill,
   in-band `!commands`, breakpoint rules (fm / budget / escalation), and
   unit-granular checkpoint rewind (`!checkpoints`, `!rewind`). Remaining
   from the full §7.1 vision: per-node streaming output, free-form
   plan-editing before resume.
5. **M4 — Learning routing** *(implemented)*: repair outcomes accumulate in
   a repairs table (model × failure mode × strategy × success) and bias the
   referee's switch-model choice toward families that have actually fixed
   the observed failure modes; efficiency report (`conflux report`,
   `/admin/report`, dashboard Efficiency panel) — spend by role, repair vs
   first-pass share, supervision-overhead KPI vs the §8 targets, daily
   repair-share trend; in-turn monitors: FM-2.6 reasoning–action gap
   (response ends announcing an action it never performs) and in-turn
   FM-1.3 (a repair attempt near-identical to its predecessor is advisory
   for verification but sends the referee structural immediately — more
   feedback is provably pointless).

## 10.5 Conversation library & extraction (implemented)

Conversations (sessions) are grouped under **projects**; each project carries
**extraction settings** that fall back field-by-field to one editable global
default, and the dashboard shows per field whether a value is inherited or
overridden (with a reset control). `export.py` "pops out" a session or project
into a single `.llmx` container:

- **Compression**: xz (default, ~9% of raw) / gzip / none.
- **Encryption** (optional, AES-256-GCM AEAD): *passphrase* with a
  user-chosen KDF (scrypt / Argon2id / PBKDF2, tunable params), or
  *public-key* hybrid (X25519 raw-base64, or RSA-OAEP PEM) — encrypt to a
  recipient who holds the private key.
- **Destination**: a saved directory, or a user command template
  (`gcloud storage cp {file} gs://…`, `rclone …`) for push-to-cloud.
- Delete is enabled for sessions and projects (deleting a project reparents
  its sessions to Default).
- Surfaces: dashboard sidebar + settings panel, `/admin/export`, and
  `conflux export --session|--project [--passphrase]`.
- **Retention** (`retention.py`): independent age limits for message
  payloads / trace events / turn history (0 = keep forever); auto-pruned
  hourly by the server, plus a dashboard "Prune now" and `conflux prune`.
  Session/project metadata is never pruned (old conversations still list;
  export before payload expiry). File space is reclaimed live: the db uses
  `auto_vacuum=INCREMENTAL` (migrated automatically at server startup, or by
  the first successful prune on a legacy file), so prune frees deleted pages
  with `incremental_vacuum` even while the server's other connections are
  open. Only an unmigrated legacy db can defer compaction to a later pass
  (`vacuum deferred: db busy`); deletion always bounds growth regardless.

### TODO (later) — blob-stripping compression
For maximum compression, strip from the bundle any large output blob that is
*deterministically reconstructible* by replaying the tool commands recorded
earlier in the conversation (build artifacts, large tool outputs, generated
files). Replace each with a reference + the command that produces it, and ship
alongside the export a minimal **input archive** (the source files those
commands need) so the outputs can be regenerated on import. This trades a
replay step at restore time for a potentially large size reduction on
tool-heavy agent conversations. Requires: a reconstructibility classifier
(which tool outputs are pure functions of recorded inputs), the input-archive
collector, and a verified `import --rehydrate` path.

## 11. Open questions

- Session reconstruction fidelity: how reliably can trajectories be rebuilt
  from stateless completion calls across clients that rewrite history
  (compaction)? May need per-client quirk handling.
- Latency budget: how much supervision latency will an interactive user
  tolerate before it must move to optimistic streaming + retract-on-fail?
- Verifier calibration: measure verifier false-pass rate against seeded
  failures before trusting risk-tiering (guard against FM-3.3 in our own
  verifier). Kwok et al.'s results use Gemini 2.5 Flash / Qwen 3.6 35B as
  verifiers; we must confirm Gemma-class models retain enough of the
  continuous-scoring advantage, or route verification to a mid-tier model.
- Best-of-N is now in scope via PPT (§6.1), but *when* to spend on N>1
  candidates (always for hard units? only on referee escalation?) needs
  empirical routing priors.

## 12. References

- Cemri, Pan, Yang et al., *Why Do Multi-Agent LLM Systems Fail?* (MAST),
  [arXiv:2503.13657](https://arxiv.org/abs/2503.13657) — failure taxonomy
  (imported in [`docs/failure-taxonomy.md`](docs/failure-taxonomy.md)).
- Kwok et al., *LLM-as-a-Verifier: A General-Purpose Verification Framework*,
  [arXiv:2607.05391](https://arxiv.org/abs/2607.05391) — continuous
  logprob-based verification, verification-scaling axes (G/K/C),
  Probabilistic Pivot Tournament, verifier-score-as-progress (VOC),
  TurboAgent proxy.
