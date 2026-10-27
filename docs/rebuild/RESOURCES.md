# Rebuild resources (secret-free)

## Controller `conflux-dev-ctl` (project `project96-sar`, `us-central1-a`)

- User `dev`; repo checkout `~/work/conflux`; Shepherd v2.5.0 + herdr 0.9.5 as systemd user services.
- Runtime identity: service account `conflux-dev-ctl@project96-sar.iam.gserviceaccount.com`
  (start/stop/ssh **only** `conflux-dev-worker-*`, read-only compute view, log writing, its own secrets).
- Provider API keys (files, mode 0600, never print them): `~/.config/devbox/secrets/`
  `surplus.key`, `nanogpt.key`, `kimi-code.key`, `zai-coding.key`, `github-token`.
  Refreshed from Secret Manager (`conflux-dev-*`) by `devbox provision`.
- Claude Code / Codex: native subscription logins in `~/.claude/` and `~/.codex/` (refresh in place).

## Evidence (outside Git)

- `~/evidence/legacy-local/artifacts/` — the founder workstation's `artifacts/` (UI captures,
  terminal-bench, optee-replay incl. lab transcripts/senate logs, optee-intervention-audit, phoenix ledger).
- `~/evidence/legacy-local/traces.db` — workstation Conflux trace DB (SQLite backup, 2026-10-26).
- `~/evidence/optee-ctl-runs/run4…run12` — OP-TEE/NetBSD live-repro runs from `conflux-optee-ctl`.
  Run 12 paused 2026-10-24 at goal (b) (NetBSD driver) when executor providers ran out of credit;
  it contains `transcript.json`, `senate.jsonl`, `proxy.log`, `runner.log`, `traces.db`, configs.
- Preserved VMs `conflux-optee-ctl`, `conflux-optee-lab`, `conflux-optee-lab2`, `llmsuper-*`: **do not
  touch** (the controller identity cannot reach them anyway).

## Lab VMs (`devbox-lab`)

- `devbox-lab up|ssh|stop|delete|list <name>` → `conflux-dev-lab-<name>`, n2d-standard-8 (8 vCPU, 32 GB) from snapshot
  `conflux-optee-baseline-clean-20261021` (100 GB pd-balanced), no external IP, no service account, self-stops after 24 h.
  Cost: ≈ $0.338/h running (GCE list price, us-central1) + ≈ $0.014/h for the disk while it exists (stopped or not).
- The core loop drives a lab with `python -m conflux.core run --lab <name> --workdir '~/optee-work' --lab-hours 4`:
  it runs `up`, waits for ssh, smokes, runs tasks in order, and always runs `stop`. Every command is a detached job in
  `~/.conflux-jobs/<id>/` on the lab (`cmd.sh`, `out`, `err`, `rc`), polled every 5 s over `gcloud compute ssh
  --internal-ip` with an ssh ControlMaster socket in `~/.ssh/cm-*`.
- **Labs have no direct internet egress (verified 2026-10-27):** no external IP, no Cloud NAT in the project (the
  controller cannot create routers), Private Google Access only. Smoke: user `dev`, passwordless sudo.
- **Egress is tunnelled (C slice 3):**
  - `run_lab` serves an HTTP CONNECT/forward proxy (`conflux.core.egress_proxy`) on the controller's 127.0.0.1;
  - a supervised `gcloud compute ssh -N -R 3128:127.0.0.1:<port>` exposes it as the lab's `127.0.0.1:3128`;
  - every lab job gets `http(s)_proxy`/`no_proxy` (`PROXY_ENV`), and harness setup sets the apt proxy
    (`/etc/apt/apt.conf.d/95conflux-proxy`) and sudo `env_keep` (`/etc/sudoers.d/conflux-proxy`);
  - an egress check (curl github/pypi, `apt-get update`) gates the first model call (`egress_failed`).
  - Verified in run c3: apt, pip, curl, git, `repo init` and the full qemu_v8 `repo sync` (56 s) all went through it.
  - Tools that ignore proxy env (raw sockets, `git://`, ping) have no egress.

## Workers

- `conflux-dev-worker-1`, `conflux-dev-worker-2`: e2-medium Spot, Debian 12, 30 GB, no provider
  credentials, service account `conflux-dev-worker@` (log writing only).
- Every start runs at most 2 h (`max-run-duration`), then GCE stops it; Spot preemption also stops it.
  Checkpoint long jobs to the controller and restart within budget. Leave workers stopped when idle.

```sh
gcloud compute instances start conflux-dev-worker-1 --zone us-central1-a
gcloud compute ssh conflux-dev-worker-1 --zone us-central1-a --internal-ip -- 'uname -a'
gcloud compute instances stop  conflux-dev-worker-1 --zone us-central1-a
```

## Provider endpoints

| Route | Base URL | Protocol | Billing |
|---|---|---|---|
| Surplus Intelligence | `https://www.surplusintelligence.ai/api/inference/v1` | OpenAI-compatible | metered cash (budget) |
| NanoGPT | `https://nano-gpt.com/api/v1` | OpenAI-compatible | subscription, 60M input tok/week; $0 paid balance |
| Kimi Code | `https://api.kimi.com/coding/v1` | OpenAI-compatible | Kimi Code plan (coding-tool use) |
| GLM Coding Plan | `https://api.z.ai/api/coding/paas/v4` | OpenAI-compatible | Lite plan (coding-tool use) |

- **Jev is a decisions model, not chat.** Use `POST https://api.surplusintelligence.ai/v1/decisions`, JEV format only:
  `{"model","state","questions":{"<id>":{"type":"choice"|"score",...}}}`. Chat/completions return 503
  `no_healthy_sellers`, `noul` returns 502, and the OpenAI-format `questions` array returns 400. The response carries
  per-option `probabilities` and token usage, but no billed cost.
- **Surplus chat returns no logprobs.** `deepseek-v4-pro` rejects the parameter with 400. Flash and the other models accept it and return
  nothing, even though the catalogue lists `logprobs`.
- Surplus chat usage reports the charge as `buyer_cost_micro` (micro-USD). Jev decisions carry no cost field.
- **Accounting source (authoritative):** the Surplus buyer API on `https://api.surplusintelligence.ai`, with the same key.
  - `GET /v1/buyer/usage/export?format=csv&from=YYYY-MM-DD&to=YYYY-MM-DD` returns a 302 to a pre-signed URL. Follow it
    **without** the Authorization header. The CSV columns are `request_id, created_at, model, input_tokens,
    output_tokens, buyer_cost_usd, direct_cost_usd, settlement_status, …`.
  - `GET /v1/buyer/me` gives `credit_balance_usdc` (micro-USD) and `model_breakdown`.
  - Jev-1.14 bills about $0.000006 per decision.
  - The inference host has no balance endpoint.
- Surplus `/models` **and chat completions** need `Accept-Encoding: identity`: the compressed body breaks httpx
  (`DecodingError`), and those requests are still billed.
- The export's `request_id` (a ULID) is not the chat response `id` (`gen-…`). Match on model, token counts and time
  (`conflux.core.reconcile`).
- Quota endpoints:
  - NanoGPT: `POST /api/check-balance` and `GET /api/subscription/v1/usage`.
  - Kimi Code: `GET /coding/v1/usages`.
  - GLM: `GET https://api.z.ai/api/monitor/usage/quota/limit`.
  - The Kimi and GLM endpoints are undocumented.
- Executed capability matrix: `docs/rebuild/PROVIDERS.md`.

Catalogue snapshot 2026-10-26: Surplus lists 489 models incl. `deepseek-v4-pro`, `deepseek-v4-flash`,
`deepseek-v4.1-flash`, `jev-1.13`, `jev-1.14`, `kimi-k3`, `kimi-k3.1-pro`, `glm-5.3`; Kimi Code lists
`kimi-for-coding`, `k3`, `k3.1-pro`; NanoGPT serves `deepseek/deepseek-v4-pro`, `z-ai/glm-5.3`,
`moonshotai/kimi-k2.6` (no logprobs). These are starting points for work item B, not verified capability.
