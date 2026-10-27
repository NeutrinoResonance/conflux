# Rebuild state

Keep this short and current. One entry per decision; newest first. Full detail per slice lives in each entry's
evidence `RESULTS.md` and in the PR that landed it (`git log`); measured model behaviour in `MODELS.md`.

MISSION-STATUS: ACTIVE

- **Goal:** work item C (minimal replacement core) aimed at the completion gate. A done offline (live rerun deferred
  to E); B done. Goal (a) a1–a4 each model-accepted (not yet as one run); goal (b) b1 not yet accepted.
- **C slice 18 (2026-10-27, demo, $0.001838 metered + $0.18 GCE): pro in flash's seat writes b1 but runs out of
  steps before the build.** One live b1 run on c3, `deepseek-v4-pro`, else as c11 (wrapper sets pro admission
  ceilings and `max_usd` 1.00; nothing built). `failed step_cap`: check 1 **passed** (new `sys/dev/fdt/optee.c`,
  `files.fdt` stanza, GENERIC64 `optee* at fdt?`), check 2 failed — no `build.sh` ever ran, so whether the driver
  compiles is unverified. 61 on-scope reads before the first write (step 26); 6 steps repairing its own edits.
  Flash wrote nothing in c10/c11. Billed $0.000046/call (≈ 25× flash), max latency 71 s. Model behaviour, no harness
  fault (D1 hit = a real Permission denied the model then fixed). With flash ceilings the fixture's `max_usd` 0.15
  would refuse pro mid-run (bound peaked at $0.33/call). Evidence: `~/evidence/pro-b1-run-2026-10-27/RESULTS.md`.
- **C slice 17 (2026-10-27, harness fix, $0): a slow provider reply no longer ends a task.** `CHAT_TIMEOUT` 180 → 900 s
  (flash replies measured up to 713 s); `run_task` retries a status-0 call (transport error/timeout) once, each attempt
  admitted, settled and traced with `attempt`; no retry past the lab deadline, HTTP errors not retried. Regression test
  reproduced `unverified provider_0` before the fix. Evidence: `~/evidence/chat-timeout-2026-10-27/RESULTS.md`.
- **C slice 16 (2026-10-27, demo, $0.001272 metered + $0 GCE): a stronger executor in flash's seat also reads.
  Hypothesis falsified; nothing built.**
  - Replayed c11/b1 (flash's history) at k=10/20/30 and sampled one next reply from `deepseek-v4-pro` (n=5 per k),
    `glm-5.3` and `kimi-k3` (n=3 at k=20/30), all via Surplus. Plausible admissible writes: **pro 0/15, glm 0/6,
    kimi 0/6** (flash 0/20). All 50 commands are reads; no denial, truncation or `finish`.
  - Scope separates them: pro's reads stay on b1 (9/10 at k=20/30; it names `sys/dev/fdt/optee_fdt.c`, `files.fdt`,
    GENERIC64) yet opens "a few more references first"; glm/kimi follow flash's b3 drift at k=30 (0/6 b1).
  - The one-step measure is saturated (0/47 over four models): it cannot tell "writes at k+3" from "never writes".
    Whether pro finishes b1 needs a multi-step live run. Pro billed ≈ $0.000057/call; max latency 81 s.
  - Evidence: `~/evidence/stronger-executor-demo-2026-10-27/RESULTS.md` (`demo.py`, `samples.jsonl`, `labels.json`,
    `reconciled.json`; 30/30 export-matched).
- **C slice 15 (demo, $0.000074): failing-check feedback before `finish` does not make flash write b1** (control,
  last-step and every-step feedback each 0/10; 6/10 reasonings dismiss the checks as "failed as expected since no
  work yet"). Prompt-level nudges to flash on b1 are exhausted. Evidence: `~/evidence/feedback-demo-2026-10-27/`.
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
  1. Re-cut b1 at the boundary slice 18 exposed: b1a = driver + `files.fdt` + GENERIC64 (check 1), b1b = build
     GENERIC64 (check 2); validate the split checks harness-only. Then run b1b with flash on c3 **as pro left it**
     (tests a pro-writes / flash-builds hand-off; compile errors become correction input). c3's `netbsd-src` now
     holds pro's uncommitted edits: reset `sys/` to `7f2c5e73f` before any fresh b1/b1a attempt.
  2. If pro becomes the b1a writer: per-model admission ceilings in `core.py` (demo numbers above), not a wrapper.
  3. For the completion gate, run a1→a4 then b1→b3 unattended from the clean snapshot on a fresh lab, then delete
     the c3 disk.
