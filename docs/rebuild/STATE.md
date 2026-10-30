# Rebuild state

Keep this short and current. One entry per decision; newest first. Full detail per slice lives in each entry's
evidence `RESULTS.md` and in the PR that landed it (`git log`); measured model behaviour in `MODELS.md`.

MISSION-STATUS: ACTIVE

- **Goal:** work item C (minimal replacement core) aimed at the completion gate. The completion run's only task input is
  `run12/task.txt` verbatim. The sub-goal fixtures (`optee_goal_a/b.json`: decomposition, locations, commands, flags,
  proof criteria) were developer-written. They are grading references only (founder decision 2026-10-28, MISSION
  773b964). Everything accepted so far (a1–a4, b1a, b1b, slice 30's b2) is **reachable with developer-written spec and
  help**: it is not progress toward the gate. b3 failed (slice 31). Top priorities: Conflux derives the spec itself
  and produces its own corrections.
- **C slice 49 (2026-10-30, build, $0.000136 metered + $0 GCE): the measured lead and slice 48's stop rule are in core.**
  - `conflux/core.py` gained `Lead`, `Steering` and `run_task(lead_call=…)`, plus the CLI flag `run --lead kimi-k3`.
    - The running lead is kimi-k3 low: it reviews every 300 s without blocking, in the conversation layout, with prompts
      verbatim from slice 43.
    - On a task with no checks, finish and the step cap go to a **fresh lead**: its own init review at k−10, and none of
      the running lead's notes, goals or injected replies.
    - DONE ends the run `unverified`/`finish_review_done`. Tasks with checks are unchanged.
    - Budget and Trace are thread-safe (re-entrant lock).
  - Replay seam: core's `Lead` on slice 43's recorded lead runs reproduces **1,796/1,796** lead requests exactly
    (prompt chars and the last 400 chars).
  - Regression test: the finish review gets none of the running lead's state. It fails on both mutations (reused Lead,
    unhidden injections).
  - Live local smoke: pro + kimi-k3 ran 4 steps; the fresh review said DONE, and the output was checked correct by hand.
    Spend: $0.000136, export-matched; 15 cost-less replies were unbilled.
  - PR #58 review fixes, each with a regression test that fails on the first commit:
    - executor + lead spend count together against `task.max_usd`, with a zero cap making no lead call;
    - the lead is closed and its in-flight call accounted on every exit, an exception included;
    - `reconcile` bills `lead.jsonl` calls, with task and role attribution (`lead_billed_usd`);
    - a review that finishes mid-turn can no longer be overwritten by its successor.
  - Evidence: `~/evidence/core-lead-2026-10-30/RESULTS.md` (`seam.json`, `smoke/`, `reconciled.json`).
- **C slice 48 (2026-10-30, finish-judgement v2, offline, $0.032298 metered + $0 GCE): with the task text scoped to
  the sub-goal, the kimi-k3 lead's fresh finish review accepts checked-done work (17/21) with 0/15 false DONE: supported.
  The live s1@237 false DONE comes from the lead's run-long notes: supported (3/6 with them vs 0/6 goal list only).**
  - A (fresh protocol, 7 P incl. relabelled c3-a2, 5 N, 3 draws). kimi 17/21 accepted, 0/15 false DONE. glm-5.3 low 13/21,
    0/15 (inconclusive). Every rejected positive has grounds in the trace: b2-inject never read its serial logs (6/6), c3-a2's trace
    holds the faulty check's failure feedback.
  - B (live state rebuilt from `lead.jsonl`; seam: prompt chars and ask tail exact on 4/4 live finish states).
    - s1@237 DONE: L (notes + goals) 3/6; Lg (goals only) 0/6; fresh 0/4 (slice 47).
    - DONE replies cite the lead's own earlier "pre-authorized honest-failure path".
    - Other live finish states under L: 0/6.
    - **No review in any arm names the missing Linux boot (G3)**: rejection is never for the gate's reason.
  - Inherited demo fidelity fault: `trace_messages` (slices 40/43/47) wrote the finish result as `finish recorded`, while core
    writes `finish recorded; the harness is running the acceptance checks` (+45–46 chars per finish in the lead prompt; found by the seam, fixed in
    the demo).
  - Evidence: `~/evidence/finish-judge-v2-2026-10-30/RESULTS.md` (`started.txt`, `seam_b.json`, `reviews.jsonl`, `reconciled.json`).
- **C slice 47 (2026-10-30, finish-judgement demo, offline, $0.004527 metered + $0 GCE): the kimi-k3 lead's finish
  review is not a supported stop rule (registered rule falsified: P accepted 6/12, false DONE 0/20, s1@237 0/2); glm-5.3
  low inconclusive (7/12, 1/20). The acceptance half of the instrument is confounded; rejection holds.**
  - 16 recorded states labelled by executed checks: 6 P (sub-goal checks passed), 6 fixture N, 4 gate N (incl. s1@237).
    2 draws each, slice 43's review protocol.
  - Confound (design flaw): fixture goals open "Overall task …; this one is: …" while the review asks about the
    *whole* task. 4/6 of kimi's rejected positives say the sub-goal is done and the overall task is not. The other 2
    (b2-inject) rightly note that the run never read its serial logs. 0/6 rejections are unfounded.
  - c3-a2's N label is wrong: its check required a file OP-TEE lacks, fixed in slice 3. glm's DONE there is correct.
  - Holds: 0 false DONE on the 9 validly labelled refuted states (36 reviews, both models). The replay rejects s1@237
    4/4, while the live lead said DONE: the live false DONE came from its run-long notes and goal list. DONE on one
    state flips between draws (b1b-31, c4-a2, c3-a1).
  - Demo faults: a deadlock in demo code (deferred-settlement callback under a non-reentrant lock; the operator saw it
    as a hang) and a missing `traces/` dir. Both fixed and redrawn; recorded as missing evidence, not results.
  - Core fix (operator request; regression tests fail on the old core):
    - a lost reply (server closed the connection, read timeout) now takes `surplus_post`'s availability backoff
      instead of ending the task `provider_0` after one retry;
    - the whole reply body is bounded by the request limit (a trickling server blocked past it);
    - earlier lost attempts come back in `conflux_lost` and are deferred to the export by `run_task`.
  - Holds did not clear: `fiat_held` went $1.87 → $4.10 with nothing of ours in flight; available + held stayed
    $30.71, so they are reservations, not spend. The other caller's deepseek-v4-pro traffic (129 rows) was in the window.
  - Evidence: `~/evidence/finish-judge-demo-2026-10-30/RESULTS.md` (`started.txt`, `reviews.jsonl`, `reconciled.json`).
- **C slice 46 (2026-10-30, build-wait demo, offline, $0): a harness wait for the executor's own background jobs would
  not free material steps or wall clock; both registered rules falsified, no core change.**
  - Recorded slice-43/40 traces, pre-registered counterfactuals. W2b = a poll waits for the job's end, harness deadline.
    It frees **11, 18, 0** steps (s1, s2b, s3; rule ≥ 12 in 2/3). The verdict is fragile: without the 3 hand-audit
    overrides s1 = 13. W2a (bounded by the poll's own `timeout_s`) frees 0 everywhere.
  - W1 (early-return sleep) frees ≥ 5.8, 1.4, 0.2% of wall (rule ≥ 10% in 2/3); upper bounds are 12.6, 19.1, 1.2%. Most
    slept time was real build time.
  - s3 ran builds in the foreground with large `timeout_s` and polled 3 times. s1's peeks fed 6 mid-build kills.
  - Checked, not a harness defect: a timed-out command's process group is killed with its `&` jobs, and the result
    says so (`timed out … (process group killed)`, since slice 2). s3:9 acted on it; s1:186 ignored it (≈ 1 step).
  - Evidence: `~/evidence/build-wait-demo-2026-10-30/RESULTS.md` (`started.txt`, `scan.py`, `audit.json`).
- **Exploratory re-grade on a task-text reading (2026-10-30, $0, recorded grades only; not the gate).** Goal (a) in
  `task.txt` ("Get QEMU set up with OP-TEE") does not name Linux. Fixtures are grading references (MISSION 773b964), so
  this re-scores the counted runs without G3 (Linux/xtest boot). It also uses **G1′ = OP-TEE sources obtained, any
  method** (inferred from G2): the qemu_v8 manifest is a fixture recipe. **Binding gate unchanged:** MISSION still
  requires the Linux boot (G3), and the registered 0–7 verdicts stand (39 falsified, 40 falsified, 43 inconclusive).
  - T-scale (0–6: G1′ G2 G4 G5 G6 G7), exploratory:
    - slice 39: lead 3, 3 vs pro alone 3, 3, 3;
    - slice 40: 5, 4, 3;
    - slice 43: 6, 5, 5.
  - Task reading of goal (a) (G2 ∧ G6): lead at 240 steps 3/3, at 120 steps 1/3, pro alone 0/3.
  - lead-s1 meets every T-scale milestone (6/6). On the binding gate, its DONE is still a false acceptance (G3 not met).
    Caveats:
    - OP-TEE liveness in the driver boot rests on the CALLS_UID reply. The secure-UART log is not in the trace, and the lab was deleted.
    - The userland client demo failed.
    - GET_OS_REVISION returned 0xffffffff.
  - **Measured cost drivers** (slice 43 traces, `scan.py` → `scan.json`). The 240-step cap binds: s2b and s3 hit it.
    - Fixed `sleep ≥ 60` waits (model `exec` with `sleep N`, N ≥ 60, not running qemu; `scan.json` `fixed_sleep`):
      **s1 37 commands, 8,100 s (16% of steps, 41% of wall clock); s2b 37, 11,160 s (15%, 35%)**; s3 1, 60 s (0%).
    - History growth: prompts reach 329–393k tokens. Latency per step rises 1.5–3× after step 120. It costs wall clock, not steps.
  - Evidence: `~/evidence/cost-drivers-2026-10-30/REGRADE.md` (`scan.py`, `scan.json`).
- **C slice 45 (2026-10-30, lead init-probe demo, live, $0.000754 metered + ≤ $0.38 GCE): giving the kimi-k3 lead its
  own `run_shell` probes on a fresh lab before the init goal list does not add goal (a)'s Linux proof; registered rule
  falsified in both arms.**
  - Arms: T0 = probes only (≤ 15, web via the proxy), T1 = T0 + "read the setup documentation of the software the task names".
    Linux/xtest boot goal with goal (b) kept (hand audit): **T0 0/6, T1 0/6** (lenient 1/6; rule ≥ 3/6). Goal (b) kept 12/12.
  - The lead probes little and generically: median 2 of 15, host census + web, **0/43 probes looked under `/home`** for the
    machine's NetBSD project. T1 read NetBSD man pages, not OP-TEE's. One T0 draw read OP-TEE's `qemu_v8.mk`/manifest and
    still wrote NetBSD as the normal world. Across slices 44–45: 0/32 non-c3 lists derive the gate's Linux boot.
  - **Demo harness fault (MISSION a58a30e):** the demo's own cap guard held cost-less replies at ceiling bounds and refused
    10 draws with 0 calls ($0.32 vs $0.000013 billed). Recorded as missing evidence and redrawn under `core.Budget`
    (export settlement); RESOURCES now says caps always use it. kimi-k3 in a tool loop: 21/44 replies without cost, all unbilled.
  - Evidence: `~/evidence/lead-probe-demo-2026-10-30/RESULTS.md` (`started.txt`: pre-registration + 3 amendments).
- **C slice 44 (2026-10-30, per-goal check demo, offline, $0.001096 metered + $0 GCE): asking the kimi-k3 lead, after
  its init turn, for each goal's executed check does not add goal (a)'s Linux proof; registered rule falsified.**
  - One generic added turn (P1: "for each goal, the executed check that would show it is done; rewrite the goal list";
    P2: + "runnable without the later goals") on the 6 recorded init conversations of slices 40/43, 2 draws each.
  - Linux/xtest boot goal with goal (b) kept: **P1 2/12, P2 2/12** (rule ≥ 6/12), all from c3, whose init reply already
    proposed the stock Linux/xtest boot; **0/20 from the other inputs**. Goal (b) kept 24/24.
  - Goal (a)'s derived check is OP-TEE's secure-world banner (`I/TC: OP-TEE version`) in 19/20 non-c3 lists, with a
    NetBSD boot in 15/20: a stable literal reading of `task.txt`, the same one the old `lab/` run reported as goal (a) done.
  - Second materially identical failure (slice 42 review, slice 44 checks): no third prompt variant on the goal list.
  - Unattributed caller still active on the shared key after slice 43 (57 rows, $0.009536, ledger "not Conflux").
  - Evidence: `~/evidence/acceptance-check-demo-2026-10-30/RESULTS.md` (24/24 export-matched).
- **C slice 43 (2026-10-29/30, step-cap demo on full `task.txt`, $0.378958 metered (export) + ≤ $8.07 GCE): a kimi-k3
  low lead at 240 steps (was 120) scores 6, 4, 4 of G1–G7 (median 4): registered rule inconclusive (≥ 5 / ≤ 3).**
  - Every counted run gained after step 120 (+2, +2, +3, paired): G5 3/3, G6 2/3, and the **first G7**: lead-s1's driver
    attached and its CALLS_UID SMC got OP-TEE's API UID words back. G3 (Linux) still 0/3, G1 1/3: goal (a) stays lost.
  - First live finish reviews: 18/19 finish proposals answered not DONE; 1 DONE (lead-s1) is a **false acceptance under
    the gate** (no Linux; it accepted a failed client demo and a wrong GET_OS_REVISION). Reviews median 178–248 s, 1/154 > 10 min.
  - Offline: the lead named 4/7 of slice 40's masked failures and made "exit 0 ≠ success" a standing rule.
  - **Harness fault, fixed in core (MISSION a58a30e):** lead-s2 ended `run_budget` at step 107 on $1.59 of usage × ceiling
    settlements vs $0.029 billed (14 replies without `buyer_cost_micro`; 25/25 such replies never reach the export, the
    balance moves by exactly the export total). Core now leaves such costs `pending` and settles them from export rows
    (`Budget.resolve`; `"unbilled"` at 0 after 10 min); regression test replays lead-s2's 6 pro replies. lead-s2 not counted,
    lead-s2b replaced it; lead-s3 ran on a frozen checkout of the registered core.
  - **Floor audit:** `scripts/provider_probe.py` sent paid requests without `X-Min-Discount` (fixed, tested); core always
    sends it. The 60%-discount kimi-k3.1-pro rows (10-29) and 1,076 deepseek-v4-pro rows (10-30) come from an unidentified
    caller on the shared key, not from this controller (ledger row "not Conflux"). Missing input (founder): who else holds
    `surplus.key`; a dedicated key or a key-level floor in the Surplus dashboard closes it.
  - Evidence: `~/evidence/step-cap-demo-2026-10-29/RESULTS.md` (`grade-lead-*.json`, `started.txt`).
- **C slice 42 (2026-10-29, goal-list review demo, offline, $0.001207 metered + $0 GCE): a different-family review of
  the kimi-k3 lead's initial goal list does not restore goal (a)'s Linux proof; registered rule falsified.**
  - Inputs: slice 40's 3 recorded init replies (goal (a) read as "QEMU + OP-TEE with NetBSD as normal world"), generic
    request "does it cover everything the task asks for, read the way the user most likely means it? corrected list".
  - Linux/xtest boot goal with goal (b) kept: glm-5.3 low **2/15** (rule ≥ 8), kimi-k3 low self-review 5/15, no
    review 0/9; reference build env (qemu_v8/repo): 0, 3, 0. Every hit came from c3's reply, whose free-text next
    steps already named the stock qemu_v8 boot; from c1/c2 0/10 per model. Review promotes, never derives. Build nothing.
  - Evidence: `~/evidence/goal-review-demo-2026-10-29/RESULTS.md` (36/36 export-matched).
- **C slice 41 (2026-10-29, D1 classification of slice 40's 25 hits, $0): 12 are real masking in the executor's own
  commands, 6 were audit false positives (now fixed), 7 are residual false positives, and one harness fault was fixed.**
  - Harness fault H1: with a trailing `cmd &`, a background child's late stderr pushed the `__CONFLUX_PIPESTATUS=` marker
    off the end, so `pipestatus`/`failed_cmds` were lost and the marker was shown to the model (3/1,553 execs).
    `_split_pipestatus` now takes the last marker line anywhere. Regression tests on recorded stderr, local, and a
    fake-remote lab fail on the old parser.
  - D1 false positives fixed: `sleep N && tail log` is a read (5), cross-prefixed `strings` (1). Residual (recorded
    only): file text from mixed read+write commands (4), `touch … || echo` writability probes (3), and the model's own
    echo text (1 in slice 39). An echo-literal exemption was dropped in review: it hid a tool error whose text equals
    an unexecuted `|| echo` fallback (regression test). After the fix slice 40 has 19 hits, slice 39 is unchanged (11),
    and no hit was added.
  - Real masking (model, for the lead/critic): `curl -s` without `-f`, `… &`, `| tee log; echo EXIT $?` inside
    `sh -c`, `|| true`.
  - Evidence: `~/evidence/d1-slice40-classify-2026-10-29/RESULTS.md`.
- **C slice 40 (2026-10-29, lead-factor demo on full `task.txt`, $0.198894 metered (export) + ≤ $2.71 GCE): a
  non-blocking kimi-k3 (`reasoning_effort=low`) lead, in place of glm-5.3 low, still does not pass the registered rule
  (lead 4, 3, 3 vs slice 39's controls 3, 2, 3; median 3 ≤ 3: falsified). But it alone reached G5 (kernel rebuilt with
  the driver, 2/3 vs 0/5 slice-39 runs) and G6 (NetBSD on OP-TEE firmware, 1/3 vs 0/5); G7 (driver attaches) 0/3.**
  - Factor choice by the registered rule: glm-5.3 now refuses `medium` (HTTP 400, accepts only low/high/max), so the
    lead model changed. Offline finish replay of slice 39's 3 false control finishes: **0/6 false DONE** for glm-5.3 low
    and 0/6 for kimi-k3 low. Whether a lead accepts a genuine DONE is unmeasured (no complete run exists).
  - Lead runs lose goal (a): G1 1/3, no Linux boot (G3 0/3). Executors follow the lead's numbered steps and work in the
    machine's NetBSD tree (2/3). No executor proposed finish (all ran to the 120-step cap). Review latency grows with the
    trace: median 275/290/424 s, max 406/655/779 s, so 2/3 runs had reviews past the 10-min cadence bound.
  - Unclassified: D1 hits 15/10/0. In lead-c1 most are masking in the model's own commands (`&`, `|| …`, `curl -s`
    printing a 404 with exit 0), plus a source-text false positive.
  - Evidence: `~/evidence/lead-factor-demo-2026-10-29/RESULTS.md` (`started.txt`, `grade-lead-c*.json`).
- **C slice 39 (2026-10-28/29, other-model-leads demo on full `task.txt`, $0.377811 metered (export) + ≤ $5.23 GCE): a
  non-blocking GLM-5.3 lead does not move milestones vs pro alone; registered rule falsified (lead 2, 2 vs control 3, 2,
  3 of G1–G7; lead-b3 futility-stopped). False DONE: 0/2 lead runs vs 3/3 controls that called finish with false
  success claims, but neither lead run ever proposed finish (both ran to the 120-step cap, 0 retries), so whether the
  lead rejects a premature finish is untested.**
  - Design as measured (founder decisions cda6dac, a594bbc, 68ad22c): conversation layout (data first, one goal per
    turn), review every ≥ 300 s of wall clock, never blocking pro; glm-5.3 at `reasoning_effort=low` (reviews 100–285 s;
    default effort took 17–20 min per review, pf rubric equal). Lead runs went further in kind (driver wired into the
    machine's NetBSD tree; OP-TEE booted to U-Boot) but not to the next milestone; lead goal lists add scope.
  - Harness faults fixed in core (regression tests fail on the old core): model-max output and input-only admission
    (90b27cd), `X-Min-Discount: 90` (5ee7a8b), no-seller replies waited out up to 4 h and never ending a run, unbilled
    errors at $0, admission on settled spend only. Pair 1 (step-counter blocking lead) was cut by provider outages; the
    blocking design is retired. All demo runs before the fixes are archived, not counted.
  - Evidence: `~/evidence/other-model-leads-demo-2026-10-28/RESULTS.md` (`started.txt` = registration history).
- **C slice 38 (2026-10-28, probe-and-replan demo, $0.071824 metered (balance delta, export-matched) + $0.07 GCE):
  stopped by founder decision (MISSION a7322df) before any re-plan reply; outcome is missing evidence.** Stage 1 ran
  slice 37's 21 test commands verbatim on c3 as harness probes (c3 restored, TERMINATED). Raw observations: U-Boot as
  BL33 boots in 4/4, `-d int` shows NetBSD entered at EL1 and silent, both TF-A rebuilds fail on a missing
  cross-compiler in PATH, no gdb on the lab. 2 stage-2 K3.1-pro requests were billed with no reply recorded (1 killed
  externally, 1 stopped). Not resumed. Evidence: `~/evidence/probe-replan-demo-2026-10-28/RESULTS.md`, `STOPPED.txt`.
- **C slice 37 (2026-10-28, hypothesis-plan demo, $0.467867 metered (balance delta; export $0.359383) + $0 GCE): a
  K3.1-pro one-shot "competing hypotheses, each with its cheapest test" plan on pro's b2 stall never tests the BL33
  kernel setting; hypothesis falsified, stage 2 not run.**
  - Setup: slice 35's observable trace to step 20, flattened, plus a generic request (no task-specific words). n=5.
  - P1 (a test that builds TF-A with that setting = 1): **0/5** (4 valid, 1 truncated twice). Slice 34 (legacy
    decider prompt, clipped slice-27 trace, so not a like-for-like baseline): 2/5. The rule (≥ 3/5) failed, and with 0 P1 plans the pro hand-back stage (lab) did not run.
  - Post-hoc: **12/12 hypotheses come with an executable QEMU-boot test (0 pure reads)**. 4/4 plans include a U-Boot-as-BL33
    control boot. 3/4 name the real mechanism (x0 not pointing at the DTB at kernel entry) and test it with a QEMU exec
    trace or a gdb break at entry. 2/4 reconstruct a full TF-A make line from the trace. None maps x0 to the build setting.
  - Demo accounting fault, fixed in-run: replies without cost were settled at list-ceiling bounds and blocked samples;
    re-settled from the balance delta (amendments in `started.txt`).
  - Evidence: `~/evidence/hypothesis-plan-demo-2026-10-28/RESULTS.md`.
- **C slice 36 (2026-10-28, model-switch takeover demo, $0.473384 metered (balance delta; export $0.131383) + $0.40
  GCE): a different-family model taking over pro's stalled b2 run with tools does not fix it; hypothesis falsified.**
  - Setup: K3.1-pro and GLM-5.3 each got slice 35's observable trace to step 20, no developer prose, and the
    remaining 10 steps on c3, through `run_task` (demo-only initial-messages seam; offline seam check 4/4).
  - Results: K3.1-pro **0/2** accepted (rule ≥ 2/3; pro baseline 0/2; run 3 skipped). GLM-5.3 0/2 (exploratory).
    0 builds in all 4 runs; 0/40 replies named the BL33 kernel setting.
  - What happened: both models reproduced the reading stall (TF-A headers, SPD, toolchain). K3.1-pro run 2 decided
    "rebuild" at step 30 without the setting, as pro did. In the tool loop both reason briefly (≤ 280 tokens) and
    are valid, fast and cheap: K3.1 ≈ $0.004/step cached, GLM ≈ $0.0001/step; 0/40 truncations. So switching
    changes who reads, not what is read. Build nothing.
  - Accounting fault: 7 replies without `buyer_cost_micro` are absent from the usage export and from `recent_usage`;
    the balance delta is recorded.
  - **Surplus credit is $8.23, below the weekly cap**: it binds paid work.
  - Evidence: `~/evidence/takeover-demo-2026-10-28/RESULTS.md`.
- **C slice 35 (2026-10-28, harness fix + live re-measure, $0.001271 metered + $0.17 GCE): reasoning passback fixed;
  pro's b2 stall survives it (failed `step_cap`, n=1); hypothesis falsified.** Harness fault (MISSION c36f507):
  `run_task` now passes each assistant turn's `reasoning_content` back; regression test fails on the old loop. Live
  pro b2 on c3 (slice 27's tasks, no injection), with reasoning delivered on every turn (request-side log): 70 commands,
  0 builds, 0 writes. At step 24 pro read the BL33 kernel setting at its default and **dismissed it in reasoning**. At
  steps 26–27 it decided to rebuild (slice 27 never did), with a flag list that omits that setting, then hunted the
  toolchain until the cap. The b2 stall is a wrong belief, not lost context: **model fault, unconfounded**. With
  slice 22 (b1b 0/5) and slice 34 (b2 0/6), passback has not moved pro off a stall in any measurement. D1 0 hits;
  30/30 export-matched. c3 unchanged.
  - Still confounded: b1 (c10/c11/slice 18, flash) and b3 (slice 31). Re-measure them live when a lab run is due anyway.
  - Evidence: `~/evidence/pro-b2-passback-c3-2026-10-28/RESULTS.md`.
- **C slice 34 (2026-10-28, work item D demo, $0.590990 metered + $0 GCE): a different-family decider does not
  reliably turn pro's b2 stall into the experiment; hypothesis falsified at n=5.** Legacy `DECIDER_PROMPT` verbatim
  (`conflux-baseline-20261026`), slice 27's trace to step 20 (no reasoning), only the model varied; rule ≥ 3/5 and
  ≥ pro + 2. Hypothesis-testing decision (flagged TF-A rebuild + boot): pro 0/5, **kimi-k3.1-pro 2/5** (both grounded
  in the executor's step-11 output), kimi-k3 and glm-5.3 **0/5 valid** (reason to the 24000-token cap, no JSON,
  20/20). K3.1-pro is ≈ $0.055/call (≈ 370× pro). Post-hoc: pro given K3.1-pro's 2 decisions builds 0/12 in the next
  step, with and without reasoning passback. It adopts the decision and hunts for the original make line, which neither
  model has (= slice 28/29 recipe-free). Build nothing.
  - Instrument fault caught in-run: the first 29 calls used `core.MAX_TOKENS` 8192 (legacy decider: 24000), 26/29
    truncated; archived, counted in spend, re-run at 24000.
  - Evidence: `~/evidence/decider-critic-demo-2026-10-28/RESULTS.md` (71/71 export-matched).
- **C slice 33 (2026-10-28, single-model baseline demo, $0.001184 metered + $0.10 GCE): a pro planner given only `run12/task.txt` derives
  none of the machine-specific spec; hypothesis unverified (1/3 probe samples, 2 lost to GCE stockouts).** Rubric of 17
  fixture items, pre-registered, hand-audited (regex in brackets): no probes (N) 7, 5, 5 (9, 7, 8); with ≤ 20 runtime
  probes on a fresh clean-snapshot lab (P0) 4 (7). 0/4 specs located the NetBSD project: no NetBSD tree, obj dir,
  tooldir or ownership. P0's 20 probes were a host census, and none looked under `/home` or searched for NetBSD. Its
  plan builds a standalone module, with no kernel, firmware or NetBSD boot. Known without probes: `repo init …
  qemu_v8.xml`, `build.sh -m evbarm64`, an fdt attach stanza. Never derived: NetBSD as TF-A BL33, the BL33 kernel
  flag, `linaro,optee-tz`, a no-OP-TEE control. N1 wrote 3 always-pass checks (`|| echo`). Build nothing.
  - Demo-harness faults fixed in the demo: truncated/invalid specs are now resubmitted. A stockout leaves
    `devbox-lab up`'s boot disk behind, so every retry fails `already exists`; the disk is now deleted before a
    retry. `core.run_lab` does not retry, so it is unaffected.
  - Evidence: `~/evidence/spec-derivation-demo-2026-10-28/RESULTS.md` (`audit.md`; 19/19 export rows).
- **C slice 32 (2026-10-28, single-model baseline demo (pro diagnosing pro; MISSION 6eafcd8), $0.002378 metered + $0.45 GCE): a fresh pro diagnostic sub-run with runtime probes
  does not produce the b2 correction: 0/3 grounded passes, hypothesis falsified.** This is a
  reachable-with-developer-written-spec instrument: the input is the fixture's b2 text plus slice 27's trace to step 20.
  c3 was reset to the slice-27 state (no-flag TF-A rebuilt, b2 check 2 fails, old job dirs archived and removed).
  Each of the 3 sequential, isolated diagnoses had ≤ 10 probes. All 30 probes were reads (0 builds, 0 boots). None
  called `correct`; 19 more probes were denied after the cap. All 3 named the right flag hypothesis in their
  reasoning and never tested it: the executor's "names it, reads on" stall again. Do not build it.
  - Demo harness fault caught before any paid call: TF-A `realclean` failed silently and relinked slice 30's flagged
    objects (b2 passed). Fixed by `rm -rf build/qemu`.
  - Evidence: `~/evidence/self-diagnosis-demo-2026-10-28/RESULTS.md`.
- **C slice 31 (2026-10-28, run, $0.017228 metered + $0.62 GCE): pro's first b3 run fails at the step cap (40 steps,
  100 commands, 0 writes, 0 builds); hypothesis falsified.** No injection, but its starting state includes slice
  30's developer-helped b2 firmware. Pre-check: b1a, b1b and b2 pass, b3 fails. At step 19 pro correctly named the
  problem: the driver matches only `linaro,optee-tz`, which is absent without OP-TEE. Steps 20–40 read TF-A, OP-TEE
  DT and NetBSD fdt code without acting. This is the 4th reading stall (flash b1, pro b1, pro b2, pro b3). Model fault;
  D1 0 hits; 40/40 export-matched.
  - Before any further b3 run: check 2 fails on pro's driver because it `#define`s the OP-TEE UID words for a
    comparison, which the task text does not forbid. Fix the task text or the check, then re-validate harness-only.
    Pro's "no attach under OP-TEE" premise came from a 4 KB-clipped log, so it is unverified (missing evidence).
  - Evidence: `~/evidence/pro-b3-c3-2026-10-28/RESULTS.md`.
- **C slice 30 (2026-10-28, hook + run, $0.007037 metered + $0.21 GCE): with slice 29's correction M injected once at
  step 20, pro's live b2 is accepted at the step cap (30/30, 0 steps to spare).** The correction was developer-authored,
  so b2 is not done (founder decision 2026-10-28). Harness: `Task.inject_step`/`inject`
  appends one `user` message before that step's model call and traces it (`inject` row); 2 regression tests fail on old
  code. The evidence sentence was restated as the slice-27 harness diagnosis, the rest verbatim. Pre-check b1a/b1b pass, b2 fail.
  - Steps 1–19: 50 reads chasing the original flags (= slices 27–29). After the correction: 5 steps of input checks,
    step 25 ran the recipe verbatim, which was a **no-op in-tree** (`Nothing to be done`). The recipe was verified
    out-of-tree, and TF-A does not track flag/BL33 changes. Pro ran `realclean` itself (27), rebuilt (28), copied the
    bios (29), boot-tested (30); the cap checks passed.
  - D1 0 hits; 30/30 export-matched. c3 now holds the flagged b2 firmware; its TF-A build dir was rebuilt for NetBSD.
  - Evidence: `~/evidence/pro-b2-inject-c3-2026-10-28/RESULTS.md`.
- **C slice 29 (2026-10-28, replay + continuation demo, $0.000971 metered + $0.03 GCE): a b2 correction that carries
  slice 27's verified make line gets pro to build; one without it does not, even within 2 steps.** Same prefix as slice
  28, pro, all 26 calls export-matched. Rule: flagged TF-A build (`make` + `ARM_LINUX_KERNEL_AS_BL33=1`).
  - M (correction + recipe, 1 step): **3/5**, rule ≥ 4/5 not passed by one; the other 2 `ls` the recipe's inputs.
    Post-hoc, those 2 continued on c3 build in 5/6 step-2 draws (5/5 samples by step 2).
  - C2 (slice 28's recipe-free correction, its draws' reads executed on c3, 3 draws each): **0/5 samples, 0/15 draws**;
    all 15 keep reconstructing the toolchain and the original flags.
  - Evidence: `~/evidence/b2-recipe-continuation-demo-2026-10-28/RESULTS.md`.
- **C slice 28 (2026-10-28, replay demo, $0.000423 metered + $0 GCE): pro adopts a grounded b2 correction but does
  not build in the next step; the rule is not passed at 1 step (2-step outcome unmeasured).** Slice 27 prefix at
  K=20 (symptom confirmed), pro, n=5 per arm; replay exact (35,233 prompt tokens = recorded). Flagged TF-A build in
  the next reply: control 0/5, correction 0/5. All 5 correction replies plan the flagged rebuild in their reasoning,
  then look for the cross-compiler and the original make flags. Slice 26's make line is not in this session. Control
  names the flag in its reasoning in 4/5 draws, yet 4/5 keep reading TF-A hand-off code (= slice 27's
  over-diagnosis). No live b2. Evidence: `~/evidence/b2-correction-demo-2026-10-28/RESULTS.md`.
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
  1. Toward the gate (lead + fresh finish review are in core since slice 49): a **gate run** on a fresh lab:
     `task.txt` only, executor `deepseek-v4-pro`, `--lead kimi-k3`, 240 steps. Its grading script must copy the run's boot
     logs (secure and normal UART, wherever the run wrote them) off the lab before the lab is deleted, so G6/G7 can be
     re-executed independently. Delete the c3 disk.
  2. Gate-reason rejection is unmeasured: no review (slices 47–48, 0/16 at s1@237) names the missing Linux boot. With
     `task.txt` alone the lead reads goal (a) as OP-TEE firmware for NetBSD (slices 42/44/45). The gate run measures it; no
     further goal-list variant (two materially identical failures).
  3. History growth (prompts to ~390k tokens, latency 1.5–3× after step 120): measure a generic old-output compaction
     on the recorded traces before any core change.
  4. Missing input (founder, non-blocking): is the Linux boot required for goal (a) when `task.txt` does not name it? The
     gate keeps G3 until it is answered. Separately measured gap: the lead's probes never locate the machine's NetBSD
     project (0/43, slice 45; = slice 33).
