# Supervising Cheap Open-Weight Models: Field Notes from Conflux on Cross-Family Verification and Governed Tool Use

*Technical report · 2026-08-22 · repo state `226a6e7` (branch `feat/unified-conversation-graph-ui`)*

> **What this document is.** An evidence-graded account of the Conflux
> system as it exists in the repository, written after a code audit of
> `conflux/` (22,984 LOC; 276 unit tests passing), a read of every
> document in `docs/`, and direct queries of the checked-in `traces.db`
> (80 sessions, 1,306 agent/supervised turns, 1,014 governed tool actions,
> $15.25 total provider spend, 2026-07-17 → 2026-07-21). It is **not** a
> venue-ready research paper; §8 says exactly what is missing. Every claim
> carries an evidence grade:
>
> | Grade | Meaning |
> |---|---|
> | **E1** | Measured; N stated; reproducible from `traces.db` or the harness |
> | **E2** | Single live run or narrative field report; qualitative |
> | **E3** | Implemented and unit-tested, but no efficacy measurement |
> | **E4** | Designed/specified only |

## Abstract

conflux is an OpenAI-compatible proxy that places a supervision loop in
front of inexpensive open-weight models (DeepSeek, GLM, Kimi, Qwen, Gemma)
served through commodity aggregators. For plain chat turns it extracts a
contract, runs the executor, executes any produced Python in a sandbox
(local or an ephemeral GCE VM), scans the answer with failure-mode
monitors, grades it with a verifier from a *different model family* using
the expected score over a one-token letter scale (after Kwok et al., 2026),
and runs a bounded repair/escalation ladder. For agentic tool-calling
loops it interposes an *action governor* that classifies each proposed
tool call, obtains an independent cross-family critique for non-trivial
ones, can substitute a governor-authored read-only probe through the
client's own tool protocol, gates irreversible actions on an operator, and
runs a post-hoc falsification check on claimed effects.

The system works end to end and has been exercised on real workloads
(a NetBSD/AArch64 cross-build and QEMU boot, an OP-TEE secure-world
bringup with a custom NetBSD kernel driver (agent-reported), a multi-hour
governed service migration, three Terminal-Bench 2.1 tasks). Its durable
contributions are *engineering findings* rather than a new method:
(i) a measured map of which hosted channels actually return logprobs and
a demonstration that aggregators silently degrade continuous verification
to discrete judging (0/27 continuous reads on two channels, E1);
(ii) the observation that digit scores tokenize into multiple tokens on
Qwen and corrupt the expectation read, fixed by a letter scale (E2);
(iii) a field measurement that verifier verdicts are effectively binary
in practice (79% of 84 live verdicts at ≤0.05 or ≥0.95, E1), which
collapses best-of-N to first-past-the-post; (iv) a governance protocol —
probe substitution plus independent falsification — that, over 1,014
governed actions, blocked 151, routed 173 to an operator, and failed
71 of 217 soundness checks against the executor's own success claims
(E1, no baseline). Efficacy claims (that supervision improves task
outcomes over the raw model) are supported only by one six-run case study
(E2) and are explicitly not established.

The project's stated thesis is broader than supervision: a *graph-first*
working environment in which the conversation is a dependency DAG, each
assistant message owns an editable workflow instance, and verification is
a node in that graph. A second audit of that layer (§2.5, F9) finds the
conversation-DAG half implemented and tested — revisions, descendant
invalidation, automatic dependency-ordered re-runs, per-message workflow
overrides — while the runtime still executes a fixed pipeline rather than
the authored topology, and verification nodes are displayed, not placed or
configured.

## 1. Problem and design bet

Open-weight models served cheaply fail in characteristic ways: premature
termination and stubs ("rest omitted for brevity"), unsupported success
claims, sycophantic compliance with false premises, and format drift.
The project imports the MAST taxonomy (Cemri et al., 2025) and extends it
with seven single-model modes (`docs/failure-taxonomy.md`, FM-X.1–X.7).
MAST's own finding — that self-verification gave modest gains while
*independent* verification gave larger ones — is the design bet: every
answer is judged by a model from a different family than the one that
produced it, and executable claims are settled by running the code.

Two secondary constraints shape the system: it must be a drop-in for
existing clients (OpenCode, Aider, Hermes) with no plugin, and a human
must be able to see, steer, pause, and cap it from inside the chat
(`!status`, `!pause`, `!budget`, `!use`, …).

## 2. System

### 2.1 Supervised text turn (`orchestrator.py:1159`, `_supervised_unit` at `:296`)

1. **Session monitors** (deterministic Jaccard/count heuristics over the
   reconstructed trajectory; advisory only).
2. **Contract extraction** — one call to a cheap utility model (Gemma,
   ≈$0.0001) returning explicit constraints and a difficulty label
   (`contract.py:40`). Failure degrades to an empty contract.
3. **Difficulty routing** — `trivial` → lite verifier tier.
4. **Planner** (optional, `planner.py`) — decomposes long or enumerated
   prompts into a DAG of units executed in waves of 3, each supervised and
   checkpointed to SQLite; synthesis is itself verified.
5. **Execute** via a provider fallback chain with a per-provider circuit
   breaker and credential self-healing (`providers.py`, `keys.py`).
6. **Sandbox** — the first ```` ```python ```` block is run with
   `python3 -I` locally or on a disposable Spot e2-micro created and
   deleted per run (`sandbox.py:96-176`); doctests are executed; the
   transcript becomes verifier evidence and repair feedback.
7. **Monitors** — regex detectors for FM-X.1 (stubs), FM-X.4 (unsupported
   success claims), FM-2.6 (reasoning–action mismatch), FM-3.1 (premature
   termination) (`monitors.py:22-119`).
8. **Verifier** — 3 criteria (Specification, Completeness, Output
   quality; +Errors when execution evidence exists; +contract criteria at
   the adversarial tier), each a separate call to a cross-family model
   (`config.py:172-190` is a hard filter on `family != executor_family`).
   The model reasons, then emits `<score>X</score>` with X ∈ A..T; the
   score is the renormalized expectation over the letter tokens found in
   the returned `top_logprobs` at that position (`verifier.py:107-140`).
   Pass iff the normalized mean ≥ 0.70 **and** no monitor fired.
9. **Referee** — attempts 1–2: deterministic `retry_feedback`; attempt 3:
   an LLM referee chooses among `switch_model | escalate_verification |
   decompose | ask_user`; attempt 4 is the single structural retry; then
   escalation to the user with the best attempt labelled (`referee.py:118-145`).
10. **Budget** — a per-task dollar cap (default $0.50) debited by every
    role, checked at loop top and before each wave.

Answer strategies `single | best N | union N | fuse N` run N candidates
concurrently (with a verifier cutoff short-circuit) and either pick the
best-scored one or merge them with an LLM call that is re-sandboxed and
re-verified (`orchestrator.py:592-778`).

### 2.2 Governed tool turn (`governance.py`, `orchestrator.py:1038`)

When the upstream model returns `tool_calls`, the governor reviews each
before it is released to the client:

- **Proposal** — arguments parsed; targets extracted from argument keys,
  shell tokens, and `ast`-parsed string constants inside `python -c`
  sources (`:466-606`).
- **Deterministic assessment** — risk ∈ {low, medium, unknown, high}
  from a tool manifest (`tool_manifests.yaml`: side-effect class,
  `allowed_targets` globs) plus ~20 shell hygiene checks: command
  substitution, heredocs, redirection, masked exit status (`;`, `||`,
  pipes without `pipefail`, trailing `echo`), SQLite CLI without
  `-readonly`, verifier scripts that collect errors but exit 0, and
  command-name tables (`:725-1056`).
- **Hard gates** — schema, target scope, exit-status propagation,
  duplicate non-idempotent fingerprints, and "use exactly N tool calls"
  limits parsed from the task block without any model call (`:1742-1889`).
- **Independent critique** — every non-low action goes to a cross-family
  model at temperature 0 returning `approve | rewrite | block | probe |
  human`; malformed output fails closed (`:1587-1659`).
- **Probe substitution** — on `probe`, the governor authors a read-only
  tool call using a tool the client already exposes, returns *that* call
  in place of the original, stores the original as `probe_pending`, and
  on the next request re-critiques with the probe result marked untrusted
  before releasing the stored original verbatim (`:2027-2069, 2154-2242`).
- **Operator gate** — all `high` actions, critic `human` verdicts, and
  retries of a previously failed action wait for a fingerprint-bound,
  one-shot approval (`:1209-1220`).
- **Post-check and soundness** — the tool result is checked for
  `ok`/`exit_code`/error strings (`:2708-2757`); any non-low action that
  passes then goes to a cross-family *falsification* step that may spend
  exactly one read-only probe and must not merely re-read the action's
  own target (`:2284-2324, 2395-2446`); its `accept | fail` sets
  `completed` vs `postcheck_failed`.

### 2.3 Durable jobs and execution lock (`durable_jobs.py`, `execution_backends.py`)

Long work runs through five typed tools (`start/watch/inspect/signal/
collect_locked_job`) that carry no backend or target arguments; the
adapter re-asserts its immutable identity on every call and refuses
model-supplied retargeting (`execution_backends.py:138-143`). Remote jobs
run under a wrapper in a new session with a 1 s heartbeat file and
normalized exit codes; watches are cursor-exact (rewinds and skips are
rejected); signals verify process-group ownership before `killpg`. GCE
and Docker adapters differ only in transport (`:872-909`).

### 2.4 Observability

Every model call, monitor hit, verdict, governed action, approval, and
checkpoint is written to SQLite (`trace.py`). Four UIs (Live, History,
Agent Graphs, Workspace) render it; `agent_flows.yaml` declares the
intended graph and the runtime validates that observed transitions follow
declared edges (it does not drive execution — see §6).

### 2.5 Graph workspace (`conversation_graph.py`, `workspace.py`, `workspace_ui.py`)

Two graph layers sit beside the trace DB. The **conversation graph**
(`workspace_endeavors → workspace_conversations → workspace_nodes/edges`)
stores each exchange as a user/assistant node pair chained by `next`
edges, with `depends_on` edges and recursive ancestor/descendant queries
(`conversation_graph.py:405-462, 535-565`). For workspace-originated
messages the graph *is* the prompt source: `prompt_messages()` rebuilds
the LLM message list by walking ancestors (`:680-701`). Every assistant
node owns a **workflow instance** — a copy of the `agent_flows.yaml`
graph or of a stored override (`:724-760`) — which the `/workspace` UI
lets the user edit per message or promote globally ("apply globally" →
`workspace_workflow_overrides`, `:848-868`). Editing any node snapshots a
revision, marks all descendants and their workflow instances `stale`, and
queues a dependency-ordered re-run under a per-conversation lock
(`:567-632`; `workspace.py:127-210`). `human_input` nodes gate execution
before any model call; `context`/`store_read`/`store_write` nodes are
executed by the service and become real prompt inputs.

What the runtime consumes from an edited instance is a flattened plan
(`workflow_plan()`, `:978-1004`) reduced to `TurnOptions`: executor
prompt/model, ensemble strategy/N/temperatures/cutoff, and a free-text
addendum to verifier constraints (`workspace.py:365-384`,
`orchestrator.py:1171-1287`). Edges, conditions, order, and node removal
are validated and displayed but not executed; the orchestrator runs the
static `supervised_tool_turn` pipeline and maps its events back onto the
instance's nodes for display (`workspace.py:246-261`).

## 3. Findings (the part worth keeping)

### F1. Hosted channels silently drop logprobs; verification degrades to discrete judging without notice. — E1

Probing 5 model families across 4 aggregators (SPEC §6; commits
`14516fd`…`21d79ff`): NanoGPT accepts `logprobs=true` and returns nothing
across all 15 selectable upstreams; Ollama Cloud has no support; the Nous
API serves 5/6 families with logprobs; OpenCode Go serves DeepSeek and
Qwen. Presence is flaky *per request* even on good channels. The
calibration run `2a4a905e4a27` (45 rows, 5 verifiers × 9 answers)
quantified it: DeepSeek-on-Nous and Gemma-on-Nous returned a usable score
distribution in **0 of 27** calls each; the same DeepSeek weights via the
Go channel returned one in 24/27; Qwen 27/27 on both channels. Any system
that assumes the provider honours `top_logprobs` is, on these channels,
running a discrete LLM-as-judge while believing it runs a continuous one.
The harness now records `continuous` per verdict so this is detectable.

### F2. Digit scores are multi-token on Qwen; a letter scale is one token on every tokenizer tested. — E2

Reading the distribution at the second token of "20" graded a perfect
answer 1.3/20. Scores must be a single capital letter A–T; one tokenizer
additionally fused the letter to the closing tag (`>T`) and the locator
must unfuse it (`verifier.py:99-104`). Kwok et al. do not report this
failure mode; it is specific to deploying the method over tokenizers one
does not control.

### F3. In the field, verifier verdicts are effectively binary. — E1

Of 84 live `verify` events in `traces.db`, 41 scored ≤ 0.05, 25 scored
≥ 0.95, and only 18 fell between. All five passing candidates in the
2026-07-17 strategy exercise scored ≥ 0.99999; a best-of-2 "winner" beat
the runner-up by 1×10⁻⁷. Consequences observed live: best-of-N degenerates
to first-past-the-post (decided by verify latency), any cutoff ≤ 0.99
always fires, and the union-merge gate `score ≥ best` passes trivially.
Part of the cause is structural: the pool verifiers are configured with
`top_logprobs = 5` (`models.yaml`), so at most 5 of 20 letters are ever
observed and the expectation is pulled toward the mode.

### F4. Mechanical evidence, not model opinion, catches false premises. — E2

Six runs of one task that embedded a nonexistent
`datetime.fromisoformat(strict=True)` (`docs/ensemble-vs-solo-2026-07-17.md`):
all three solo models (DeepSeek, GLM, Qwen) complied and shipped
confident modules that raise `TypeError` on first call; Qwen invented
full semantics for the flag. No model, solo or supervised, *refused* the
premise. The supervised `union 2` run refused to bless anything
(sandbox failure → all candidates ≈ 0.00 → honest escalation); the
supervised `single` run fed the crash back three times and the LLM
referee emitted a correct root-cause diagnosis and an `ask_user`
(`traces.db` referee event: "impossible constraint — `datetime.fromisoformat`
has no `strict` parameter"). This is one task; it is an existence proof,
not a rate.

### F5. Seeded calibration: zero false-passes on blatant flaws across five verifiers; discrimination 0.94–1.00. — E1 (floor only)

9 seeded answers (3 good, 6 flawed: stub, unsupported "all tests pass",
ignored constraint, wrong arithmetic, wrong question) × 5 verifiers:
false-pass 0/6 for every verifier, mean good 1.00, mean flawed 0.00–0.06.
With n=6 the rule-of-three upper bound on the false-pass rate is ≈0.5;
the suite has no near-miss answers, no human labels, no held-out set, and
one case's contract contains the answer. It measures the floor.

### F6. Governance at scale of ~1,000 actions: what the governor did. — E1 (descriptive, no baseline)

`governed_actions` (2026-07-19 and 2026-07-21; Phoenix Ledger migration,
durable-job ladder, Terminal-Bench `gpt2-codegolf`):

| | count |
|---|---:|
| proposed actions | 1,014 |
| risk low / medium / unknown / high | 553 / 55 / 251 / 155 |
| deterministically or critic-blocked | 151 |
| operator approval requested / denied | 173 / 64 |
| completed | 660 |
| post-check failed (tool envelope) | 126 |
| critic verdicts (approve / block / human / rewrite / probe) | 246 (189 / 28 / 18 / 9 / 2) |
| soundness checks accept / fail | 146 / 71 |
| total governance LLM spend | ≈ $1.12 |

The 71 soundness failures are the most interesting rows: e.g. an executor
that "ran `/app/gpt2`" with exit 0 whose stdout was a separator line, not
generated text; an executor that re-ran a known-broken binary and claimed
repair. 57 of the 71 are the deterministic rule that a checker probe
"merely rereads an action target" and is therefore not independent
evidence. What cannot be said from these numbers: how many blocks were
false positives (one logged block is literally annotated "False-positive
read batch from classifier"), or what would have happened without the
governor.

### F7. Long-horizon field deployments completed their targets; the system's own deficiency logs are the best record of what supervision did *not* do. — E2

- **NetBSD/AArch64** (2026-07-18; `docs/netbsd-arm64-*`): cross-compiled a
  NetBSD release on an x86_64 GCE VM and booted it under `qemu-system-aarch64`
  TCG, serial-verified. Its footprint in `traces.db` is three 1-turn
  acceptance-supervision sessions (`a7cfccda0288`, `dd8af54b87b2`,
  `3e90d8f1cf59`), about $0.04 total (E1); the build agent ran under the
  Hermes client, and its work is not included in this trace footprint. The
  forensic report documents that, at the time, agentic supervision "is
  mostly absent between tool calls" — no contract, no monitors, no
  verification until the final text — and that cloud safety was
  "prompt-only and failed during recovery" (16 terminal calls with 8
  `gcloud config set`). The governor (§2.2) was built in response.
- **NetBSD/OP-TEE** (2026-07-19;
  `docs/netbsd-optee-driver-2026-07-19.md`): session `e5bda6f26e80` ran
  277 agent turns in about 2h15m for $10.59 (E1). Its final report claims
  QEMU + ARM Trusted Firmware + OP-TEE OS + U-Boot bringup and a custom
  NetBSD kernel driver at `sys/dev/optee/optee.c`: an SMCCC probe of the
  secure world, `/dev/optee` character device, and inclusion in `GENERIC64`,
  with dmesg-based proof (E2). The source and boot log are on the preserved
  VM disk, not in this repository; those implementation and boot claims are
  the agent's self-report.
- **Phoenix Ledger** (2026-07-19): a governed service migration with
  backup/restore rehearsal; the operator denied 14 actions with notes.
- **Terminal-Bench 2.1** (2026-07-21): `fix-git` (easy), `log-summary`
  (medium), `gpt2-codegolf` (hard) all reached reward 1 on the official
  verifier. `gpt2-codegolf` required **1 initial + 22 human-authored
  continuation prompts**; the unsupervised `fix-git` baseline also scored
  1. Three of 89 tasks, human-in-the-loop: not a benchmark result.

### F8. Cost. — E1

A fully supervised small coding turn (contract + execute + GCE sandbox +
3-criterion cross-family verify) costs $0.003–$0.0065 and one extra
round-trip; a `union 2` turn ≈ 3×. Supervision overhead on small tasks is
54–64% of tokens against a <15% design target, because three criteria are
three calls each re-sending task+output+evidence.

### F9. The conversation is a real dependency DAG with invalidation; the workflow graph is a configurable overlay on a fixed pipeline. — E3

Implemented and covered by 40 tests (`test_conversation_graph.py`,
`test_workspace_service.py`, `test_workspace_routes.py`,
`test_workspace_ui.py`): node pairs, edges, revisions, descendant
invalidation, automatic re-runs that stop at `awaiting_input /
awaiting_approval / failed`, pause/resume at a message node, approval
resumption of the exact node from the durable action ledger, and
per-message workflow overrides. Not implemented: the runtime walking the
authored topology (edges/conditions/loops are decorative); placing,
removing, re-wiring, or configuring verification nodes (the "additional
verifier" palette entry appends a prompt string — no family, tier, model,
or threshold; deleting `final_verifier` changes nothing at runtime,
`orchestrator.py:1096`); a branch-comparison view; a revisions UI (the
endpoint exists, the UI never calls it); any `!command` that edits a
graph; and the chat-completions API writing into the graph at all (only
`/admin/workspace/*` does, so OpenCode/Aider/Hermes sessions bypass it).
The two `.org` mockups in `docs/` (contract compiler, check-author →
pinned check sets, sandbox effect trials with write-set accounting,
context epochs, reconciliation preview) are design, not code.

One further correction to the thesis as stated: the system does not
"come up with tests before running your code". In all 218 soundness
checks in `traces.db` the falsifying test was designed *after*
`action_result` (0 before `action_started`); the pre-action path is the
deterministic gate, the critic, and — twice in 1,014 actions — a read-only
probe. The sandbox runs the model's own doctests. Test-before-execution
(AlphaCodium, CodeT) is established prior art and would be a natural node
to add; it is not what exists.

## 4. What is distinctive

Against the nearest prior work — Kwok et al.'s expected-score verifier,
cross-model verification ensembles ("Beyond Self-Checking", ICLR 2026;
Multi-Agent Verification, arXiv:2502.20379), guardrail-feedback agent
frameworks (TRIAD, arXiv:2606.05805), and the permission systems in
Claude Code / OpenHands — the parts that do not have an obvious
antecedent are:

1. **Probe substitution through the client's own tool protocol** (§2.2):
   the governor answers a held tool call with a *different*, read-only
   call, lets the unmodified client execute it, then releases the original
   without regenerating. This is a protocol-level trick that makes
   look-before-you-leap governance work with third-party agent loops.
2. **An independent falsification stage with an independence rule**: the
   checker is cross-family, gets exactly one probe, and a probe that
   re-reads the action's own target is rejected as non-evidence.
3. **Evidence-hygiene as hard gates**: masked exit status, read-shaped
   SQLite that is not opened read-only, and verifiers that cannot fail are
   blocked deterministically. Bespoke, but they encode a real class of
   self-certification failures.
4. The deployment findings F1–F3, which are transferable to anyone running
   logprob-based verification over aggregators.
5. **Per-message workflow instances with dependency invalidation.** Each
   assistant message owns an editable copy of its workflow; editing an
   earlier message or node stales and re-runs exactly the dependents.
   Flowise/LangFlow/Dify re-run whole flows and have no per-message
   instance; canvas-chat tools (CanvasConvo, Flowith, Canvas Chat) branch
   spatially but have no invalidation, verification, or execution. This
   is the product-level idea with the best claim to being first-class —
   and the one whose runtime is least finished (F9).

Everything else — checklist extraction, generate→judge→repair with a
capped ladder, model switching, planner DAGs, best-of-N and LLM fusion,
regex laziness detectors, tool allow-lists and risk tiers, human gating,
durable jobs with heartbeats — is standard agent-harness engineering,
competently done.

## 5. Threats to validity and known defects (from the audit)

**Verifier.**
- `top_logprobs=5` truncates the 20-letter support; the granularity
  argument of the source paper assumes the full distribution.
- The text-parsed point score is computed but **never persisted**
  (`verifier_calibration.py:198-214`), so the continuous-vs-discrete
  comparison the design rests on cannot be run from the existing data.
- When no `<score>` tag is found the parser returns 1/20 (`verifier.py:154`):
  "verifier did not answer" is indistinguishable from "clearly fails".
- The rubric anchors "J = borderline" (10/20) but the pass rule is ≈14.3/20.
- K=1 at temperature 0: token-level uncertainty only, no reasoning variance.
- Outputs are truncated at 12,000 chars without telling the verifier.
- If every cross-family verifier fails, the orchestrator proceeds
  *unverified* (`orchestrator.py:441-452`).

**Monitors.** Pure regex; `\bTODO\b` fires on tasks *about* TODOs,
"all tests pass" fires even when the sandbox transcript proves it, and any
hit forces a paid repair round because `passed` requires zero events. No
precision/recall has ever been measured and there are no unit tests for
them. Taxonomy ID drift: FM-X.6 means "sycophantic revision" in the
taxonomy and "token starvation" in code; FM-X.3 is used for "code failed
to run".

**Ensemble and referee.** Candidate families are padded with the primary
when families run out, so cross-family is *not* enforced for candidates;
`union` is an LLM merge performed by the primary executor. With no
`referee` model configured the failed executor's own model judges its own
failure. `escalate_verification` regenerates rather than re-judging.

**Governor.** The risk classifier is a hand-written heuristic ladder
fitted to the Phoenix Ledger workload; "irreversible" is command-name
membership; any `>` redirection is high and operator-gated; target
extraction is blind to `cd`, variable expansion, and non-literal paths.
`success_signals` is dead code. Post-checks trust the *client's* tool
result; for third-party clients there is no proof the call ran. The
"locked backend" is a controller-integrity check, not isolation — the
isolation is the disposable VM with no service account.

**Orchestration.** `agent_flows.yaml` is validated against observed
events but does not drive execution; declared budgets (`max_iterations`)
are checked for presence, never counted. Checkpoint resume restores units
with `verify=None`. Agent-turn verification runs with an empty contract.
Budget is checked only at loop top, so one attempt can overrun the cap.

**Evidence.** Every efficacy result is n=1 per condition.**Graph layer.** The runtime executes a hard-coded pipeline and projects
events onto the user's graph; edited topology is validated, stored, and
drawn, not run. Verification nodes are uneditable stages. The
`external-vector` store adapter is a stub that refuses reads and writes.
The chat API and the graph are disjoint, so the "drop-in proxy" and the
"graph-first workspace" are currently two products sharing a database.

 There is no
run of the supervised pipeline against an unsupervised baseline on more
than one task. Terminal-Bench runs are human-steered.

## 6. Related work

- Kwok et al., *LLM-as-a-Verifier* (arXiv:2607.05391, July 2026):
  expected score over scoring-token logits; granularity, repetition, and
  criteria decomposition as verification-scaling axes. Conflux is a
  deployment of this method; F1–F3 are what happens when it meets
  commodity gateways.
- Cemri et al., *Why Do Multi-Agent LLM Systems Fail?* (MAST,
  arXiv:2503.13657): the imported taxonomy and the independent-verification
  design bet.
- *Beyond Self-Checking: Fragment-Level Verification Across Diverse LLMs*
  (ICLR 2026): cross-family generator/verifier pairing with measured error
  correlation (ρ≈0.54 cross-family vs 0.77 within-family on their data).
  Conflux assumes this asymmetry but never measures it on its pool.
- *Multi-Agent Verification* (arXiv:2502.20379): multiple verifiers as a
  test-time-compute axis.
- TRIAD (arXiv:2606.05805): guardrail-generated verbal feedback steering
  agent planning per step — the closest analogue to the governor's
  `rewrite`/`probe` verdicts.
- Permission/approval systems in coding agents (Claude Code, OpenHands,
  Devin): tool allow-lists, risk tiers, human gating. The probe
  substitution and falsification stages are the delta.
- **Non-linear chat canvases.** *Conversations in Space* / CanvasConvo
  (arXiv:2605.15848, May 2026; 24-participant field study), Sensecape
  (UIST 2023), Graphologue (UIST 2023), and commercial Flowith / Canvas
  Chat: branching from messages onto a node-link canvas for exploration
  and comparison. None has dependency invalidation, re-execution,
  verification, or sandboxed code; all have a branch-comparison UI that
  Conflux lacks.
- **Flow builders.** Flowise, LangFlow, Dify, n8n: free-form authored
  topologies with typed ports, hundreds of components, and a runtime that
  executes the authored graph. None has per-message workflow instances,
  cross-family verification or sandbox execution as default stages, or a
  durable approval ledger that resumes the exact node.
- **Test-first code generation.** AlphaCodium (arXiv:2401.08500) and CodeT
  generate tests before or alongside code and iterate against them — the
  antecedent for any "design tests, then run" node.

## 7. Is this a paper?

**As a research contribution: no, not in its current state.** There is no
new method; the verifier is a faithful (and slightly truncated)
reimplementation of a July-2026 paper; the governor's core is a heuristic
classifier; and the evidence consists of single runs. A reviewer would
ask for a baseline and an ablation within the first page.

**As a systems/experience report (workshop, arXiv tech report, or a long
blog post): yes.** F1, F2, F3, and the governance protocol of §4 are
findings that practitioners deploying logprob verification or
tool-governing proxies over open-weight models would benefit from, and
they are reproducible from the harness in this repo.

**As an HCI / interactive-systems contribution (UIST, CHI, VL/HCC, or a
demo track): plausible, and this is the framing the project's own thesis
points at.** The claim "a conversation that is a dependency DAG with
per-message editable workflows, automatic re-execution of dependents, and
verification in the loop" is a design contribution that those venues
accept — but their bar is a working artifact that does what the paper
says plus a user study (CanvasConvo ran 24 participants for 5–7 days).
Today the artifact does roughly a third of the thesis (F9), and there is
no study.

## 8. What is missing for a real paper

Ordered by how much each one changes the verdict.

1. **A supervised-vs-unsupervised experiment with N.** Pick a task set of
   ≥50 items with mechanical grading (Terminal-Bench 2.1 has 89 tasks and
   is already vendored; a curated set of sandbox-gradable coding tasks
   also works). Run each model solo and under `super` with the same token
   headroom, **no human continuations**, and report pass rate, cost, and
   latency with confidence intervals. This single experiment decides
   whether the design bet holds.
2. **Ablations.** Remove one stage at a time: cross-family constraint
   (verify with same family), sandbox evidence, monitors, repair ladder,
   continuous vs discrete read. The last requires persisting the point
   score — a one-line change — and is the cheapest, highest-value
   experiment in the repo.
3. **Verifier calibration against subtle flaws with human labels.** Extend
   the seeded suite to ≥100 near-miss answers (off-by-one, silently
   weakened requirement, plausible wrong edge case), label them, and
   report ROC/AUC per verifier and per channel; fit the pass threshold
   instead of hand-setting it; set `top_logprobs=20` and measure whether
   F3's bimodality survives.
4. **Measure cross-family error correlation on this pool.** The entire
   design rests on ρ_cross < ρ_within; "Beyond Self-Checking" gives a
   recipe. Until measured, "different family" is an assumption.
5. **Monitor precision/recall.** Label monitor hits over the existing
   `traces.db` and a seeded corpus; report false-positive cost in repair
   rounds. Fix the FM-X.6/FM-X.3 ID drift.
6. **Governor evaluation with a baseline.** Replay the 1,014 governed
   actions through (a) no governor, (b) deterministic gates only,
   (c) gates + critic, (d) full protocol; label each action's true risk;
   report block precision/recall, operator interruptions avoided, and the
   71 soundness failures' true-positive rate. Add an adversarial set
   (prompt-injected tool results, masked failures) to test the
   falsification stage.
7. **Honest benchmark runs.** Terminal-Bench 2.1 end to end, autonomous,
   with the official harness, reporting the number of tasks attempted.
8. **Fix the defects in §5** that would otherwise be reviewer findings:8. **Make the runtime execute the authored graph** — at minimum honour
   node presence/absence and order for verifier, sandbox, critic, and
   ensemble stages, with configurable family/tier/threshold on
   verification nodes — and route the chat-completions API through the
   same graph so proxy clients and the workspace are one product. Add a
   pre-execution "check author" node (tests designed before the sandbox
   run, per the `.org` mockups) so the thesis sentence becomes true.
9. **A formative user study** for the HCI framing: 10–20 participants on
   real multi-step tasks, measuring whether invalidation + re-run and
   in-graph verification change how people catch model errors versus a
   linear chat with the same models.
10. **Fix the defects in §5** that would otherwise be reviewer findings:
   enforce cross-family for ensemble candidates, require a distinct
   referee model, distinguish "no score" from "score 1", persist the point
   score, and make the monitors evidence-aware (an FM-X.4 hit should be
   suppressed when the transcript shows the tests running).

Items 1–3 (ML framing) or 8–9 (HCI framing) are each roughly two to four weeks of compute-light work on the
existing harness; together they would turn this report into a defensible
workshop paper, and a positive result on item 1 into a full submission.

## 9. Conclusion

conflux is a complete, observable, operator-steerable supervision layer
that was built and field-hardened in eight days, and the repository's own
deficiency logs are unusually candid about what it does not do. Its value
today is as a set of reproducible deployment findings — aggregators
silently break continuous verification, digit scores break on Qwen,
verdicts are binary in practice — and a governance protocol (probe
substitution + independent falsification) that has a plausible claim to
novelty but no measured efficacy. The question the project was built to
answerThe graph workspace is the most original product idea in the repository
and the least finished: the conversation DAG, revisions, and dependent
re-runs are real, but the pipeline the graph depicts is not the pipeline
the graph controls. The question the project was built to
answer — does cross-family verification with execution evidence make
cheap open-weight models reliable enough to trust? — is still open,
because the experiment that would answer it has not been run.

## Appendix A — reproduction pointers

```bash
uv venv --python 3.12 && uv pip install -e . && uv pip install pytest
.venv/bin/python -m pytest -q tests/                  # 276 passed (2026-08-22)
.venv/bin/conflux probe                             # provider logprobs presence
.venv/bin/conflux calibrate --config models.yaml --db traces.db
sqlite3 traces.db "select risk,status,count(*) from governed_actions group by 1,2"
sqlite3 traces.db "select json_extract(data,'$.score') from events where kind='verify'"
```

Note: `pytest` with no path also collects the vendored Terminal-Bench
corpus under `benchmarks/` and fails on its dependencies; pass `tests/`.

## Appendix B — source of each number

| Number | Source |
|---|---|
| 22,984 LOC / 276 tests | `wc -l conflux/*.py`; `pytest tests/` |
| 80 sessions, 1,306 turns, $15.25 | `sessions`, `events` in `traces.db` |
| 84 verify events; 41 / 18 / 25 split | `events where kind='verify'` |
| 0/27, 24/27, 27/27 continuous reads | `verifier_calibration` run `2a4a905e4a27` |
| 1,014 governed actions and breakdown | `governed_actions`; `events` kinds `critic_verdict`, `soundness_check_result`, `action_blocked`, `human_approval_requested` |
| NetBSD OP-TEE (2026-07-19; session `e5bda6f26e80`): 277 turns, $10.59 | `sessions` / `events` by session |
| Terminal-Bench rewards and 22 continuations | `artifacts/terminal-bench/*/reward.txt`, `prompts/terminal-bench-gpt2-codegolf-hard-continuation-*.txt` |
| Six-run false-premise study | `docs/ensemble-vs-solo-2026-07-17.md` |
