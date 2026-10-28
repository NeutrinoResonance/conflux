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

## Cheap baselines to beat
- Keyword failure rule (`error|failed|fatal|…`): "did this command fail?" 23/30 (catches no silent failures,
  never false-alarms on writes); acceptance 14/16 by always saying pass. A model judge must beat this.
