# Field report — supervised pipeline through the new capture stack (2026-07-23)

**Status: accepted.** Two live supervised turns and a zero-token browser
pass exercised, end to end, every feature landed today: explicit
conversation/endeavor identity, write-time durable entities, capture-time
step summaries, the SSE live channel, streamed supervisor status lines, the
GCE-locked sandbox, the union answer strategy, admin-auth defaults, and the
shared design tokens.

Companion records (all under `artifacts/field-test-2026-07-23/` and
`artifacts/ui-tokens-2026-07-23/`):

- `turn1.sse`, `turn2.sse` — exact SSE streams as received by the client
- `startup-warning.txt` — the exact unauthenticated-control-plane warning
- `parity-gce.json`, `parity-docker.json` — the backend-parity envelopes
  ([separate report](./durable-job-backend-parity-2026-07-23.md))
- Screenshots: Live dark + forced-light, History endeavor detail,
  Workspace, Agent Graphs

Setup: `llm-super serve` on :8056 in a scratch directory with a fresh
`traces.db` (the proxy is control plane and runs on the workstation;
all generated code executes on GCE per the operator lock).

## 1. Turn 1 — coding with doctests (single strategy)

Conversation `field-durparse-1`, endeavor `field-test-2026-07-23`, both
supplied as validated headers (`X-LLM-Super-Conversation` /
`X-LLM-Super-Endeavor`). The explicit-ID path also skipped the
new-conversation gate, as designed.

Task: implement `parse_duration(text)` (h/m/s components, ordered,
non-repeating, `ValueError("malformed duration")`) with doctests.

The client saw live supervisor progress as SSE comments — the whole
"silence instead of progress" gap is closed:

```text
: [llm-super] contract extracted
: [llm-super] executing on deepseek-v4-pro
: [llm-super] running generated code in the sandbox
: [llm-super] verified 1.00 by qwen-3.7-plus
```

Database facts (`events` for `field-durparse-1`): `contract`
(gemma-4-31b) → `execute` (deepseek-v4-pro) → `execute_code` with
`backend=gce, ok=1, exit_code=0` — the doctests ran on an ephemeral Spot
e2-micro in project96-sar, which was deleted afterwards (instance listing
showed no residue beyond the session VM) → `verify` (qwen-3.7-plus,
cross-family) → `turn_end`. Trailer: `executor=deepseek-v4-pro attempts=1
verifier=qwen-3.7-plus score=1.00 cost=$0.0065`. The returned
implementation is correct (regex with ordered optional groups,
at-least-one-component check, five doctests).

Write-time capture (no derivation involved): `steps` row phase=finish,
status=succeeded, tokens 3,531/6,035, cost $0.0065; `runs` row succeeded
with the server instance id; deterministic `step_summaries` row produced on
the exchange write path.

## 2. Turn 2 — union ensemble on genuine-divergence enumeration

Conversation `field-edgecases-2`, same explicit endeavor. `!strategy
union 2` (an in-band control command — itself captured as a durable
`control` milestone step), then: enumerate the malformed/tricky input
categories a strict RFC-3339 parser must handle.

Status stream showed the whole ensemble shape:

```text
: [llm-super] contract extracted
: [llm-super] launching candidates
: [llm-super] executing on glm-5.2
: [llm-super] candidate from glm-5.2
: [llm-super] executing on deepseek-v4-pro
: [llm-super] candidate from deepseek-v4-pro
: [llm-super] synthesizing unit results
```

Events: `ensemble_start` → two cross-family candidates, each verified →
`synthesis` → merged answer verified 1.00 by qwen-3.7-plus →
`ensemble_winner union(deepseek-v4-pro)`. The merge returned **47 distinct
categories** — the candidates genuinely differed (leap seconds, `-00:00`
unknown-offset semantics, lowercase `t`/`z`, minute-60 offsets, control
characters, truncation classes all present) — at `attempts=3
cost=$0.0488`, ~3× the single-strategy turn, as the strategy's own help
text predicts.

## 3. Grouping: one endeavor, two conversations, at write time

`endeavor_members` after the two turns:

```text
field-durparse-1   initial       explicit_api
field-edgecases-2  continuation  explicit_api
```

`steps` for the endeavor: two workload steps (succeeded, $0.0065 and
$0.0488) plus the `!strategy` control milestone. The History UI opened
directly to this endeavor showing "2 conversations · 2 logical steps",
duration, tokens (9,870), cost ($0.006577 at screenshot time), and the
prose step summaries — with `capture: {durable: true}` confirming rows came
from the ledger, not from derived grouping. This is the forensic report's
§7 gap ("no aliases, checkpoints, or edit records that can explicitly join
these sessions") closed by explicit ingress identity.

## 4. Live channel and dashboards (zero-token browser pass)

Chrome DevTools MCP against the running server, all four surfaces:

- console: zero errors and zero warnings on `/`, `/history`, `/graphs`,
  `/workspace`;
- the Live header's SSE dot reported connected (`livedot on`), and an idle
  40-second window transferred **8 requests versus 160** under the old
  2-second eight-endpoint refetch design (20×; active turns paint
  sub-second via the push channel);
- design tokens resolved identically everywhere (`--ds-page #111310` under
  OS dark; legacy aliases like `--grid`/`--panel` resolve through the
  shared tokens); forcing `data-theme="light"`/`"dark"` on the Live page
  flipped `--ds-page` between `#f6f6f2` and `#111310`; the Workspace pins
  the dark token set by design;
- the auth-disabled startup warning printed verbatim
  (`startup-warning.txt`); the earlier VM smoke validated the enabled path
  (401 without token, 200 with bearer, cookie via `?token=`).

## 5. Deficiencies observed (open)

1. A blank-titled explicit endeavor displays as its first conversation's
   title ("Conversation field-durparse-1") with status `unknown` until
   named/statused; a `PATCH /admin/workspace/endeavors/{id}` rename fixes
   it, but the History header could prefer the explicit endeavor id when
   the title is empty.
2. The union merge's `ensemble_winner` label (`union(deepseek-v4-pro)`)
   names the synthesizer, not the contributing set; the candidate list is
   in the events, but the trailer could carry both families.
3. `verified 1.00` in both turns is consistent with the calibration
   finding (good work saturates high); the discrimination guard now exists
   (`llm-super calibrate`) but per-turn score variance remains worth a
   dashboard strip.

## 6. Reproduction

```bash
.venv/bin/llm-super serve --port 8056   # in a scratch dir with models.yaml
curl -sN localhost:8056/v1/chat/completions \
  -H 'X-LLM-Super-Conversation: field-durparse-1' \
  -H 'X-LLM-Super-Endeavor: field-test-2026-07-23' \
  -d '{"model":"super","stream":true,"messages":[…]}'
# then: sqlite3 traces.db 'SELECT … FROM steps/runs/endeavor_members …'
```
