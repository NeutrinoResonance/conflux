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
- **Cheapest billed:** < 1 micro-USD per 2k-token call (2026-10-27); 46 judge calls cost 19 micro-USD.
- **Strong: command semantics.** "Did this command fail?" 29/30 (28 after the label fix); reasoned
  "grep with no match exits 1" on all three empty-grep items Jev missed. Evidence: Jev fair test above.
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

## Cheap baselines to beat
- Keyword failure rule (`error|failed|fatal|…`): "did this command fail?" 23/30 (catches no silent failures,
  never false-alarms on writes); acceptance 14/16 by always saying pass. A model judge must beat this.
