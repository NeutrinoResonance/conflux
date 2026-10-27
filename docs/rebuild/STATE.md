# Rebuild state

Keep this short and current. One entry per decision; newest first.

MISSION-STATUS: ACTIVE

- **Goal:** work item C (minimal replacement core). A is done offline (live rerun deferred to E); B is done.
- **C slice 1 done (2026-10-27, executed, $0.000848 billed this step):** `conflux/core.py` is one explicit loop.
  `deepseek-v4-flash` proposes `run_shell`/`finish` calls through Surplus chat. Deterministic code does budget
  admission, a permissive policy (tool name, arguments, command size; no path scope), execution, and acceptance.
  Acceptance is the task's own shell checks, run by the harness; on failure their evidence goes back to the model.
  Statuses: `accepted` / `failed` / `unverified` (no verdict, T2 semantics). Per-call cost is `buyer_cost_micro`, or the
  admission bound when it is missing. `reconcile` matches every call to the usage export.
  - **Hypothesis supported:** ≥ 4/6 accepted at ≤ $0.005 each. Result: **6/6 accepted** on 3 tuning tasks × 2
    (run c1b), 0 acceptance retries, 3–6 steps, 9–39 s. Cost: **$0.000116 billed per accepted run**
    ($0.000696 / 26 calls), and all 26 calls were export-matched on tokens with billed = in-flight.
  - **Failure found and fixed:** run c1 (6 calls) failed with `DecodingError` because Surplus chat compresses the body
    and needs `Accept-Encoding: identity`. Those calls were billed ($0.000152). Calls with no usage now
    reconcile by time.
  - **Caveat:** the tasks are easy tuning tasks, so the ceiling effect says nothing about harder work.
    Evidence: `~/evidence/core-runs/2026-10-27-c1{,b}/`. Replay fixture: `tests/fixtures/core_loop/recorded_fix-mean.json`.
    Tests: `tests/test_core_loop.py` (17). Suite: 643 passed, 1 xfailed.
- **Next action:** C slice 2 aims at the completion gate (MISSION.md: full run-12 task unattended on a lab VM).
  The toy tasks saturate, so: (1) give the loop a lab-VM execution backend (`devbox-lab ssh`, long commands
  with timeouts and checkpointed output); (2) cut run-12 goal (a) (`~/evidence/optee-ctl-runs/run12/task.txt`) into
  sub-goals with executed checks (build artefacts exist, QEMU boot markers in the serial log); (3) run bare flash on
  the first sub-goal, ≤ $0.20 metered, and stop/delete the lab afterwards. Record failure modes; add the Jev
  `choice` gate only at a decision those failures show to be bounded. Admission reads the cumulative ledger
  total, which is ≥ this ISO week's spend, so it is conservative under the weekly cap. Legacy
  `scripts/direct_vm_tool_loop.py` stays until its GCE/durable-job features are replaced.
- **T2 fixed (2026-10-27, verified offline, $0):** a soundness check that produced no verdict (checker
  unavailable, provider error such as 402, malformed output across the whole chain, budget
  exhausted) now gives decision/status `unverified`, not `postcheck_failed`. `unverified` is final
  but is not a "recent effect", so an identical retry goes through normal governance instead of the
  failed-retry human hold. Real `fail` verdicts are unchanged.
  - **Replay of run-12 `traces.db`** (`t2_fix_replay.txt`): 26/26 no-verdict checks become
    `unverified`. Of the 10 failed-retry holds, 6 are removed (including `act_f2e51f2cc42840a1`) and
    4 are kept (their prior `act_edaa16c73d5d46ab` had a real fail).
  - **Acceptance:** `tests/test_run12_t2_unverified.py` (402 → unverified + retry released; a real
    fail is still held). Suite: 603 passed, 1 xfailed (letter scale).
  - **Over-budget fail (from orphaned PR #4):** a checker `fail` that costs more than the remaining
    budget stays `postcheck_failed` with its reason, in both the direct and the probe path. The overrun
    is logged as `soundness_budget_exceeded` (`checker_cost_usd`, so it is not counted twice). Before
    the fix, both regressions were red on the base.
  - **Not covered:** unsafe or same-target probes stay `postcheck_failed`.
- **T1 fixed (2026-10-27, verified offline, $0):** `_shell_effects` now strips fd prefixes (`2>&1`),
  consumes `>&`/`<&` targets, parses option values (`head`/`tail -n`, grep `-e/-f/-m/-A/-B/-C`) and
  grep patterns. Replay of all 293 run-12 commands: actions with phantom relative paths 38 → 2.
  The two left are not T1, both still fail closed: `case` patterns in `act_df85b83b994640ac`, qemu
  `-serial file:PATH` in `act_527d9183f574432e`. Old-vs-new effect diff: 0 real paths lost. 20 more
  actions lose phantom reads under a `cd` dir (e.g. `/tmp/conflux-agent/1`), so T1 affected ≥58
  actions, not 39. Suite: 599 passed, 1 xfailed (letter scale).
- **Finding (2026-10-27, verified offline, $0):** run 12 never launched the NetBSD clone (0 clone
  proposals reached governance). The stall comes from two deterministic transformations, both in code:
  1. **T1 — first incorrect transformation:** `conflux/decider.py` `_shell_effects()` turns non-path
     operands into relative file paths: grep patterns containing `/` (`'I/TC:'`), option values
     (`tail -n 1`) and fd numbers (`2>&1`). This happens from the very first action
     (`act_716b22ec52c6403b`, 03:24Z) and affects 39/308 actions. Correct read-only checks become
     "scope unproven", which raises them to medium/high risk. That risk triggers the batch human-hold
     rule (`governance.py`: >1 action and any non-low) and a model soundness check.
  2. **T2 — missing evidence recorded as failure:** soundness checks that failed closed on **HTTP 402
     Insufficient funds** were stored as `postcheck_failed` (26/60, from 10:29Z), even when the check
     printed its expected marker. That status then makes identical re-checks a "non-idempotent retry
     after failed postcondition", which is held for a human (`act_f2e51f2cc42840a1`). After goal (a)
     (17:02Z), every NetBSD-phase decision looped through these holds until reconsideration was
     exhausted.
  - **H2** (seat `cwd` disagreement / model-prefixed `combine()` steps) is not supported as the cause:
    those consultations happened downstream of the holds.
  - "Child-model mapping": the phrase does not appear in the evidence. The closest artifact is that
    `combine()` labels steps with resolved fallback routes (`(deepseek-v4-pro-ollama)`). The executor
    read these as attribution, so this is an observation, not a cause.
- **Evidence:** `~/evidence/optee-ctl-runs/run12/` (hashes and action ids in
  `tests/fixtures/run12_netbsd/manifest.json`); analysis outputs in `~/evidence/analysis/run12-netbsd/`.
- **Acceptance:** `tests/test_run12_scope_mapping.py`: the 9 T1 cases now pass, plus regressions
  checking that real operands are still scoped.
- **Known contract violation (2026-10-27, PR #1):** `conflux/verifier.py` `_parse_point` still accepts
  digit scores (`<score>7</score>`); pinned by strict xfail in `tests/test_letter_scale_contract.py`.
