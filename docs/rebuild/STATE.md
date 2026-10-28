# Rebuild state

Keep this short and current. One entry per decision; newest first. Full detail per slice lives in each entry's
evidence `RESULTS.md` and in the PR that landed it (`git log`); measured model behaviour in `MODELS.md`.

MISSION-STATUS: ACTIVE

- **Goal:** work item C (minimal replacement core) aimed at the completion gate. A done offline (live rerun deferred
  to E); B done. Goal (a): a1–a4 each model-accepted, but not yet in one run. Goal (b): b1a's check passes on pro's
  slice-18 edits; **b1b model-accepted on c3 (slice 26)** after slices 20–25 removed the harness faults (no-cost
  settlement, 4 KB tail cut) and pro cleared the ownership stall; b2 not accepted (slices 26–27: NetBSD silent as BL33;
  the cause, a missing `ARM_LINUX_KERNEL_AS_BL33=1`, is verified harness-only).
- **C slice 27 (2026-10-28, diagnosis + run, $0.001710 metered + $0.32 GCE): the BL33 cause is verified; pro's b2
  continuation fails at the step cap again (2nd identical b2 failure).** Pre-check b1a pass, b1b pass, b2 fail.
  - Harness-only: two out-of-tree TF-A builds with pro's slice-26 flags, booted 150 s each. Without
    `ARM_LINUX_KERNEL_AS_BL33=1`, serial0 ends after BL31 (= slice 26). With it, NetBSD prints the b1b kernel's banner
    and autoconfigures. So pro's recipe plus that one flag meets b2's boot markers.
  - Live b2, pro, unchanged task: `failed step_cap` (30), 77 commands, **0 builds, 0 writes**. It re-confirmed the
    symptom with 3 boots, then read TF-A hand-off code; at step 30 it asked whether the kernel wants a DTB in x0.
    Model fault (over-diagnosis); 30/30 export-matched; D1 0 hits. Tree unchanged.
  - Evidence: `~/evidence/pro-b2-c3-2026-10-28/RESULTS.md`.
- **C slice 26 (2026-10-28, run + D1 fix, $0.001540 metered + $0.42 GCE): pro's b1b continuation is accepted; b2, its
  first live run, fails at the step cap.** Pre-check b1a pass, b1b fail, b2 fail.
  - b1b `accepted checks_passed` at step 31: it fixed the include via `sudo sed`, and a 600 s build timed out (its
    own choice); the 900 s rerun built in 609 s.
  - b2 (same session) `failed step_cap` (30): 19 steps before the first TF-A build (`SPD=opteed`, BL32 = OP-TEE
    v2 images, BL33 = `netbsd.img`). OP-TEE reaches `switching to normal world` and NetBSD prints nothing.
  - Likely, untested: no `ARM_LINUX_KERNEL_AS_BL33=1`, which legacy ctl-run-3 and slice 9's control build set. Model fault.
  - 13/31 b1b replies had no `buyer_cost_micro` and are absent from the export (unbilled so far).
  - **D1 false positive fixed:** build.sh's banner `MAKECONF file: … (File not found)` matched on a successful build.
    `core.BENIGN_TEXT` exempts it; the fixture case fails on old code; over 34 traces only that hit changes (11 → 10).
  - Evidence: `~/evidence/pro-b1b-b2-c3-2026-10-28/RESULTS.md`.
- **C slice 25 (2026-10-28, run + D1 fix, $0.001667 metered + $0.18 GCE): with head+tail output pro acts on ownership
  one step after the denial; b1b still `failed step_cap` (model fault in its own rewrite).** Pre-check b1a pass, b1b fail.
  Step 13's build.sh showed 11 `Permission denied` in the 1 KB head (0 in the last 3 KB); step 14 pro ran `sudo chown`,
  by step 24 it had `chown -R dev:dev` the whole obj tree, built as dev, hit the 2 known `-Werror` errors (step 26),
  fixed them via `sudo sed`/`sudo dd` rewrite, and the rebuild (step 37) failed on its new `#include <arm/smccc.h>`
  (header is `arm/arm/smccc.h`); step cap at 40. 40/40 export-matched. **D1 false-positive class fixed:** all 9 D1 hits
  since `failed_cmds` exists (slice 7) had `failed_cmds ≥ 1` in the header the model saw; `core.audit` now skips them
  (10 older hits incl. both demo true positives unchanged; 2 fixture cases fail on old code). **c3 state changed:** obj
  tree now owned by `dev`. Evidence: `~/evidence/pro-b1b-headtail-2026-10-28/RESULTS.md`.
- **C slice 24 (2026-10-28, harness-only + fix, $0 metered + $0.01 GCE): the 4 KB tail cut build.sh's `Permission
  denied` on slice 21 step 12; harness fault, fixed.** Read slice 21's 7 build.sh job files on c3 (no rerun): step 12's
  output (stderr only, 4966 B) starts with 3 `Permission denied` lines on the darrenhidalgo-owned tooldir wrapper
  `bin/nbmake-evbarm`; `tail -c 4096` dropped them. In the other 6 pro's own `tail -N`/`grep | head` had already
  dropped the denial (model behaviour, `MODELS.md`). Fix: output over 4096 B returns its first 1024 B + an
  omission marker + its last 3072 B (`core._clip`, local and lab); regression test replays the recorded output (old
  code 4/4 fail). Evidence: `~/evidence/tail-cut-check-2026-10-28/RESULTS.md`.
- **C slice 23 (2026-10-28, continuation demo + offline trigger, $0.000203 metered + $0 GCE): pro acts on the
  adopted correction; a plain ownership trigger is mostly redundant; the 4 KB output tail may hide the cause.**
  Slice 22's 3 correction samples that read `ls -d tooldir.*/` first, continued one step with the recorded listing
  (3 draws each): 8/9 draws run the task's build.sh via `sudo -n -u darrenhidalgo` (3/3 samples) → **5/5 overall; the
  rule fired.** Offline trigger (`Permission denied`, command under darrenhidalgo's home, no sudo) on 6 b1/b1b traces:
  5 firings, all genuine, but 3 were self-fixed by pro within 2 steps (s18, s20). The pre-registered build rule fails
  (redundancy); a post-hoc "no sudo 2 steps after a denial" variant fires only on s21 (steps 23, 39), but it was fitted on
  these traces. Nothing built. **Harness-fault candidate:** s21's 7 build.sh-as-dev runs each returned a full
  `core.TAIL` (4096 B) of one echoed nbmake line + `*** [cleandirkernlib] Error code 1`, with no `Permission denied`; the
  full output is missing evidence (only on c3). Evidence: `~/evidence/correction-continuation-demo-2026-10-28/RESULTS.md`.
- **C slice 22 (2026-10-28, replay demo, $0.000645 metered + $0 GCE): neither reasoning carry-back nor a grounded
  correction passes its rule on pro's b1b ownership stall.** Planning found that `run_task` replays assistant turns
  without `reasoning_content`. Pro's `content` is empty on 39/40 replies (flash: 38/40), so the executor never sees
  its own reasoning, although DeepSeek's thinking-mode guide says to pass it back. Slice 21 prefix at step 23, pro,
  n=5 per arm, all complete and valid (B's delivery was verified by +3,083 prompt tokens). Ownership action
  (`sudo`/`chown`): control 0/5; reasoning replayed 0/5 (the same 3/5 `NETBSDSRCDIR` detour); correction
  (requirement + `Permission denied` evidence + `sudo -n -u darrenhidalgo`) 2/5. All 5 correction replies adopt it
  in their reasoning; the other 3 list the tooldir first. Neither rule fired; nothing built. H1 is falsified at this
  prefix; it is untested on flash's b1 stall. Evidence: `~/evidence/reasoning-carry-demo-2026-10-28/RESULTS.md`.
- **C slice 21 (2026-10-28, run + D1 fix, $0.001201 metered + $0.16 GCE): pro reruns b1b, `failed step_cap`;
  model fault.** Setup restored the 2-error driver; pre-check b1a pass, b1b fail. Under `usage_bound` the 7 no-cost
  replies were settled at $0.274 and the run reached the cap (fix holds). Pro ran `build.sh` 9× as `dev`, never with
  sudo: the darrenhidalgo-owned compile dir's `cleandir` failed; it named ownership at steps 22–23, then chased a
  `NETBSDSRCDIR` error its own hand-run `nbmake` caused. Never reached `optee.c`; 0 edits. D1 false positive (`nbmake
  -n` dry run) fixed: `READ_ONLY` covers `…make … -n`, fixture case. Lab stop now in a `finally` (3 failure paths
  tested). Evidence: `~/evidence/pro-b1b-rerun-2026-10-28/RESULTS.md`.
- **C slice 20 (2026-10-28, run + harness fixes, $0.000670 metered + $0.11 GCE): pro's b1b repair cut off by a
  harness fault.** Harness: per-model admission ceilings `core.CEILINGS` (flash; pro 2e-6/7.6e-6; unknown model
  refused before any call); D1 now treats `git -c/-C … diff|log|…` as a read (slice-19 step-2 false positive, fixture
  case). Live b1b, pro, c3 (pre-check b1a pass, b1b fail): `unverified task_budget` at step 28. Pro built at step 15
  (flash: 25), read both errors at 16, and edited from step 17 (6 fragile scripted edits; step 27: "write the whole
  file cleanly"). **Harness fault:** 7/27 pro replies had no `buyer_cost_micro` (not in the export either). Each was
  settled at its request bound ($0.08–0.24), $0.94 charged for $0.0007 billed. Fix: settle at usage × ceilings
  (`usage_bound`); a regression test replays the 27 recorded calls (old code: `task_budget` at step 28). The hypothesis
  is untested, not falsified. Evidence: `~/evidence/pro-b1b-run-2026-10-28/RESULTS.md`.
- **C slice 19 (2026-10-28, demo + fixture, $0.000040 metered + $0.19 GCE): b1 split; flash builds pro's driver but
  never fixes it.** Fixture: `b1-driver-build` → `b1a-driver-source` + `b1b-kernel-build` (b1a's check + the build
  check). b1a's check needs a `files*` stanza (`device optee`, `attach optee at fdt`, `file <x>.c … optee`) whose
  `.c` is new and has `CFATTACH_DECL` (critic: a GENERIC64 line alone passed). Harness-only on c3: b1a pass, b1b
  fail; config-only and stanza-only clones fail b1a. Live b1b (pre-review check 1; the new one also passes on this
  tree), flash, c3 as pro left it: `failed step_cap`. Flash ran `build.sh -T …` at step 25 (79 s): 2 `-Werror`
  errors in pro's `optee.c` (unused `faa`, unused `optee_smc_call`). It predicted both at step 24 and restated them
  at steps 36/40, yet made **no edit** (27 later reads drift to b3: optee_msg, PTAs, shm, DMA). Model fault, no
  harness fault. D1 false positive at step 2 (`git diff; …; cat optee.c` flagged on the source text "failed").
  Flash's write stall now spans c10, c11, slices 12–16 and 19: it is not the b1 writer or repairer.
  Evidence: `~/evidence/b1b-flash-run-2026-10-27/RESULTS.md`.
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
  1. b2 has failed twice identically, so no third plain rerun. Run a grounded-correction demo on slice 27's recorded
     trace (slices 22–23 pattern; ≈ $0.001, $0 GCE). Replay the b2 prefix after the symptom is confirmed (≈ step 20)
     and sample pro's next replies, n=5 per arm: control vs a correction with the requirement (NetBSD banner on serial0),
     the evidence (serial0 stops after BL31; slice 27's `flag` arm boots) and the action (rebuild TF-A with
     `ARM_LINUX_KERNEL_AS_BL33=1`, copy `qemu_fw.bios`). Pre-registered rule: a flagged TF-A build within 2 steps in
     ≥ 4/5 correction draws and ≤ 1/5 control draws. Run live b2 only if the rule passes. Where the correction comes
     from (a stronger model or deterministic evidence) is a later, separate demo.
  2. For the completion gate, run a1→a4 then b1a→b3 unattended from the clean snapshot on a fresh lab (ownership
     friction returns there: snapshot trees are darrenhidalgo's), then delete the c3 disk. Executor per sub-goal is an
     open, measured choice (flash on a1–a4, pro on b1a/b1b/b2 so far).
