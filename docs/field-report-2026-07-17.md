# Field report — first live exercise of answer strategies (2026-07-17)

Five supervised turns were driven manually against `/v1/chat/completions`
(curl/urllib client, no agent framework) to exercise the full chain —
contract → strategy → execute → sandbox → verify → merge/short-circuit →
trailer — with deliberately small tasks. Total spend: **≈ $0.042**.
Three accounting/chain bugs were found and fixed mid-exercise; the trace
data below is the evidence.

## Runs

| Run | Strategy | Task | Wall | Cost | Outcome |
|-----|----------|------|------|------|---------|
| A | `single` | `parse_duration` + exactly 3 doctests | 49.7s | $0.0058 | 1 attempt, score 1.00; doctests ran in local sandbox (exit 0, 0.8s) |
| B | `best 2`, cutoff 0.9 | Roman numeral converter | 22.8s | $0.0043 | short-circuit fired: glm-5.2 verified 1.00 first, deepseek's pending verify cancelled |
| C | `union 2` | ISO-8601 duration parser edge cases | 177.9s | $0.0173 | glm 19 items + deepseek 35 → union 41 (+6 over best candidate); merge won at 1.00 |
| D | `best 2`, cutoff 0.9 | median lambda | 28.7s | $0.0053 | post-fix run: verify overhead measured 64.3% of tokens |
| E | `best 2` | `is_leap` + 4 doctests | 44.9s | $0.0089 | evidence fix live: BOTH candidates sandboxed (exit 0) before verification |

All five turns completed the chain with no repairs, no provider failovers,
no 429s (all executor/verifier traffic on Nous).

## What worked

- **The chain end-to-end.** Contract extraction (gemma, ~$0.0001/turn),
  strategy dispatch, parallel candidates, cross-family verification with
  continuous logprob scores, sandbox doctest execution, merge gating,
  in-band `!strategy`/`!cutoff` control, and the trailer — all observable
  in the trace with per-stage timing.
- **Union added real coverage.** Run C is the strategy's existence proof:
  the merged list (41 distinct cases) strictly contains more than the best
  single candidate (35), picking up glm-only items (e.g. comma decimal
  separators `PT0,5S`) deepseek missed.
- **Short-circuit works live.** Run B returned in 22.8s vs run E's 44.9s
  for the same shape of work — the cutoff genuinely halves latency when
  the first verdict is high.

## Bugs found and fixed during the exercise

1. **Verify events carried no token counts.** `VerifyReport` summed tokens
   internally but the orchestrator's `verify` events logged only cost, so
   the efficiency report's headline KPI (overhead % of tokens — the SPEC §8
   <15% target) silently excluded ALL verification tokens. Fixed:
   the verifier now reports `tokens_in`/`tokens_out` and every verify log
   site records them. Run D immediately showed the real number (below).
2. **Ensemble candidate verification spend was invisible.**
   `ensemble_candidate` events weren't in the report's bucket map at all —
   best/union/fuse verification cost vanished from the KPIs, and the event
   names the *candidate* model while carrying the *verifier's* spend, which
   would have misattributed per-model cost. Fixed: bucketed to `verify`,
   attributed to the verifier named in the event.
3. **Multi-candidate strategies skipped the sandbox.** The supervised-unit
   path runs produced code and hands the transcript to the verifier; the
   ensemble path verified candidates *without evidence* — verification
   without execution is just an opinion. Fixed: every candidate and every
   merged answer now runs its code pre-verification (run E shows both
   candidates' doctests executing). Harness asserts the transcript reaches
   the verifier prompt.
4. **(Process foot-gun, documented not fixed)** the trace/history DBs are
   cwd-relative: a server started from a different directory silently
   opens a fresh ledger. Runs A–C and D landed in different DBs during
   this exercise. Candidate fix: resolve DB paths relative to the config
   file, or a `data_dir` setting.

## Deficiencies observed (open)

1. **Verifier score saturation is the big one.** Every verdict across all
   five runs was ≥ 0.99999. With no discrimination between passing
   candidates, best-of-N degenerates to *first-past-the-post*: run E's
   "winner" beat the runner-up by 1×10⁻⁷ — noise; runs B/D were decided by
   verify latency, not quality. The merge gate (`>= best`) passes
   trivially, and any cutoff ≤ 0.99 always fires. The continuous-logprob
   machinery works (scores are genuine expectations, not parsed ints) but
   at these task sizes the rubric ceiling does not separate candidates.
   Ideas, in rough order of value:
   - score ensemble candidates at the **adversarial tier** (refutation
     stance exists already, is unused by the ensemble path);
   - **pairwise comparative ranking** for N=2 ("which is better and why")
     — one call, discriminating by construction; SPEC §6.1's PPT becomes
     the natural upgrade at N>2;
   - a **calibration probe**: periodically score a known-flawed output;
     alert (new FM) when the verifier stops discriminating.
2. **Supervision overhead is 54–64% of tokens vs the <15% target** on
   small tasks (post-fix measurement, runs A–E). Root cause: 3 criteria ×
   1 call each, and every call re-sends the full task + output + evidence.
   The target is only reachable today on large tasks. Ideas: score all
   criteria in **one call with three score tags** (read logprobs at three
   positions); scale criteria count with difficulty; loosen the
   difficulty classifier — a one-line-lambda task was classed "routine",
   so the trivial→lite path (1 criterion, cheapest verifier) never fired
   in five runs.
3. **Short-circuit saves verification, not generation.** In run B both
   candidates had finished generating (and billing) before the first
   verification completed; the cancellation killed only a pending verify.
   Idea: **staggered speculative launch** — start candidate 2 only if
   candidate 1's generation exceeds a latency percentile or its verify
   comes back below the cutoff; trades tail latency for real savings.
4. **The merge is the latency hog in union/fuse.** Run C: 67s synthesis +
   24s merge verification ≈ half the turn. For list-shaped outputs the
   merge is nearly mechanical; it could route to the utility model, or
   dedup programmatically and only verify.
5. **Strategy state is global, not per-session.** `!strategy union 2`
   from one client changes how every concurrent conversation's turns are
   produced. Fine for a single-user proxy; wrong the moment two sessions
   overlap. Idea: per-session ControlState overlay with the global state
   as default.
6. Cosmetic: `turn_start` logs the pre-strategy routed executor, which is
   misleading for multi-candidate turns (the winner is only known at
   `ensemble_winner`).

## Ideas beyond fixes

- **Auto-strategy by difficulty**: the contract call already classifies
  trivial/routine/hard — map trivial→single (cheap), hard→best/union,
  keeping `!strategy` as the manual override.
- **Verifier-health monitor**: saturation (deficiency 1) is detectable
  from the trace alone — a rolling "score variance across candidates"
  stat on the dashboard would have flagged this in one glance.
- **Evidence-weighted scoring**: when doctests exist and pass, the Errors
  criterion is redundant with the transcript; when they fail, no LLM
  opinion should be able to rescue the score. The sandbox verdict could
  gate rather than merely inform.

## Verification of this exercise

Harness `verify_strategy.py` grew to 29 checks (evidence transcript
reaching the verifier, candidate token/verifier attribution); full
regression across all 8 harnesses: **132 checks green**. Live smoke:
runs D/E on the patched server confirmed verify tokens in
`/admin/report` and `execute_code` events inside the ensemble path.
