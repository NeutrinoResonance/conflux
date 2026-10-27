# Spend ledger

Metered budget for the initial 48 h campaign: **$50** (Surplus + any paid overflow).
Subscription usage (Claude, Codex, NanoGPT, Kimi, GLM) is tracked in its own column, not as cash.
USD comes from provider responses or documented prices — never estimated silently.

| Date (UTC) | Route | Model | Input tok | Output tok | USD (metered) | Subscription usage | Purpose |
|---|---|---|---|---|---|---|---|
| 2026-10-27 | Surplus chat | `deepseek-v4-flash` | 2629 | 278 | 0.000063 | — | B probes: 3 tool round trips + 3 logprobs requests (9 calls) |
| 2026-10-27 | Surplus chat | `deepseek-v4-pro` | 1991 | 299 | 0.000018 | — | B probes: 3 tool round trips (6 calls) |
| 2026-10-27 | Surplus `/v1/decisions` | `jev-1.14` | 355 | 32 | 0.010800 est. | — | B probe: 1 `choice` decision. The response has no billed cost, so this is the charge bound (list price × input ≈ $0.000015) |
| 2026-10-27 | NanoGPT / Kimi Code / GLM | — | 0 | 0 | 0 | catalogue + quota GETs only | B discovery |

The chat USD figures are `buyer_cost_micro` from the responses. They are not reconciled with the account,
because no Surplus balance endpoint exists (see `PROVIDERS.md`). The operator probe before the campaign
cost < $0.001 and is not itemized.

**Metered total: $0.010881**
