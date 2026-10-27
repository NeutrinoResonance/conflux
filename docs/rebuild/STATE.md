# Rebuild state

Keep this short and current. One entry per decision; newest first. Full detail per slice lives in each entry's
evidence `RESULTS.md` and in the PR that landed it (`git log`); measured model behaviour in `MODELS.md`.

MISSION-STATUS: ACTIVE

- **Goal:** work item C (minimal replacement core) aimed at the completion gate. A done offline (live rerun deferred
  to E); B done. Goal (a) a1–a4 each model-accepted (not yet as one run); goal (b) b1 not yet accepted.
- **C slice 15 (2026-10-27, demo, $0.000074 metered + $0 GCE): failing-check feedback before `finish` does not make
  flash write b1. Hypothesis falsified; nothing built.**
  - Replayed c11/b1 at k=20/30 (prompt_tokens match c11 exactly), 5 samples per cell. Arms: control; the verbatim
    `_check_feedback` of c11's failing b1 checks appended to the last tool result (Flast) or to every tool result
    (Fevery). Writes/builds/finishes: **control 0/10, Flast 0/10, Fevery 0/10**; all 59 commands are reads.
  - Flash reads the feedback and discounts it: 6/10 Flast reasonings say the checks "failed as expected since no
    work yet". Fevery reasonings restate what the checks need, then read b3-scope material.
  - With slices 12–14: budget, scope, read cap, pro plan, headroom and check feedback all fail. **Prompt-level nudges
    to bare flash on b1 are exhausted** (codex's main diagnosis is tested and rejected).
  - All 30 calls took 4–39 s (none > `CHAT_TIMEOUT` 180 s); slice 14's slow seller did not recur, the risk stands.
  - Admission reserved every call's worst-case bound before dispatch under a $3.00 cap (bounds sum $1.99). 30/30
    export-matched. Evidence: `~/evidence/feedback-demo-2026-10-27/RESULTS.md` (`demo.py`, `samples.jsonl`,
    `reconciled.json`).
- **C slice 14 (demo, $0.008170): more output headroom does not make flash's truncated driver writes executable.**
  Complete admissible edits at max_tokens 8192 2/9 vs 16384 0/9; reasoning grows to fill the limit; 2 heredocs hit
  `MAX_COMMAND`. `MAX_TOKENS` stays 8192. **Live-run risk:** 10/18 calls took > 180 s (max 713 s); in `run_task` one
  chat timeout ends the task `unverified provider_0`. 2 calls hit a slow list-priced seller ($0.0023–0.0057).
  Evidence: `~/evidence/headroom-demo-2026-10-27/RESULTS.md`.
- **C slice 13 (demo, $0.001352): scope framing, a read cap and a pro plan each fail** (0 plausible writes, n=10
  each). Denied reads, flash writes token files; `echo … > f` matches `READ_ONLY`. The 3 real driver writes hit 8192
  completion tokens. Diagnosis handed to `codex exec`: flash stalls between understanding and implementing.
  Evidence: `~/evidence/b1-arms-demo-2026-10-27/RESULTS.md` (`codex-diagnosis.md`).
- **C slice 12 (demo, $0.000084): telling flash its step budget does not make it write** (0/30 incl. a policy
  sentence; reasoning cites "only 10 steps left" and reads on). Evidence: `~/evidence/overexplore-demo-2026-10-27/`.
- **C slice 11 (run c11, $0.000073 + $0.19 GCE): b1 `failed` at the step cap; model fault, 2nd identical failure.**
  0 truncations with `MAX_TOKENS` 8192; all 76 commands were reads (b2/b3 scope); no write, no `finish`.
  Evidence: `~/evidence/core-runs/2026-10-27-c11/RESULTS.md`. Lab c3 stopped, disk kept, NetBSD tree untouched.
- **C slice 10 (run c10, $0.000055 + $0.23 GCE): b1 failed; harness fault fixed** — `MAX_TOKENS` 2048 cut off tool
  calls (now 8192; truncation is named to the model as `truncated_at_max_tokens`, and a truncated reply with no call
  is not a finish). GCE stockouts happen: retry the lab start. Evidence: `~/evidence/core-runs/2026-10-27-c10/`.
- **C slice 9 (harness-only, $0.58 GCE): goal (b) cut into b1–b3** (`tests/fixtures/core_loop/optee_goal_b.json`:
  b1 driver build, b2 TF-A+OP-TEE firmware booting NetBSD, b3 driver proof incl. a no-SPD control boot, packaged
  QEMU only). Every check validated on c3 against untouched, reference and faked trees. Residual: the model has root.
  Labs need `build.sh -T <tooldir>`. Evidence: `~/evidence/core-runs/2026-10-27-c9/RESULTS.md`.
- **C slice 8 (run c8, $0.000034 + $0.25 GCE): flash accepted on a3 (at the step cap; it does not stop) and a4
  (24 steps).** D1 false positive on `strings` fixed. Evidence: `~/evidence/core-runs/2026-10-27-c8/`.
- **C slices 6–7 ($0.07 GCE):** every command runs under `set -o pipefail`; results carry `pipestatus` and
  `failed_cmds` (ERR trap), shown to the model. a1–a4 re-validated harness-only. Not covered: `|| true`, tools that
  exit 0 with warnings. Evidence: `~/evidence/core-runs/2026-10-27-c{6,7}/`.
- **F step 1 ($0): D1 self-audit runs at the end of every task** (`core.audit`, `python -m conflux.core audit`).
  Evidence: `~/evidence/self-audit-d1-2026-10-27/`; fixture `tests/fixtures/core_loop/audit_d1_cases.json`.
- **C slices 1–5 (2026-10-27):** `conflux/core.py` is one explicit loop (flash proposes `run_shell`/`finish`;
  deterministic admission, policy, execution, acceptance; `accepted`/`failed`/`unverified`; export reconciliation).
  `lab_shell` drives `devbox-lab` VMs; egress is tunnelled through a controller proxy. Default executor
  `deepseek-v4.1-flash` (billed < 1 micro-USD/call). Goal (a) cut into a1–a4 with executed checks; wrong checks
  cost whole sub-goals twice, so **every check passes harness-only on a real tree before a paid run**.
  Evidence: `~/evidence/core-runs/2026-10-27-c{1,1b,2,3,4,5}/`.
- **A (2026-10-27, $0): run 12's NetBSD stall came from two deterministic transformations**, both fixed: T1
  `decider._shell_effects()` turned non-path operands into phantom paths (`tests/test_run12_scope_mapping.py`); T2
  no-verdict soundness checks (HTTP 402) were stored as `postcheck_failed`, now `unverified`
  (`tests/test_run12_t2_unverified.py`). Evidence: `~/evidence/optee-ctl-runs/run12/`,
  `tests/fixtures/run12_netbsd/manifest.json`, `~/evidence/analysis/run12-netbsd/`.
- **Known contract violation (PR #1):** `conflux/verifier.py` `_parse_point` still accepts digit scores; pinned by
  strict xfail in `tests/test_letter_scale_contract.py`.
- **Next action:**
  1. Harness fault before the next live run: reproduce the chat-timeout risk (a reply slower than `CHAT_TIMEOUT`
     ends the task `unverified provider_0`) in a regression test, then fix it structurally (e.g. a longer timeout
     or one retry). $0.
  2. Changed hypothesis for b1 (prompt nudges exhausted; work item D): demo a localized stronger-model step. From
     replayed c11/b1 prefixes, have `deepseek-v4-pro` (or a Kimi/GLM route) produce the next reply as executor and
     count plausible, executable, size-admissible writes against flash's 0/20, with billed cost per write. Reserve
     worst-case bounds before dispatch (pro bounds ≈ $0.10–0.23/call).
  3. If a stronger model writes: demo deny recovery (split after `command_too_long`/`truncated_at_max_tokens`) and
     a flash-builds/pro-writes hand-off on c3.
  4. For the completion gate, run a1→a4 then b1→b3 unattended from the clean snapshot on a fresh lab, then delete
     the c3 disk.
