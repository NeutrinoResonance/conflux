"""Deterministic durable-job backend parity probe (operator harness).

Drives one backend adapter — GCE or Docker — through the complete durable-job
protocol with a fixed data-wrangling workload, and emits a JSON envelope of
protocol-relevant observations. Running it against both adapters and diffing
the envelopes proves the backend-neutral contract with zero model tokens.

The workload is application-level: parse an order log, aggregate revenue per
day, write a summary CSV artifact plus its SHA-256, and stream progress lines
(so watch-cursor windows are exercised). A second job is started and then
terminated to exercise ownership-exact signaling and cursor persistence.

Usage (trusted operator only; backend/target are never agent arguments):
  python scripts/backend_parity_probe.py gce --vm V --project P --account A --zone Z
  python scripts/backend_parity_probe.py docker --container NAME
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conflux.durable_jobs import (  # noqa: E402
    DockerAuthorizedTarget,
    DockerJobBackend,
    DurableJobStore,
    GCEAuthorizedTarget,
    GCEJobBackend,
)
from conflux.execution_backends import ExecutionBackendLock  # noqa: E402

WORKLOAD = r"""
set -e
cd "$CONFLUX_ARTIFACT_DIR"
cat > orders.csv <<'CSV'
date,item,price,quantity
2026-07-20,widget,2.50,4
2026-07-20,gadget,10.00,3
2026-07-21,sprocket,1.25,8
2026-07-21,widget,2.50,2
2026-07-22,gadget,10.00,1
CSV
echo "phase=parse"
python3 - <<'PY'
import csv, hashlib
from collections import defaultdict
totals = defaultdict(float)
with open('orders.csv') as fh:
    for row in csv.DictReader(fh):
        totals[row['date']] += float(row['price']) * int(row['quantity'])
lines = ['date,revenue'] + [f'{d},{totals[d]:.2f}' for d in sorted(totals)]
body = '\n'.join(lines) + '\n'
open('daily_revenue.csv', 'w').write(body)
digest = hashlib.sha256(body.encode()).hexdigest()
open('daily_revenue.sha256', 'w').write(digest + '\n')
print('phase=aggregate rows=%d' % len(totals))
print('sha256=' + digest)
PY
sleep 3
echo "phase=done"
"""


def run_probe(backend, label_prefix: str) -> dict:
    report: dict = {"backend": backend.backend_name,
                    "target": dict(backend.target_descriptor)}

    start = backend.start(
        WORKLOAD, cwd="/tmp/conflux-agent", timeout_s=300,
        label=f"{label_prefix} parity workload",
        context={"session": "parity-probe", "task": "daily revenue summary"},
    )
    report["start_ok"] = bool(start.get("ok"))
    report["start_state"] = start.get("state")
    if not start.get("ok"):
        report["error"] = start.get("error")
        return report
    job_id = start["job_id"]
    so = se = 0
    stdout_all = ""
    watches = 0
    for _ in range(40):
        watch = backend.watch(job_id, stdout_cursor=so, stderr_cursor=se,
                              wait_seconds=10, max_bytes=32768)
        if not watch.get("ok"):
            report["error"] = watch.get("error")
            return report
        watches += 1
        assert watch["stdout_cursor"] >= so, "cursor went backwards"
        so, se = watch["stdout_cursor"], watch["stderr_cursor"]
        stdout_all += watch.get("stdout", "")
        if watch.get("state") in ("completed", "failed", "lost"):
            break
    collect = backend.collect(job_id, stdout_cursor=so, stderr_cursor=se,
                              max_bytes=65536)
    stdout_all += collect.get("stdout", "")
    sha = next((line.split("=", 1)[1] for line in stdout_all.splitlines()
                if line.startswith("sha256=")), None)
    report.update({
        "job_id_shape_ok": job_id.startswith("job_") and len(job_id) == 28,
        "watches": watches,
        "final_state": collect.get("state"),
        "exit_code": collect.get("exit_code"),
        "stdout_phases": [line for line in stdout_all.splitlines()
                          if line.startswith("phase=")],
        "workload_sha256": sha,
        "artifacts": sorted(a["path"] for a in collect.get("artifacts", [])),
        "collected": bool(collect.get("collected")),
        "cursors_final": [collect.get("stdout_cursor"),
                          collect.get("stderr_cursor")],
    })

    # Second job: exercise ownership-exact cancellation semantics.
    second = backend.start(
        "echo cancel-me; sleep 120",
        cwd="/tmp/conflux-agent", timeout_s=300,
        label=f"{label_prefix} cancellation probe",
        context={"session": "parity-probe", "task": "cancellation"},
    )
    if second.get("ok"):
        sig_job = second["job_id"]
        time.sleep(2)
        signal = backend.signal(sig_job, signal_name="terminate")
        report["signal_ok"] = bool(signal.get("ok"))
        report["signal_state"] = signal.get("state")
        report["signal_repeats_cursors"] = (
            signal.get("next", {}).get("stdout_cursor") == 0
            and signal.get("next", {}).get("stderr_cursor") == 0
        )
        final = None
        fso = fse = 0
        for _ in range(20):
            final = backend.watch(sig_job, stdout_cursor=fso,
                                  stderr_cursor=fse, wait_seconds=5,
                                  max_bytes=4096)
            if not final.get("ok"):
                break
            fso, fse = final["stdout_cursor"], final["stderr_cursor"]
            if final.get("state") in ("completed", "failed", "lost"):
                break
        report["cancelled_final_state"] = (final or {}).get("state")
        report["cancelled_exit_code"] = (final or {}).get("exit_code")
    else:
        report["signal_ok"] = False
        report["error"] = second.get("error")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", choices=("gce", "docker"))
    parser.add_argument("--vm")
    parser.add_argument("--project")
    parser.add_argument("--account")
    parser.add_argument("--zone")
    parser.add_argument("--container")
    parser.add_argument("--db", default="")
    args = parser.parse_args()

    db = args.db or str(Path(tempfile.mkdtemp()) / "parity.db")
    store = DurableJobStore(db)
    if args.backend == "gce":
        for name in ("vm", "project", "account", "zone"):
            if not getattr(args, name):
                parser.error(f"--{name} required for gce")
        target = GCEAuthorizedTarget(args.vm, args.project, args.account,
                                     args.zone)
        lock = ExecutionBackendLock("gce", target.descriptor)
        backend = GCEJobBackend(target, store,
                                boundary_fingerprint=lock.fingerprint)
    else:
        if not args.container:
            parser.error("--container required for docker")
        target = DockerAuthorizedTarget(args.container)
        lock = ExecutionBackendLock("docker", target.descriptor)
        backend = DockerJobBackend(target, store,
                                   boundary_fingerprint=lock.fingerprint)

    report = run_probe(backend, args.backend)
    report["job_ledger_db"] = db
    print(json.dumps(report, indent=2, sort_keys=True))
    ok = (report.get("start_ok") and report.get("final_state") == "completed"
          and report.get("exit_code") == 0 and report.get("signal_ok"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
