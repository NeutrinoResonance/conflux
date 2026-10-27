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

C slice 1 rows are reconciled with the export by `python -m conflux.core reconcile` (`~/evidence/core-runs/2026-10-27-c1*/reconciled.json`;
export total for 2026-10-27: 83 rows, $0.001372).

**Accounting source:** the Surplus buyer usage export (`GET https://api.surplusintelligence.ai/v1/buyer/usage/export`,
`buyer_cost_usd` per request; see `RESOURCES.md`). The B rows above are reconciled with the export of 2026-10-27
(`~/evidence/provider-probes/2026-10-27-reconcile/usage.csv`: 51 rows, all `accrued`, total $0.000524). Rows were
matched on timestamp, model and token counts. The probe's in-flight figures (`buyer_cost_micro`, derived Jev,
charge-bound estimates) are only admission-time bounds. They are replaced by billed values here: the earlier
$0.0108 Jev and $0.0207 rejected-request estimates were billed $0.000006 and $0. Account credit after these runs
is $9.369476 (`/v1/buyer/me`).

**Metered total: $0.001372**
