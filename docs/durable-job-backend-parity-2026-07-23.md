# Field report — durable-job backend parity, GCE vs Docker (2026-07-23)

**Status: accepted.** The Docker adapter reproduced the GCE adapter's
durable-job protocol behavior exactly on an application-level workload, with
zero model tokens spent.

Companion records:

- Probe harness: [`scripts/backend_parity_probe.py`](../scripts/backend_parity_probe.py)
- Adapter under test: `DockerJobBackend` in `llm_super/durable_jobs.py`
- Contract being proven: README "Execution power" — "Docker or another
  backend can implement the same internal protocol without adding
  agent-visible backend/target arguments."

## 1. What was tested

The backend-neutral durable-job contract (start / watch / inspect / signal /
collect) through two adapters that share every remote program, cursor rule,
and ownership check, and differ only in transport argv:

| Leg | Controller | Transport | Workload location |
|---|---|---|---|
| gce | local workstation | `gcloud compute ssh llmsuper-session-20260723` | session VM (project96-sar, us-central1-a) |
| docker | session VM | `docker exec llm-super-agent /bin/sh -c …` | `python:3.11-slim` container on the same VM |

The workload is deliberately application-level (per the test-task brief: no
OS/disk/database-under-load exercises): write an orders CSV, aggregate
revenue per day with `csv.DictReader`, write `daily_revenue.csv` plus its
SHA-256 as artifacts, and stream `phase=` progress lines. A second job
(`echo cancel-me; sleep 120`) exercises ownership-exact cancellation.

## 2. Results

Both legs exited 0 from the probe. Protocol-relevant observations were
identical on every field that must match:

| Observation | gce | docker |
|---|---|---|
| start state | running | running |
| job id shape `job_<24 hex>` | ✓ | ✓ |
| final state / exit code | completed / 0 | completed / 0 |
| stdout phases | parse, aggregate rows=3, done | identical |
| workload SHA-256 | `4a1138df89341240c125ae378f09e6416f641278bd1e11a9b200a438f92a1655` | identical |
| artifact manifest | daily_revenue.csv, daily_revenue.sha256, orders.csv | identical |
| final cursors (stdout, stderr) | 118, 0 | 118, 0 |
| collected flag | true | true |
| signal state | signaled | signaled |
| signal repeats persisted cursors | true | true |
| cancelled final state / exit | failed / 143 (SIGTERM) | failed / 143 |

Differences observed, both expected and non-semantic:

- `watches` until completion: gce 1, docker 4 — the `gcloud compute ssh`
  round trip (~10 s) covers the 3 s workload sleep in one watch window;
  `docker exec` returns in milliseconds, so the same 10 s watch windows saw
  the phases arrive incrementally. Cursors advanced monotonically in both.
- `target` descriptor: `{vm, project, account, zone}` vs `{container}` —
  the operator-locked identity, by design never an agent argument.

## 3. What this exercised in the framework

- The `_transport_argv` seam introduced for the Docker adapter: every remote
  program (start wrapper with isolated process groups and heartbeats,
  status, cursor-windowed watch, ownership-exact `killpg`, bounded collect
  with artifact walk) ran unmodified inside a container.
- Cursor discipline across adapters: watch after signal resumed from the
  exact persisted cursors; no rewind, no duplicate output.
- Exit-code normalization (`128 + signal` → 143) matches across `/usr/bin/
  timeout` + `setsid` semantics on a VM and in a `python:3.11-slim`
  container (GNU coreutils 9.7 in both).
- The zero-cost local-container test path: the docker leg runs with no
  cloud round trips at all once the container exists — suitable for CI.

## 4. Deficiencies and notes

- The container must provide `python3` and GNU coreutils (`timeout`);
  `python:3.11-slim` does. This is now documented on `DockerJobBackend`.
- `docker exec` runs as the container's default user (root in the stock
  image). The GCE leg runs as the ssh user. Parity of the *protocol* is
  proven; production Docker deployments should run a non-root container
  user. Recorded as an operator note, not a protocol gap.
- The cancelled job reports `failed` (exit 143) rather than a distinct
  `cancelled` state in both adapters — consistent, and the signal event
  trail in the job ledger disambiguates operator cancellation from a crash.
  A first-class `cancelled` state remains possible future work.

## 5. Reproduction

```bash
# once: docker run -d --name llm-super-agent python:3.11-slim sleep infinity
#       docker exec llm-super-agent mkdir -p -m 700 /tmp/llm-super-agent
python scripts/backend_parity_probe.py docker --container llm-super-agent
python scripts/backend_parity_probe.py gce \
  --vm <vm> --project <project> --account <account> --zone <zone>
```

Exit 0 requires: start ok, final state completed, exit code 0, and
successful ownership-exact signaling. Compare the two JSON envelopes; every
field except `target`, `watches`, and `job_ledger_db` must match.
