# Preserved GCE disks and stopped instances

Ledger of `llmsuper-*` instances whose boot disks were deliberately kept for
inspection. All in project `project96-sar`, zone `us-central1-a`. A stopped
instance bills for its disk only (~$0.04/GB-month standard PD); restart with
`gcloud compute instances start <name> --zone=us-central1-a`, connect with
`gcloud compute ssh <name> --zone=us-central1-a`.

## llmsuper-session-20260723 — 2026-07-23 session VM (STOPPED, disk kept)

- **What it was:** the single session VM for the 2026-07-23 feature/test
  session (admin auth, SSE live channel, durable endeavor ledger, explicit
  ingress IDs, summary job ledger, Docker job adapter, verifier
  calibration, streamed status lines, design tokens). e2-small, debian-12,
  25 GB disk, created with `--no-boot-disk-auto-delete`.
- **On the disk:**
  - `~/llm-super/` — working tree replica used for the iterative test loop
    (all 276 tests green at session end);
  - `~/llm-super-final/` — pristine extract of the final committed HEAD
    with its own venv, where the final `unittest discover` run passed
    276/276;
  - `~/parity-docker.json` — Docker leg of the durable-job parity probe;
  - Docker with the `llm-super-agent` container (`python:3.11-slim`) and
    `/tmp/llm-super-agent` inside it, used for the Docker-adapter parity
    field test (workloads under `/tmp/llm-super-agent/.jobs/` in the
    container filesystem);
  - `~/server.log`, `~/server2.log`, `~/sse.out`, `~/smoke.sh` — the
    admin-auth / SSE live smoke evidence.
- **Reports referencing it:**
  [durable-job-backend-parity-2026-07-23](./durable-job-backend-parity-2026-07-23.md),
  [field-test-supervised-pipeline-2026-07-23](./field-test-supervised-pipeline-2026-07-23.md).

## llmsuper-appsafe-audit — pre-existing stray (STOPPED 2026-07-23, disk kept)

- Found RUNNING at session start; created 2026-07-18, e2-standard-2, no
  reference in this repository's docs or artifacts (it does not belong to
  this session). Stopped — not deleted — on 2026-07-23 to end ~$0.067/h of
  idle burn while preserving whatever its owner left on the disk. If it
  belongs to abandoned work, delete it after inspection.

## llmsuper-netbsd-arm64 — pre-existing (TERMINATED, disk kept)

- The NetBSD ARM64 endeavor worker (n2-standard-8), already stopped before
  this session; its retained disk is part of that endeavor's documented
  evidence (see the 2026-07-18 NetBSD reports). Left untouched.
