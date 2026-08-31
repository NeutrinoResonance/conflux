"""Docker durable-job adapter: same protocol, different transport only."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from conflux.durable_jobs import (
    DockerAuthorizedTarget,
    DockerJobBackend,
    DurableJobStore,
    GCEAuthorizedTarget,
    GCEJobBackend,
    docker_exec_argv,
)
from conflux.execution_backends import (
    ExecutionBackendLock,
    ExecutionBoundaryError,
    LockedJobExecutor,
)

TARGET = DockerAuthorizedTarget("conflux-agent")


class _QueuedRunner:
    def __init__(self, results: list[dict]):
        self.results = list(results)
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        result = self.results.pop(0)
        return subprocess.CompletedProcess(
            argv, result.pop("returncode", 0),
            (json.dumps(result) + "\n").encode(), b"",
        )


def _backend(tmp: str, runner: _QueuedRunner) -> DockerJobBackend:
    store = DurableJobStore(Path(tmp) / "jobs.db")
    lock = ExecutionBackendLock("docker", TARGET.descriptor)
    return DockerJobBackend(
        TARGET, store, boundary_fingerprint=lock.fingerprint, runner=runner,
        job_id_factory=lambda: "job_" + "0" * 24,
    )


class DockerTransportTests(unittest.TestCase):
    def test_argv_is_fixed_shape_docker_exec(self) -> None:
        argv = docker_exec_argv(TARGET, "echo hi")
        self.assertEqual(argv[:4], ["docker", "exec", "conflux-agent",
                                    "/bin/sh"])
        self.assertEqual(argv[4], "-c")
        self.assertIn("echo hi", argv[5])

    def test_target_selector_is_validated(self) -> None:
        with self.assertRaises(ExecutionBoundaryError):
            DockerAuthorizedTarget("--privileged")
        with self.assertRaises(ExecutionBoundaryError):
            DockerAuthorizedTarget("name with spaces")

    def test_command_envelope_bounds(self) -> None:
        with self.assertRaises(ExecutionBoundaryError):
            docker_exec_argv(TARGET, "")
        with self.assertRaises(ExecutionBoundaryError):
            docker_exec_argv(TARGET, "x" * 200_000)


class DockerBackendProtocolTests(unittest.TestCase):
    def test_start_records_docker_backend_and_uses_docker_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = _QueuedRunner([{
                "ok": True, "state": "running", "job_id": "job_" + "0" * 24,
                "pid": 41, "owned": True, "stdout_size": 0, "stderr_size": 0,
                "stdout_cursor": 0, "stderr_cursor": 0,
            }])
            backend = _backend(tmp, runner)
            result = backend.start(
                "sleep 5", cwd="/tmp/conflux-agent", timeout_s=60,
                label="docker smoke", context={"session": "s", "task": "t"},
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["execution"]["backend"], "docker")
            self.assertEqual(result["execution"]["target"],
                             {"container": "conflux-agent"})
            self.assertEqual(runner.calls[0][:2], ["docker", "exec"])
            stored = backend.store.get("job_" + "0" * 24)
            self.assertEqual(stored["backend"], "docker")
            self.assertEqual(stored["target"], {"container": "conflux-agent"})

    def test_watch_enforces_exact_persisted_cursors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = _QueuedRunner([
                {"ok": True, "state": "running", "job_id": "job_" + "0" * 24,
                 "pid": 41, "owned": True, "stdout_size": 0, "stderr_size": 0,
                 "stdout_cursor": 0, "stderr_cursor": 0},
            ])
            backend = _backend(tmp, runner)
            backend.start("sleep 5", cwd="/tmp/conflux-agent", timeout_s=60,
                          label="cursors", context={})
            with self.assertRaises(ExecutionBoundaryError):
                backend.watch("job_" + "0" * 24, stdout_cursor=5,
                              stderr_cursor=0, wait_seconds=1, max_bytes=1024)

    def test_gce_job_is_not_reachable_from_docker_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DurableJobStore(Path(tmp) / "jobs.db")
            gce_target = GCEAuthorizedTarget("vm", "project", "acct@x.com",
                                             "us-central1-a")
            gce_lock = ExecutionBackendLock("gce", gce_target.descriptor)
            gce_runner = _QueuedRunner([{
                "ok": True, "state": "running", "job_id": "job_" + "1" * 24,
                "pid": 7, "owned": True, "stdout_size": 0, "stderr_size": 0,
                "stdout_cursor": 0, "stderr_cursor": 0,
            }])
            gce = GCEJobBackend(
                gce_target, store, boundary_fingerprint=gce_lock.fingerprint,
                runner=gce_runner, job_id_factory=lambda: "job_" + "1" * 24)
            gce.start("sleep 1", cwd="/tmp/conflux-agent", timeout_s=60,
                      label="gce job", context={})
            docker_lock = ExecutionBackendLock("docker", TARGET.descriptor)
            docker = DockerJobBackend(
                TARGET, store, boundary_fingerprint=docker_lock.fingerprint,
                runner=_QueuedRunner([]))
            with self.assertRaises(ExecutionBoundaryError):
                docker.inspect("job_" + "1" * 24)

    def test_lock_accepts_matching_docker_adapter_and_rejects_others(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backend = _backend(tmp, _QueuedRunner([]))
            lock = ExecutionBackendLock("docker", TARGET.descriptor)
            lock.assert_adapter(backend)  # must not raise
            LockedJobExecutor(lock, backend)
            gce_lock = ExecutionBackendLock(
                "gce", {"vm": "v", "project": "p", "account": "a",
                        "zone": "z"})
            with self.assertRaises(ExecutionBoundaryError):
                gce_lock.assert_adapter(backend)


if __name__ == "__main__":
    unittest.main()
