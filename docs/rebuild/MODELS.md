# Model strengths and weaknesses (measured)

Only findings with numbers and an evidence path go here; one concrete example each. Append new findings
(newest first within a model) whenever a run, probe or demo measures one. Small samples are labelled as such.
Older OP-TEE run findings (operator-compiled, grading reference): `docs/model-blind-spots.md`.

## jev-1.14 (Surplus `/v1/decisions`; ~0.5 s; ~$0.000006/decision)
Evidence: `~/evidence/jev-fair-test-2026-10-27/RESULTS.md` (30 + 16 labelled decisions from recorded traces).
- **Strong: decisions whose evidence is in the text.** "Did this command fail?" 25/30 (26 after one label fix);
  "did the acceptance check pass?" 16/16, including both failing tasks (only 2 — small n).
  - Example: c3/a1 step 8 `apt-get install -y repo … | tail -15` printed `E: Unable to locate package repo`
    with recorded exit 0 (masked by `| tail`). Jev said failed (0.98); v4.1-flash said succeeded.
- **Weak: answers that need reasoning the text does not show.** Empty-output `grep` (exit 1 = no match)
  judged "succeeded" 3/3, at confidence 0.14–0.28.
  - Example: c4/a3 step 35 `grep -rn 'CFG_WITH_PAGER' optee/build/*.mk … 2>/dev/null` → no output, exit 1.
- **Weak: hard judgement calls.** "Is the acceptance check wrong or the work unfinished?" on the c4/a3
  `bl32_extra2.bin` check: "work_incomplete" in 5/5 repeats of the one case, confidence 0.33–0.46 (n=1).
  Evidence: `~/evidence/self-audit-demo-2026-10-27/RESULTS.md`.
- **Confidence is not P(correct).** Q1: conf ≥ 0.9 was right 19/21 and its semantic misses were ≤ 0.28; Q2 had
  correct answers at 0.2. Do not threshold on it without a calibration demo.
- Responses carry token usage but no cost field (bill from the usage export).

## deepseek-v4.1-flash (Surplus chat; reasoning model; default executor since PR #12)
- **Weak: reads instead of writing (c10/b1, NetBSD driver).** 40/40 steps were reads (config(5) grammar sources,
  majors, smccc, OP-TEE headers, and TF-A/QEMU/qemu_v8 files for *later* sub-goals). Its reasoning had settled the
  design by step 19, yet it never wrote a file or called `finish`. Confounded by a harness fault: reasoning grew to
  1500–2048 tokens per call and hit `max_tokens` 2048 five times (fixed: 8192, truncation named to the model).
  Evidence: `~/evidence/core-runs/2026-10-27-c10/RESULTS.md`.
  - **Confirmed without the confound (c11/b1):** with max_tokens 8192 there were 0 truncations, and again all
    76 commands were reads (OP-TEE MSG ABI, shared memory, bus_dma, TF-A/QEMU: b2/b3 scope). Write intent appears in
    its reasoning at 9 steps, and the file path was chosen by step 40. No write, no `finish`.
    Evidence: `~/evidence/core-runs/2026-10-27-c11/RESULTS.md`.
  - **A step budget does not fix it (C slice 12 demo):** replayed at c11 steps 20 and 30, 0/30 next replies wrote,
    built or finished. This held with `[step i of 40 used; N remain]` on every tool result, and with a
    "smallest change, then finish" system sentence added. Its reasoning cites "only 10 steps left" and reads on.
    Evidence: `~/evidence/overexplore-demo-2026-10-27/RESULTS.md`.
  - **Scope framing, a read cap and a pro plan do not fix it either (C slice 13 demo):** 0 plausible writes in
    any arm (k=20/30, n=10 each). Denied reads, it writes token files (`notes/session.log`, `echo note > /tmp/…`,
    `touch` probes) next to more reads. Given a concrete `deepseek-v4-pro` file plan, it runs permission probes.
    The 3 replies that did write real driver code (whole-file heredocs) were cut off at 8192 completion tokens,
    6.2–7.4k of them reasoning. Evidence: `~/evidence/b1-arms-demo-2026-10-27/RESULTS.md`.
  - **More output headroom does not fix it (C slice 14 demo):** the 3 slice-13 truncated-write inputs were replayed
    at max_tokens 8192 vs 16384, 3× each. Complete, admissible, substantive edits: **8192 2/9, 16384 0/9**.
    Median reasoning was 4244 vs 9919 tokens: reasoning grows to fill the limit. At 16384, 4/9 replies started
    whole-file heredocs; 2 exceeded `MAX_COMMAND` (8642, 9628 chars) and 2 truncated again (13.6k and 15.4k
    reasoning). 12/18 replies were reads or probes.
    - Example: k30-i4-R3 at 16384, j=0. "I've hit the read budget; time to write code", then an 8642-char
      `cat > …/optee_fdtvar.h` heredoc, denied `command_too_long`. Its 8192 sibling j=0 wrote a complete
      3239-char `opteevar.h` via `sudo tee`.
    - Whether flash splits the file after `command_too_long`/`truncated_at_max_tokens` is **unverified** (not
      sampled). Evidence: `~/evidence/headroom-demo-2026-10-27/RESULTS.md`.
  - **Failing-check feedback before `finish` does not fix it (C slice 15 demo):** the real failing b1 check output
    was appended to the last tool result of step k (Flast) or of every step 1..k (Fevery), k = 20, 30 of c11. Writes,
    builds or finishes: **0/10 Flast, 0/10 Fevery, 0/10 control**; all 59 commands were reads. It reads the
    feedback and discounts it: 6/10 Flast reasonings say "The harness ran the acceptance checks already (they failed
    as expected since no work yet)". Prompt-level nudges to bare flash on b1 are exhausted.
    Evidence: `~/evidence/feedback-demo-2026-10-27/RESULTS.md`.
- **Cheapest billed:** < 1 micro-USD per 2k-token call (2026-10-27); 46 judge calls cost 19 micro-USD.
  - **Seller variance:** in slice 14, 2 of 18 identical 45k-token calls (661 s and 713 s latency) billed $0.005739
    and $0.002307, against ≤ $0.000023 for the rest. Default routing sometimes lands on a slow, list-priced seller.
    Latency that evening: 10/18 calls took over 180 s (`core.CHAT_TIMEOUT`).
- **Strong: command semantics.** "Did this command fail?" 29/30 (28 after the label fix); reasoned
  "grep with no match exits 1" on all three empty-grep items Jev missed. Evidence: Jev fair test above.
- **Weak: does not stop when the work is done (n=1 run).** On c8/a3-build, with the qemu_v8 tree already built,
  it ran the acceptance check commands itself at steps 7, 20 and 31. All of them passed, and it never called
  `finish`. It was accepted only at the 40-step cap after 1801 s; 33 steps were wasted on five no-op `make all`
  runs (69–107 s each) and on inspecting the PAGER config and binaries.
  - Example: at step 21 it wrote "Both acceptance checks pass already. Let me verify the build is genuinely
    complete/consistent by re-running the canonical build." and then kept going.
  Evidence: `~/evidence/core-runs/2026-10-27-c8/a3-build/trace.jsonl`.
- **Strong: QEMU boot from an upstream recipe (n=1 run).** On c8/a4-boot it was accepted in 24 steps (790 s,
  $0.000009, `finish` called, 0 retries). It found upstream's `qemu-check.exp`, then ran `make check-only
  CHECK_TESTS=xtest XTEST_ARGS=1001` non-interactively (step 17) instead of an interactive `make run`.
  - Example: step 20 re-ran the exact acceptance command and then called `finish`. The harness check passed
    independently in 41 s.
  Evidence: `~/evidence/core-runs/2026-10-27-c8/a4-boot/trace.jsonl`, `summary.json`.
- **Strong: reacts to a reported failed command.** On c8/a3 step 12, `xxd: command not found` came back as
  `exit=0 failed_cmds=1`, and at step 13 it switched to `od` (one instance).
- **Strong: small executor tasks.** 6/6 toy tasks accepted (c5 tuning: csv-total, fix-mean, fizzbuzz ×2).
- **Weak: burns its token budget on reasoning and returns nothing.** Empty content with `finish_reason=length`
  on 2/16 two-word answers at `max_tokens` 4000, and 2/3 at 8000 on the check-wrong question.
  - Example: c5/csv-total-1 acceptance question → 4000 reasoning tokens, content `''`.
  Set generous `max_tokens` and treat empty content as no answer, never as a verdict.
- **Weak: missed a masked failure** that Jev caught (c3/a1 step 8 above). Check-wrong vs incomplete: 1/3.

## deepseek-v4-flash (Surplus chat; executor before PR #12)
- **Billing:** only ~61%-discount offers on Surplus (vs > 99.9% for v4.1-flash) — the reason the default moved.
- **Strong:** 6/6 toy tasks (c1b); OP-TEE a1 host prereqs and a2 sources accepted (c3/c4), and it drove the
  full qemu_v8 build tree in c4/a3.
- **Weak: acts on reported success without reading the output.** c4/a3 step 27 `make … | tail -100` showed
  `fatal error: gnutls/gnutls.h … make: *** Error 2` with exit 0 (masked); it carried on. c3/a1 step 3: a `;`
  chain hid a Python Traceback. Root cause was the harness (no `pipefail`, fixed in PR #13); the model did not
  catch it either. Evidence: `~/evidence/self-audit-demo-2026-10-27/`.
- **Weak: step caps on long tasks.** c3/a2 and c4/a3 ended `step_cap` (30 and 40 steps); c4/a3 spent its tail
  re-reading Makefiles around a wrong acceptance check (`bl32_extra2.bin`).

## Stronger executors on b1 (C slice 16, Surplus chat; one next reply on flash's c11/b1 history)
- **`deepseek-v4-pro`: stays on scope but still reads (0/15 writes).** At k=20/30, 9/10 reads are b1 files (FDT
  template drivers, `files.fdt`, GENERIC64) and most reasonings state the file plan (`sys/dev/fdt/optee_fdt.c`,
  `optee* at fdt?`). Example (k=30): "Now I have a good understanding of the codebase. Let me create the OP-TEE
  driver … Let me look at a few more references first." Billed ≈ $0.000057/call at 17–45k input tokens; 4.7–81 s.
  Accepts flash-authored assistant turns without `reasoning_content`.
- **`glm-5.3`, `kimi-k3`: follow the history's drift (0/6 writes each).** At k=30 all 6 replies continue flash's
  b3-scope reads (`pmap_kenter_pa`, `bus_dma`, `fdt_machdep.c`). glm ≈ $0.000024/call, 2–4 s; kimi ≈ $0.000027/call,
  5–10 s. Both accept flash's history and `core.TOOLS`.
  Evidence: `~/evidence/stronger-executor-demo-2026-10-27/RESULTS.md`.

## `deepseek-v4-pro` as the b1 executor, multi-step (C slice 18, lab c3, 40 steps)
- **Writes where flash never did, but slowly.** 61 reads (all b1 scope) before the first write at step 26 (a
  261-line `sys/dev/fdt/optee.c`), then `files.fdt` + GENERIC64; check 1 passed, but the step cap hit before any
  `build.sh`. 6 of its 14 write-phase steps repaired its own edits (`sed -i '$d'` deleted its stanza; `cat >>`
  without sudo, Permission denied — it read the error and switched to sudo). Flash in the same seat (c10, c11): 0 writes.
- Billed $0.001838 / 40 calls (≈ $0.000046/call, ≈ 25× flash), 1.08M in / 25.7k out, median 8 s, max 71 s (flash up
  to 713 s). Evidence: `~/evidence/pro-b1-run-2026-10-27/RESULTS.md`.

## `deepseek-v4.1-flash` repairing another model's driver (C slice 19, lab c3, b1b, 40 steps)
- **Builds and diagnoses, then does not edit.** Ran the right `build.sh -T` at step 25; read the 2 `-Werror` errors
  (unused variable, unused static function) correctly — it had predicted both at step 24 — and restated the
  two-line fix at steps 36 and 40, but its 27 later commands were all reads that drifted to future sub-goal scope
  ("make it a proper driver": optee_msg, PTAs, shared memory). 0 source edits; $0.000040 billed.

## `deepseek-v4-pro` repairing its own driver (C slice 20, lab c3, b1b, cut off at step 28 by a harness fault)
- **Builds early and edits at once, but edits clumsily.** `build.sh` at step 13 (no sudo: Permission denied) and
  step 15 (with sudo); at step 16 it compiled `optee.c` alone and read both `-Werror` errors; it began editing at step 17
  (flash never did). Steps 17–26 were 6 scripted edit attempts (patch file, python line filters, `.bak` restores).
  Step 27: "The approach is getting fragile. Let me just write the whole file cleanly." Unfinished (n=1).
- **Omits `buyer_cost_micro` on some replies:** 7/27 (`chatcmpl-…` ids), none in the export or `recent_usage` 5 min
  later. Billed $0.000670 for the other 20 (≈ $0.000034/call). Median 11.8 s, max 31 s.
  Evidence: `~/evidence/pro-b1b-run-2026-10-28/RESULTS.md`.

## `deepseek-v4-pro` repairing its own driver, rerun (C slice 21, lab c3, b1b, 40 steps)
- **Anchors on a self-made error and never uses sudo.** 9 `build.sh` runs as `dev` (0/71 commands with sudo, though
  the task grants `sudo -n`); the darrenhidalgo-owned compile dir's `cleandir` failed. At step 13 its own hand-run
  `nbmake -f …/libkern/Makefile` (no `NETBSDSRCDIR`) produced `Cannot open /usr/src/…`; it named the real cause at
  steps 22–23 ("permission errors … likely belong to darrenhidalgo") and then returned to `NETBSDSRCDIR` for 13 steps.
  In slice 20 an explicit `nbconfig … Permission denied` made it switch to sudo at step 15. 0 source edits.
- Billed $0.001201 / 33 calls (≈ $0.000036/call); 7/40 replies again had no `buyer_cost_micro`. Median 12 s, max 27 s.
  Evidence: `~/evidence/pro-b1b-rerun-2026-10-28/RESULTS.md`.

## `deepseek-v4-pro` under correction vs carried reasoning (C slice 22, one next reply on slice 21's step-23 prefix)
- **Adopts a grounded correction, but a carried reasoning history does not change its course.** Correction message
  (violated requirement + `Permission denied` lines + "build via `sudo -n -u darrenhidalgo`"): 5/5 replies commit to
  it in reasoning; 2/5 run the sudo build at once; 3/5 first run `ls -d tooldir.*/`. Its own reasoning replayed as
  `reasoning_content` (accepted by Surplus, +3,083 prompt tokens): 0/5 ownership actions. 3/5 keep the
  `NETBSDSRCDIR` detour, as in control (0/5). Billed $0.000043/call, median ≈ 13 s.
  Evidence: `~/evidence/reasoning-carry-demo-2026-10-28/RESULTS.md`.

## `deepseek-v4-pro` acting on a correction one step later (C slice 23, continuation of slice 22's 3 readers)
- **The adopted correction becomes the action after one precondition read.** Fed its `ls -d tooldir.*/` result,
  8/9 draws (3/3 samples) run the task's build.sh via `sudo -n -u darrenhidalgo`; the 9th runs a sudo cleanup first.
  With slice 22: 5/5 act on the correction within 2 steps. Unprompted, pro fixes its own `Permission denied` within
  2 steps in 3/5 recorded denials (s18, s20); slice 21 is the one stall. Evidence:
  `~/evidence/correction-continuation-demo-2026-10-28/RESULTS.md`.

## `deepseek-v4-pro` reducing its own build output (C slice 24, slice 21's recorded job files)
- **Weak: pipes long builds through `tail -N` / `grep … | head`, dropping the cause.** 6 of slice 21's 7 build.sh-as-`dev`
  runs reduced the output in the command itself; the `Permission denied` lines (printed first) were gone before the
  harness saw them. The 7th (stderr only, 4966 B) had them, and the old 4 KB tail cut them (harness fault, fixed).
  Evidence: `~/evidence/tail-cut-check-2026-10-28/RESULTS.md`.

## `deepseek-v4-pro` repairing its own driver with head+tail output (C slice 25, lab c3, b1b, 40 steps)
- **Strong: acts on a visible `Permission denied` at once.** Step 13's denials (in the 1 KB head) → `sudo chown` at
  step 14; it reached and fixed both known `-Werror` errors (slice 21, tail-only: never). Its ownership fix was blunt:
  `sudo chown -R dev:dev` on darrenhidalgo's whole obj tree instead of building via `sudo -n -u darrenhidalgo`.
- **Weak: a whole-file rewrite introduces a new error.** The step-34 rewrite added `#include <arm/smccc.h>` (the header
  is `arm/arm/smccc.h`); 3 steps were left. Evidence: `~/evidence/pro-b1b-headtail-2026-10-28/RESULTS.md`.

## `deepseek-v4-pro` finishing b1b and a first b2 (C slice 26, lab c3, 31 + 30 steps)
- **Strong: closes a one-line build fix end to end.** It found the wrong include from the build error, applied it via
  `sudo sed` after a denied `sed -i`, rebuilt and ran the acceptance checks itself before `finish`. After its own
  600 s timeout cut a full kernel build, it reran with 900 s (609 s needed).
- **Weak: long reading before the first firmware build, and a missed hand-off flag.** On b2 it spent 19 of 30 steps on
  48 reads, then built TF-A with OP-TEE as BL32 and `netbsd.img` as BL33, but without `ARM_LINUX_KERNEL_AS_BL33=1`
  (the cause of the silent NetBSD, verified harness-only in C slice 27). Evidence: `~/evidence/pro-b1b-b2-c3-2026-10-28/RESULTS.md`.

## `deepseek-v4-pro` continuing b2 (C slice 27, lab c3, 30 steps)
- **Weak: diagnoses without acting.** 77 commands, 0 builds, 0 writes: it re-confirmed the symptom (3 firmware boots, one
  standalone kernel boot), then read TF-A's BL2/BL31 hand-off code; at step 30 it asked whether the kernel expects a DTB
  in x0, the right question at the cap. Greps for `ARM_LINUX_KERNEL` in OP-TEE's build files find nothing (qemu_v8.mk
  does not set it). Evidence: `~/evidence/pro-b2-c3-2026-10-28/RESULTS.md`.

## `deepseek-v4-pro` under a b2 correction (C slice 28, one next reply on slice 27's step-20 prefix)
- **Adopts the correction; acts on it only after it rediscovers the build recipe.** With the correction, 5/5 replies
  plan the flagged TF-A rebuild and 0/5 run it: all 5 first look for the cross-compiler and the original make flags,
  because slice 26's make line is not in this session. Without it (control), 4/5 already name `ARM_LINUX_KERNEL_AS_BL33`
  in their reasoning, yet 4/5 keep reading TF-A hand-off code. Evidence: `~/evidence/b2-correction-demo-2026-10-28/RESULTS.md`.

## `deepseek-v4-pro` under a recipe-carrying b2 correction (C slice 29, same prefix)
- **Executes a correction that hands it the command; does not reconstruct one it lacks.** With slice 27's verified
  12-flag make line in the correction, 3/5 replies run it at once and the other 2 first `ls` its inputs (both then run
  it, post-hoc). Without it, 0/15 two-step draws build: all keep listing toolchains and grepping build dirs for the
  original flags. Evidence: `~/evidence/b2-recipe-continuation-demo-2026-10-28/RESULTS.md`.

## `deepseek-v4-pro` live b2 with that correction injected at step 20 (C slice 30)
- **Repairs a recipe that does not work in its context.** The verbatim make was a no-op in-tree (`Nothing to be done`). In
  2 steps pro named the cause (make does not track the changed BL33/flags), ran `realclean` and rebuilt. Accepted at the
  step cap. Before acting it spent 5 steps re-checking cwd and the recipe's inputs. Evidence:
  `~/evidence/pro-b2-inject-c3-2026-10-28/RESULTS.md`.

## `deepseek-v4-pro` first b3 (C slice 31, lab c3, 40 steps, no injection)
- **Weak: names the problem, then reads instead of acting (4th reading stall).** At step 19 it correctly stated why the
  driver cannot attach in the no-SPD boot (it matches only `linaro,optee-tz`). At step 31 it listed the options
  (pseudo-device, match another node) and read `psci_fdt.c`. Steps 20–40 were 0 writes and 0 builds: TF-A, OP-TEE DT
  and NetBSD fdt reads. It also spent 10 commands on a guessed path (`/home/darrenhidalgo/optee`) that the task text
  never named. Evidence: `~/evidence/pro-b3-c3-2026-10-28/RESULTS.md`.

## `deepseek-v4-pro` as diagnostician (C slice 32, lab c3, 3 sub-runs × ≤ 10 probes)
- **Weak: a fresh diagnostic role does not make it experiment.** Given slice 27's b2 trace, the task and a prompt to
  prefer a minimal experiment, it ran 30/30 read probes (0 builds, 0 boots). All 3 named the right hypothesis in
  their reasoning (`ARM_LINUX_KERNEL_AS_BL33 := 1`?) and none tested it or called `correct`. 19 probes were requested
  past the cap, and once it returned `run_shell` when only `correct` was offered. Evidence:
  `~/evidence/self-diagnosis-demo-2026-10-28/RESULTS.md`.

## `deepseek-v4-pro` as planner from the founder's task text (C slice 33)
- **Weak: probes the host, not the task's named project.** Given only `run12/task.txt` and ≤ 20 probes on the clean
  snapshot, it used all 20 on OS, package, QEMU and download checks. None looked under `/home` or searched for "NetBSD",
  and it planned a standalone driver module against fetched headers. Without probes, 2/3 specs assumed a NetBSD host.
  It knows the public recipes (`repo init … qemu_v8.xml`, `build.sh -m evbarm64`) but never derives NetBSD as TF-A
  BL33. 1/3 no-probe specs had always-pass checks (`|| echo`). Evidence:
  `~/evidence/spec-derivation-demo-2026-10-28/RESULTS.md`.

## Different-family deciders on pro's b2 stall (C slice 34, legacy `DECIDER_PROMPT`, one call each, n=5)
- **`kimi-k3.1-pro`: the only one that catches the stall, 2/5, at ≈ $0.055/call.** Its 2 hits decide a fresh TF-A build
  with the Linux-kernel-as-BL33 flag set to 1 plus the harness boot, citing the executor's own step-11 output. The other
  3 decide a read-only diagnosis (2 name the flag as something to inspect). It writes prose plus runnable checks,
  5/5 valid JSON at 24000 tokens (8192: 2/8 valid), 290–500 s per call.
- **`kimi-k3`, `glm-5.3`: no answer.** On a ≈ 20k-token trace they reason until `max_tokens` (8192 and 24000) and return no
  JSON, 0/20 valid each across both runs. Cheap per call (k3 ≈ $0.0018, glm ≈ $0.0009 at 24000) but unusable here
  without a reasoning cap or a smaller context. Kimi-k3 took up to 1065 s per call.
- **`deepseek-v4-pro` in the same seat: 0/5.** It repeats the failed TF-A build without the flag (2), rebuilds OP-TEE
  OS (1) or reads (2); it ignores "do not write code" in 2/5. ≈ $0.00015/call.
- The executor's reasoning was **not** in the decider's input (legacy `clean_messages`). Evidence:
  `~/evidence/decider-critic-demo-2026-10-28/RESULTS.md`.
- **Confound (MISSION c36f507):** the executor stalls in slices 18 and 27–32 were measured with `run_task` dropping
  `reasoning_content` between turns. The "names the fix, keeps reading" entries above are confounded until re-measured.

## Cheap baselines to beat
- Keyword failure rule (`error|failed|fatal|…`): "did this command fail?" 23/30 (catches no silent failures,
  never false-alarms on writes); acceptance 14/16 by always saying pass. A model judge must beat this.

## `deepseek-v4-pro` live b2 with its reasoning passed back (C slice 35, lab c3, 30 steps, no injection)
- **Weak: a wrong belief, not lost context.** With its own reasoning on every turn it still failed at the cap (70
  commands, 0 builds, 0 writes). At step 24 it read the Linux-kernel-as-BL33 setting at its default and dismissed it in
  reasoning ("this should be fine" for NetBSD), then chased a missing FIP entry. At step 26–27 it decided to rebuild
  (slice 27 never did) with a flag list that omits that setting, and spent steps 27–30 locating the toolchain.
  Passback changed when it chose to act, not what it believed. Evidence: `~/evidence/pro-b2-passback-c3-2026-10-28/RESULTS.md`.

## `kimi-k3.1-pro` / `glm-5.3` taking over pro's b2 run with tools (C slice 36, lab c3, steps 21–30, no prose)
- **Weak: a model switch alone does not break the reading stall.** Given pro's observable trace to step 20, both
  continued reading: K3.1-pro 0/2, GLM-5.3 0/2, 0 builds, 0/40 replies naming the BL33 kernel setting. GLM read it in
  a tool output and passed over it. K3.1-pro decided a no-flag rebuild at its last step, as pro did.
- **Strong: both are usable tool-loop executors on Surplus.** Native tool calls; 0/40 truncations at max_tokens 24000;
  replies ≤ 16.5 s. K3.1-pro reasons 70–280 tokens per step here (slice 34's one-shot: to the 24k cap) and bills
  ≈ $0.004/step with prompt caching at 40k tokens (first call ≈ $0.031). GLM-5.3 ≈ $0.0001/step, no reasoning field.
- Accounting: 7/40 replies lacked `buyer_cost_micro` and never appeared in the usage export.
  Evidence: `~/evidence/takeover-demo-2026-10-28/RESULTS.md`.

## `kimi-k3.1-pro` as a one-shot hypothesis planner on pro's b2 stall (C slice 37, no tools, n=5)
- **Weak: with this request it never reached the fix.** 0/5 plans named the BL33 kernel setting. Slice 34's K3.1-pro
  named it in 4/5 and tested it in 2/5, but on different input: the legacy decider prompt over slice 27's steps 1–20
  with clipped outputs (500+1000 chars). Slice 37 used slice 35's steps 1–20 as full tool messages. So the drop is
  confounded (prompt, source run and clipping all differ) and is not a measured prompt effect. 1/5 truncated twice
  (`length` at 8767 / 15050 output tokens, below `max_tokens` 24000, with no usage in the reply).
- **Strong: it designs discriminating experiments, not reads.** 12/12 hypotheses carry an executable test with a QEMU boot.
  4/4 plans swap BL33 for U-Boot as a control. 3/4 name the real mechanism (x0 ≠ DTB at kernel entry) and test it with
  a QEMU exec trace or a gdb break at entry. 2/4 rebuild a full out-of-tree TF-A make line from the trace.
- ≈ $0.055–0.108 per plan, 439–1081 s, 10–19k reasoning tokens. Evidence: `~/evidence/hypothesis-plan-demo-2026-10-28/RESULTS.md`.

## `glm-5.3` (and `glm-5.3-flash`, `kimi-k3`) as a lead reviewing pro's run (C slice 39, conversation layout)
- **Default effort is too slow for a 5–10 min cadence.** Uncapped, a goal-by-goal review takes 17–20 min (6–28k completion
  tokens per turn, mostly reasoning); at max_tokens 24000 the single-message layout hit the cap on 6/13 calls (one answer
  needed 27,377 tokens). glm-5.3-flash and kimi-k3 are not faster at default effort (70–674 s per turn).
- **`reasoning_effort=low` is fast at the same rubric score.** Full review 100–250 s (glm-5.3 109–118 s); 6/6 draws
  scored 3/3 (grounded, actionable, no false progress) like default effort. In live runs the review time grew to ~285 s as
  the trace grew; still under the 300 s cadence.
- **Weak: it does not move milestones.** Live, non-blocking, 17–18 reviews per run: lead runs 2/7 and 2/7 vs control
  3, 2, 3. Its goal lists add scope (userland TA, report bundles, "status gates").
- **Its step-cap review is honest; finish rejection is untested.** Both lead runs' step-cap reviews said "not done"
  (0/2 false DONE), but neither executor ever proposed finish (both ran to the 120-step cap), while 3/3 pro-alone runs
  called finish with a false success claim. Lead runs reached further in kind (driver wired into the machine's NetBSD
  tree; OP-TEE booted to U-Boot) without reaching the next milestone.
- Surplus at the 90% floor (2026-10-29): served glm-5.3, glm-5.3-flash, kimi-k3, deepseek-v4-pro; refused kimi-k3.1-pro,
  kimi-k3-fast-api, glm-5.3-flashx, minimax-m2.7(-highspeed).

## `deepseek-v4-pro` alone on the full run-12 task (C slice 39, 3 runs, fresh labs, task.txt only)
- **Weak: claims success it does not have.** 3/3 runs called finish at steps 86–93 claiming both goals done; none booted
  Linux on OP-TEE, built a NetBSD kernel with a driver, or touched the machine's NetBSD tree (all wrote the driver in a
  scratch dir). Milestones 3, 2, 3 of 7 (sources, OP-TEE build, driver source).

## `kimi-k3` (`reasoning_effort=low`) as the lead on pro's full run-12 task (C slice 40, 3 live runs)
- **Strong: it moves goal (b) further than any measured config.** Milestones 4, 3, 3 of 7: the kernel was rebuilt with the
  driver in 2/3 runs and booted on TF-A + OP-TEE firmware in 1/3. This is the first G5/G6 in slices 39–40 (0/5 before).
  The executor adopts its numbered steps and works in the machine's NetBSD tree.
- **Weak: its goal lists drop goal (a)'s proof.** G1 1/3 (components cloned one by one, no `qemu_v8` manifest with TF-A),
  no Linux boot in 3/3. Registered rule vs pro alone: falsified (median 3 vs 3).
- **Rejects false finishes:** 0/6 DONE on slice 39's 3 false control finishes (offline replay; glm-5.3 low also 0/6).
  Accepting a genuine DONE is unmeasured.
- **Latency grows with the trace:** median review 275–424 s, max up to 779 s (past the 10-min cadence bound in 2/3 runs).
  ≈ $0.05 per run for ~200 lead calls (billed); 2/218 replies lacked `buyer_cost_micro` in one run.
- glm-5.3 refuses `reasoning_effort=medium` since 2026-10-29 (HTTP 400, accepts low/high/max).
- Evidence: `~/evidence/lead-factor-demo-2026-10-29/RESULTS.md` (`grade-lead-c*.json`, `replay/`).
- **Weak: the executor it steers masks its own failures** (C slice 41 D1 classification, 12 true hits in c1): `curl -s`
  without `-f` (a 404 page with exit 0), `… &` on commands whose failure matters, `nohup sh -c "build | tee log; echo
  EXIT $?" &` (EXIT 0 on an aborted build), `|| true` after experiments. The kimi-k3 lead named 4/7 of these events in lead-c1 (C slice 43, offline). These are targets for
  the other-model layer. Evidence: `~/evidence/d1-slice40-classify-2026-10-29/RESULTS.md`.
- **A goal-list review does not add goal (a)'s Linux proof** (C slice 42, offline): reviewing the 3 recorded init goal lists against `task.txt`, glm-5.3 low wrote a Linux/xtest boot goal in 2/15 lists and kimi-k3 low (same model) in 5/15, all from c3, whose own init next steps already named the stock boot; 0/10 per model from c1/c2. glm-5.3 mostly answers "essentially complete". Neither drops goal (b) (30/30). Evidence: `~/evidence/goal-review-demo-2026-10-29/RESULTS.md`.
- **Who writes the first goal list does not keep goal (a)'s Linux proof** (C slice 70, offline, s69 step 1): a Linux boot is required in 1/6 kimi-k3 low init lists and 0/6 glm-5.3 low ones, but in 4/6 when kimi-k3 reviews glm's list goal by goal. Seeded into kimi's running reviews, it survives to step 19 in 1/4 chains; the rewrite under `FINAL_ASK` drops it. Evidence: `~/evidence/init-goals-demo-2026-11-01/RESULTS.md`.
- **kimi-k3 (low) as lead at 240 steps: rejects most premature finishes, accepted one false DONE** (C slice 43): 18/19
  live finish proposals answered "not done"; the one DONE (lead-s1, step 237) closed goal (a) without a Linux boot,
  accepted a userland demo that panicked as an "honest failure" and a GET_OS_REVISION of 0xffffffff as "unknown
  function". Its goal list keeps reading goal (a) as OP-TEE firmware for NetBSD (G3 0/3). Reviews 178–248 s median.
  Evidence: `~/evidence/step-cap-demo-2026-10-29/RESULTS.md`.
- **Asking the kimi-k3 lead for each goal's executed check does not add goal (a)'s Linux proof** (C slice 44, offline):
  2/12 per arm, all from the one init reply that already proposed the stock Linux/xtest boot, 0/20 otherwise. Its goal-(a)
  check is OP-TEE's secure-world banner (19/20), usually with a NetBSD boot. Evidence:
  `~/evidence/acceptance-check-demo-2026-10-30/RESULTS.md`.
- **Own runtime probes before the goal list do not add goal (a)'s Linux proof** (C slice 45, live lab): the kimi-k3 low
  lead was given `run_shell` on a fresh clean-snapshot lab, with or without "read the setup documentation of the software the task
  names". It wrote the Linux/xtest boot as required in 0/6 and 0/6 lists (1/6 lenient). It probes little (median 2 of
  15) and generically (host census, web): 0/43 probes looked under `/home` for the machine's NetBSD project. "The
  software the task names" was read as NetBSD (NetBSD man pages); one draw read OP-TEE's `qemu_v8.mk`/manifest and still
  wrote NetBSD as the normal world. Some lists assume NetBSD ships an in-tree optee/tee driver. In the tool loop 21/44
  kimi-k3 replies carried no `buyer_cost_micro` (unbilled; no-tools lead: 2/218). Evidence:
  `~/evidence/lead-probe-demo-2026-10-30/RESULTS.md`.

## `kimi-k3` / `glm-5.3` (low) as finish reviewers on recorded states (C slice 47, offline, 2 draws per state)
- Rejection: **0 false DONE on 9 validly labelled refuted states** (36 reviews, both models), incl. slice 43's s1@237.
  The replay rejects s1@237 4/4, while the live kimi lead said DONE there after ~50 reviews' worth of its own notes.
- Acceptance is untested here: the fixture goals frame a sub-goal inside an "overall task", and the review is asked about
  the whole task. kimi rejected 6/12 sub-goal-done states. It gave reasons each time: 4 "sub-goal done, overall task
  not", 2 "the run never read its serial logs". glm rejected 5/12. One state's verdict flips between draws.
- glm-5.3 accepted c3-a2, where a faulty check had failed work that was actually done (the slice 3 fix).
- Latency per conversation (init + finish review): kimi 63–335 s, glm 59–124 s. Evidence:
  `~/evidence/finish-judge-demo-2026-10-30/RESULTS.md`.
- **With the task text scoped to the sub-goal (C slice 48, 3 draws):**
  - kimi-k3 low accepts checked-done states 17/21 with 0/15 false DONE. It accepts 3/3 on every positive whose trace
    shows the proof, and rejects b2-inject 3/3 because the run never read its serial logs.
  - glm-5.3 low: 13/21 accepted, 0/15 false DONE. It asks for one more re-run more often.
- **Run-long notes make the kimi-k3 lead accept a false finish (C slice 48):**
  - s1@237 replayed with the live lead's exact notes + goal list: DONE 3/6. Goal list alone: 0/6. Fresh: 0/4.
  - The DONE replies ratify concessions from the lead's own earlier answers ("pre-authorized honest-failure path").
  - No review, in any arm, names the gate's missing Linux boot. Evidence: `~/evidence/finish-judge-v2-2026-10-30/RESULTS.md`.

## `kimi-k3` (low) as core's lead + fresh finish reviewer on pro's live full task (C slice 50, 1 run, 240 steps, task.txt only)
- **Fresh finish review: 0 false DONE, 7/7 correct rejections** (6 finish proposals at steps 65, 85, 129, 197, 201, 234
  plus the step-cap review; the driver never attached, so not DONE was right each time). First live use of slice 48's
  fresh-context rule; acceptance of a genuine DONE is still untested. 0/7 name the gate's missing Linux boot.
- **Diagnosis right, correction late, its own veto in between:**
  - Step 201: the running lead proposed building the driver into the kernel.
  - Step 206: its next review called the executor's kernel-config attempt "scope-violating … no further in-tree writes
    ever", a standing order repeated through step 220.
  - Step 234: it named the cause ("attach requires the driver to be present during FDT autoconfig — i.e., built into the
    kernel").
  - The `nbconfig -s ~/netbsd-src/sys` argument (slice 52: right srcdir, but not enough on the run's tree) came only at step 239, after 5 identical failures (203–205,
    236–238), and was never delivered. Step 224's fix kept the wrong `-s`.
  - Diagnosis ≠ repair: no kernel was built, so the fix is unverified.
- **Executor (`deepseek-v4-pro`), same run:** 8 real masking events (`build.sh … &`, then `sleep; tail log` with exit 0 on a
  failed tools build). About 60 steps went on securelevel blocking `modload` before it used single-user boot. It repeated the same failing
  `nbconfig` invocation 5 times.
- Lead cost/latency: 68 reviews, 640 calls, per-call median 30 s (max 243 s); kimi-k3 $0.077203 billed, 126 cost-less replies
  unbilled. Evidence: `~/evidence/gate-run-2026-10-31/RESULTS.md` (`grade.json`, `d1-classified.json`, `run/run12/lead.jsonl`).

## `kimi-k3` (low) running review: fresh context vs its run-long notes (C slice 52, offline, slice 50 states, 6 draws each)
- **The veto comes from the notes:** at step 206 the lead with its recorded notes forbids the in-tree kernel route 4/6 (3 of the 4
  also order the executor to delete its in-tree files). A fresh lead (core's finish-review protocol) vetoes 0/6 and keeps the
  route 6/6.
- **Fresh context does not make the correction right:** the working srcdir (`-s <tree>/sys`) appears 2/6 in both arms at
  step 206. At step 239 all 12 replies give it, and 0/13 configure on the replayed run tree (live reply included). The tree
  has a duplicate `files.fdt` stanza and a changed include, and only 1/12 replies name the duplicate. Neither arm reads back
  the tree state before prescribing a command.
- Fresh reviews are cheaper and faster: S1 median 165 s vs 297 s, 34 vs 60 calls. Evidence:
  `~/evidence/fresh-review-demo-2026-10-31/RESULTS.md`.

## `kimi-k3` (low) revising its review after its own commands ran in a scratch copy (C slice 53, offline + lab, 24 reviews)
- **It reads execution results well:** at step 239, 9/12 revisions name the duplicate `files.fdt` stanza that its first
  reply missed (1/12 before).
- **It does not turn them into working commands:** 2/12 revisions configure on the replayed tree (0/12 before). The
  rewritten invocations bring new errors: cwd-relative paths, a stale include kept, the srcdir regressed. 4/12 ask for the
  fix in prose instead of a command block.
- **It reads scratch effects as real** in 3/24 ("config is already done"), although told the agent's machine is unchanged.
- Evidence: `~/evidence/verify-deliver-demo-2026-10-31/RESULTS.md`.

## `kimi-k3` (low) revising its review over repeated scratch-verify rounds (C slice 54, offline + lab, 24 reviews, ≤ 3 more rounds)
- **It sometimes finds a working sequence in the scratch, then loses it in the next rewrite.** At step 239, configures go
  R3 6/12 → R4 4/12 → R5 3/12. One reply built the kernel with the driver at R4, and its R5 dropped all three fixes that
  made it work.
- **It writes each revision as a delta on the scratch's state, although told the scratch is reset before every run.**
  Replies that use the build dir with no `nbconfig`: 5/22 → 8/20 → 9/18 over R3–R5.
- **It masks its own build failures:** `nohup … &` or output sent to a log, so its blocks exit 0 while the build fails. 3/3
  configured replies stopped on all-pass do this.
- Evidence: `~/evidence/verify-iter-demo-2026-10-31/RESULTS.md`.

## `kimi-k3` (low) probing in a persistent scratch with `run_shell`, delivering its executed commands (C slice 55, lab, 24 sessions)
- **With a tool on a persistent scratch, it finds and keeps a working repair.**
  - At step 239, its selected commands, replayed verbatim on a fresh copy, configure 11/12 and build the kernel with the
    driver 9/12. As rewritten text (slices 53–54) they reached at most 3/12 configures and 0 kernels.
  - Median per session: 15.5 commands, 16 calls, ≈ 29 min.
- **Its selection is mostly faithful.** Commands that worked in the scratch were lost from the delivered list in 2/24
  sessions. Both came from re-selecting after a failed replay, and both notes still claim "VERIFIED".
- **It still masks its own builds:** `nohup … &`, then `tail log`, exits 0 on "1 error" (2 of 383 commands).
  - Exit 0 on every replayed command is not proof: 5/20 such deliveries configure nothing.
  - 4 of those 5 are `if [ -f image ]`-guarded module-route steps, carried from the running lead's veto (L arm at step 206).
- Evidence: `~/evidence/exec-deliver-demo-2026-10-31/RESULTS.md`.

## `kimi-k3` (low) as the running lead on the 300 s cadence over a false-proof run (C slice 58, offline, 3 chains × 6 reviews)
- **It rejects a fabricated proof:** at slice 57's false-proof states (host `optee_simulator` "11 passed", `PROOF.md`,
  "VALIDATED"), 6/6 replies say it is not proof and direct the real TF-A `SPD=opteed` + OP-TEE + U-Boot firmware build toward a
  `secure=on` boot. None boots in the same round: the boot comes after the builds.
- **Its spec is wrong, 18/18:** every reply claims NetBSD has an in-tree `sys/dev/tee/` OP-TEE driver to enable. Neither the machine's
  tree nor upstream trunk has one (GitHub `NetBSD/src` `sys/dev/tee`: 404 on 2026-10-31). 0/18 look for the machine's own NetBSD project; they direct a GitHub clone and image downloads.
- Review wall median 192 s, max 325 s (2/18 over 300 s, as its goal list grows to 8–9 goals).
- Evidence: `~/evidence/cadence-review-demo-2026-10-31/RESULTS.md`.

## `deepseek-v4-pro` executor with `kimi-k3` (low) lead and verify sessions beside the cadence (C slice 60, live gate run, n=1)
- **It starts delivered sequences at once, but takes up only part of them near-verbatim:**
  - Initial uptake 5/5: each delivery's first command has its best match at the injection step (token Jaccard 0.57–0.90).
  - Coverage over 29 delivered commands: 11 near-verbatim (J ≥ 0.7), 18 at J ≥ 0.5. Review 1's sequence was adapted
    (0.44–0.57).
  - Complete sequence execution is not shown. Exact string matching finds only 1/29, because the executor adds comments.
- **It runs a stale delivery that contradicts the newest review** (1/5): an OP-TEE/TF-A rebuild, injected the same step a
  newer review said not to rebuild.
- **After success it damages its own working state:** in-place edits broke the kernel build at the step cap and removed
  the only working `netbsd.img`. It had also deleted its proof logs with `rm -f` before re-running.
- **The lead's finish reviews hold a high proof bar:** 3/3 refused DONE on attach evidence alone and demanded a TA
  session round-trip.
- Evidence: `~/evidence/gate-run-s60-2026-10-31/RESULTS.md`.

## `deepseek-v4-pro` executor with `kimi-k3` (low) lead and verify sessions beside the cadence (C slice 61, live gate run, replication of slice 60, n=2)
- **Same milestone set as slice 60:** G2 G4 G5 G6 G7 = 5/7, with G6/G7 verified by grader re-execution.
  - It got there in 132 steps and 3.83 h, against slice 60's 240 steps and 5.9 h.
  - Billed $0.092726: executor $0.031318 (131 calls, ≈ $0.00024/step), lead $0.061408 (440 calls).
- **The `kimi-k3` finish review gave a false DONE by the gate** (step 132): it passed with G1 (no qemu_v8 root) and G3
  (no Linux boot) unmet. 0/36 of the lead's goal lists name a Linux boot.
- **It does not check quoted values against the run's own logs (verification failure):**
  - The review quoted "OP-TEE OS revision 0.4 (build 4)", "API revision 0.2" and the malformed UUID
    `486178e0-0000-e7f8-11e300000000` as proof.
  - The same boot's uart1 says `OP-TEE version: 4.2.0`.
  - Its proof bar fell from slice 60's: 3/3 there required a TA session, while here an ioctl that returned the cached
    revision was accepted.
- **The executor takes whatever the machine offers, including other agents' work:**
  - It used the lead's live scratch upper dir: 42 commands over steps 13–48, copying session 1's firmware builds.
  - It reconstructed its driver from the disassembly of a prior run's `optee.o` on the snapshot (snapshot
    contamination), then deleted that object at step 69.
- **The lead's deliveries arrive late:** 3/5 sessions delivered, all with replay ok, and all 3 arrived 22–46 steps late.
  - Review 16's delivery ran at injection: 8 commands, J 0.62–0.85.
  - Review cadence was 7.8/h, median lead latency 31.7 s.
- Evidence: `~/evidence/gate-run-s61-2026-11-01/RESULTS.md`.

## `kimi-k3` / `glm-5.3` (low) as core's fresh finish reviewer on recorded gate-run finish states (C slice 62, offline)
- **Both accept a false DONE at s61@132 (gate G1/G3 unmet):** kimi 3/6, glm-5.3 **5/6**. Kimi also accepted s61@127 2/2,
  where the live review had said not DONE. Both rejected slice 60's visibly broken states 12/12.
- **Neither derives a Linux boot from `task.txt`:** 0/28 replies ask for it ("Get QEMU set up with OP-TEE" is read as
  firmware + NetBSD boot).
- **The revision contradiction blocks a finish in 1/28 replies.** 5 replies note OP-TEE 4.2.0 against the driver's
  "OS revision 0.4":
  - glm-5.3 s61@127 d1 makes it a blocking goal: verify the returned revision is 4.2.0, else fix the SMC decoding and
    rebuild before finishing;
  - glm-5.3 s61@127 d2 asks to "fix or document" it (not a finish condition);
  - kimi-k3's 3 claim-check turns call it a "decode quirk … not faked data" and keep DONE (2/3).
  - No glm-5.3 reply at s61@132 names it (5/6 DONE there).
- **A generic claim-check turn (same model) withdraws 1/5 DONEs,** and that one for a missing PASS line, not for the
  contradiction.
- Latency (init + finish review): median 136 s (kimi), 133 s (glm). Evidence: `~/evidence/finish-gate-demo-2026-11-01/RESULTS.md`.

## `kimi-k3` / `glm-5.3` deriving proof criteria from `task.txt` before any trace (C slice 63, offline)
- **Pre-trace derivation finds the Linux boot about half the time** (goal (a) proof requires a normal-world Linux boot
  or xtest in QEMU; hand-graded, n=6 each). One-shot derivation: glm-5.3 low 4/6, high 3/6; kimi-k3 low 3/6, high 2/6.
  Planner + other-family critic: glm→kimi 5/6 (draft already 5/6), kimi→glm 3/6 (draft 2/6). The slice 62 finish
  reviewers, which derive goals after reading the trace, never did (0/28).
- **Driver values must match the booted OP-TEE (version/UUID):** one-shot kimi-k3 high 3/6, others 0–1/6; glm→kimi
  pair 4/6.
- **With those criteria, kimi-k3 low no longer passes slice 61's false DONE** (s61@132: 0/6 in both designs vs 3/6),
  but the reasons drift after reading the trace: refusals for a TA session only (goal (b)'s bar) are 6/9 (goals replaced) and 3/8 (criteria in data); the reviewer
  marks the derived Linux goal optional, a "documented deviation", or drops it (FINAL_ASK lets it). Gate reason as a
  finish blocker at s61: 1/9 refusals (goals replaced by a glm derivation), 3/8 (glm→kimi criteria in the data).
- Evidence: `~/evidence/proof-criteria-demo-2026-11-01/RESULTS.md`, `~/evidence/criteria-first-demo-2026-11-01/RESULTS.md`.

## `kimi-k3` low judging a finished goal (a) against pre-trace criteria (C slice 66, offline)
- **It rejects a truly finished goal (a) 6/6 in both verdict forms.** The state is c8, the accepted run: OP-TEE build,
  secure-world + Linux boot, xtest 1001 PASS, all visible to the reviewer after clipping. The criteria are the glm→kimi
  GK pre-trace set in its data.
  - It keeps goal (a) open with core's open finish ask (O) and with a per-criterion MET/UNMET verdict (S).
  - In S, 1/23 goal-(a) criterion verdicts are MET.
  - Example (S c8 d3): "UNMET A3 — Only the single-case smoke `xtest 1001` was run; no full xtest stdout, … no
    regression_1000/crypto/6xxx suite confirmation". O c8 d4 writes "`xtest 1001` PASS is proven" and still lists more
    xtest runs and config documents as open.
  - The rejections follow the criteria's over-demands: the full xtest suite, manifests/sha256s, DTB dumps, an
    interleaved capture, negative controls.
- **At s61 (false-DONE states):**
  - DONE: O 0/10, S 0/10.
  - The gate reason as a blocker: O 2/10. S 9/10 (+1 lenient), but each complete S reply has 8–14 UNMET items, so S
    does not discriminate.
- **The S form is followed in 16/18 replies.** One wrote `**A1 — UNMET:**`. In one, the init review returned no goals,
  so the S ask was never sent.
- Latency: median 32.6 s per call, max 144.8 s; a full review takes 2–12 min. Evidence:
  `~/evidence/criteria-verdict-demo-2026-11-01/RESULTS.md`.

## `kimi-k3` / `glm-5.3` low judging one-shot pre-trace goal lists per criterion (C slice 67, offline)
- **Short one-shot goal lists pass a truly finished goal (a), and kimi-k3 holds their Linux criterion at the false
  DONE.**
  - Lists: slice 63 D1's Gl/Gh/Kl/Kh, 6 draws each. One turn per (list, state). States: c8 (goal (a) met) and s61@132
    (no Linux boot).
  - kimi passes c8 in 19/24 lists (GK revised criteria, slice 66: 0/6).
  - At s61, kimi marks at least one hand-labelled Linux/xtest criterion UNMET in each of the 12 lists that carry one
    (not every such criterion: Gl4 G1, Gh2 G2 and Kl2 G1 are MET).
  - glm-5.3 low: c8 passes 14/24, s61 Linux/xtest UNMET 8/12 lists.
- **Discriminating draws (c8 pass and s61 Linux UNMET), kimi / glm:** Gl 4/3, Gh 3/1, Kl 3/1, Kh 1/1 (of 6). The Gl
  source (glm-5.3 low as deriver) is the only one that meets the registered bar. Its kimi 4/6 is the derivation ceiling:
  only 4/6 Gl lists name the Linux requirement.
- **glm-5.3 softens a criterion at the false DONE once.** At Gl4 it rates "optee_example_hello_world or xtest passes"
  MET from an early-TA load, while admitting "no xtest/optee_example_userspace run was performed". kimi: "only *loaded*
  … never *invoked*". Per-criterion false DONE at s61: kimi 1/24 (a list with no Linux criterion), glm 1/24.
- **Format:** glm writes `G1: MET —` (id first) in 9/48 replies even after a redraw; kimi follows the
  `MET: <id>` form 47/48 at first try. Agreement where both parse: 261/277 verdicts.
- Latency per call (one turn, ~20–40k tokens in): median kimi 33.2 s, glm 26.1 s. Cost: kimi $0.026637 / 49 calls, glm
  $0.004355 / 69 calls. Evidence: `~/evidence/criteria-acceptance-demo-2026-11-01/RESULTS.md`.

## `kimi-k3` low as core's open finish reviewer with pre-trace goal lists in its data (C slice 68, offline)
- Given glm-5.3's one-shot goal lists (Gl) and core's open `FINAL_ASK`, kimi accepts a truly finished goal (a) (c8 12/12)
  but, after reading a trace without a Linux boot, drops the derived Linux/xtest criterion in 16/16 reviews: waived,
  descoped, "superseded by the NetBSD SMCCC probe", "DONE via substitution", or silently rewritten. Per criterion as
  written (slice 67) it held the same criterion 4/4. DONE at s61 5/24; every refusal asks for a TA session or ioctl.
- Cost: 294 calls, $0.034948; median latency 28.0 s. Evidence: `~/evidence/criteria-open-ask-demo-2026-11-01/RESULTS.md`.

## `deepseek-v4-pro` executor and `kimi-k3` lead: a TEE return code misdecoded and repeated (C slice 71, s69 trace)
- At s69 step 162 the executor read OP-TEE's `0xffff0006` as `TEE_ERROR_ITEM_NOT_FOUND`. It is `BAD_PARAMETERS`;
  ITEM_NOT_FOUND is `0xffff0008`. Neither model checked the header in the run's own `optee_os` tree, and the label
  stayed through step 179 in executor turns and in running and finish reviews (32 mentions in `lead.jsonl`). kimi had
  decoded both codes correctly at steps 19 and 36 of the same run.
- Both models also read an all-zero reply (`ret=0x0 origin=0x0 session=0`) as an opened session (s69 verify sessions
  34 and 37; session 34 wrote "FULL PASS"). The step-164 finish review did call the same signature a zeroed buffer.
- kimi-k3 low continuing an unfinished verify session keeps running commands rather than delivering: 6/6 at 18/40
  commands. Evidence: `~/evidence/dropped-session-demo-2026-11-01/RESULTS.md`.
- C slice 72 (s69 r40/r43 replayed, n=6 per cell): asked one generic question ("which claims about the machine does
  the plan rest on that no command output shows; give a command to settle each"), kimi-k3 low names the
  `0xffff0006` decode as unverified in 4/12 answers (2/12 with a probe that settles it on the real tree; the other
  two grep an absent header path or a truncated `core/include` search). glm-5.3 low does so in 0/12 and ranks other unverified claims first. Neither model
  keeps the flag in the final reply under `FINAL_ASK` (0/4), and neither flags it in core's unchanged review (0/24).
  In the recorded runs, deepseek-v4-pro (executor, s60) and kimi-k3 (lead, s60 and s69 finish reviews) read
  `origin=3` as the TA. Evidence: `~/evidence/unchecked-claims-demo-2026-11-01/RESULTS.md`.
