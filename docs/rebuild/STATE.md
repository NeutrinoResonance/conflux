# Rebuild state

Keep this short and current. One entry per decision; newest first.

MISSION-STATUS: ACTIVE

- **Goal:** work item A — reproduce the NetBSD / child-model mapping failure from evidence.
- **T1 fixed (2026-10-27, verified offline, $0):** `_shell_effects` now strips fd prefixes (`2>&1`),
  consumes `>&`/`<&` targets, parses option values (`head`/`tail -n`, grep `-e/-f/-m/-A/-B/-C`) and
  grep patterns. Replay of all 293 run-12 commands: actions with phantom relative paths 38 → 2.
  The two left are not T1, both still fail closed: `case` patterns in `act_df85b83b994640ac`, qemu
  `-serial file:PATH` in `act_527d9183f574432e`. Old-vs-new effect diff: 0 real paths lost. 20 more
  actions lose phantom reads under a `cd` dir (e.g. `/tmp/conflux-agent/1`), so T1 affected ≥58
  actions, not 39. Suite: 592 passed, 1 xfailed (letter scale).
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
- **Next action:** T2. Write an acceptance test: a provider/billing error (HTTP 402) in the
  soundness checker must leave the action unverified, not `postcheck_failed`, and must not trigger
  the failed-retry hold (`act_f2e51f2cc42840a1`). Strict-xfail it first, then fix.
