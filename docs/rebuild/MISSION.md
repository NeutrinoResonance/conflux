# Conflux core rebuild — mission contract

Persisted once (2026-10-26). Child agents get their role plus the relevant slice of this file,
not the whole history. Durable working state lives in `docs/rebuild/STATE.md`.

## Objective

Make inexpensive DeepSeek execution achieve the best **reliable work per dollar**.

- DeepSeek is capable and cheap, but the founder has seen unreliable decisions and failure to act
  on correction.
- Jev (TypeSafe, served via Surplus `/v1/decisions` as `jev-1.14`; see Founder decisions) is preferred for supported, *bounded* semantic
  decisions when it improves total economics.
- Other models supply selective planning, criticism, correction or localized repair.
- Deterministic code owns permissions, budgets, evidence and acceptance.
- Build a **small replacement core**. The legacy implementation is preserved at tag
  `conflux-baseline-20261026` (= `d21261d`, main `7215e6d` + snapshot of uncommitted work) and is the
  comparison baseline. Preserve its real traces, failure cases, useful tests and provider evidence.
- The project discovers good model/supervision configurations itself; do not ask the founder to
  guess them.

## Completion gate (founder decision 2026-10-27)

The endeavor is done when **Conflux, driving DeepSeek as its normal executor, completes the full
run-12 task unattended from the clean OP-TEE snapshot** — goal (a) OP-TEE build + QEMU boot of the
secure world and Linux, then goal (b) the NetBSD driver work — with every goal's success
independently verified by executed checks (not model self-grades), within the weekly budgets below.
Task text: `~/evidence/optee-ctl-runs/run12/task.txt`. Run it on a lab VM (`devbox-lab`). Held-out
comparisons against bare DeepSeek and the baseline (item E) remain required supporting evidence.
Only then set `MISSION-STATUS: COMPLETE` and open the promotion PR to `main`.

## Founder decisions (binding; newest first)

- **2026-10-28 — Lead prompt layout: data first, request and goals last; one goal per turn.** Founder experience with
  the MoE models (GLM, Kimi, DeepSeek): the instruction and the goals to check belong at the END of the prompt, after
  the data, not before it. Shape: "Analyze this: <all previous activity and bookkeeping>", then "Do X with regard to
  our goals:", then the goals. Better still, run it as a conversation, which has worked before: after the data, give
  one goal at a time and take the model's answer on it, then the next goal in a new message; when every goal has been
  covered, a final message asks for the next steps (or whatever the call's output is). This is a layout rule, not
  task content: no goal text is written by a developer, the goals come from the run's own goal list. Measure it like
  any other change (e.g. against the single-message layout on the same inputs), but this is the default layout for
  the lead from now on.
- **2026-10-28 — The other model is asked to lead, not to fill a form; Jev comes later.** Slices 34–37 gave Kimi/GLM
  the developer-written b2 sub-goal, a stalled step-20 trace, and a fixed question ("up to 3 competing hypotheses,
  JSON"), or dropped them into the stalled conversation with 10 steps left. That imposes structure too early and
  under-uses the resources at hand (founder: "a piss poor result given the abundant resources"). Instead the
  other model gets the previous activity plus the run's bookkeeping (the goal list derived from `task.txt`, progress
  recorded so far, claims made) and an open request of the form "look at where we are on the goal list, update
  progress, provide next steps". It decides for itself whether the problem is one bug, a wrong plan, or a false
  progress claim. No developer-chosen answer shape beyond what the harness needs to parse. The goal list and
  progress are kept and revised by the models, which is also how the spec is derived from `task.txt`. Jev (deciding
  *when* to call this) is an optimization: first show that calling the other model regularly helps on the real
  task, then add Jev and the random cheap inspector to cut cost. Measure on the full `task.txt` run, at a scale the
  cheap models allow (GLM ≈ $0.0001/step), not n=2 on one developer-written sub-goal.
- **2026-10-28 — Correction is model switching, with as few hardcoded prompts as possible.** Prefer changing *who*
  acts over writing *what to say*. The intended shape: deterministic code detects a candidate stall from the trace;
  Jev (`/v1/decisions`) decides whether to intervene and whom to bring in; GLM, Kimi, or both, read the executor's
  trace and produce the correction, or take over the next steps, before handing back. Developer-written correction
  or nudge prose (fixed reminders, "apply or test it" messages, "search the machine first" planner instructions)
  is the last resort: minimize it, keep any that survives generic and measured, and never task-specific. Which
  models, when to switch and for how long are chosen by measured outcomes on the recorded stalls. The
  OSS harness survey (`~/evidence/harness-survey-2026-10-28/`) is a source of candidates to measure, not prompts to copy.
  Jev can fail or miss: in addition to Jev's trigger, a very cheap model inspects the trace at **random** steps
  (rate and model chosen by measurement). This is the fallback when Jev is unavailable or silent, and its findings
  on steps Jev did not flag measure Jev's miss rate.
- **2026-10-28 — Harness fault: the core dropped DeepSeek's `reasoning_content` between turns.** DeepSeek requires
  it to be passed back on every turn when tools are used. Every measurement of "the executor names the fix, then
  keeps reading" (slices 18, 27–32) was taken with the executor's previous reasoning erased at every step, so those
  conclusions are confounded. Fix it first (regression test), then re-measure the recorded stalls before attributing
  them to the model.
- **2026-10-28 — Corrections and the spec come from Conflux's other models, not from the executor grading
  itself.** The executor's measured failure (it names the fix, then keeps reading; it does not look for what it
  needs) is the failure the multi-model layer exists to catch: a different model (critic, planner, decider/Jev,
  stronger or differently-trained model) reads the executor's trace and plan, states what is wrong with evidence,
  and turns it into an executed probe or a correction. A demo where the executor's own model diagnoses, corrects or
  plans for itself (e.g. slice 32: pro diagnosing pro) is a single-model baseline, not a test of Conflux. Work item D
  is therefore next, and spec derivation (decision below) is done the same way: a planner plus at least one critic of
  a different model family. Candidates are the configured routes (Kimi K3/K3.1-pro, GLM-5.3, DeepSeek pro/flash,
  Jev decisions, and Claude/Codex via subscription where the measured economics allow); which models play which role
  is chosen by measured outcomes on the recorded stalls (b2 slice 27, b1 c10/c11/slice 18, b3 slice 31) and the
  spec-derivation grade, never by a developer's guess. The legacy senate/critic/decider/verifier code
  (`conflux-baseline-20261026`) is the first thing to reuse or demo before writing new mechanisms.
- **2026-10-28 — Conflux gets from the founder's task text to the spec itself.** The completion run's only
  task input is `~/evidence/optee-ctl-runs/run12/task.txt` verbatim (plus the machine itself). Everything the
  developer has been writing into fixtures — sub-goal decomposition, file and tree locations, build commands and
  flags, design choices (SMC, FDT attach, device name), boot command lines, what counts as proof — must be produced
  by Conflux at runtime (planning, criticism, runtime probes as defined below), not supplied. The developer-written
  sub-goal fixtures (`optee_goal_a.json`, `optee_goal_b.json`) and their checks remain grading references and
  test instruments only; a sub-goal accepted under them shows reachability, not progress toward the gate. The
  rebuild's measure of progress is how much of that spec Conflux now produces itself, demonstrated first on the
  recorded runs (old runs 4–12 and slices 10–30 show where agents got lost without it), then live.
- **2026-10-28 — Conflux must produce its own corrections; this is the point of the endeavor and the top
  priority.** A sub-goal passed with a developer-authored intervention (a recipe, correction, diagnosis or
  injected message written by Claude/Codex during development, e.g. slice 30's b2 correction M, whose recipe came
  from the developer's slice-27 diagnosis) is **not done**: it shows the task is reachable, not that Conflux can
  reach it. Before running further sub-goals with developer help, make Conflux generate the missing correction at
  runtime from its own trace and its own executed probes (e.g. a stronger model, critic or diagnostic sub-run
  triggered by a measured stall), demonstrated first on the recorded stalls (b2 slice 27, b1 over-reading in
  c10/c11/slice 18) per the demo rule, then live. The developer's role is to build that capability, never to hand
  the executor the answer. Developer-found recipes are grading references only.
  A *runtime probe* is a command that (1) a Conflux component (executor, critic, diagnostic model or deterministic
  code) chose during the run, from only the task text, the run's trace and the environment, with no developer-written
  input specific to this task or failure (deterministic code may decide *when* to diagnose, never name a task-specific
  command, file or flag); (2) ran on the task's lab VM, in the task tree or a scratch copy; (3) is in the run's trace
  and charged to its budget under a probe cap; (4) the correction is traceably built from its output. Developer runs
  outside the loop (e.g. slice 27's out-of-tree TF-A builds) are not probes, only grading references.
- **2026-10-27 — Demo first for any conjectured change to how Conflux uses agents.** This covers new
  mechanisms (detectors, classifiers, supervision or review layers), model or route choices, prompts,
  policies, panel/critic/decider wiring and loop changes, whether a developer or Conflux itself proposes
  them. Before implementation, run a throwaway demo (a short script, cost-capped, on recorded traces in
  `~/evidence/` or a tiny live run) and write its numbers to `~/evidence/<demo>/RESULTS.md`; build only
  what the numbers support, and cite that file in the PR. A fix for an observed harness fault is
  demonstrated by its regression test reproducing the fault. The founder has seen layer-on-layer
  abstraction drive costs up; work item F is the worked example (one detector of four survived).
- **2026-10-27 — Fix first: the executor masks pipeline failures.** `conflux/core.py` runs model commands
  as plain `bash -c` (local `execute()` and the lab job launcher), so `make … | tail` reports exit 0 when
  make fails, and the model acts on false success. The old governor enforced `pipefail`; the rebuild
  dropped it. The next step fixes this structurally, before any further paid run: every model command
  (local and lab) runs with `pipefail`, and the observation includes each pipeline stage's exit status
  (`PIPESTATUS`). Don't fix it in the prompt. Re-validate the acceptance checks harness-only on a real tree,
  because `pipefail` can turn `… | head` (SIGPIPE, 141) into a false failure. Add regression tests for both.
- **2026-10-27 — Pick Surplus models by billed price; default executor is `deepseek-v4.1-flash`.**
  `deepseek-v4-flash` only has ~61%-discount offers. On an identical 2k-token request (2026-10-27,
  default `price` routing) it billed $0.000020; `deepseek-v4.1-flash` billed <$0.000001,
  `deepseek-v4.1-flash-1017` $0.000004–13, `deepseek-v4-pro` $0.000008. Switch the core loop's default
  to `deepseek-v4.1-flash` (re-check acceptance on the tuning tasks and reconcile billing), and before
  adopting any Surplus model compare current offers (markets/prices API) and billed cost from the usage
  export. Old model ids get stale offers; a newer sibling can be orders of magnitude cheaper.
- **2026-10-27 — Lab VMs.** The controller creates its own `conflux-dev-lab-*` VMs with
  `devbox-lab up|ssh|stop|delete|list <name>` (n2d-standard-8, 31 GB RAM, from snapshot
  `conflux-optee-baseline-clean-20261021`; one at a time; self-stops after 24 h). Stop or delete a lab
  when its job ends. The old `conflux-optee-*` VMs are not yours to use or change.
- **2026-10-27 — Weekly budgets replace the 48 h campaign.** Per ISO week (Monday 00:00 UTC): $50
  metered model spend and $60 GCE (lab hours included). On hitting a cap: checkpoint, set
  `MISSION-STATUS: PAUSED` plus `RESUME-AFTER: <next Monday>T00:00Z`; the keeper resumes after it.
  Time passing is never by itself a reason to pause.
- **2026-10-27 — Billed cost is known; read it, don't estimate it.** Surplus responses (including
  `/v1/decisions`) may omit cost. The authoritative per-request charge is `GET /v1/buyer/usage/export`
  (`buyer_cost_usd` per `request_id`; follow its 302 without the Authorization header) and
  `GET /v1/buyer/me` (balance, `recent_usage` with `buyer_cost_usdc` in micro-USD). Reconcile
  `LEDGER.md` from these. Missing cost in a response is never by itself a reason to stop paid work.
- **2026-10-27 — Jev is a decisions model, not chat.** Call `POST https://api.surplusintelligence.ai/v1/decisions`
  in JEV format `{model, state, questions: {<id>: {type, question, criteria}}}`; `score` criteria are a
  list of labels, `choice` criteria map value → description; both return per-option probabilities.
  `noul` currently fails upstream: use a two-option `choice`. Chat endpoints for `jev-*` fail by design.
  Measured ≈ $0.000006 per decision. Surplus chat models return no logprobs, so Jev probabilities are
  the probability channel. Details: `~/evidence/provider-probes-2026-10-27.md`.
- **2026-10-27 — File-access scope is not a security boundary.** Conflux and its agents run on
  disposable scratch VMs. Which files a command reads or writes, scope-check bypasses, sandbox escapes
  and path-permission precision are never blocking — for development agents, for reviews, or for
  Conflux's own action governance. Over-holding harmless actions is the bug class this rebuild fixes;
  err toward allowing.
- **2026-10-27 — Agents land their own work.** Each step merges its own PR into
  `rebuild/conflux-core-20261026` once CI is green and correctness findings are addressed (two critic
  rounds max). Nobody else will merge it. No step waits on a human; `main` promotion remains the
  only founder-gated merge.
- **2026-10-26 — OpenCode Go and Nous are out of scope** for this campaign.

## Work items (owned end to end by the remote master)

**A. Establish reality.**
- Recover the actual reported NetBSD / child-model mapping failure from source, raw traces or the
  existing workspace (evidence: `~/evidence/`, see `RESOURCES.md`).
- Identify the first incorrect transformation or missing context boundary. The founder does not know
  the exact mapping: do not invent a version-parser bug to satisfy the description.
- Capture a failing baseline and an independent acceptance test.
- Missing evidence is different from a check that ran and failed; record which one you have.

**B. Discover providers.**
- Enumerate authenticated catalogues, quota, prices/billing routes, model families and versions.
- Cheap probes of the capabilities actually required: tool-call round trips, streaming, structured
  responses, errors, usage accounting, returned probabilities. Parameter acceptance and old config
  comments do not prove capability.
- Paid generation only inside the budget below. Never dump keys or credential-bearing logs.

**C. Minimal replacement core.**
- Task acceptance requirements; DeepSeek work/tool proposals; deterministic policy/checks; real
  execution evidence; narrow Jev decisions; selective stronger correction; bounded repair; accurate
  trace/cost/quota accounting.
- One explicit execution loop. Defer: general DAG scheduler, workflow editor, store framework, broad UI.

**D. Jev integration + correction mechanisms.**
- Stronger criticism states the violated requirement, supporting evidence and an actionable correction.
- Measure whether DeepSeek incorporates it. If it fails to apply a correction, compare a localized
  stronger-model patch against another DeepSeek retry.
- Kimi/GLM may review without logprobs. Keep grounded criticism distinct from probability scoring;
  never fabricate probabilities. Verifier scores that use logprobs use the letter scale (A–T).

**E. Evaluate.**
- Against bare DeepSeek and the preserved baseline, on matched held-out tasks and budgets.
- Record independently verified success, false acceptance, all retries, latency, billed cash,
  subscription usage and human interventions.
- Promote only changes supported by this evidence. A model's self-grade is insufficient.

## Provider rules

- DeepSeek is the normal execution model. No aggregate-score router may silently replace it with an
  expensive model for ordinary work. Stronger models chiefly correct/enhance.
- Deterministic computation first, then Jev for supported bounded decisions. Jev is not a generator,
  unconstrained diagnostician or permission authority; its probability is not the probability that a
  whole task succeeds.
- **NanoGPT** subscription when eligible (60M input tokens/week, per-model multipliers). Paid balance
  is $0, so overflow fails rather than charging: route overflow deliberately to Surplus.
- **Kimi Code** (`api.kimi.com/coding/v1`) and **GLM Coding Plan** (`api.z.ai/api/coding/paas/v4`, Lite)
  only for traffic those plans cover (coding tools). Product-runtime traffic they do not cover goes to
  the corresponding **Surplus** route. Never impersonate an approved client.
- Otherwise-paid product inference goes through **Surplus Intelligence**
  (`https://www.surplusintelligence.ai/api/inference/v1`, OpenAI-compatible). Verify actual billed
  pricing; do not assume a blanket discount.
- **Development tools are separate from the product runtime.** Claude Code and Codex here run on the
  founder's own subscriptions (native logins on the controller). Never route Claude Code through
  Surplus, never install `claude-script.sh` or Anthropic base-URL overrides, never add API keys to them.
- OpenCode Go and Nous are out of scope for this campaign (founder decision 2026-10-26).

## Budgets and stop conditions

| Item | Limit | On exhaustion |
|---|---|---|
| New metered model spend (Surplus + any paid overflow) | **$50 per ISO week** (billed, from the usage export) | checkpoint, PAUSED + RESUME-AFTER next Monday |
| GCE (controller + workers + labs) | **$60 per ISO week**; $100/month alert is informational | stop labs/workers, PAUSED + RESUME-AFTER |
| Workers | max 2 (`conflux-dev-worker-1/2`), e2-medium Spot, 2 h per start | checkpoint long jobs; restart within budget |
| Labs | 1 at a time (`conflux-dev-lab-*`), n2d-standard-8, self-stop after 24 h | checkpoint; restart within budget |
| Concurrency | 1 implementation session + independent reviewer | parallelize only independent work |
| Plan review / code review rounds | 2 / 2 | then one fresh diagnosis with new evidence |

- Subscription usage (Claude, Codex, NanoGPT, Kimi, GLM) is tracked separately from cash.
- After two materially identical failures: reassess the hypothesis or hand diagnosis to the other
  developer model. Do not wrap the same failed approach again.
- A genuinely nonrecoverable blocker: checkpoint, record precise evidence in `STATE.md`, notify.
  Never mark blocked or unverified work successful.
- `main` stays the preserved baseline. Work merges into `rebuild/conflux-core-20261026`. Open a
  promotion PR to `main` only when the completion gate above is met; do not merge it — the
  founder authorizes promotion. Waiting for that does not block further work on the rebuild branch.

**F. Self-audit, scoped by a demo (founder decision 2026-10-27).**
Demo before build: `~/evidence/self-audit-demo-2026-10-27/RESULTS.md` (17 real traces, one 60-line script).
- Build only what the demo showed works: a deterministic check that flags any step whose reported
  success is contradicted by its own output (found the masked `make` failure in c4 and an unknown `;`-chain
  case in c3). Run it after every run; a hit is a harness fault and gets a structural fix + regression test.
  Fix its known false positives (read-only command parsing) first. Grade on the demo's traces.
- Failing acceptance checks on objects the model kept inspecting are flagged for review only. Cheap
  classification of "check wrong vs work incomplete" failed in the demo (v4.1-flash 1/3; Jev wrong on the one
  case, 5 repeats, near-chance confidence; see `docs/rebuild/MODELS.md` for its measured strengths): build no
  model-based classifier unless a new demo, on recorded traces, beats those numbers.
- Any further self-improvement mechanism follows the same rule: a throwaway demo on recorded traces with
  its numbers in `~/evidence/`, before code lands. No new layer without demo evidence.

## Engineering discipline

- A failure mode you observe is never only a note. Classify it as harness or model fault. A harness
  fault gets a structural fix plus a regression test before the next paid run; a model fault becomes a
  measured supervision experiment. Either way, record it so item F's audit can be graded against it.

- Minimize total tokens, cash, retries and operator attention per *verified* successful task. A few
  strong reasoning calls can beat many ineffective cheap attempts.
- Read targeted code/context; keep `STATE.md` short (goal, hypothesis, evidence, decision, next
  action). Do not resend whole histories, all repo files or full traces to every model.
- No abstraction stacking: a new layer needs a demonstrated requirement simpler code cannot meet,
  shown by a throwaway demo on recorded traces before it is built.
  Favor deletion, direct functions, explicit transitions.
- On the rebuild branch, delete superseded legacy implementation files in the same commits as their
  replacements; keep only useful tests/fixtures/docs. The legacy code lives on in the baseline tag.
- Experiments: state hypothesis, cheapest falsifying test, primary outcome, max spend, stopping
  condition. Start with a small policy comparison: bare DeepSeek, Jev-gated review, targeted Kimi/GLM
  correction, brief stronger planning, localized stronger repair. Change one main factor at a time;
  keep tuning tasks separate from held-out evaluation; paired repeated runs where stochasticity
  matters; report uncertainty and negative results. No exhaustive Cartesian search.
- Select on the quality/cost frontier, including scarcity of subscription quota.
- Large or private traces stay outside Git (`~/evidence/` on the controller); commit sanitized fixtures
  and manifests that reference retained evidence. Explicit file staging; inspect diffs for secrets.
