# Rebuild state

Keep this short and current. One entry per decision; newest first.

MISSION-STATUS: ACTIVE

- **Goal:** work item C (minimal replacement core) aimed at the completion gate. A done offline (live rerun deferred to E); B done.
- **C slice 14 (2026-10-27, demo, $0.008170 metered + $0 GCE): more output headroom does not turn flash's
  truncated driver writes into executable edits. The hypothesis is rejected, and nothing was built (`MAX_TOKENS` stays 8192).**
  - The demo replays the 3 slice-13 truncated-write inputs at max_tokens 8192 vs 16384, 3× each (18 calls, no lab).
    `prompt_tokens` matched the recorded inputs on 18/18 replies.
  - Primary outcome, complete admissible substantive edits: **8192 2/9, 16384 0/9** (the rule needed ≥ 5/9 vs ≤ 1/9).
    The two 8192 successes are complete NetBSD-tree headers (`opteevar.h`, `opteeio.h`), not the driver `.c`.
  - At 16384, reasoning grows to fill the limit (median 9919 vs 4244 tokens). 4/9 replies started whole-file
    heredocs: 2 were over `MAX_COMMAND` (8642/9628 chars → `command_too_long`) and 2 truncated again at 16384.
    12/18 replies were reads or probes, so slice 13's single truncated samples overstated write propensity.
  - **Live-run risk (observed, not yet in a harness run):** 10/18 calls took over 180 s (max 713 s), while
    `core.CHAT_TIMEOUT` is 180 s. In `run_task`, one chat timeout ends the task `unverified provider_0`. 2 calls hit a
    slow seller billed $0.0023–0.0057 (the rest ≤ $0.000023).
  - Evidence: `~/evidence/headroom-demo-2026-10-27/RESULTS.md` (`demo.py`, `samples.jsonl`, `reconciled.json` 18/18).
- **C slice 13 (2026-10-27, demo, $0.001352 metered + $0 GCE): scope framing, a read cap and a pro plan each fail to
  make flash write b1. All three hypotheses are falsified, and nothing was built.**
  - The demo replays c11/b1 at k=10/20/30 with 5 samples per cell. The primary outcome is one reply per sample, pooled
    at k=20/30 (n=10), counting replies with a write/build/`finish` call; plausible counts are hand-labelled:
    - (i) scope framing (no "overall task" preface, deliverables listed as files): 1/10, 0 plausible (control 0/10).
    - (ii) read cap, the reply after a denial: 2/10, 0 plausible (matched control: the reply after executed reads, 0/10).
    - (iii) one `deepseek-v4-pro` file plan injected: 3/10, all `touch` permission probes, 0 plausible.
  - **The read cap is gamed:** denied, flash writes token files (`notes/session.log`, `echo note > /tmp/…`) next to
    more reads. `echo … > f` even matches `READ_ONLY`, so a cap built on it would let these through.
  - **The pro plans are concrete** (`optee_fdt.c`, the `files.fdt` attach line, `device optee: smccc`), and flash
    still only probes and reads.
  - **New conditional bottleneck:** all 3 replies that wrote real driver code (whole-file heredocs) hit 8192
    completion tokens, 6.2–7.4k of them reasoning. The harness would deny each one as `truncated_at_max_tokens`.
  - **Diagnosis handed to `codex exec`** (contract; Codex subscription): flash stalls between understanding and
    implementing, and `run_task` gives acceptance feedback only after `finish`, a reply with no tool call, or the cap.
  - Admission reserved each call's worst case before dispatch. The cap was raised from the plan's $0.10 to $0.30,
    because pro's bounds ($0.10–0.23) exceeded the planned cap. Billed spend: 92/92 calls export-matched.
  - Evidence: `~/evidence/b1-arms-demo-2026-10-27/RESULTS.md` (`demo.py`, `samples.jsonl`, `plans.json`,
    `reconciled.json`, `codex-diagnosis.md`).
- **C slice 12 (2026-10-27, demo, $0.000084 metered + $0 GCE): telling flash its step budget does not make it write.
  The hypothesis is falsified, and nothing was built.**
  - The demo replays c11/b1's exact prefix at steps 20 and 30 (prompt tokens match c11 exactly) and samples the next
    reply 5× per arm:
    - A, control: 0/10 replies contain a write, build or `finish` call.
    - B, `[step i of 40 used; N remain]` on every tool result: 0/10.
    - C, B plus a "smallest change, then finish" system sentence: 0/10.
    - Hand-checked: all 58 commands (A 20, B 19, C 19) are reads.
  - At k=30, the reasoning of 9 of 10 B/C samples says "only 10 steps left", and every one of them reads on, mostly
    outside b1's scope (OP-TEE SMC return codes, PTA, QEMU `virt.c`). The cause is not missing budget information.
  - Offline: goal (a) traces first write or build at steps 4–21; c10/b1 and c11/b1 never do.
  - Evidence: `~/evidence/overexplore-demo-2026-10-27/RESULTS.md` (`demo.py`, `samples.jsonl`, `reconciled.json`).
- **C slice 11 (2026-10-27, executed, $0.000073 metered + $0.19 GCE): b1 re-run with the output-limit fix. The
  hypothesis "with room to write, flash gets b1 accepted" is falsified. The remaining failure is a model fault.**
  - Run c11: lab c3, bare `deepseek-v4.1-flash`, 40/40 calls export-matched, 1875 s. Both b1 checks fail, and the
    model wrote no file again; the NetBSD tree is untouched.
  - The fix worked: 0 truncations, all calls `finish_reason=tool_calls`, peak completion 7429 of 8192 tokens
    (12 calls over 2.5k completion tokens, which c10 would have cut off).
  - **Model fault, 2nd materially identical failure on b1 (c10, c11):** all 76 commands were reads. They covered
    OP-TEE MSG/SMC ABI, Linux `smc_abi.c`, shared memory, bus_dma and TF-A/QEMU/DTB, i.e. b3 and b2 scope inside b1.
    Reasoning states write intent at 9 steps. At step 40 the file and `files.fdt` stanza were already chosen, and
    the model went on reading. It never called `finish`. The model is never told its step budget.
  - D1: 1 hit, a true positive (step 8, `cd` to a missing dir in a `;` chain). No harness fault.
  - Evidence: `~/evidence/core-runs/2026-10-27-c11/RESULTS.md`. c3 stopped, disk kept.
- **C slice 10 (2026-10-27, executed, $0.000055 metered + $0.23 GCE): first model run on goal (b). b1 `failed` at the
  step cap. Root cause is a harness fault (output limit), now fixed. The hypothesis "flash reaches b1 and b2" is not
  tested yet: confounded.**
  - Run c10: lab c3, bare `deepseek-v4.1-flash`, 40/40 calls export-matched. The first lab start failed on a GCE
    stockout (n2d-standard-8, us-central1-a; $0, VM not started), and a retry 5 min later started it. Wall time 2300 s.
    Both b1 checks fail: no `optee` line and no diff under `sys`. **The model wrote no file.**
  - **Harness fault:** `MAX_TOKENS` 2048 counts flash's reasoning tokens. Per-call completion tokens grew with
    context (157 → 2048), and 5 calls hit the cap with their tool arguments cut off (one was just `{`). The model
    saw only `denied: bad_arguments`. Late calls had almost no tokens left for a file write. Latent bug, same cause:
    a truncated reply with no tool call counted as `finish`.
    - **Fix:** `MAX_TOKENS` is now 8192. Truncation (finish_reason `length` or completion tokens at the cap) is named
      to the model: the deny reason is `truncated_at_max_tokens` with a hint to write in smaller commands, and a reply
      with no tool call gets a user message, not a finish. `finish_reason` is now traced. 2 regression tests, red on the base.
    - The worst-case admission bound per call grows by $0.0147, so caps are raised: b1–b3 to $0.15 and a4 to $0.08.
      Recorded peaks: b1 $0.076, a4 $0.047. Billed cost is ≈ $0.000003 per call.
  - **Model fault (record only; demo-first):** all 40 steps were reads, half of them for later sub-goals
    (TF-A/QEMU/DTB). The design was settled by step 19. The model never called `finish` (same pattern as c4/c8).
  - D1: 1 hit, a true positive (step 14, `cat` of a missing file in a `;` chain). Evidence:
    `~/evidence/core-runs/2026-10-27-c10/RESULTS.md`. c3 stopped, disk kept, NetBSD tree untouched.
    Suite 738 passed, 1 xfailed.
- **C slice 9 (2026-10-27, executed harness-only, $0 metered + $0.58 GCE): goal (b) is cut into b1–b3, and every
  check is validated on c3. The checks were revised after the critic found 5 holes.**
  - `tests/fixtures/core_loop/optee_goal_b.json`:
    - **b1-driver-build:** the `optee` driver is enabled in GENERIC64, and the kernel is newer than every file changed
      since the snapshot commit `7f2c5e73f` (committed, staged, unstaged and untracked edits all count). The kernel
      has `optee_cd`.
    - **b2-firmware-boot:** TF-A + OP-TEE with NetBSD as BL33 at `netbsd-optee/qemu_fw.bios`. The firmware is newer
      than the kernel, and the booted kernel's banner matches the built `netbsd.img`.
    - **b3-driver-proof:**
      - all 4 UID words and `API revision 2.x` appear;
      - `OS revision <maj>.<min> build 0x<hash>` matches the secure log's OP-TEE version;
      - no UID word or build-hash literal appears in the tree.
      - The harness also builds TF-A **without an SPD** from the unmodified TF-A tree and boots the same kernel. The
        driver must print its UID line there, but not OP-TEE's UID.
    - Both boots use Debian's packaged QEMU (7.2.22), checked with `dpkg -S`/`dpkg -V`. The model-built QEMU is never used.
  - **Hypothesis supported (`~/evidence/core-runs/2026-10-27-c9/RESULTS.md`):**
    - untouched tree: fail;
    - reference driver (legacy, with the required print formats): b1/b2/b3 pass;
    - planted UID literal: fail;
    - numeric fake UID (`0x384fb3dfUL + 1`): only the no-SPD boot catches it;
    - edit after build (b2 and b3), staged edit and committed edit: all fail until rebuilt;
    - native ELF fake installed over the packaged QEMU: rejected before it runs.
  - **Negative result:** the first no-OP-TEE boot (QEMU PSCI over HVC) let the numeric fake through, because
    `smccc_probe()` fails there and no driver reaches its print path.
  - **Residual:** the model has root. It could rewrite dpkg's md5sums, or print OP-TEE's values only on a
    successful call (which still means it communicated). The checks raise the cost of faking; they do not prove absence.
  - **Environment fact:** labs run kernel 6.1.0-54, but the snapshot tooldirs are for -50/-51, so the goal text says
    to pass `-T`. With it, a kernel rebuild takes about 1 min.
  - c3 is reset to its untouched NetBSD state and stopped with its disk kept. Tests: +5 in `test_core_loop.py`;
    suite 736 passed, 1 xfailed.
- **C slice 8 (2026-10-27, executed, $0.000034 metered + $0.25 GCE): flash is accepted on a3 and a4. Every goal-(a)
  sub-goal now has a model-accepted run, but a1–a4 have not yet run as one unattended run.**
  - Run c8 on kept lab `c3`, `--only a3-build,a4-boot`, `deepseek-v4.1-flash`, 1 tunnel start, lab stopped at 12:30Z.
    64/64 calls export-matched.
  - **a3 `accepted` only at the step cap (40 steps, 1801 s, $0.000025). The "≤ 5 steps" hypothesis is falsified.**
    Flash ran the acceptance checks itself at steps 7, 20 and 31 (all passed). At step 21 it said "Both acceptance
    checks pass already". It then re-ran no-op `make all` five times (69–107 s each) and kept inspecting the PAGER config and the
    binaries. It never called `finish`. This is a **model fault**: the work is done but flash does not stop.
  - **a4 `accepted` in 24 steps** (790 s, $0.000009, `finish` called, 0 retries). Flash read `qemu-check.exp`, then
    ran upstream's `make check-only CHECK_TESTS=xtest XTEST_ARGS=1001` itself at step 17. It ran the exact check
    command at step 20 and then called `finish`. The harness check passed independently in 41 s.
  - **D1 audit: 4 hits.**
    - 3 are real failures inside `;` chains, and flash saw each as `failed_cmds≥1`: `xxd: command not found` (step
      13 switched to `od`), a missing `conf.mk`, and no `/dev/kvm`.
    - 1 is a **harness fault (D1 false positive)**: `strings fip.bin` printed error-message literals embedded in the
      firmware. Fixed: `strings`, `od`, `xxd`, `hexdump` and (prefixed) `objdump`/`readelf`/`nm` count as reads.
      Regression case: the real row, added to `audit_d1_cases.json`, red on the base. Regrade of all 25 recorded
      traces: only that hit drops, 14 → 13 (`~/evidence/core-runs/2026-10-27-c8/d1-regrade.txt`).
  - Evidence: `~/evidence/core-runs/2026-10-27-c8/` (`summary.json`, `reconciled.json`, traces).
    Suite 731 passed, 1 xfailed.
- **C slice 7 (2026-10-27, executed, $0 metered + $0.04 GCE): failed simple commands reach the model.**
  - Every command's preamble adds a bash `ERR` trap that counts failing simple commands outside conditions (`if`,
    `&&`/`||` lists, `!`). The EXIT marker carries the count. Results carry `failed_cmds`, which goes into exec trace rows
    and check results. When the command exits 0 with a non-zero count, the model sees `exit=0 failed_cmds=N`. Commands
    inside shell functions are not counted (no `errtrace`).
  - **Hypothesis supported.** Offline: 12 new test cases across both shells, all red on the base. They cover the c3/a1
    step 3 shape (`python3 -c 'import nope'; echo ok` → exit 0, `failed_cmds=1`) and handled failures (0). PIPESTATUS
    is preserved: bash restores it after the trap, so `false | true; exit 3` → 3 `[1, 0]` and
    `false; true | false` → 1 `[0, 1]`, 2 failed.
  - On c3 (bash 5.2.15, no model): the same probes match the local results, and **a1–a4 all `pass`** (a4 in 56 s).
    Their checks report `failed_cmds=0`.
  - Still not covered: `|| true` and tools that exit 0 with warnings; neither leaves a failing exit status to count.
  - Evidence: `~/evidence/core-runs/2026-10-27-c7/` (`recheck_goal_a.py`, `recheck.json`). Suite 730 passed, 1 xfailed.
- **F step 1 (2026-10-27, executed offline, $0): the D1 self-audit runs at the end of every task.**
  - D1 flags a model step that exited 0 although its own output reports failure. `conflux/core.py` `audit()` runs in
    `run_task`'s `end()` on every exit path, so it covers both `run` and `run --lab`. It writes an `audit` trace row and
    `audit_hits` on `task_end` and in `summary.json`; a hit does not change the status. Recorded traces:
    `python -m conflux.core audit <trace.jsonl>...`, which needs no key.
  - The demo's false positives are fixed generically:
    - commands are split on separators outside quotes and comments;
    - `git log`/`show`/`diff`, `apt search`/`show` and `command -v` count as reads; for a read only stderr is scanned
      (stdout is file content; `cat missing; echo done` still hits);
    - a command whose shell expands `$?` (not single-quoted, escaped or commented) is exempt, because the model
      captured the exit itself.
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
    `tests/fixtures/core_loop/audit_d1_cases.json` (7 cases with source sha256). Tests: 60 in `test_core_loop.py` (+8 new; critic round 1 added the read-stderr and `$?` regressions);
    suite 718 passed, 1 xfailed.
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
  1. Demo feedback before `finish` (codex's main diagnosis; slice 14 rejected the headroom alternative). On replayed
     c11/b1 prefixes at k=20/30, append the real failing b1 check output to the last tool result, as `run_task` would
     if it ran the checks after each step. Use c11's recorded check evidence; no lab. Measure next-reply write/build
     propensity against the slice-12/13 control (0/10).
  2. If flash then writes: demo deny recovery. Feed back the harness's `command_too_long`/`truncated_at_max_tokens`
     denial for the 4 slice-14 16384 writes and the 3 slice-13 writes, then sample whether flash splits the file.
  3. Before the next live run: reproduce the chat-timeout risk (a > 180 s reply ends the task `provider_0`) in a
     regression test, then fix it structurally, e.g. a longer timeout or one retry.
  4. For the completion gate, run a1→a4 then b1→b3 unattended from the clean snapshot on a fresh lab. Then delete
     the c3 disk. GCE stockouts happen (c10): retry the lab start, it is not a blocker.
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
