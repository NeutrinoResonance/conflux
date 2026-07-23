# Field report — first live verifier-calibration run (2026-07-23)

**Status: accepted; measurement caveats recorded.** The new calibration
harness (`llm-super calibrate`) ran against all five pool verifiers with
real providers. Zero false-passes on the seeded suite; the run also
quantified, for the first time, how often each channel actually delivers the
continuous logprob read versus silently degrading to a discrete judge.

Companion records:

- Harness: `llm_super/verifier_calibration.py` · seeded suite embedded
- Persisted rows: `verifier_calibration` table, run `2a4a905e4a27`, in the
  repo `traces.db` (also served at `GET /admin/calibration`)
- Motivating deficiency: [field report 2026-07-17](./field-report-2026-07-17.md)
  deficiency 1 — every observed verdict ≥ 0.99999, best-of-N degenerated to
  first-past-the-post; SPEC §11 open question "measure verifier false-pass
  rate against seeded failures before trusting risk-tiering."

## 1. What was tested

9 seeded answers (3 tasks × one known-good + two known-flawed each; flaws
keyed to FM-X.1 stub, FM-X.4 unsupported success claim, FM-1.1 ignored
constraint, wrong arithmetic, FM-X.5 wrong question) scored at the standard
tier (3 criteria, K=1) by every pool verifier individually — no
cross-family failover, so each family is measured rather than masked.

## 2. Results (run `2a4a905e4a27`, $0.051804 reported usage)

| verifier | false-pass | false-fail | discrimination | mean good | mean flawed | continuous-read |
|---|---:|---:|---:|---:|---:|---:|
| deepseek-v4-pro (Nous) | 0.00 | 0.00 | 0.944 | 1.000 | 0.056 | **0.00** |
| deepseek-v4-pro-go | 0.00 | 0.00 | 1.000 | 1.000 | 0.000 | 0.89 |
| gemma-4-31b (Nous) | 0.00 | 0.00 | 1.000 | 1.000 | 0.000 | **0.00** |
| qwen-3.7-plus (Nous) | 0.00 | 0.00 | 1.000 | 1.000 | 0.000 | 1.00 |
| qwen-3.7-plus-go | 0.00 | 0.00 | 1.000 | 1.000 | 0.000 | 1.00 |

Saturation share was 0.33 for every family — exactly the share of good
answers, i.e. good answers score ~1.0 and nothing else does. That is the
*healthy* shape; the 2026-07-17 pathology would show flawed answers
saturating too.

## 3. Findings

1. **No false-passes on blatant flaws.** Every family failed every seeded
   flawed answer, including the FM-X.4 answer whose text confidently claims
   "I tested this thoroughly: doctests … all pass." The evidence-skeptical
   prompt framing is doing its job at this difficulty level.
2. **The continuous-read rate is the real differentiator.** deepseek-v4-pro
   and gemma-4-31b on the Nous channel returned usable score-token logprob
   distributions in **0 of 27** calls each this run — every verdict
   silently degraded to the discrete text-parsed score. The same DeepSeek
   model on the Go channel read continuously 24/27. This matches the same
   day's `llm-super probe` (gemma 0/3) and quantifies the "logprobs
   presence is flaky per-request on aggregators" caveat with real numbers.
   Verdicts still discriminated because the flaws are blatant; on subtle
   comparisons the discrete fallback is exactly where ties and corrupted
   reads return.
3. **Caveat recorded, not hidden:** this suite measures the floor, not the
   ceiling. Zero false-pass on obvious flaws does not certify the verifiers
   against subtle ones (an off-by-one in a plausible implementation, a
   requirement silently weakened). Extending the suite with near-miss
   answers is the natural next increment; the harness accepts additional
   cases without code changes elsewhere.

## 4. What changed because of this run

- The calibration harness, rows, and `/admin/calibration` endpoint are now
  part of the product (commit "Verifier-calibration harness"), so the
  2026-07-17 saturation pathology is detectable by rerunning one command
  and comparing `discrimination` and `false_pass_rate` over time.
- Routing guidance: prefer Qwen (either channel) or DeepSeek-Go when the
  continuous read matters; treat Nous-served DeepSeek/Gemma scores as
  discrete-judge quality until a probe shows their logprobs are back.

## 5. Reproduction

```bash
.venv/bin/llm-super probe          # provider sanity first
.venv/bin/llm-super calibrate --config models.yaml --db traces.db
curl -s localhost:8055/admin/calibration | python3 -m json.tool
```
