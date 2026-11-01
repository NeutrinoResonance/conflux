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

- One lab at a time (MISSION budgets table). `~/.config/devbox/lab.env` has `LAB_MAX=2`; C slice 39 ran two labs at
  once on an explicit operator note (2026-10-29, scheduling only; its GCE rows in LEDGER.md count both). Later runs keep
  to one lab unless MISSION is amended.
- `devbox-lab up|ssh|stop|delete|list <name>` → `conflux-dev-lab-<name>`, n2d-standard-8 (8 vCPU, 32 GB) from snapshot
  `conflux-optee-baseline-clean-20261021` (100 GB pd-balanced), no external IP, no service account, self-stops after 24 h.
  Cost: ≈ $0.338/h running (GCE list price, us-central1) + ≈ $0.014/h for the disk while it exists (stopped or not).
- GCE stockouts for n2d-standard-8 in us-central1-a can last ≥ 1 h (C slice 33: 21 failed starts). A failed
  `devbox-lab up` of a *new* lab leaves its boot disk behind: delete it (`gcloud compute disks delete
  conflux-dev-lab-<name> --zone us-central1-a`) before retrying, or every retry fails `already exists`.
- `--lead kimi-k3` (C slice 49) adds the lead: it reviews every 300 s without blocking the executor (`lead.jsonl` next to
  `trace.jsonl`). On a task with no checks, finish and the step cap go to a fresh lead's finish review, and DONE ends the run
  `unverified`/`finish_review_done`. Grade that outcome outside the run.
- With a lead, a running review that returns while no verify session is open opens one (C slice 56, `core.Lead.verify`;
  off with `--no-scratch`). Since C slice 59 the session runs on its own thread beside the review cadence: the reply is
  injected when its review returns, the delivery later as its own message; at most one session is open at a time.
  - The lead runs commands in a scratch: a private mount namespace held by `sleep infinity`, with an overlay of the live
    `/home`. Since C slice 64, the upper/work dirs and the private `/tmp` are on a sparse ext4 image
    (`/var/tmp/conflux-scratch/<id>/img`, root-owned). The image is loop-mounted only inside that namespace.
  - The scratch's `/tmp` is private and empty, and `~/.conflux-jobs` is hidden.
  - Writes outside `/home` and `/tmp` are **not** isolated.
  - Before slice 64, the upper dirs were visible to root-namespace commands. Slice 60's executor (steps 10–39) and slice
    61's (steps 13–48) read and copied a live session's upper dir, and slice 61's also wrote to it. Now root-namespace
    commands see an empty `m/` and an opaque `img`. Only a deliberate `nsenter` or loop-mount reaches the contents
    (`~/evidence/scratch-isolation-2026-11-01/RESULTS.md`).
  - The first scratch installs `/etc/sudoers.d/zz-conflux-nopty` (`!use_pty`, as in slice 55's demo).
  - Each scratch command is one lab job: about 13 s round trip even for `true`.
  - At task end, `Steering.close` kills every scratch namespace (`killall`); the kill never targets the root namespace.
- The core loop drives a lab with `python -m conflux.core run --lab <name> --workdir '~/optee-work' --lab-hours 4`:
  it runs `up`, waits for ssh, smokes, runs tasks in order, and always runs `stop`. Every command is a detached job in
  `~/.conflux-jobs/<id>/` on the lab (`cmd.sh`, `out`, `err`, `rc`), polled every 5 s over `gcloud compute ssh
  --internal-ip` with an ssh ControlMaster socket in `~/.ssh/cm-*`.
- Every command (model, checks, setup; local and lab) runs under `set -o pipefail`; results carry `pipestatus` (the
  last pipeline's per-stage exits) and `failed_cmds`, the count of failing simple commands outside conditions, from an `ERR` trap. Checks must not pipe a producer that may still be writing into an early-exiting reader (`| head`, `grep -q`):
  that is SIGPIPE 141, a false failure.
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
- Every task ends with the D1 self-audit (`audit` trace row, `audit_hits` on `task_end`/`summary.json`); recorded
  traces: `python -m conflux.core audit <trace.jsonl>...` (no key needed).
- **The snapshot holds the NetBSD project (goal b)**, owned by `darrenhidalgo` (lab user `dev` has passwordless sudo):
  `/home/darrenhidalgo/netbsd-src` (git `7f2c5e73f`, clean, has `sys/arch/arm/arm/smccc.{c,h}`, no optee driver);
  `/home/darrenhidalgo/netbsd-obj` (built GENERIC64 `netbsd`/`netbsd.img` from 2026-10-21, tooldirs
  `tooldir.Linux-6.1.0-50/51-cloud-amd64-x86_64`); `/home/darrenhidalgo/llmsuper-netbsd-run` (earlier NetBSD-only
  QEMU boot).
  - **Snapshot contamination** (operator, 2026-11-01): `netbsd-obj/sys/arch/evbarm/compile/GENERIC64/optee.{o,d,su}`
    is an earlier agent's compiled driver (2026-07-19; its source `sys/dev/optee/optee.c` is gone). Slice 60 mined it;
    slice 61 reconstructed its driver from the disassembly, so G4 provenance is affected for both.
  - **Since C slice 65, core removes it on every lab** (`core.LAB_CLEAN`, after setup and before the egress check;
    failure ends the run `clean_failed` with no model call). The clean job's script deletes itself, so the path list
    never reaches `~/.conflux-jobs`. The snapshot itself is unchanged: the controller identity cannot create snapshots
    (`testIamPermissions`: only `compute.snapshots.get`).
  - Slice 65's inventory found no other residue: those three files are the only `*optee*` names on the disk, and
    `optee.o` is GENERIC64's only object without a `.depend` target. The prebuilt kernels have no optee symbols. There
    are no shell histories, and the 07-19/10-21 rebuilds are stock. A stock `build.sh -u kernel=GENERIC64` passes after
    the clean (`~/evidence/snapshot-clean-2026-11-01/RESULTS.md`).
  - `llmsuper-netbsd-run/` (`arm64.img`, `qemu-command.txt`, logs) is the founder's NetBSD-only QEMU boot validation:
    stock NetBSD 10.1 + UEFI, no OP-TEE, no driver content. It is kept as environment.
  - Labs run kernel `6.1.0-54`, so plain `build.sh` finds no matching tooldir; pass `-T <existing tooldir>`.
- The c3 disk holds a built qemu_v8 tree in `~/optee-work/optee`. `make check-only CHECK_TESTS=xtest XTEST_ARGS=1001`
  boots it and passes in ≈ 54 s. The snapshot has no `expect`; the a4 check installs it.
  Since C slice 32 its in-tree TF-A build (`optee/trusted-firmware-a/build/qemu/release`) and `netbsd-optee/qemu_fw.bios`
  are pro's slice-26 no-flag NetBSD-as-BL33 build again (b2 check 2 fails; unchanged by slices 35–36; slice 36's
  pre-run backup of that state is `~/takeover-reset/` on c3),
  and `~/.conflux-jobs` also holds slice 35's jobs (older jobs archived in `~/evidence/self-diagnosis-demo-2026-10-28/`). TF-A does not track flag changes, and
  `make realclean` failed there: to rebuild with different flags, `rm -rf optee/trusted-firmware-a/build/qemu` first.
  Goal (a)'s Linux firmware must be rebuilt before an a-check there.

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
- Surplus chat usage reports the charge as `buyer_cost_micro` (micro-USD). Some replies omit it (C slice 36: 7/40; slice 43:
  25/2,625), and those requests are missing from the usage export and move no balance: they were not billed. Core keeps
  them `pending` and settles them from export rows (`core.Budget.resolve`, MISSION a58a30e); export rows appear 1-3 min after
  a call and their `created_at` is within 3 s of the reply.
- The Surplus key is shared with an unidentified caller (2026-10-29/30: kimi-k3.1-pro at 60% discount, 1,076 deepseek-v4-pro
  rows; not from this controller). Attribute spend by matching export rows to a run's own calls, never by window totals.
- `kimi-k3.1-pro` and `glm-5.3` do native tool calls on Surplus chat (C slice 36). Prompt caching makes K3.1-pro
  ≈ $0.004/step at 40k tokens. Jev decisions carry no cost field.
- **Accounting source (authoritative):** the Surplus buyer API on `https://api.surplusintelligence.ai`, with the same key.
  - `GET /v1/buyer/usage/export?format=csv&from=YYYY-MM-DD&to=YYYY-MM-DD` returns a 302 to a pre-signed URL. Follow it
    **without** the Authorization header. The CSV columns are `request_id, created_at, model, input_tokens,
    output_tokens, buyer_cost_usd, direct_cost_usd, settlement_status, …`.
  - `GET /v1/buyer/me` gives `credit_balance_usdc` (micro-USD) and `model_breakdown`.
  - Jev-1.14 bills about $0.000006 per decision: input-only metering (≈ $0.042/M input tokens, output free), ≈ 300
    input tokens minimum per request (`~/evidence/provider-probes-2026-10-27.md`). `gpt-6-luna` decisions returned 429.
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
- Current per-seller offers: `GET https://api.surplusintelligence.ai/v1/prices` (same key; `models[].providers[].pricing`
  in $/M tokens). List price ≠ billed: v4.1-flash lists above v4-flash, but it billed < 1 micro-USD per call on 2026-10-27.
  `deepseek-v4-pro` offers on 2026-10-27: $0.875–1.73/M in, $1.75–3.80/M out (billed ≈ $0.000046/call in C slice 18).
  Admission bounds are per executor in `core.CEILINGS` (v4.1-flash 4e-7 $/byte, 2.4e-6 $/out-token; pro 2e-6, 7.6e-6);
  a model without an entry is refused before any call. Pro's per-call bound is ≥ $0.062, so pro tasks need `max_usd` ≫ 0.15.
  The bound is traced, never settled as a cost. A reply without `buyer_cost_micro` (pro: 7/27 in C slice 20), or a lost
  reply, is `pending` at 0 until the usage export settles it (`export`, its `buyer_cost_usd`) or it is still absent 10 min
  later (`unbilled`, 0); rows already matched to calls billed in their reply are reserved (MISSION a58a30e).
- **Discount floor (MISSION 5ee7a8b):** every Surplus chat request sends `X-Min-Discount: 90` (`core.surplus_post`).
  `404 minimum_discount_not_met` = no seller at the floor now. Served at the floor 2026-10-29: `deepseek-v4-pro`,
  `glm-5.3`, `glm-5.3-flash`, `kimi-k3`; refused: `kimi-k3.1-pro`, `kimi-k3-fast-api`, `glm-5.3-flashx`, `minimax-m2.7`.
  HTTP 200 with `{"error": no_healthy_sellers}` and no choices also happens (C slice 39): core waits these out (≤ 4 h).
- **Lost replies (C slice 47):** a closed connection or a reply not complete within the request limit (whole body, not
  per read) takes `surplus_post`'s availability backoff. Earlier lost attempts, which may be billed, come back in the
  body's `conflux_lost` and are settled from the export. A 2026-10-30 "hang" with sockets in CLOSE-WAIT was a demo
  deadlock: no thread was reading those idle keep-alive connections.
- **Edge 403 (C slice 57):** Surplus's edge can return an nginx `403 Forbidden` HTML page (no JSON) for a request that
  succeeds when resent minutes later. `surplus_post` waits it out like an outage; a JSON 403 stays final. On 2026-10-31
  it came with a billing gap: no usage was recorded after 17:47:45Z, and replies after that carried no `buyer_cost_micro`.
- **Holds:** Surplus holds each in-flight request's worst case (max output × price) in `credit_balance_usdc`; see
  `GET /v1/payments/balance` (`fiat_available_usdc`, `fiat_held_usdc`). A ~$0.45 `fiat_held_usdc` persisted with nothing
  in flight on 2026-10-29, and on 2026-10-30 `fiat_held` grew $1.87 → $4.10 with no request of ours in flight while
  available + held stayed $30.71 (C slice 47): reconcile spend from the usage export, not from available + held.
- Output limits: `top_provider.max_completion_tokens` in `/models` (core `MAX_OUTPUT`). `reasoning_effort=low` is accepted
  by glm-5.3, glm-5.3-flash and kimi-k3; `low` cut GLM reviews from 17–20 min to ~2 min. Since 2026-10-29 08:49Z glm-5.3
  rejects `medium` with HTTP 400 `request_rejected` ("must be one of: 'low', 'high', 'max'"; C slice 40).
- kimi-k3 (low) replies without `buyer_cost_micro`:
  - as a lead without tools, 2/218 (C slice 40);
  - in a `run_shell` tool loop, 21/44 (C slice 45), none of them in the usage export (unbilled).
  - Any cap or admission, demos included, uses `core.Budget` with `billing=core.fetch_export`. It defers such replies at
    $0 and settles them from export rows. Bounds are never counted: slice 45's demo-local bound refused 10 draws at
    $0.32 against $0.000013 billed.
- Executed capability matrix: `docs/rebuild/PROVIDERS.md`.
- Measured model strengths/weaknesses with examples: `docs/rebuild/MODELS.md` (append new findings there).

Catalogue snapshot 2026-10-26: Surplus lists 489 models incl. `deepseek-v4-pro`, `deepseek-v4-flash`,
`deepseek-v4.1-flash`, `jev-1.13`, `jev-1.14`, `kimi-k3`, `kimi-k3.1-pro`, `glm-5.3`; Kimi Code lists
`kimi-for-coding`, `k3`, `k3.1-pro`; NanoGPT serves `deepseek/deepseek-v4-pro`, `z-ai/glm-5.3`,
`moonshotai/kimi-k2.6` (no logprobs). These are starting points for work item B, not verified capability.
