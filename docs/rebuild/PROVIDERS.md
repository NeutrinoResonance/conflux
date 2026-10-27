# Provider capability matrix (work item B)

Executed 2026-10-27 from `conflux-dev-ctl` with `scripts/provider_probe.py`. Raw evidence (outside
Git): `~/evidence/provider-probes/2026-10-27/probes.jsonl`
(sha256 `59c9d9c876d49001b8f6db39ec34fc08bb591340460bd8e140dac5caaee4fd73`, 44 lines, 16 admissions →
16 responses) and `summary.json` (sha256 `d637e257af7d95277cfa9d764fa72481baedd04f4719d992be4cec46aed85831`).
Follow-up runs b2 (`--only decision_choice,decision_score,deepseek-v4-pro:logprobs,stream_usage`) and b3
(`--only stream_usage`; b2 stopped on the logprobs 400) are in `~/evidence/provider-probes/2026-10-27-b2/`
(probes.jsonl sha256 `b24d48f76a6cb5097d07e38008b672894d2d23a17d003e4b33355c8253318109`, 26 lines, 7 admissions →
7 responses; summary.json `843c793140c23c77a68e4b7977ad47771f2053beafe094c790752d90422d6ed6`) and
`…/2026-10-27-b3/` (probes.jsonl `07b2e4bb8d86c509d34b50dca51a45be2cf7d7dc7bc0d6f47fa06bffcc9b8433`, 24 lines,
6 → 6; summary.json `ab95e0d30a0ed6feb0dcc83f3298ca5ac38c7438c5c73d7d043aec3d2dd223e5`).
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
| `deepseek-v4-pro` | logprobs | **rejected 1/1** | HTTP 400 `InvalidParameter: logprobs is not supported`, with no usage block. One sample was enough, because this stopped the run (see below) |
| `deepseek-v4-flash` | streaming + usage | **pass 3/3** | 62–122 chunks ending in `[DONE]`; the final chunk carries `usage` including `buyer_cost_micro` |
| `deepseek-v4-pro` | streaming + usage | **pass 3/3** | 24–34 chunks; the final usage chunk carries `buyer_cost_micro` (1–2 µUSD) |
| `jev-1.14` (`POST https://api.surplusintelligence.ai/v1/decisions`) | 2-option `choice` | **pass 4/4** | `{"answers":{"q1":{"choice":"accept","confidence":0.88,"probabilities":{"accept":0.94,"retry":0.06}}}}`. Accept 0.94–0.96 across samples; 0.2–3.4 s |
| `jev-1.14` | 3-criterion `score` | **pass 3/3** | `score` 1.80–1.82, probabilities `{"0":0.04,"1":0.10–0.12,"2":0.84–0.86}`, `legend` echoes the criteria; ~0.25 s |

## Billing and accounting findings

- **Surplus chat usage** has two cost fields:
  - `buyer_cost_micro`: the buyer charge in micro-USD.
  - `cost`: an upstream inference cost. It is only present on flash responses, and it is 1.8–13× `buyer_cost_micro`.
- `buyer_cost_micro` is far below the catalogue list price:
  - `deepseek-v4-pro`: 286 input + 74 output tokens is listed at ≈ $0.000414 and billed at $0.000003.
  - `deepseek-v4-flash`: billed at about 35–45% of list.
- **Accounting source: the Surplus buyer API** (`https://api.surplusintelligence.ai`, same Bearer key):
  - `GET /v1/buyer/usage/export?format=csv&from=…&to=…` returns a 302 to a pre-signed URL. Follow it **without** the
    Authorization header. The CSV has one row per billed request, with `buyer_cost_usd`.
  - `GET /v1/buyer/me` gives the credit balance and a per-model breakdown.
  - The export of 2026-10-27 (sha256 `ce57f31987314b5d1e0b8e751577045c17c86485abe8dafd5092faea9577b08b`, 51 rows, all
    `accrued`) matches every probe call on timestamp, model and tokens. Its total is $0.000524, which is what LEDGER books.
  - Every in-response `buyer_cost_micro` matched its export row exactly.
  - The export `request_id` is a ULID. It matches the `request_id` on error bodies, not the chat `id`.
- The earlier "no balance endpoint" finding was about the inference host. The `…/inference/v1/balance` probes below are still 404.
- **Jev usage** reports `input_tokens`/`output_tokens` but **no billed-cost field**. The catalogue lists input-only
  pricing of $0.042/1M (355 tokens ≈ $0.000015). Following the probe contract, the first run booked the charge bound
  ($0.0108) as a labeled estimate and stopped all paid calls. Since run b2, the probe settles Jev as a **derived** cost:
  `max(input_tokens, 300) × prompt + output_tokens × completion` from the live catalogue, labeled `derived`.
  That is about 2.4× the billed charge, so it is a safe in-flight bound. **Billed Jev:** $0.000005–0.000006 per decision
  (312–355 input tokens) in the export.
- **A rejected request (4xx) carries no usage.** The probe books it at its charge bound and stops the run. The export
  has **no row** for the v4-pro logprobs 400, so it was not billed.
- **Streaming usage** (`stream_options.include_usage`) carries `buyer_cost_micro` in the final chunk on both
  DeepSeek models, so streamed calls are accountable.
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
| Surplus | `…/inference/v1/balance`, `…/credits`, `api.…/v1/balance`, `api.…/v1/account` | all 404 `not_found` |
| Surplus | `GET api.…/v1/buyer/me`, `GET api.…/v1/buyer/usage/export` | 200: credit $9.369476, per-request billed CSV (the accounting source) |
| NanoGPT | `POST /api/check-balance` | 200: USD balance 0.00 (overflow fails, as expected) |
| NanoGPT | `GET /api/subscription/v1/usage` | 200: weekly input tokens 60M limit, 366 used; `allowOverage=false`; billing mode `subscription_only` |
| Kimi Code | `GET /coding/v1/usages` (undocumented) | 200: 5-hour window 100/100 remaining; 7-day window used ratio 0, resets 2026-11-02 |
| GLM Coding | `GET https://api.z.ai/api/monitor/usage/quota/limit` (undocumented) | 200: level `lite`. Short-window credit limit 0/2000 used. Long-window limit **6964/10000 used (69 %)** |

## Consequences for C/D

- DeepSeek tool calling works on both models through Surplus, so the core can use plain OpenAI `tools`.
- No Surplus chat model returns probabilities. Probability-based checks must use Jev `/v1/decisions` (`choice`), not
  logprobs. The letter scale (A–T) applies only if a logprob reader ever comes back.
- Cost accounting is the buyer usage export, joined on time, model and tokens (or on the ULID `request_id`).
  In-flight bounds are `buyer_cost_micro` for chat and the derived figure for Jev. Jev `choice` and `score` both return normalized probabilities.
- Streaming is usable with exact billed accounting.
