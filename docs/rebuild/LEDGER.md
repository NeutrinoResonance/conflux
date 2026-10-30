# Spend ledger

Weekly caps (ISO week, Monday 00:00 UTC; founder decision 2026-10-27): **$50** metered model spend
(Surplus + any paid overflow, billed values from the usage export) and **$60** GCE including lab VM hours.
Subscription usage (Claude, Codex, NanoGPT, Kimi, GLM) is tracked in its own column, not as cash.
USD comes from provider responses or documented prices — never estimated silently.

| Date (UTC) | Route | Model | Input tok | Output tok | USD (metered) | Subscription usage | Purpose |
|---|---|---|---|---|---|---|---|
| 2026-10-27 | Surplus chat | 9 models (`deepseek-v4-pro`/`-flash`, `qwen3*`, `glm-5.3`, `glm-4.7-flash`, `deepseek-v3.2`, `kimi-k2`) | 1204 | 1215 | 0.000295 | — | operator logprobs probe 04:29–04:31Z (21 calls) |
| 2026-10-27 | Surplus `/v1/decisions` | `jev-1.14` | 655 | 57 | 0.000011 | — | operator Jev shape probe 04:40Z (2 billed calls) |
| 2026-10-27 | Surplus chat | `deepseek-v4-flash` | 2629 | 278 | 0.000063 | — | B probes run 1: 3 tool round trips + 3 logprobs (9 calls) |
| 2026-10-27 | Surplus chat | `deepseek-v4-pro` | 1991 | 299 | 0.000018 | — | B probes run 1: 3 tool round trips (6 calls) |
| 2026-10-27 | Surplus `/v1/decisions` | `jev-1.14` | 355 | 32 | 0.000006 | — | B probes run 1: 1 `choice` |
| 2026-10-27 | Surplus `/v1/decisions` | `jev-1.14` | 2073 | 150 | 0.000036 | — | B probes run b2: 3 `choice` + 3 `score` |
| 2026-10-27 | Surplus chat | `deepseek-v4-pro` | — | — | 0 | — | B probe run b2: 1 logprobs request, HTTP 400 (no export row, so not billed) |
| 2026-10-27 | Surplus chat (stream) | `deepseek-v4-flash` | 282 | 1119 | 0.000090 | — | B probes run b3: 3 streams |
| 2026-10-27 | Surplus chat (stream) | `deepseek-v4-pro` | 45 | 393 | 0.000005 | — | B probes run b3: 3 streams |
| 2026-10-27 | NanoGPT / Kimi Code / GLM | — | 0 | 0 | 0 | catalogue + quota GETs only | B discovery |
| 2026-10-27 | Surplus chat | `deepseek-v4-flash` | 3284 | 815 | 0.000152 | — | C slice 1 run c1: 6 calls whose compressed bodies failed to decode (billed; export-matched by time) |
| 2026-10-27 | Surplus chat | `deepseek-v4-flash` | 19992 | 3304 | 0.000696 | — | C slice 1 run c1b: 6 loop runs, 26 calls, 6/6 accepted |
| 2026-10-27 | Surplus chat | `deepseek-v4-flash` | 231998 | 4812 | 0.002930 | — | C slice 2 run c2: a1 on lab VM, 30 calls, failed (step cap; lab has no internet egress) |
| 2026-10-27 | Surplus chat | `deepseek-v4-flash` | 334697 | 13408 | 0.004105 | — | C slice 3 run c3 (lab with tunnelled egress): a1 accepted (19 calls, $0.00126), a2 failed at the step cap because its check was wrong (30 calls, $0.002845); 49/49 export-matched |
| 2026-10-27 | Surplus chat | `deepseek-v4-flash` | 880640 | 10802 | 0.011158 | — | C slice 4 run c4 (lab c3, kept disk): a2 accepted (12 calls, $0.00052), a3 built the full tree but failed at the step cap on a wrong check (40 calls, $0.010638); 52/52 export-matched |
| 2026-10-27 | Surplus chat | `deepseek-v4.1-flash` | 16167 | 2799 | 0.000000 | — | C slice 5 tuning run c5: 3 tasks × 2, 20 calls, 6/6 accepted; 20/20 export-matched, each `buyer_cost_usd` 0.000000 (< 1 micro-USD; `direct_cost_usd` sum $0.002887) |
| 2026-10-27 | Surplus `GET /v1/prices` | — | 0 | 0 | 0 | — | C slice 5 offers snapshot (no export row) |
| 2026-10-27 | Surplus chat | `deepseek-v4.1-flash` | 12019 | 21749 | 0.000019 | — | operator Jev fair test: 46 judge calls (MODELS.md) |
| 2026-10-27 | Surplus `/v1/decisions` | `jev-1.14` | 23470 | 1570 | ≈0.00028 (46 × documented $0.000006; no cost field) | — | operator Jev fair test: 46 decisions (MODELS.md) |
| 2026-10-27 | Surplus chat | `deepseek-v4.1-flash` | 1162291 | 38398 | 0.000034 | — | C slice 8 run c8 (lab c3, kept disk): a3 accepted at the step cap (40 calls, $0.000025), a4 accepted (24 calls, $0.000009); 64/64 export-matched |
| 2026-10-27 | Surplus chat | `deepseek-v4.1-flash` | 1094705 | 42567 | 0.000055 | — | C slice 10 run c10 (lab c3, kept disk): b1 failed at the step cap (40 calls; 5 cut off at max_tokens 2048); 40/40 export-matched |
| 2026-10-27 | Surplus chat | `deepseek-v4.1-flash` | 1203222 | 69034 | 0.000073 | — | C slice 11 run c11 (lab c3, kept disk): b1 failed at the step cap again (40 calls, 0 truncated at max_tokens 8192, no file written); 40/40 export-matched |
| 2026-10-27 | Surplus chat | `deepseek-v4.1-flash` | 1117270 | 84617 | 0.000084 | — | C slice 12 over-explore demo: 30 replayed c11/b1 next-step samples (3 arms × 2 resume points × 5), no lab; 30/30 export-matched |
| 2026-10-27 | Surplus chat | `deepseek-v4.1-flash` 89 calls ($0.000712), `deepseek-v4-pro` 3 calls ($0.000640) | 2692821 | 232054 | 0.001352 | — | C slice 13 b1 arms demo: scope / read cap / pro plan vs control on replayed c11/b1 prefixes, no lab; 92/92 export-matched |
| 2026-10-27 | Codex CLI (`codex exec`, read-only) | Codex default | — | — | — | Codex subscription: 2 invocations (1 hung on stdin, 1 answered) | C slice 13: diagnosis hand-off after all 3 arms failed (`codex-diagnosis.md`) |
| 2026-10-27 | Surplus chat | `deepseek-v4.1-flash` 18 calls (2 slow-seller calls billed $0.008046) | 619944 | 135106 | 0.008170 | — | C slice 14 headroom demo: 3 slice-13 truncated-write inputs × max_tokens 8192/16384 × 3, no lab; 18/18 export-matched |
| 2026-10-27 | Surplus chat | `deepseek-v4.1-flash` 30 calls | 1236830 | 99359 | 0.000074 | — | C slice 15 feedback-before-finish demo: c11/b1 replay at k=20/30, control vs failing-check feedback (last / every step), no lab; 30/30 export-matched |
| 2026-10-27 | Surplus chat | `deepseek-v4-pro` 16 calls ($0.000909), `glm-5.3` 7 ($0.000171), `kimi-k3` 7 ($0.000192) | 897465 | 11746 | 0.001272 | — | C slice 16 stronger-executor demo: one next reply per model on replayed c11/b1 prefixes (3 smoke + 27 outcome), no lab; 30/30 export-matched |
| 2026-10-27 | Surplus chat | `deepseek-v4-pro` 40 calls | 1080051 | 25684 | 0.001838 | — | C slice 18 pro b1 run on lab c3 (failed at step cap; wrote driver, never built); 40/40 export-matched |
| 2026-10-28 | Surplus chat | `deepseek-v4.1-flash` 40 calls | 938565 | 48317 | 0.000040 | — | C slice 19 b1b run on lab c3 (flash on pro's driver: built, 2 compile errors, never fixed; step cap); 40/40 export-matched (exports of 10-27 + 10-28) |
| 2026-10-28 | Surplus chat | `deepseek-v4-pro` 27 calls | 537301 | 9131 | 0.000670 | — | C slice 20 pro b1b run on lab c3 (unverified `task_budget` at step 28: harness charged 7 no-cost calls at their bound); 20/27 export-matched, 7 without `buyer_cost_micro` absent from export and `recent_usage` at 01:01Z (unbilled so far) |
| 2026-10-28 | Surplus chat | `deepseek-v4-pro` 40 calls | 885916 | 14258 | 0.001201 | — | C slice 21 pro b1b rerun on lab c3 (failed step_cap; never used sudo); 33/40 export-matched, 7 without `buyer_cost_micro` absent from the export at 01:48Z (unbilled so far) |
| 2026-10-28 | Surplus chat | `deepseek-v4-pro` 15 calls | 415205 | 6112 | 0.000645 | — | C slice 22 replay demo: slice-21 b1b prefix at step 23, control / reasoning carried / grounded correction × 5, no lab; 15/15 export-matched |
| 2026-10-28 | Surplus chat | `deepseek-v4-pro` 9 calls | 242643 | 2646 | 0.000203 | — | C slice 23 continuation demo: slice 22's 3 correction samples continued one step after the tooldir listing, 3 draws each, no lab; 9/9 export-matched |
| 2026-10-28 | Surplus chat | `deepseek-v4-pro` 40 calls | 788286 | 10861 | 0.001667 | — | C slice 25 pro b1b rerun on lab c3 under head+tail output (failed step_cap; fixed ownership + both errors, rewrite broke an include); 40/40 export-matched |
| 2026-10-28 | Surplus chat | `deepseek-v4-pro` 61 calls | 1272979 | 33670 | 0.001540 | — | C slice 26 pro on lab c3: b1b continuation (accepted, 31 calls) then b2 (failed step_cap, 30 calls); 48/61 export-matched, 13 b1b replies without `buyer_cost_micro` absent from the export at 05:10Z (unbilled so far) |
| 2026-10-28 | Surplus chat | `deepseek-v4-pro` 30 calls | 791934 | 46488 | 0.001710 | — | C slice 27 pro b2 continuation on lab c3 (failed step_cap, 0 builds); 30/30 export-matched |
| 2026-10-28 | Surplus chat | `deepseek-v4-pro` 10 calls | 353765 | 10845 | 0.000423 | — | C slice 28 b2 correction replay demo (slice 27 prefix, K=20, 5 control + 5 correction); 10/10 export-matched; no lab |
| 2026-10-28 | Surplus chat | `deepseek-v4-pro` 26 calls | 947221 | 12751 | 0.000971 | — | C slice 29 b2 recipe-correction demo (5 M step-1 + 15 C2 and 6 M step-2 continuations on lab c3 outputs); 26/26 export-matched |
| 2026-10-28 | Surplus chat | `deepseek-v4-pro` 30 calls | 709620 | 16526 | 0.007037 | — | C slice 30 live b2 on lab c3 with recipe correction injected at step 20: accepted at the step cap; 30/30 export-matched |
| 2026-10-28 | Surplus chat | `deepseek-v4-pro` 40 calls | 1291303 | 123928 | 0.017228 | — | C slice 31 first live b3 on lab c3 (no injection): failed step_cap, 0 writes; 40/40 export-matched |
| 2026-10-28 | Surplus chat | `deepseek-v4-pro` 35 calls | 870706 | 91275 | 0.002378 | — | C slice 32 diagnostic sub-run demo on lab c3 (3 pro diagnoses × ≤ 10 runtime probes on slice 27's b2 stall: 0 corrections); 34/35 export-matched (1 transport-error call billed by time match), diag0.1 without `buyer_cost_micro` absent from the export (unbilled so far) |
| 2026-10-28 | Surplus chat | `deepseek-v4-pro` 19 calls | 68564 | 73743 | 0.001184 | — | C slice 33 spec-derivation demo (3+4 no-probe planner calls, 12 planner calls with 20 runtime probes on fresh lab sd0); 19/19 export rows token-matched |
| 2026-10-28 | Surplus chat | `kimi-k3.1-pro` 13 calls, `kimi-k3` 18, `glm-5.3` 17, `deepseek-v4-pro` 11 | 1176744 | 781373 | 0.589936 | — | C slice 34 work-item-D decider demo (legacy `DECIDER_PROMPT` on slice 27's b2 trace; 29 calls truncated at 8192 tokens, 30 at 24000); K3.1-pro $0.553023; 59/59 export-matched (1 `kimi-k3` reply had no usage: time-matched, tokens not counted) |
| 2026-10-28 | Surplus chat | `deepseek-v4-pro` 12 calls | 540330 | 6289 | 0.001054 | — | C slice 34 post-hoc continuation (pro on slice 27 K=20 + K3.1-pro's 2 decisions, reasoning dropped vs passed back); 12/12 export-matched |
| 2026-10-28 | Surplus chat | `deepseek-v4-pro` 30 calls | 1021138 | 10814 | 0.001271 | — | C slice 35 live b2 on lab c3 with reasoning passed back (no injection): failed step_cap, 0 builds; 30/30 export-matched |
| 2026-10-28 | Surplus chat | `kimi-k3.1-pro` 22 calls, `glm-5.3` 22 calls | 1646387 | 4568 | 0.473384 | — | C slice 36 takeover demo (preflight + 4 lab runs, all failed step_cap): balance delta $8.699060 → $8.225676; export matched 37/44 calls = $0.131383, the 7 replies without `buyer_cost_micro` are absent from the export (upper bound recorded) |
| 2026-10-28 | Surplus chat | `kimi-k3.1-pro` 6 calls | 191826 | 86888 | 0.467867 | — | C slice 37 hypothesis-plan demo (5 one-shot plans on slice 35's b2 prefix, 1 resubmit; P1 0/5, no lab): balance delta $8.225676 → $7.757809; export matched 5/6 requests = $0.359383, plan 2 (no `buyer_cost_micro`) absent from the export; tokens: export rows + plan 2's reply usage, the 2 refused admissions made no request |
| 2026-10-28 | Surplus chat | `kimi-k3.1-pro` 2 calls | 57188 | 6700 | 0.071824 | — | C slice 38 probe-and-replan demo, stopped by founder decision (MISSION a7322df): 2 stage-2 re-plan requests billed, no reply recorded (1 killed externally, 1 stopped); balance delta $7.757809 → $7.685985; export matched 2/2 |
| 2026-10-28/29 | Surplus chat | `deepseek-v4-pro` 864, `glm-5.3` 556, `kimi-k3.1-pro` 11, `glm-5.3-flash` 28, `kimi-k3` 15, 3 others 3 | 54439659 | 2510622 | 0.377811 | — | C slice 39 other-model-leads demo: preflights + 11 live lab runs (export 2026-10-28T22:40Z–2026-10-29T08:10Z, 1,477 rows, token totals from its input_tokens/output_tokens columns, 0 rows missing; available-balance delta $0.3814; kimi-k3.1-pro $0.1912 was billed before the 90% floor); `~/evidence/other-model-leads-demo-2026-10-28/reconciled.json` |
| 2026-10-29 | Surplus chat | `kimi-k3` 637, `deepseek-v4-pro` 359, `glm-5.3` 40 | 53475464 | 964562 | 0.198894 | — | C slice 40 lead-factor demo: 3 live kimi-k3-lead runs (lead 606 + executor 359 requests) + finish replay (kimi-k3 31, glm-5.3 40); 4 glm-5.3 `medium` 400s unbilled (absent from the export); export 2026-10-29T08:49Z–16:28Z excluding 3 `kimi-k3.1-pro` rows ($0.015657, 15:12–16:02Z) that match no slice-40 call (another consumer of the key); `~/evidence/lead-factor-demo-2026-10-29/reconciled.json` |
| 2026-10-29 | Surplus chat | `kimi-k3` 21, `glm-5.3` 15 | 25225 | 18210 | 0.001207 | — | C slice 42 goal-list review demo (offline: 6 kimi-k3 init draws + 15 glm-5.3 low and 15 kimi-k3 low reviews of slice 40's 3 init goal lists); 36/36 export-matched, = balance delta 7.548428 → 7.547221 |
| 2026-10-29/30 | Surplus chat | `kimi-k3` 1,606, `deepseek-v4-pro` 994 | 176885432 | 2249586 | 0.378958 | — | C slice 43 step-cap demo: 4 live kimi-k3-lead runs at 240 steps (lead-s1, -s2 cut by the ceiling-settlement fault, -s2b, -s3); export rows matched by tokens per run (`~/evidence/step-cap-demo-2026-10-29/export-s*.csv`, `cost.json`), 25 replies without `buyer_cost_micro` absent from the export |
| 2026-10-29/30 | Surplus chat (not Conflux) | `deepseek-v4-pro` 1,076, `kimi-k3.1-pro` 4, `glm-5.3` 7 | — | — | 0.251287 | — | unattributed caller on the shared key, counted against the weekly cap: kimi-k3.1-pro $0.097557 at 60% discount (10-29 15:11, 15:41, 16:02, 21:22Z; floor bypass, MISSION a58a30e), deepseek-v4-pro $0.152919 (10-30 06:45–16:34Z), glm-5.3 $0.000811; no controller process, file or Codex session matches |
| 2026-10-30 | Surplus chat | `kimi-k3` 24 | 23608 | 13506 | 0.001096 | — | C slice 44 per-goal check demo (offline: P1/P2 follow-up turns on 6 recorded kimi-k3 init conversations, 2 draws each); 24/24 export-matched by tokens; `~/evidence/acceptance-check-demo-2026-10-30/reconciled.json` |
| 2026-10-30 | Surplus chat (not Conflux) | `deepseek-v4-pro` 55, `kimi-k3` 2 | — | — | 0.009536 | — | unattributed caller on the shared key after slice 43 ended (16:34Z–16:56Z export pull; kimi-k3 rows 24–25k input tokens, no slice-44 call matches), counted against the weekly cap |
| 2026-10-30 | Surplus chat | `kimi-k3` 45 | 88010 | 21271 | 0.000754 | — | C slice 45 lead init-probe demo (live, lab lp1): 12 kimi-k3 low init conversations with `run_shell` probes + 1 preflight; 23 replies billed in-reply, export-matched by tokens; 21 replies without `buyer_cost_micro` absent from the export (`unbilled`, $0); `~/evidence/lead-probe-demo-2026-10-30/reconciled.json` |
| 2026-10-30 | Surplus chat (not Conflux) | `deepseek-v4-pro` 144, `kimi-k3` 4 | — | — | 0.018639 | — | unattributed caller on the shared key in slice 45's window (17:04–18:22Z export; kimi-k3 rows 19–27k input tokens, no slice-45 call matches), counted against the weekly cap |
| 2026-10-30 | Surplus chat | `kimi-k3` 199 calls (15 billed), `glm-5.3` 201 calls (36 billed) | 801700 | 40058 | 0.004527 | — | C slice 47 finish-judgement demo (offline replay of 16 recorded finish states, 64 review conversations, both at `reasoning_effort=low`); 51 replies billed in-reply and export-matched by tokens; 349 without `buyer_cost_micro` have no export row (unbilled); includes 6 calls of a crashed first start and the calls of the deadlocked run; `~/evidence/finish-judge-demo-2026-10-30/reconciled.json` |
| 2026-10-30 | Surplus chat (not Conflux) | `deepseek-v4-pro` 129, `kimi-k3` 1 | — | — | 0.031831 | — | unattributed caller on the shared key in slice 47's window (19:19–21:09Z export; no pro call from this demo; the one kimi-k3 row ($0.000115) is unmatched to any demo call and may be a demo reply recorded without usage), counted against the weekly cap |

C slice 1 rows are reconciled with the export by `python -m conflux.core reconcile` (`~/evidence/core-runs/2026-10-27-c1*/reconciled.json`;
export total for 2026-10-27: 83 rows, $0.001372).

**Accounting source:** the Surplus buyer usage export (`GET https://api.surplusintelligence.ai/v1/buyer/usage/export`,
`buyer_cost_usd` per request; see `RESOURCES.md`). The B rows above are reconciled with the export of 2026-10-27
(`~/evidence/provider-probes/2026-10-27-reconcile/usage.csv`: 51 rows, all `accrued`, total $0.000524). Rows were
matched on timestamp, model and token counts. The probe's in-flight figures (`buyer_cost_micro`, derived Jev,
charge-bound estimates) are only admission-time bounds. They are replaced by billed values here: the earlier
$0.0108 Jev and $0.0207 rejected-request estimates were billed $0.000006 and $0. Account credit after these runs
is $9.369476 (`/v1/buyer/me`).

**Metered total: $2.860537** (the Jev fair-test decisions are counted at their ≈$0.00028 estimate)

## GCE lab VMs (week 2026-W44 cap $60)

Rate: n2d-standard-8 ≈ $0.338/h running (GCE list price, us-central1) + 100 GB pd-balanced ≈ $0.014/h while the disk exists.

| Date (UTC) | Lab | Running (UTC) | Hours | USD | Purpose |
|---|---|---|---|---|---|
| 2026-10-27 | `conflux-dev-lab-c2` | 06:42:57–06:58:07, 06:58:30–06:59:50 | 0.28 | 0.10 | C slice 2 run c2 + egress check; deleted 06:59Z |
| 2026-10-27 | `conflux-dev-lab-c3` | 07:36:02–07:55:35, 07:56:26–07:58:08 | 0.35 | 0.13 | C slice 3 run c3 + a2 recheck; stopped, disk kept (≈ $0.014/h, $0.34/day) for a3 |
| 2026-10-27 | `conflux-dev-lab-c3` | 08:15:46–09:17:47, 09:18:51–09:20:32 | 1.06 | 0.36 | C slice 4 run c4 (a2 + a3) + model-free a3 recheck; stopped, disk kept for a4 |
| 2026-10-27 | `conflux-dev-lab-c3` | 09:35:27–09:37:50, 09:38:56–09:41:54 | 0.09 | 0.03 | C slice 5 model-free a3 + a4 checks (try 1: no `expect`; try 2: pass); stopped, disk kept |
| 2026-10-27 | `conflux-dev-lab-c3` | 09:49:42–09:53:36 | 0.07 | 0.02 | C slice 5 critic fix: pristine-evaluator a4 check passes, tampered `qemu_v8.mk` fails; stopped, disk kept |
| 2026-10-27 | `conflux-dev-lab-c3` | 10:20:19–10:25:23 | 0.08 | 0.03 | C slice 6 harness-only a1–a4 recheck under pipefail: 4/4 pass; stopped, disk kept |
| 2026-10-27 | `conflux-dev-lab-c3` | 11:19:13–11:25:50 | 0.11 | 0.04 | C slice 7 harness-only probes (ERR trap keeps PIPESTATUS, `failed_cmds`) + a1–a4 recheck: 4/4 pass; stopped, disk kept |
| 2026-10-27 | `conflux-dev-lab-c3` | 11:45:57–12:30:55 | 0.75 | 0.25 | C slice 8 model run c8 (a3 + a4, both accepted); stopped, disk kept |
| 2026-10-27 | `conflux-dev-lab-c3` | 12:44:46–12:47:46, 12:55:01–13:18:59, 13:19:06–13:19:59 | 0.47 | 0.16 | C slice 9 snapshot NetBSD inspection + model-free goal-(b) check validation (5 controls, all as expected); stopped, disk kept |
| 2026-10-27 | `conflux-dev-lab-c3` | 13:30:48–13:32:06, 13:35:24–14:23:16, 14:23:39–14:49:13 | 1.25 | 0.42 | C slice 9 critic round: revised goal-(b) checks re-validated (numeric fake UID, staged/committed edits, native fake QEMU, no-SPD TF-A boot); stopped, disk kept |
| 2026-10-27 | `conflux-dev-lab-c3` | 15:08:26–15:48:27 | 0.67 | 0.23 | C slice 10 run c10 (b1, failed at the step cap); first start 15:02Z failed on a GCE stockout ($0, VM not started); stopped, disk kept |
| 2026-10-27 | `conflux-dev-lab-c3` | 16:02:24–16:35:13 | 0.55 | 0.19 | C slice 11 run c11 (b1, failed at the step cap, model fault); stopped, disk kept |
| 2026-10-27 | `conflux-dev-lab-c3` | 22:37:58–23:10:03 | 0.53 | 0.18 | C slice 18 pro b1 run (failed at step cap); 2 starts 22:32Z/22:33Z failed on GCE stockouts ($0); stopped, disk kept (holds pro's b1 edits) |
| 2026-10-27/28 | `conflux-dev-lab-c3` | 23:33:15–00:01:29 | 0.47 | 0.16 | C slice 19 harness-only b1a/b1b checks + flash b1b run (failed at step cap); stopped, disk kept (pro's edits + flash's build log) |
| 2026-10-28 | `conflux-dev-lab-c3` | 00:08:10–00:10:23, 00:10:57–00:14:30 | 0.10 | 0.03 | C slice 19 critic round 1: revised b1a check harness-only (pro tree pass; config-only and stanza-only clones fail; try 1 clone refused by git ownership); stopped, disk kept |
| 2026-10-28 | `conflux-dev-lab-c3` | 00:37:45–00:56:23 | 0.31 | 0.11 | C slice 20 harness-only b1a/b1b pre-check + pro b1b run (unverified `task_budget`, harness fault); stopped, disk kept (pro's partial repair + `optee.c.bak`) |
| 2026-10-28 | `conflux-dev-lab-c3` | 01:17:18–01:46:17 | 0.48 | 0.16 | C slice 21 restore + harness-only pre-check + pro b1b rerun (failed step_cap); stopped, disk kept (2-error driver, no `.bak`) |
| 2026-10-28 | `conflux-dev-lab-c3` | 02:31:18–02:33:25 | 0.04 | 0.01 | C slice 24 harness-only read of slice 21's job files (4 KB tail cut step 12's `Permission denied`); stopped, disk kept |
| 2026-10-28 | `conflux-dev-lab-c3` | 03:01:56–03:34:26 | 0.54 | 0.18 | C slice 25 state check + harness-only pre-check + pro b1b rerun (failed step_cap); stopped, disk kept (pro's rewrite, obj tree now dev-owned) |
| 2026-10-28 | `conflux-dev-lab-c3` | 03:47:19–05:01:14 | 1.23 | 0.42 | C slice 26 state + harness-only pre-check + pro b1b continuation (accepted) + b2 (failed step_cap); stopped, disk kept (b1b kernel built, pro's b2 firmware) |
| 2026-10-28 | `conflux-dev-lab-c3` | 05:18:14–06:14:21 | 0.93 | 0.32 | C slice 27 state + harness-only pre-check + BL33 diagnosis (2 TF-A builds, 2 boots) + pro b2 continuation (failed step_cap); stopped, disk kept (tree unchanged) |
| 2026-10-28 | `conflux-dev-lab-c3` | 06:49:28–06:54:50 | 0.09 | 0.03 | C slice 29 state check + harness-only execution of 17 recorded read commands (slice 28 C draws, slice 29 M0/M4); stopped, disk kept (tree unchanged) |
| 2026-10-28 | `conflux-dev-lab-c3` | 07:20:55–07:59:01 | 0.64 | 0.21 | C slice 30 state + harness-only pre-check + pro b2 with injected correction (accepted); stopped, disk kept (flagged b2 firmware, TF-A build dir rebuilt for NetBSD) |
| 2026-10-28 | `conflux-dev-lab-c3` | 08:17:44–10:07:51 | 1.84 | 0.62 | C slice 31 state + harness-only pre-check (b1a/b1b/b2 pass, b3 fail) + pro b3 run (failed step_cap); stopped, disk kept (tree unchanged by the model) |
| 2026-10-28 | `conflux-dev-lab-c3` | 10:36:12–10:49:39, 10:52:13–11:59:05 | 1.34 | 0.45 | C slice 32 diagnostic sub-run demo: try 2 stopped at setup (restore did not clean TF-A; b2 passed, no paid call), try 3 setup + 3 diagnoses + resets; 3 starts 10:23–10:27Z and 1 at 10:50Z failed on GCE stockouts ($0); stopped, disk kept (in-tree TF-A back to no-flag build) |
| 2026-10-28 | `conflux-dev-lab-sd0` | 12:41:22–12:56:55 (created 12:39:04Z) | 0.30 | 0.10 | C slice 33 spec-derivation planner with 20 probes, fresh lab from the clean snapshot; deleted 12:56Z. sd1: 21 starts 12:56–13:54Z failed on GCE stockouts ($0 compute; one stray boot disk 12:57–13:15Z ≈ $0.004, deleted) |
| 2026-10-28 | `conflux-dev-lab-c3` | 17:34:51–18:05:26 | 0.51 | 0.17 | C slice 35 harness-only pre-check (b1a/b1b pass, b2 fail) + pro b2 run with reasoning passback (failed step_cap, no writes); stopped, disk kept (tree unchanged by the model) |
| 2026-10-28 | `conflux-dev-lab-c3` | ≈ 18:32–18:47, 18:46–19:04, 19:06–19:23, 19:22–19:38, 19:41–19:46 | 1.18 | 0.40 | C slice 36 takeover demo: 4 restore + pre-check + takeover runs (K3.1-pro ×2, GLM-5.3 ×2) + final restore; 3 starts failed on GCE stockouts ($0); stopped, disk kept (slice-27 state) |
| 2026-10-28 | `conflux-dev-lab-c3` | 21:50:55–22:03:02 | 0.20 | 0.07 | C slice 38 stage-1 runtime probes (21 slice-37 test commands, 5 restores); stopped, disk kept (slice-27 state) |
| 2026-10-28/29 | `conflux-dev-lab-ol1`, `-ol2` | 14 up→delete windows 23:50Z–08:05Z (two labs at a time) | ≤ 14.87 | ≤ 5.23 | C slice 39 live runs (fresh labs from the clean snapshot, graded, deleted); upper bound: windows include the post-run stop before grading |
| 2026-10-29 | `conflux-dev-lab-lc1`, `-lc2`, `-lc3` | 08:49–11:23, 11:23–14:03, 14:03–16:30 (one lab at a time) | ≤ 7.7 | ≤ 2.71 | C slice 40 live kimi-k3-lead runs (fresh labs from the clean snapshot, graded, deleted); upper bound incl. post-run grading start |
| 2026-10-29/30 | `conflux-dev-lab-s1`, `-s2`, `-s2b`, `-s3` | 17:33–23:11, 23:13–01:28, 01:29–10:32, 10:33–16:33 (one lab at a time) | ≤ 22.9 | ≤ 8.07 | C slice 43 live 240-step kimi-k3-lead runs (fresh labs from the clean snapshot, graded, deleted); upper bound incl. post-run grading start |
| 2026-10-30 | `conflux-dev-lab-lp1` | 17:09:50–17:25:12, 17:26:13–17:43:00, 17:43:48–17:48:06, 17:49:20–18:17:38 (up issued → deleted; 2 stockouts 17:11Z, 17:15Z) | ≤ 1.08 | ≤ 0.38 | C slice 45 lead init-probe demo (4 fresh labs from the clean snapshot, one at a time, deleted; VMs existed ≈ 0.84 h) |

**GCE lab total: ≤ $21.97** (plus the c3 disk while it exists)
