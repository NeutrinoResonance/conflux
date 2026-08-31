from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from conflux import sandbox
from conflux.durable_jobs import (
    JOB_TOOL_DEFINITIONS,
    DurableJobStore,
    GCEAuthorizedTarget,
    GCEJobBackend,
)
from conflux.execution_backends import (
    ExecutionBackendLock,
    ExecutionBoundaryError,
    LockedJobExecutor,
)
from conflux.flows import FlowRegistry, SQLiteFlowRuntime


TARGET = GCEAuthorizedTarget(
    "locked-test-vm", "project96-sar", "gce-operator@example.com",
    "us-central1-a",
)


class _QueuedRunner:
    def __init__(self, results: list[dict]):
        self.results = list(results)
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        result = self.results.pop(0)
        return subprocess.CompletedProcess(
            argv,
            result.pop("returncode", 0),
            (json.dumps(result) + "\n").encode(),
            b"",
        )


class _FakeAdapter:
    backend_name = "docker"
    target_descriptor = {"container": "locked-one"}

    def start(self, command, **kwargs):
        return {"ok": True, "command": command, **kwargs}

    def watch(self, job_id, **kwargs):
        return {"ok": True, "job_id": job_id, **kwargs}

    def inspect(self, job_id):
        return {"ok": True, "job_id": job_id}

    def signal(self, job_id, **kwargs):
        return {"ok": True, "job_id": job_id, **kwargs}

    def collect(self, job_id, **kwargs):
        return {"ok": True, "job_id": job_id, **kwargs}


class ExecutionBoundaryTests(unittest.TestCase):
    def test_lock_rejects_local_or_retargeted_execution(self) -> None:
        lock = ExecutionBackendLock("gce", TARGET.descriptor)
        self.assertEqual(lock.resolve(None), "gce")
        self.assertEqual(lock.resolve("off"), "off")
        with self.assertRaises(ExecutionBoundaryError):
            lock.resolve("local")
        with self.assertRaises(ExecutionBoundaryError):
            lock.assert_adapter(_FakeAdapter())

    def test_generic_executor_never_accepts_agent_backend_selector(self) -> None:
        lock = ExecutionBackendLock("docker", {"container": "locked-one"})
        executor = LockedJobExecutor(lock, _FakeAdapter())

        result = executor.execute(
            "start", {"command": "true", "label": "portable", "timeout_s": 5}
        )

        self.assertTrue(result["ok"])
        with self.assertRaises(ExecutionBoundaryError):
            executor.execute("start", {
                "command": "true", "label": "escape", "timeout_s": 5,
                "backend": "local",
            })

    def test_locked_sandbox_refuses_before_local_spawn(self) -> None:
        lock = ExecutionBackendLock("gce", {
            "mode": "ephemeral", "project": "p", "account": "a",
            "zone": "z", "machine_type": "e2-micro",
        })
        result = asyncio.run(sandbox.run("print('must not run')", "local", boundary=lock))
        self.assertFalse(result.ran)
        self.assertFalse(result.ok)
        self.assertIn("locked", result.note)

    def test_agent_tool_schemas_are_backend_neutral(self) -> None:
        self.assertEqual(len(JOB_TOOL_DEFINITIONS), 5)
        for tool in JOB_TOOL_DEFINITIONS:
            properties = tool["function"]["parameters"]["properties"]
            self.assertNotIn("backend", properties)
            self.assertNotIn("target", properties)


class DurableGCEJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "jobs.db"
        self.store = DurableJobStore(self.db)
        self.boundary = ExecutionBackendLock("gce", TARGET.descriptor)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def backend(self, runner, *, runtime=None):
        return GCEJobBackend(
            TARGET, self.store, boundary_fingerprint=self.boundary.fingerprint,
            runner=runner, job_id_factory=lambda: "job_0123456789abcdef01234567",
            flow_runtime=runtime,
        )

    def test_start_uses_only_fixed_gcloud_transport_and_persists_identity(self) -> None:
        runner = _QueuedRunner([{
            "ok": True, "state": "running", "job_id": "job_0123456789abcdef01234567",
            "pid": 901, "owned": True, "stdout_size": 0, "stderr_size": 0,
            "stdout_cursor": 0, "stderr_cursor": 0,
        }])
        backend = self.backend(runner)
        secret_command = "printf 'only on the remote VM\\n'; sleep 3"

        result = backend.start(
            secret_command, cwd="/tmp/conflux-agent", timeout_s=30,
            label="streaming proof", context={"session": "s", "task": "t"},
        )

        self.assertTrue(result["ok"])
        argv, kwargs = runner.calls[0]
        self.assertEqual(argv[:3], ["gcloud", "compute", "ssh"])
        self.assertEqual(argv[3], "locked-test-vm")
        self.assertNotIn(secret_command, argv[-1])
        self.assertFalse(kwargs["shell"])
        item = self.store.get(result["job_id"])
        self.assertEqual(item["state"], "running")
        self.assertEqual(item["backend"], "gce")
        self.assertEqual(item["target"], TARGET.descriptor)
        self.assertEqual(item["boundary_fingerprint"], self.boundary.fingerprint)

    def test_watch_advances_byte_cursors_without_duplicate_output(self) -> None:
        start = _QueuedRunner([{
            "ok": True, "state": "running", "job_id": "job_0123456789abcdef01234567",
            "pid": 901, "owned": True, "stdout_size": 0, "stderr_size": 0,
            "stdout_cursor": 0, "stderr_cursor": 0,
        }])
        backend = self.backend(start)
        job = backend.start("sleep 1", cwd="/tmp/conflux-agent", timeout_s=30,
                            label="cursor proof", context={})
        backend._runner = _QueuedRunner([{
            "ok": True, "state": "running", "job_id": job["job_id"],
            "pid": 901, "owned": True, "stdout": "step 1\n", "stderr": "",
            "stdout_size": 7, "stderr_size": 0, "stdout_cursor": 7,
            "stderr_cursor": 0, "changed": True, "more": False,
        }])

        watched = backend.watch(
            job["job_id"], stdout_cursor=0, stderr_cursor=0,
            wait_seconds=30, max_bytes=1024,
        )

        self.assertEqual(watched["stdout"], "step 1\n")
        self.assertEqual(watched["stdout_cursor"], 7)
        self.assertEqual(self.store.get(job["job_id"])["stdout_cursor"], 7)

        backend._runner = _QueuedRunner([{
            "ok": True, "state": "signaled", "job_id": job["job_id"],
            "pid": 901, "owned": True, "stdout_size": 12, "stderr_size": 0,
        }])
        signaled = backend.signal(job["job_id"], signal_name="interrupt")
        self.assertEqual(signaled["next"]["stdout_cursor"], 7)
        self.assertEqual(signaled["next"]["stderr_cursor"], 0)
        self.assertIn("not cursors", signaled["next"]["instruction"])

        with self.assertRaisesRegex(ExecutionBoundaryError, "rewind or skip"):
            backend.watch(
                job["job_id"], stdout_cursor=0, stderr_cursor=0,
                wait_seconds=1, max_bytes=1024,
            )
        with self.assertRaisesRegex(ExecutionBoundaryError, "stdout_cursor=7"):
            backend.collect(job["job_id"], stdout_cursor=12, stderr_cursor=0,
                            max_bytes=1024)

        backend._runner = _QueuedRunner([{
            "ok": True, "state": "completed", "job_id": job["job_id"],
            "pid": 901, "owned": False, "exit_code": 0,
            "stdout": "", "stderr": "", "stdout_size": 7, "stderr_size": 0,
            "stdout_cursor": 7, "stderr_cursor": 0, "more": False,
            "artifacts": [], "collected": True,
        }])
        backend.collect(job["job_id"], stdout_cursor=7, stderr_cursor=0,
                        max_bytes=1024)
        self.assertEqual(self.store.get(job["job_id"])["last_stdout"], "step 1\n")
        with self.assertRaisesRegex(ExecutionBoundaryError, "stdout_cursor=7"):
            backend.collect(job["job_id"], stdout_cursor=0, stderr_cursor=0,
                            max_bytes=1024)

    def test_restart_recovers_job_and_wrong_boundary_cannot_adopt_it(self) -> None:
        runner = _QueuedRunner([{
            "ok": True, "state": "running", "job_id": "job_0123456789abcdef01234567",
            "pid": 901, "owned": True, "stdout_size": 0, "stderr_size": 0,
            "stdout_cursor": 0, "stderr_cursor": 0,
        }])
        job = self.backend(runner).start(
            "sleep 60", cwd="/tmp/conflux-agent", timeout_s=90,
            label="restart proof", context={},
        )
        recovered = DurableJobStore(self.db)
        self.assertEqual(recovered.get(job["job_id"])["pid"], 901)
        wrong = GCEJobBackend(
            TARGET, recovered, boundary_fingerprint="0" * 64,
            runner=_QueuedRunner([]),
        )
        with self.assertRaises(ExecutionBoundaryError):
            wrong.inspect(job["job_id"])

    def test_job_operations_project_into_the_declared_graph(self) -> None:
        registry = FlowRegistry.load(Path(__file__).parents[1] / "agent_flows.yaml")
        runtime = SQLiteFlowRuntime(self.store.connection, registry)
        runner = _QueuedRunner([{
            "ok": True, "state": "running", "job_id": "job_0123456789abcdef01234567",
            "pid": 901, "owned": True, "stdout_size": 0, "stderr_size": 0,
            "stdout_cursor": 0, "stderr_cursor": 0,
        }])
        job = self.backend(runner, runtime=runtime).start(
            "sleep 1", cwd="/tmp/conflux-agent", timeout_s=30,
            label="graph proof", context={"session": "s", "task": "t"},
        )
        observed = runtime.inspect(job["job_id"])
        self.assertEqual(observed["flow_id"], "durable_locked_job")
        self.assertEqual(observed["current_node"], "durable_start")
        self.assertEqual(
            [e["node_id"] for e in observed["events"]],
            ["job_request", "execution_lock", "durable_start"],
        )


if __name__ == "__main__":
    unittest.main()
