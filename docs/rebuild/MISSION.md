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

## Engineering discipline

- Minimize total tokens, cash, retries and operator attention per *verified* successful task. A few
  strong reasoning calls can beat many ineffective cheap attempts.
- Read targeted code/context; keep `STATE.md` short (goal, hypothesis, evidence, decision, next
  action). Do not resend whole histories, all repo files or full traces to every model.
- No abstraction stacking: a new layer needs a demonstrated requirement simpler code cannot meet.
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
