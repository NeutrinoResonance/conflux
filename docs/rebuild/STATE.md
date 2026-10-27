# Rebuild state

Keep this short and current. One entry per decision; newest first.

MISSION-STATUS: ACTIVE

- **Goal:** work item C (minimal replacement core) aimed at the completion gate. A done offline (live rerun deferred to E); B done.
- **F step 1 (2026-10-27, executed offline, $0): the D1 self-audit runs at the end of every task.**
  - D1 flags a model step that exited 0 although its own output reports failure. `conflux/core.py` `audit()` runs in
    `run_task`'s `end()` on every exit path, so it covers both `run` and `run --lab`. It writes an `audit` trace row and
    `audit_hits` on `task_end` and in `summary.json`; a hit does not change the status. Recorded traces:
    `python -m conflux.core audit <trace.jsonl>...`, which needs no key.
  - The demo's false positives are fixed generically:
    - commands are split on separators outside quotes;
    - `git log`/`show`/`diff`, `apt search`/`show` and `command -v` count as reads;
    - a command that prints `$?` is exempt, because the model captured the exit itself.
  - **Hypothesis supported.** On the 16 demo traces, D1 gives exactly the 2 required hits and nothing else; the demo
    script gave 5 extra:
    - c4/a3 step 27, `make … | tail`;
    - c3/a1 step 3, a `;` chain hiding a Traceback.

    RESULTS.md says 17 traces, but its output covers 16.
  - **Held-out** (7 unseen traces, rules not tuned to them): c1 gave 0 hits. c2/a1 gave 8 hits; all 8 are real
    failures reported as exit 0 (hand-labelled, single labeller):
    - 6 are pipe-masked (pre-pipefail; slice 6 covers them);
    - in step 9, `apt-get update` only warned and itself exited 0;
    - step 2 is a model-written `|| true`.
  - **Residual class after pipefail:** `;` chains, `|| true`, and tools that exit 0 with warnings. The model sees the
    text, but nothing in the exit status reflects it.
  - Evidence: `~/evidence/self-audit-d1-2026-10-27/` (`grade.txt`, `README.md`). Fixture
    `tests/fixtures/core_loop/audit_d1_cases.json` (7 cases with source sha256). Tests: 57 in `test_core_loop.py` (+5 new);
    suite 710 passed, 1 xfailed.
- **C slice 6 (2026-10-27, executed, $0 metered + $0.03 GCE): the executor no longer masks pipeline failures.**
  - Every command (model, checks, setup; local `execute` and `lab_shell`) runs under `set -o pipefail`. An `EXIT` trap
    reports the last pipeline's per-stage exits as a stderr marker. The harness strips the marker and returns it as `pipestatus`, which
    goes into exec trace rows and check results. The model sees `exit=2 pipestatus=2 0` when a pipeline has more than one stage.
  - **Hypothesis supported.** Offline: 7 new tests, red on the base. They cover `false | tail` → 1 `[1, 0]` in both shells, a c4-shaped
    `… 2>&1 | tail` build now non-zero in the model observation, and `seq | head` → 141 (the case checks must avoid).
    On c3 (no model): `make no-such-target | tail` → exit 2 `[2, 0]`; **a1, a2, a3 and a4 all `pass`** under the
    new shell (a4 in 55 s, OP-TEE 4.11.0 + Linux 7.3.0 markers). The a3 QEMU check dropped `| head -n 1 | grep -q`
    (a SIGPIPE risk); the a1/a4 `head <file> | grep -q` checks are safe and unchanged.
  - Model habits like `cat big | head` now report 141 with `pipestatus=141 0`. That is intended.
  - Evidence: `~/evidence/core-runs/2026-10-27-c6/` (`recheck_goal_a.py`, `recheck.json`). Suite 688 passed, 1 xfailed.
- **Next action:**
  1. Structural fix for the D1 residual (harness fault, c3/a1 step 3). Extend slice 6's EXIT-trap marker with an
     `ERR` trap that counts failing simple commands outside conditions, and show `failed_cmds=N` to the model when
     exit=0. Add a regression test on the c3 shape (`python3 -c 'import nope'; echo ok` → exit 0, failed_cmds=1), and
     revalidate the a1–a4 checks harness-only on c3 before any paid run.
  2. Then run `--only a3-build,a4-boot --lab c3 --workdir '~/optee-work'` on the default executor (expected: a3 accepts
     at once, a4 within 25 steps). Check `audit_hits`, then cut goal (b) sub-goals with harness-validated checks.
  - Delete the c3 disk once goal (a) is done or abandoned.
- **C slice 5 (2026-10-27, executed, $0.000000 metered + $0.05 GCE): default executor is `deepseek-v4.1-flash`; a4 cut.**
  - **Offers** (`GET https://api.surplusintelligence.ai/v1/prices`, 09:31Z): at list price v4.1-flash is *not* cheaper
    ($0.14–0.30/M in, $0.42–1.20/M out vs v4-flash $0.05–0.17 / $0.275–0.45). Billed price decides (founder decision).
  - **H5a supported:** tuning run c5 (3 tasks × 2) gave **6/6 accepted**, 2–5 steps, 0 retries, 20 calls, 20/20
    export-matched on tokens. Every call billed `buyer_cost_usd` 0.000000, below the export's 1 micro-USD resolution
    (v4-flash c1b: $0.000116 per accepted run). `direct_cost_usd` (list) sum: $0.002887. `MODEL` switched.
  - **Admission bound fixed:** the old `(bytes + MAX_TOKENS) × 4e-7` was below v4.1-flash's top output list rate
    ($1.2e-6/tok). The bound is now `bytes × 4e-7 + MAX_TOKENS × 2.4e-6` (≈ +$0.0049 per call). The new test is red
    under the old formula.
  - **a4-boot cut and harness-validated (H5b supported):** the check runs upstream's `make check-only CHECK_TESTS=xtest
    XTEST_ARGS=1001` (no rebuild) after deleting the old logs, then greps the regenerated logs. Try 1 failed with
    `expect: command not found`: a1 never installs `expect`, so the check now installs it if missing (the committed form runs `cd optee/build` first). Try 2: **pass
    in 54 s**. Log markers: `I/TC: OP-TEE version: 4.11.0`, `Primary CPU switching to normal world boot`, `Linux version
    7.3.0`, `optee: revision 4.11`, `Status: PASS (10 test cases)`. This is a harness pass, not a model-accepted run.
    The logs were reset afterwards; c3 is stopped with its disk kept.
  - **Critic fix (the evaluator is model-editable):** before booting, the check requires `optee/build` (the Makefile and
    expect drivers) to be clean, with HEAD in the history of the freshly fetched `OP-TEE/build` master, and QEMU to be
    an ELF binary. On c3: pristine tree → pass (55 s); appending to `qemu_v8.mk` → fail. The regression test rejects a
    fabricated echo target, a dirty tree, a fake QEMU and stale logs. Trust boundary: built images are the work under
    test.
  - Evidence: `~/evidence/core-runs/2026-10-27-c5/` (`offers.json`, `tuning/reconciled.json`, `recheck_a4.try{1,2}.json`).
    Tests: 55 in `tests/test_core_loop.py`; suite 681 passed, 1 xfailed.
- **C slice 4 (2026-10-27, executed, $0.011158 metered + $0.36 GCE): bare flash builds the full qemu_v8 tree.**
  Run c4 on kept lab `c3`, `--only a2-sources,a3-build`, 1 tunnel start, 0 restarts.
  - **a2 accepted** in 12 steps / 256 s / $0.00052. That is more than the predicted ≤ 5: flash re-installed `repo`
    and re-ran `repo init`/`sync` instead of first inspecting the existing tree.
  - **a3 `failed` at the step cap** (40 steps, 3353 s, $0.010638), **but the build is complete.** `make toolchains`
    (step 21) and `make -j8` (step 29, 2129 s) both finished, and QEMU 10.0.0 was built. The check was wrong again: it
    required `bl32_extra2.bin` to be non-empty. That file links to `tee-pageable_v2.bin`, which is 0 bytes because the
    default config has `CFG_WITH_PAGER=n`. Flash spent steps 32–40 investigating the impossible check.
  - Check fixed: the file must exist, and every other image must be non-empty. A regression test covers the real
    layout. A model-free recheck on the kept disk gives a3 `pass` on both checks (`recheck_a3.json`). That pass is
    not a model-accepted run.
  - **Hypothesis partly supported:** with tunnelled egress, flash drives the whole goal-(a) build within its caps.
    Acceptance failed on the harness's check, not on the work.
  - **Model failure modes (bare flash):**
    - Steps 1–20 went to reading makefiles in 4 KB slices and installing packages before any build started.
    - `make … | tail` masks make's exit code.
    - It never questions a check it cannot satisfy and never calls `finish`.
  - **Process lesson (twice now):** every acceptance check must pass, harness-only, on a real tree *before* a paid
    model run.
  - 52/52 calls export-matched. Lab `c3` is stopped with its disk kept (built tree).
    Evidence: `~/evidence/core-runs/2026-10-27-c4/`. Tests: 53 in `tests/test_core_loop.py`.
- **C slice 3 (2026-10-27, executed, $0.004105 metered + $0.13 GCE): labs have egress.** No Cloud NAT exists (0 routers).
  - **How:** `run_lab` serves a stdlib HTTP CONNECT/forward proxy on the controller (`egress_proxy`). A supervised
    `gcloud compute ssh -N -R 3128:…` reverse-tunnels it to the lab. Every lab job gets `PROXY_ENV`. Harness setup
    adds the apt proxy and sudo `env_keep`. An egress check gates the first model call (`egress_failed`, $0).
    Tests: 52 in `tests/test_core_loop.py`; suite 678 passed, 1 xfailed.
  - **Hypothesis supported:** slice 2's a1 failure was caused by the environment. Run c3 (bare flash, fixture
    unchanged): egress check passed (github 200, pypi 200, `APT_OK`), 1 tunnel start, 0 restarts.
    - **a1 accepted** in 19 steps / 470 s / $0.00126.
    - **a2 `failed` at the step cap** (30 steps, $0.002845). Its *check* was wrong: it required
      `optee_os/core/arch/arm/plat-qemu/conf.mk`, which OP-TEE does not have (qemu_v8 builds `plat-vexpress`,
      `vexpress-qemu_armv8a`). Flash had already fetched the tree correctly: it found that `-b qemu_v8` is not a
      branch and recovered with `-m qemu_v8.xml`, then `repo sync` OK in 56 s by step 15. It spent the remaining
      15 steps chasing the impossible check.
    - Check fixed in `optee_goal_a.json`. A post-hoc harness recheck on the kept disk (no model) gives a2 `pass` on
      all 3 checks (`recheck_a2.json`). That pass is not a model-accepted run. The a3 check paths
      (`out/bin`, `qemu/build`) match `qemu_v8.mk`.
  - **Model behaviour:** flash corrected itself on tool errors (PEP 668 pip → apt `python3-pycryptodome` →
    `Cryptodome` vs `Crypto` → pip `--break-system-packages`; wrong manifest branch). It never called `finish`
    early. A wrong acceptance check costs a whole sub-goal: checks need an executed validation against a real tree.
  - The proxy's EOF handling became a half-close after run c3 had started (c3 ran commit `6bce1ef`); covered by a test.
  - 49/49 calls export-matched. Lab `conflux-dev-lab-c3` is **stopped with its disk kept** (a1 + a2 state).
    Evidence: `~/evidence/core-runs/2026-10-27-c3/`.
- **C slice 2 (2026-10-27, executed, $0.00293 metered + $0.10 GCE):** `conflux/core.py` now runs commands through a
  `Shell`. `lab_shell` runs each command as a detached job on a `devbox-lab` VM (`~/.conflux-jobs/<id>/`), polled over
  `gcloud compute ssh`. Waits are capped by one deadline that starts at lab startup. `run --lab` owns up → smoke →
  tasks → stop, and always stops the lab. `run_shell` takes `timeout_s` (1..10800). Run-12 goal (a) is cut into
  a1 host prerequisites / a2 sources / a3 build (`tests/fixtures/core_loop/optee_goal_a.json`, executed checks).
  `PRICE_CEILING` was lowered to 4e-7 $/byte (≈2× flash's list rate) because the old bound refused long-context calls.
  - **Hypothesis falsified, by the environment rather than the model:** a1 `failed` at step cap (30 steps, 850 s,
    $0.00293, 30/30 export-matched). **Labs have no internet egress.** They have no external IP, the project has
    no Cloud NAT router (`gcloud compute routers list`: 0), and the subnet only has Private Google Access.
    Independent check (`egress-check.txt`): github.com, deb.debian.org and pypi.org time out; Google endpoints answer.
    Run 12 ran on `conflux-optee-lab`, which had egress. Goal (a) needs GitHub, so no sub-goal can pass on today's labs.
  - **Model failure modes seen (bare flash):** it spent 26/30 steps probing mirrors, IPs and caches. It never stated
    the blocker or gave up (no `finish`), so the step cap ended the run. It used `sudo` inconsistently
    (`apt-get download` without sudo hit dpkg lock errors). It also asked for `python3-crypto`, which does not exist on
    Debian 12. A cheap Jev `choice` ("blocked by environment / keep trying") after N tool failures is a candidate
    bounded gate.
  - **Infra:** ssh round trip + 5 s poll ≈ 13 s per trivial command; smoke: user `dev`, passwordless sudo, 8 vCPU,
    80 GB free. Lab deleted at 06:59Z. Evidence: `~/evidence/core-runs/2026-10-27-c2/`. Tests: 44 in
    `tests/test_core_loop.py`; suite 670 passed, 1 xfailed.
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
