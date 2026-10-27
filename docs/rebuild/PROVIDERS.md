# Provider capability matrix (work item B)

Executed 2026-10-27 from `conflux-dev-ctl` with `scripts/provider_probe.py`. Raw evidence (outside
Git): `~/evidence/provider-probes/2026-10-27/probes.jsonl`
(sha256 `59c9d9c876d49001b8f6db39ec34fc08bb591340460bd8e140dac5caaee4fd73`, 44 lines, 16 admissions →
16 responses) and `summary.json` (sha256 `d637e257af7d95277cfa9d764fa72481baedd04f4719d992be4cec46aed85831`).
The earlier operator notes are in
`~/evidence/provider-probes-2026-10-27.md`.

**Status legend.**
- **pass n/N:** the check ran and passed.
- **absent:** the parameter was accepted but nothing came back.
- **not tested:** no request was sent (this is not a failure).

## Paid probes (Surplus, temperature 0)

| Model | Capability | Result | Notes |
|---|---|---|---|
| `deepseek-v4-flash` | tool-call round trip | **pass 3/3** | `get_weather` call, then a text answer after the tool result; ~2–3 s per leg |
| `deepseek-v4-flash` | logprobs (`logprobs`, `top_logprobs=5`) | **absent 3/3** | HTTP 200, no logprobs returned, even though the catalogue lists `logprobs` in `supported_parameters` |
| `deepseek-v4-pro` | tool-call round trip | **pass 3/3** | `reasoning_content` echoed back on leg 2; 14–29 reasoning tokens per leg count against `max_tokens` |
| `deepseek-v4-pro` | logprobs | not tested | the operator probe on 2026-10-27 saw HTTP 400 rejected |
| `deepseek-v4-flash`, `-pro` | streaming + usage | not tested | the run stopped first (unknown accounting, see below) |
| `jev-1.14` (`POST https://api.surplusintelligence.ai/v1/decisions`) | 2-option `choice` | **pass 1/1** | `{"answers":{"q1":{"choice":"accept","confidence":0.88,"probabilities":{"accept":0.94,"retry":0.06}}}}`; 0.34 s |
| `jev-1.14` | 3-criterion `score` | not tested | the operator probe got HTTP 200 with probabilities |

## Billing and accounting findings

- **Surplus chat usage** has two cost fields:
  - `buyer_cost_micro`: the buyer charge in micro-USD.
  - `cost`: an upstream inference cost. It is only present on flash responses, and it is 1.8–13× `buyer_cost_micro`.
- `buyer_cost_micro` is far below the catalogue list price:
  - `deepseek-v4-pro`: 286 input + 74 output tokens is listed at ≈ $0.000414 and billed at $0.000003.
  - `deepseek-v4-flash`: billed at about 35–45% of list.
- No Surplus balance endpoint was found, so these billed figures **are not verified against the account**. Treat them as
  provider-reported only until they are reconciled with the Surplus dashboard.
- **Jev usage** reports `input_tokens`/`output_tokens` but **no billed-cost field**. The catalogue lists input-only
  pricing of $0.042/1M (355 tokens ≈ $0.000015). Following the probe contract, the run booked the charge bound
  ($0.0108) as a labeled estimate and stopped all paid calls.
- The Surplus catalogue (`/models`) answers with `content-encoding` set but a body that httpx cannot decode. Clients
  must send `Accept-Encoding: identity`.

## Catalogues ($0, GET)

| Route | Models | Families present (relevant ids) | Prices in catalogue |
|---|---|---|---|
| Surplus | 489 | `deepseek-v4-pro`, `deepseek-v4-flash`, `jev-1.14` (modality `decisions`) | yes, per token: v4-flash $0.091/$0.182 per 1M, v4-pro $0.955/$1.911 per 1M, jev $0.042 per 1M input |
| NanoGPT | 327 | `deepseek/deepseek-v4-pro`, `deepseek/deepseek-v4-flash`, `deepseek/deepseek-v4.1-flash`, `typesafe/jev-1.14`, `z-ai/glm-5.3`, `moonshotai/kimi-k2.6` (+ `:thinking` variants) | no |
| Kimi Code | 6 | `kimi-for-coding`, `k3`, `k3-256k`, `k3.1-pro`, `-highspeed` variants | no |
| GLM Coding | 11 | `glm-5.3`, `glm-5.3-flash`, `glm-5.3-flashx`, `glm-5.2`, `glm-5-turbo`, … | no |

## Balance and quota endpoints ($0)

| Route | Endpoint | Result |
|---|---|---|
| Surplus | `…/inference/v1/balance`, `…/credits`, `api.…/v1/balance`, `api.…/v1/account` | all 404 `not_found`: no programmatic balance endpoint found |
| NanoGPT | `POST /api/check-balance` | 200: USD balance 0.00 (overflow fails, as expected) |
| NanoGPT | `GET /api/subscription/v1/usage` | 200: weekly input tokens 60M limit, 366 used; `allowOverage=false`; billing mode `subscription_only` |
| Kimi Code | `GET /coding/v1/usages` (undocumented) | 200: 5-hour window 100/100 remaining; 7-day window used ratio 0, resets 2026-11-02 |
| GLM Coding | `GET https://api.z.ai/api/monitor/usage/quota/limit` (undocumented) | 200: level `lite`. Short-window credit limit 0/2000 used. Long-window limit **6964/10000 used (69 %)** |

## Consequences for C/D

- DeepSeek tool calling works on both models through Surplus, so the core can use plain OpenAI `tools`.
- No Surplus chat model returns probabilities. Probability-based checks must use Jev `/v1/decisions` (`choice`), not
  logprobs. The letter scale (A–T) applies only if a logprob reader ever comes back.
- Jev cost must come from price × `input_tokens`, because the response carries no charge. That accounting rule needs
  approval in the contract before Jev runs unattended.
