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

C slice 1 rows are reconciled with the export by `python -m conflux.core reconcile` (`~/evidence/core-runs/2026-10-27-c1*/reconciled.json`;
export total for 2026-10-27: 83 rows, $0.001372).

**Accounting source:** the Surplus buyer usage export (`GET https://api.surplusintelligence.ai/v1/buyer/usage/export`,
`buyer_cost_usd` per request; see `RESOURCES.md`). The B rows above are reconciled with the export of 2026-10-27
(`~/evidence/provider-probes/2026-10-27-reconcile/usage.csv`: 51 rows, all `accrued`, total $0.000524). Rows were
matched on timestamp, model and token counts. The probe's in-flight figures (`buyer_cost_micro`, derived Jev,
charge-bound estimates) are only admission-time bounds. They are replaced by billed values here: the earlier
$0.0108 Jev and $0.0207 rejected-request estimates were billed $0.000006 and $0. Account credit after these runs
is $9.369476 (`/v1/buyer/me`).

**Metered total: $0.020110** (the Jev fair-test decisions are counted at their ≈$0.00028 estimate)

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

**GCE lab total: $1.96** (plus the c3 disk while it exists)
