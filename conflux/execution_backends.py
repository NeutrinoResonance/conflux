"""Fail-closed execution-backend boundaries.

Agent-selected workloads must never select where they run.  An operator binds
one backend adapter to an immutable lock, then exposes backend-neutral
operations to the agent.  The lock verifies the adapter and target on every
operation; swapping to a local process, another VM, or a future Docker target
requires rebuilding the trusted controller configuration.

The controller is still allowed to run its transport (for example ``gcloud
compute ssh``).  The boundary governs where the *agent workload* is spawned.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable


class ExecutionBoundaryError(RuntimeError):
    """A workload attempted to escape its operator-pinned backend boundary."""


@dataclass(frozen=True)
class ExecutionBackendLock:
    """Immutable operator authority for one backend and one target.

    ``target`` is a public, stable descriptor (never credentials).  Its digest
    is persisted with jobs so recovery cannot silently attach a job to a
    different machine or container.
    """

    backend: str
    target: Mapping[str, str]

    def __post_init__(self) -> None:
        backend = self.backend.strip() if isinstance(self.backend, str) else ""
        if not backend or backend in {"auto", "local", "off"}:
            raise ExecutionBoundaryError(
                "the execution lock must name a non-local concrete backend"
            )
        clean: dict[str, str] = {}
        for key, value in self.target.items():
            if not isinstance(key, str) or not key or not isinstance(value, str) or not value:
                raise ExecutionBoundaryError("execution-lock target fields must be strings")
            clean[key] = value
        if not clean:
            raise ExecutionBoundaryError("the execution lock requires a target descriptor")
        object.__setattr__(self, "backend", backend)
        object.__setattr__(self, "target", clean)

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {"backend": self.backend, "target": dict(sorted(self.target.items()))},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def resolve(self, requested: str | None, *, allow_off: bool = True) -> str:
        """Resolve an optional human/controller preference under this lock."""
        if requested in (None, "", "auto"):
            return self.backend
        if requested == "off" and allow_off:
            return "off"
        if requested != self.backend:
            raise ExecutionBoundaryError(
                f"execution backend is locked to {self.backend!r}; "
                f"refusing {requested!r}"
            )
        return self.backend

    def assert_adapter(self, adapter: "DurableJobBackend") -> None:
        if adapter.backend_name != self.backend:
            raise ExecutionBoundaryError(
                f"adapter {adapter.backend_name!r} does not match the "
                f"locked backend {self.backend!r}"
            )
        actual = {str(k): str(v) for k, v in adapter.target_descriptor.items()}
        if actual != dict(self.target):
            raise ExecutionBoundaryError(
                "backend adapter target does not match the immutable execution lock"
            )

    def public_descriptor(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "target": dict(self.target),
            "fingerprint": self.fingerprint,
            "locked": True,
            "agent_selectable": False,
            "local_workload_spawn": False,
        }


@runtime_checkable
class DurableJobBackend(Protocol):
    """Backend-neutral durable process contract.

    A Docker, Kubernetes, SSH, or other implementation can satisfy this
    protocol.  None of these methods receives a backend or target selector.
    """

    backend_name: str

    @property
    def target_descriptor(self) -> Mapping[str, str]: ...

    def start(self, command: str, *, cwd: str, timeout_s: int,
              label: str, context: Mapping[str, str]) -> Mapping[str, Any]: ...

    def watch(self, job_id: str, *, stdout_cursor: int, stderr_cursor: int,
              wait_seconds: int, max_bytes: int) -> Mapping[str, Any]: ...

    def inspect(self, job_id: str) -> Mapping[str, Any]: ...

    def signal(self, job_id: str, *, signal_name: str) -> Mapping[str, Any]: ...

    def collect(self, job_id: str, *, stdout_cursor: int, stderr_cursor: int,
                max_bytes: int) -> Mapping[str, Any]: ...


class LockedJobExecutor:
    """The only dispatch surface presented to backend-neutral job tools."""

    def __init__(self, boundary: ExecutionBackendLock,
                 adapter: DurableJobBackend) -> None:
        boundary.assert_adapter(adapter)
        self.boundary = boundary
        self.adapter = adapter

    def execute(self, operation: str, arguments: Mapping[str, Any], *,
                context: Mapping[str, str] | None = None) -> Mapping[str, Any]:
        # Re-check on every invocation.  This catches a mutable or incorrectly
        # reused adapter before the agent workload can be started or signaled.
        self.boundary.assert_adapter(self.adapter)
        args = dict(arguments)
        if "backend" in args or "target" in args:
            raise ExecutionBoundaryError(
                "agent job operations may not select a backend or target"
            )
        if operation == "start":
            return self.adapter.start(
                args["command"],
                cwd=args.get("cwd", "/tmp/conflux-agent"),
                timeout_s=args.get("timeout_s", 3600),
                label=args.get("label", "background job"),
                context=context or {},
            )
        if operation == "watch":
            return self.adapter.watch(
                args["job_id"],
                stdout_cursor=args.get("stdout_cursor", 0),
                stderr_cursor=args.get("stderr_cursor", 0),
                wait_seconds=args.get("wait_seconds", 30),
                max_bytes=args.get("max_bytes", 32768),
            )
        if operation == "inspect":
            return self.adapter.inspect(args["job_id"])
        if operation == "signal":
            return self.adapter.signal(args["job_id"], signal_name=args["signal"])
        if operation == "collect":
            return self.adapter.collect(
                args["job_id"],
                stdout_cursor=args.get("stdout_cursor", 0),
                stderr_cursor=args.get("stderr_cursor", 0),
                max_bytes=args.get("max_bytes", 65536),
            )
        raise ExecutionBoundaryError(f"unknown durable-job operation {operation!r}")
