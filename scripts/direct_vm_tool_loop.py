#!/usr/bin/env python3
"""Non-streaming conflux client with a locked remote execution backend.

Short commands and durable job operations share one immutable GCE backend
lock.  The Google Cloud identity and target are client inputs and are never
copied from model output.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import math
import os
import posixpath
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from conflux.durable_jobs import (
    COLLECT_JOB_TOOL,
    INSPECT_JOB_TOOL,
    JOB_TOOL_DEFINITIONS,
    JOB_TOOL_OPERATIONS,
    SIGNAL_JOB_TOOL,
    START_JOB_TOOL,
    WATCH_JOB_TOOL,
    DockerAuthorizedTarget,
    DockerJobBackend,
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


TOOL_NAME = "run_on_authorized_gce_vm"
TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Run one shell command on the pre-authorized GCE VM. The client fixes "
            "the VM, project, account, and zone; they are not tool arguments."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute on the authorized VM.",
                }
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}
CONTAINER_TOOL_NAME = "run_in_locked_container"
CONTAINER_TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": CONTAINER_TOOL_NAME,
        "description": (
            "Run one shell command inside the operator-pinned container on the "
            "pre-authorized GCE VM. The client fixes the VM, container, and working "
            "directory; none are tool arguments."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute inside the locked container.",
                }
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}
CONTAINER_WRITE_TOOL_NAME = "write_file_in_locked_container"
CONTAINER_WRITE_TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": CONTAINER_WRITE_TOOL_NAME,
        "description": (
            "Atomically replace one UTF-8 file inside the operator-pinned container "
            "on the pre-authorized GCE VM. The path must remain under the pinned "
            "working directory. Use this instead of a heredoc, shell redirection, "
            "base64 command, or printf when creating or replacing source files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Exact absolute destination path under the locked workdir.",
                },
                "content": {
                    "type": "string",
                    "description": "Complete UTF-8 file content.",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
}
TOOL_DEFINITIONS: list[dict[str, Any]] = [TOOL_DEFINITION, *JOB_TOOL_DEFINITIONS]
AVAILABLE_TOOL_NAMES = {
    TOOL_NAME, CONTAINER_TOOL_NAME, CONTAINER_WRITE_TOOL_NAME,
    *JOB_TOOL_OPERATIONS,
}

_SELECTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]*$")
_QUOTED_VALUE = re.compile(r"'(?:[^']*)'|\"(?:[^\"\\]|\\.)*\"|`(?:[^`]*)`")
_ASSIGNMENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)=[^\s;&|]+")
_SENSITIVE_FLAG = re.compile(
    r"(?i)(--?(?:api[-_]?key|authorization|password|passwd|secret|token))"
    r"(?:=|\s+)\S+"
)
_BEARER = re.compile(r"(?i)\bBearer\s+\S+")
_GOVERNOR_CORRECTION_PREFIX = "conflux governor correction:"
_GOVERNOR_CORRECTION_NAME = "conflux_governor"


def _is_governor_correction(message: Mapping[str, Any]) -> bool:
    return (
        message.get("role") in {"system", "user"}
        and str(message.get("content") or "").startswith(_GOVERNOR_CORRECTION_PREFIX)
    )


class DirectClientError(RuntimeError):
    """A safe, user-facing failure in the direct client."""


class BoundaryError(DirectClientError):
    """The immutable remote-execution boundary is invalid."""


class ProtocolError(DirectClientError):
    """The completion server returned an unusable tool transcript."""


class LimitReached(DirectClientError):
    """A configured step or wall-clock limit was reached."""


def require_supervised_virtual_model(model: str) -> None:
    """Fail closed before tools can be exposed to a passthrough model."""
    if model != "super":
        raise BoundaryError(
            "the locked tool client requires model 'super'; explicit provider "
            "models are unsupervised passthroughs"
        )


def _positive_number(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be finite and greater than zero")
    return parsed


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


@dataclass(frozen=True)
class AuthorizedVM:
    vm: str
    project: str
    account: str
    zone: str

    def __post_init__(self) -> None:
        for field_name in ("vm", "project", "account", "zone"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not _SELECTOR.fullmatch(value):
                raise BoundaryError(
                    f"invalid {field_name}: expected one non-option selector token"
                )


def gcloud_ssh_argv(target: AuthorizedVM, command: str) -> list[str]:
    """Return the only local command shape this client is allowed to run."""
    if not isinstance(command, str) or not command.strip():
        raise BoundaryError("remote command must be a non-empty string")
    if "\x00" in command:
        raise BoundaryError("remote command contains a NUL byte")
    if len(command.encode("utf-8")) > 65_536:
        raise BoundaryError("remote command exceeds the 65536-byte limit")
    return [
        "gcloud",
        "compute",
        "ssh",
        target.vm,
        "--project",
        target.project,
        "--account",
        target.account,
        "--zone",
        target.zone,
        "--quiet",
        "--command",
        command,
    ]


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def _clip_utf8(value: str, limit: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True


def command_preview(command: str, max_chars: int = 160) -> str:
    """Return a one-line, conservatively redacted command preview."""
    if max_chars < 16:
        raise ValueError("max_chars must be at least 16")
    preview = " ".join(command.split())
    preview = _QUOTED_VALUE.sub("<quoted>", preview)
    preview = _ASSIGNMENT.sub(lambda match: f"{match.group(1)}=<redacted>", preview)
    preview = _SENSITIVE_FLAG.sub(lambda match: f"{match.group(1)}=<redacted>", preview)
    preview = _BEARER.sub("Bearer <redacted>", preview)
    # These commands deliberately render their arguments; do not echo those
    # arguments into an operator log even when they were unquoted.
    preview = re.sub(
        r"(?i)(^|(?:&&|\|\||;|\|)\s*)(echo|printf)\b[^;&|]*",
        lambda match: f"{match.group(1)}{match.group(2)} <redacted-output>",
        preview,
    )
    if len(preview) <= max_chars:
        return preview
    return preview[: max_chars - 1] + "…"


def _progress_result(result: Mapping[str, Any]) -> str:
    exit_code = result.get("exit_code")
    rendered_exit = str(exit_code) if isinstance(exit_code, int) else "n/a"
    rendered = (
        f"ok={str(bool(result.get('ok', False))).lower()} "
        f"exit={rendered_exit} "
        f"timed_out={str(bool(result.get('timed_out', False))).lower()}"
    )
    if isinstance(result.get("state"), str):
        rendered += f" state={result['state']}"
    if isinstance(result.get("job_id"), str):
        rendered += f" job={result['job_id']}"
    return rendered


class AuthorizedVMExecutor:
    """Execute only a fixed-target ``gcloud compute ssh`` subprocess.

    There is intentionally no local-shell or local-subprocess execution path
    for model-selected commands.  The sole subprocess shape is constructed by
    :func:`gcloud_ssh_argv` with frozen selectors and ``shell=False``.
    """

    def __init__(
        self,
        target: AuthorizedVM,
        *,
        timeout_s: float = 900.0,
        capture_limit_bytes: int = 1_048_576,
        runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
        boundary: ExecutionBackendLock | None = None,
    ) -> None:
        if timeout_s <= 0 or not math.isfinite(timeout_s):
            raise ValueError("timeout_s must be finite and greater than zero")
        if capture_limit_bytes < 1:
            raise ValueError("capture_limit_bytes must be greater than zero")
        self.target = target
        self.timeout_s = timeout_s
        self.capture_limit_bytes = capture_limit_bytes
        self._runner = runner
        self.boundary = boundary
        self.tool_name = TOOL_NAME

    def run(self, command: str, *, timeout_s: float | None = None) -> dict[str, Any]:
        if self.boundary is not None:
            if self.boundary.backend != "gce" or dict(self.boundary.target) != {
                "vm": self.target.vm, "project": self.target.project,
                "account": self.target.account, "zone": self.target.zone,
            }:
                raise BoundaryError(
                    "short-command executor does not match the immutable GCE lock"
                )
        argv = gcloud_ssh_argv(self.target, command)
        effective_timeout = self.timeout_s
        if timeout_s is not None:
            effective_timeout = min(effective_timeout, timeout_s)
        try:
            completed = self._runner(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                check=False,
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            stdout, stdout_cut = _clip_utf8(
                _text(exc.stdout or exc.output), self.capture_limit_bytes
            )
            stderr, stderr_cut = _clip_utf8(
                _text(exc.stderr), self.capture_limit_bytes
            )
            return {
                "ok": False,
                "timed_out": True,
                "timeout_seconds": effective_timeout,
                "execution": {"backend": "gce_ssh", "remote_only": True,
                              "vm": self.target.vm, "project": self.target.project,
                              "zone": self.target.zone},
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": stdout_cut,
                "stderr_truncated": stderr_cut,
            }
        except OSError as exc:
            message, cut = _clip_utf8(str(exc), 1024)
            return {
                "ok": False,
                "error": {"kind": "gcloud_launch_failed", "message": message},
                "error_truncated": cut,
                "execution": {"backend": "gce_ssh", "remote_only": True,
                              "vm": self.target.vm, "project": self.target.project,
                              "zone": self.target.zone},
            }

        stdout, stdout_cut = _clip_utf8(
            _text(completed.stdout), self.capture_limit_bytes
        )
        stderr, stderr_cut = _clip_utf8(
            _text(completed.stderr), self.capture_limit_bytes
        )
        return {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "execution": {"backend": "gce_ssh", "remote_only": True,
                          "vm": self.target.vm, "project": self.target.project,
                          "zone": self.target.zone},
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_cut,
            "stderr_truncated": stderr_cut,
        }


@dataclass(frozen=True)
class AuthorizedContainer:
    """One operator-selected container namespace on an authorized VM."""

    name: str
    working_dir: str = "/app"

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _SELECTOR.fullmatch(self.name):
            raise BoundaryError("invalid container: expected one non-option selector token")
        if (
            not isinstance(self.working_dir, str)
            or not self.working_dir.startswith("/")
            or "\x00" in self.working_dir
            or "\n" in self.working_dir
        ):
            raise BoundaryError("container working directory must be an absolute NUL-free path")


class AuthorizedContainerExecutor:
    """Execute model-selected commands only inside one pinned remote container.

    The model never supplies the Docker executable, container name, host target,
    or container working directory. The outer transport remains the immutable
    GCE executor; this adapter adds a second immutable namespace boundary.
    """

    tool_name = CONTAINER_TOOL_NAME

    def __init__(
        self,
        transport: AuthorizedVMExecutor,
        container: AuthorizedContainer,
        *,
        boundary: ExecutionBackendLock | None = None,
    ) -> None:
        self.transport = transport
        self.container = container
        self._descriptor = {
            "vm": transport.target.vm,
            "project": transport.target.project,
            "account": transport.target.account,
            "zone": transport.target.zone,
            "container": container.name,
            "working_dir": container.working_dir,
        }
        self.boundary = boundary or ExecutionBackendLock(
            "gce_container", self._descriptor
        )
        self._assert_boundary()

    def _assert_boundary(self) -> None:
        if (
            self.boundary.backend != "gce_container"
            or dict(self.boundary.target) != self._descriptor
        ):
            raise BoundaryError(
                "container executor does not match the immutable GCE/container lock"
            )

    def run(self, command: str, *, timeout_s: float | None = None) -> dict[str, Any]:
        self._assert_boundary()
        if not isinstance(command, str) or not command.strip() or "\x00" in command:
            raise BoundaryError("container command must be non-empty and NUL-free")
        remote_command = " ".join(
            (
                "sudo docker exec --workdir",
                shlex.quote(self.container.working_dir),
                shlex.quote(self.container.name),
                "bash -lc",
                shlex.quote(command),
            )
        )
        result = dict(self.transport.run(remote_command, timeout_s=timeout_s))
        result["execution"] = {
            "backend": "gce_container",
            "remote_only": True,
            "vm": self.transport.target.vm,
            "project": self.transport.target.project,
            "zone": self.transport.target.zone,
            "container": self.container.name,
            "working_dir": self.container.working_dir,
            "boundary_fingerprint": self.boundary.fingerprint,
        }
        return result

    def write_file(
        self, path: str, content: str, *, timeout_s: float | None = None,
    ) -> dict[str, Any]:
        """Atomically write one bounded UTF-8 file in the locked workdir.

        The model never authors the transport command. The controller validates
        the destination, encodes the payload, and chooses the temporary file.
        """
        self._assert_boundary()
        if not isinstance(path, str) or not path.startswith("/"):
            raise BoundaryError("container write path must be absolute")
        if "\x00" in path or "\n" in path or "\r" in path:
            raise BoundaryError("container write path must be NUL and newline free")
        normalized_root = posixpath.normpath(self.container.working_dir)
        normalized_path = posixpath.normpath(path)
        if path != normalized_path:
            raise BoundaryError("container write path must already be normalized")
        if (
            normalized_path == normalized_root
            or not normalized_path.startswith(normalized_root.rstrip("/") + "/")
        ):
            raise BoundaryError("container write path escapes the locked workdir")
        if not isinstance(content, str) or "\x00" in content:
            raise BoundaryError("container file content must be NUL-free UTF-8 text")
        encoded_content = content.encode("utf-8")
        if len(encoded_content) > 32_768:
            raise BoundaryError("container file content exceeds the 32768-byte limit")

        payload = base64.b64encode(encoded_content).decode("ascii")
        digest = hashlib.sha256(encoded_content).hexdigest()
        temporary_path = normalized_path + ".conflux-write-tmp"
        inner = " ".join((
            "set -e; umask 077; printf %s", shlex.quote(payload),
            "| base64 -d >", shlex.quote(temporary_path),
            "; chmod 600 --", shlex.quote(temporary_path),
            "; mv --", shlex.quote(temporary_path), shlex.quote(normalized_path),
            "; stat -c '%n %s' --", shlex.quote(normalized_path),
            "; sha256sum --", shlex.quote(normalized_path),
        ))
        remote_command = " ".join((
            "sudo docker exec --workdir",
            shlex.quote(self.container.working_dir),
            shlex.quote(self.container.name),
            "bash -lc",
            shlex.quote(inner),
        ))
        result = dict(self.transport.run(remote_command, timeout_s=timeout_s))
        result["execution"] = {
            "backend": "gce_container",
            "remote_only": True,
            "vm": self.transport.target.vm,
            "project": self.transport.target.project,
            "zone": self.transport.target.zone,
            "container": self.container.name,
            "working_dir": self.container.working_dir,
            "boundary_fingerprint": self.boundary.fingerprint,
        }
        result["write"] = {
            "path": normalized_path,
            "bytes": len(encoded_content),
            "sha256": digest,
            "atomic_replace": True,
        }
        return result


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def bounded_tool_json(result: Mapping[str, Any], max_bytes: int) -> str:
    """Serialize one valid JSON tool result without crossing ``max_bytes``."""
    if max_bytes < 128:
        raise ValueError("max_bytes must be at least 128")
    try:
        encoded = _json_bytes(result)
    except (TypeError, ValueError):
        result = {
            "ok": False,
            "error": {
                "kind": "non_json_tool_result",
                "message": "tool executor returned a non-JSON value",
            },
        }
        encoded = _json_bytes(result)
    if len(encoded) <= max_bytes:
        return encoded.decode("utf-8")

    compact: dict[str, Any] = {
        "ok": bool(result.get("ok", False)),
        "result_truncated": True,
    }
    for key in ("exit_code", "timed_out", "timeout_seconds"):
        value = result.get(key)
        if isinstance(value, (bool, int, float)) and not isinstance(value, complex):
            compact[key] = value

    text_fields: list[tuple[str, str]] = []
    for key in ("stdout", "stderr"):
        if key in result:
            text_fields.append((key, _text(result[key])))
    if "error" in result:
        error = result["error"]
        error_text = error if isinstance(error, str) else json.dumps(
            error, ensure_ascii=False, separators=(",", ":"), default=str
        )
        text_fields.append(("error", error_text))

    # JSON escaping can expand a string, so retry with progressively smaller
    # per-field byte shares until the complete serialized object fits.
    share = max_bytes // max(1, len(text_fields))
    while share > 0:
        candidate = dict(compact)
        for key, value in text_fields:
            clipped, cut = _clip_utf8(value, share)
            candidate[key] = clipped
            if cut:
                candidate[f"{key}_truncated"] = True
        try:
            candidate_bytes = _json_bytes(candidate)
        except (TypeError, ValueError):
            candidate_bytes = b""
        if candidate_bytes and len(candidate_bytes) <= max_bytes:
            return candidate_bytes.decode("utf-8")
        share //= 2

    fallback = _json_bytes({"ok": False, "result_truncated": True})
    if len(fallback) > max_bytes:  # guarded by the minimum above
        raise AssertionError("bounded JSON fallback exceeded its fixed limit")
    return fallback.decode("utf-8")


class ChatCompletionsClient:
    def __init__(
        self,
        endpoint: str,
        *,
        api_key: str | None = None,
        timeout_s: float = 300.0,
        max_response_bytes: int = 2_097_152,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        parsed = urllib.parse.urlsplit(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path.rstrip("/") != "/v1/chat/completions"
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("endpoint must be an HTTP(S) /v1/chat/completions URL")
        if timeout_s <= 0 or not math.isfinite(timeout_s):
            raise ValueError("timeout_s must be finite and greater than zero")
        if max_response_bytes < 1024:
            raise ValueError("max_response_bytes must be at least 1024")
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.max_response_bytes = max_response_bytes
        self._opener = opener

    def complete(
        self, body: Mapping[str, Any], *, timeout_s: float | None = None
    ) -> dict[str, Any]:
        effective_timeout = self.timeout_s
        if timeout_s is not None:
            effective_timeout = min(effective_timeout, timeout_s)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with self._opener(request, timeout=effective_timeout) as response:
                raw = response.read(self.max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            # Upstreams sometimes echo request material in error bodies. Do
            # not print that body: status alone is sufficient and stays safe.
            raise DirectClientError(f"completion HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise DirectClientError(f"completion request failed: {exc}") from exc
        if len(raw) > self.max_response_bytes:
            raise ProtocolError("completion response exceeded the configured byte limit")
        try:
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolError("completion response was not valid JSON") from exc
        if not isinstance(data, dict):
            raise ProtocolError("completion response must be a JSON object")
        return data


@dataclass
class ToolLoopResult:
    final_message: dict[str, Any]
    transcript: list[dict[str, Any]]
    tool_steps: int

    @property
    def text(self) -> str:
        content = self.final_message.get("content")
        if not isinstance(content, str):
            raise ProtocolError("final assistant content was not text")
        return content


def load_transcript(path: Path, task: str) -> list[dict[str, Any]] | None:
    """Load one exact task transcript, failing closed on mismatch or corruption."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise DirectClientError(f"cannot read transcript {path}: {exc}") from exc
    expected = hashlib.sha256(task.encode()).hexdigest()
    if (
        not isinstance(payload, dict)
        or payload.get("version") != 1
        or payload.get("task_sha256") != expected
        or not isinstance(payload.get("messages"), list)
    ):
        raise DirectClientError("transcript does not match this task or is malformed")
    messages = payload["messages"]
    if (
        not messages
        or {"role": "user", "content": task} not in messages
    ):
        raise DirectClientError("transcript is missing the exact initial task message")
    return copy.deepcopy(messages)


def save_transcript(path: Path, task: str, messages: list[dict[str, Any]]) -> None:
    """Atomically checkpoint protocol messages for approval/restart recovery."""
    payload = {
        "version": 1,
        "task_sha256": hashlib.sha256(task.encode()).hexdigest(),
        "messages": messages,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except OSError as exc:
        raise DirectClientError(f"cannot checkpoint transcript {path}: {exc}") from exc


def _assistant_message(response: Mapping[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProtocolError("completion response has no first choice")
    message = choices[0].get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise ProtocolError("completion response has no assistant message")
    return copy.deepcopy(message)


def _assistant_has_no_output(message: Mapping[str, Any]) -> bool:
    """True when a provider returned neither usable text nor tool calls."""
    content = message.get("content")
    tool_calls = message.get("tool_calls")
    return (
        (not isinstance(content, str) or not content.strip())
        and (tool_calls is None or tool_calls == [])
    )


def _tool_error(kind: str, message: str) -> dict[str, Any]:
    clipped, truncated = _clip_utf8(message, 2048)
    result: dict[str, Any] = {
        "ok": False,
        "error": {"kind": kind, "message": clipped},
    }
    if truncated:
        result["error_truncated"] = True
    return result


def _valid_job_id(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"job_[a-f0-9]{24}", value))


def _parse_tool_call(
    call: Any, available_names: set[str] | None = None,
) -> tuple[str, str | None, dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(call, dict):
        raise ProtocolError("assistant tool call was not an object")
    call_id = call.get("id")
    if not isinstance(call_id, str) or not call_id or len(call_id) > 512:
        raise ProtocolError("assistant tool call has no usable id")
    if call.get("type") != "function" or not isinstance(call.get("function"), dict):
        return call_id, None, None, _tool_error(
            "invalid_tool_call", "tool call must have type function"
        )
    function = call["function"]
    name = function.get("name")
    allowed_names = AVAILABLE_TOOL_NAMES if available_names is None else available_names
    if name not in allowed_names:
        return call_id, None, None, _tool_error(
            "unauthorized_tool", "the requested tool is not available"
        )
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        return call_id, name, None, _tool_error(
            "invalid_tool_arguments", "function arguments must be a JSON string"
        )
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return call_id, name, None, _tool_error(
            "invalid_tool_arguments", "function arguments are not valid JSON"
        )
    if not isinstance(parsed, dict) or "backend" in parsed or "target" in parsed:
        return call_id, name, None, _tool_error(
            "invalid_tool_arguments",
            "arguments must be an object and may not select a backend or target",
        )

    def reject(message: str):
        return call_id, name, None, _tool_error("invalid_tool_arguments", message)

    if name in {TOOL_NAME, CONTAINER_TOOL_NAME}:
        if set(parsed) != {"command"}:
            return reject("arguments must contain exactly one command field")
        command = parsed.get("command")
        if (not isinstance(command, str) or not command.strip() or "\x00" in command
                or len(command.encode("utf-8")) > 65_536):
            return reject("command must be non-empty, NUL-free, and at most 65536 bytes")
    elif name == CONTAINER_WRITE_TOOL_NAME:
        if set(parsed) != {"path", "content"}:
            return reject("container write requires exactly path and content")
        path = parsed.get("path")
        content = parsed.get("content")
        if (
            not isinstance(path, str) or not path.startswith("/")
            or "\x00" in path or "\n" in path or "\r" in path
            or len(path.encode("utf-8")) > 4096
        ):
            return reject("path must be a bounded absolute NUL-free path")
        if (
            not isinstance(content, str) or "\x00" in content
            or len(content.encode("utf-8")) > 32_768
        ):
            return reject("content must be NUL-free UTF-8 text up to 32768 bytes")
    elif name == START_JOB_TOOL:
        if not {"command", "label", "timeout_s"} <= set(parsed) <= {
            "command", "label", "timeout_s", "cwd"
        }:
            return reject("start requires command, label, timeout_s, and optional cwd")
        if (not isinstance(parsed.get("command"), str)
                or not parsed["command"].strip() or "\x00" in parsed["command"]
                or len(parsed["command"].encode()) > 32768):
            return reject("command must be non-empty, NUL-free, and at most 32768 bytes")
        if not isinstance(parsed.get("label"), str) or not 1 <= len(parsed["label"]) <= 120:
            return reject("label must contain 1 to 120 characters")
        if (not isinstance(parsed.get("timeout_s"), int)
                or isinstance(parsed["timeout_s"], bool)
                or not 1 <= parsed["timeout_s"] <= 86400):
            return reject("timeout_s must be an integer from 1 to 86400")
        if "cwd" in parsed and (not isinstance(parsed["cwd"], str) or "\x00" in parsed["cwd"]):
            return reject("cwd must be a NUL-free string")
    elif name == WATCH_JOB_TOOL:
        if not {"job_id", "stdout_cursor", "stderr_cursor"} <= set(parsed) <= {
            "job_id", "stdout_cursor", "stderr_cursor", "wait_seconds", "max_bytes"
        }:
            return reject("watch requires job_id and both output cursors")
        if not _valid_job_id(parsed.get("job_id")):
            return reject("job_id is invalid")
        for field, maximum in (("stdout_cursor", 2**63 - 1),
                               ("stderr_cursor", 2**63 - 1),
                               ("wait_seconds", 60), ("max_bytes", 131072)):
            if field in parsed and (not isinstance(parsed[field], int)
                                    or isinstance(parsed[field], bool)
                                    or not 0 <= parsed[field] <= maximum):
                return reject(f"{field} is outside its allowed integer range")
        if "max_bytes" in parsed and parsed["max_bytes"] < 256:
            return reject("max_bytes must be at least 256")
    elif name == INSPECT_JOB_TOOL:
        if set(parsed) != {"job_id"} or not _valid_job_id(parsed.get("job_id")):
            return reject("inspect requires exactly one valid job_id")
    elif name == SIGNAL_JOB_TOOL:
        if (set(parsed) != {"job_id", "signal"}
                or not _valid_job_id(parsed.get("job_id"))
                or parsed.get("signal") not in {"interrupt", "terminate", "kill"}):
            return reject("signal requires a valid job_id and an allowed signal")
    elif name == COLLECT_JOB_TOOL:
        if not {"job_id", "stdout_cursor", "stderr_cursor"} <= set(parsed) <= {
            "job_id", "stdout_cursor", "stderr_cursor", "max_bytes"
        } or not _valid_job_id(parsed.get("job_id")):
            return reject("collect requires a valid job_id and both output cursors")
        for field, maximum in (("stdout_cursor", 2**63 - 1),
                               ("stderr_cursor", 2**63 - 1),
                               ("max_bytes", 262144)):
            if field in parsed and (not isinstance(parsed[field], int)
                                    or isinstance(parsed[field], bool)
                                    or not 0 <= parsed[field] <= maximum):
                return reject(f"{field} is outside its allowed integer range")
        if "max_bytes" in parsed and parsed["max_bytes"] < 256:
            return reject("max_bytes must be at least 256")
    return call_id, name, parsed, None


def run_tool_loop(
    task: str,
    *,
    model: str,
    client: ChatCompletionsClient,
    executor: AuthorizedVMExecutor,
    job_executor: LockedJobExecutor | None = None,
    max_steps: int = 32,
    max_governor_retries: int = 3,
    max_tokens: int = 8192,
    max_tool_result_bytes: int = 32_768,
    total_timeout_s: float = 14_400.0,
    clock: Callable[[], float] = time.monotonic,
    progress: Callable[[str], None] | None = None,
    tool_definitions: list[dict[str, Any]] | None = None,
    initial_messages: list[dict[str, Any]] | None = None,
    checkpoint: Callable[[list[dict[str, Any]]], None] | None = None,
) -> ToolLoopResult:
    require_supervised_virtual_model(model)
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be non-empty")
    if max_steps < 1 or max_tokens < 1:
        raise ValueError("max_steps and max_tokens must be greater than zero")
    if max_governor_retries < 0:
        raise ValueError("max_governor_retries must not be negative")
    if max_tool_result_bytes < 128:
        raise ValueError("max_tool_result_bytes must be at least 128")
    if total_timeout_s <= 0 or not math.isfinite(total_timeout_s):
        raise ValueError("total_timeout_s must be finite and greater than zero")

    # Deliberately no system message: in particular, no Hermes prompt is sent.
    messages: list[dict[str, Any]] = copy.deepcopy(
        initial_messages if initial_messages is not None
        else [{"role": "user", "content": task}]
    )
    if (
        not messages
        or not all(isinstance(message, dict) for message in messages)
        or {"role": "user", "content": task} not in messages
    ):
        raise ValueError("initial_messages must contain the exact initial task message")

    active_correction = next((
        message for message in reversed(messages)
        if _is_governor_correction(message)
    ), None)
    if active_correction is not None:
        # A named user-level control message is consistently honored across
        # provider families. The proxy explicitly excludes this internal name
        # from task identity, leaving the exact original user task unchanged.
        content = str(active_correction.get("content") or "")
        messages.remove(active_correction)
        # Older checkpoints may contain the provider's empty reply after the
        # correction. It is not a meaningful protocol turn; put the correction
        # back at the live boundary so a resume can actually answer it.
        while messages and _assistant_has_no_output(messages[-1]):
            messages.pop()
        active_correction = {
            "role": "user", "name": _GOVERNOR_CORRECTION_NAME,
            "content": content,
        }
        messages.append(active_correction)

    def persist() -> None:
        if checkpoint is not None:
            checkpoint(copy.deepcopy(messages))

    persist()
    deadline = clock() + total_timeout_s
    tool_steps = 0
    completion_steps = 0
    governor_retries = 0
    exposed_tools = tool_definitions or TOOL_DEFINITIONS
    exposed_names = {
        str((tool.get("function") or {}).get("name")) for tool in exposed_tools
    }
    executor_tool_name = str(getattr(executor, "tool_name", TOOL_NAME))

    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise LimitReached("total tool-loop timeout reached")
        body = {
            "model": model,
            "messages": copy.deepcopy(messages),
            "tools": copy.deepcopy(exposed_tools),
            "tool_choice": "auto",
            "stream": False,
            "max_tokens": max_tokens,
        }
        response = client.complete(body, timeout_s=remaining)
        completion_steps += 1
        assistant = _assistant_message(response)
        messages.append(assistant)
        persist()
        tool_calls = assistant.get("tool_calls")
        if tool_calls is None or tool_calls == []:
            content = assistant.get("content")
            if not isinstance(content, str) or not content.strip():
                # Some providers occasionally acknowledge a correction with an
                # empty assistant object. Never checkpoint that as successful
                # completion: remove it and ask once more within the same
                # bounded correction budget.
                messages.pop()
                if governor_retries >= max_governor_retries:
                    persist()
                    raise ProtocolError(
                        "assistant repeatedly returned neither text nor tool calls"
                    )
                governor_retries += 1
                prior = ""
                if active_correction in messages:
                    prior = str(active_correction.get("content") or "")
                    messages.remove(active_correction)
                active_correction = {
                    "role": "user",
                    "name": _GOVERNOR_CORRECTION_NAME,
                    "content": (
                        (prior + "\n\n") if prior else _GOVERNOR_CORRECTION_PREFIX + " "
                    ) + (
                        "The prior assistant response was empty. Respond with a "
                        "non-empty textual answer now, preserving the evidence and "
                        "all action constraints already stated."
                    ),
                }
                messages.append(active_correction)
                persist()
                if progress is not None:
                    progress(
                        f"completion={completion_steps} decision=protocol_retry "
                        f"attempt={governor_retries}"
                    )
                continue
            human_hold = (
                isinstance(content, str)
                and content.startswith("[conflux] Human approval is required")
            )
            if human_hold:
                # The synthetic notice stands in for a durably held assistant
                # tool-call response. Remove it so an approved retry can insert
                # that exact original response at the same protocol boundary.
                messages.pop()
                persist()
                if progress is not None:
                    progress(f"completion={completion_steps} decision=human_hold")
                return ToolLoopResult(assistant, messages, tool_steps)
            governor_blocked = (
                isinstance(content, str)
                and content.startswith("[conflux] Action")
                and " blocked" in content[:80]
            )
            if governor_blocked:
                if governor_retries >= max_governor_retries:
                    # A governor notice replaces a rejected assistant proposal;
                    # it is not durable conversation output. Keep only the prior
                    # correction boundary so a later resume can generate a fresh
                    # proposal under updated policy or operator guidance.
                    messages.pop()
                    persist()
                    raise LimitReached(
                        "maximum governor correction attempts reached"
                    )
                governor_retries += 1
                # The proxy derives task identity from the last user message.
                # Keep corrective policy out of that channel, and discard the
                # synthetic assistant notice it replaces.
                messages.pop()
                if active_correction in messages:
                    messages.remove(active_correction)
                active_correction = {
                    "role": "user",
                    "name": _GOVERNOR_CORRECTION_NAME,
                    "content": (
                        _GOVERNOR_CORRECTION_PREFIX + " The action governor rejected the prior "
                        "proposal; this rejection is not task completion. Incorporate the "
                        "exact objection below, propose a narrower corrected action, and "
                        "preserve all valid evidence already observed.\n\n" + content
                    ),
                }
                messages.append(active_correction)
                persist()
                if progress is not None:
                    progress(
                        f"completion={completion_steps} decision=governor_retry "
                        f"attempt={governor_retries}"
                    )
                continue
            if progress is not None:
                progress(f"completion={completion_steps} decision=final")
            return ToolLoopResult(assistant, messages, tool_steps)
        if not isinstance(tool_calls, list):
            raise ProtocolError("assistant tool_calls field was not a list")
        if progress is not None:
            progress(
                f"completion={completion_steps} decision=tool_calls "
                f"count={len(tool_calls)}"
            )

        for call in tool_calls:
            if tool_steps >= max_steps:
                raise LimitReached(f"maximum of {max_steps} tool steps reached")
            call_id, tool_name, arguments, error = _parse_tool_call(call, exposed_names)
            if error is not None:
                result: Mapping[str, Any] = error
                if progress is not None:
                    progress(
                        f"tool_step={tool_steps + 1} tool={tool_name or 'rejected'} "
                        "arguments=<invalid-or-rejected>"
                    )
            else:
                remaining = deadline - clock()
                if remaining <= 0:
                    raise LimitReached("total tool-loop timeout reached")
                assert tool_name is not None and arguments is not None
                if progress is not None:
                    if tool_name in {TOOL_NAME, CONTAINER_TOOL_NAME, START_JOB_TOOL}:
                        detail = f"command={command_preview(arguments['command'])}"
                    elif tool_name == CONTAINER_WRITE_TOOL_NAME:
                        detail = (
                            f"path={arguments['path']} "
                            f"bytes={len(arguments['content'].encode('utf-8'))}"
                        )
                    else:
                        detail = f"job={arguments.get('job_id', 'n/a')}"
                    progress(f"tool_step={tool_steps + 1} tool={tool_name} {detail}")
                if tool_name == executor_tool_name:
                    result = executor.run(arguments["command"], timeout_s=remaining)
                elif tool_name == CONTAINER_WRITE_TOOL_NAME and isinstance(
                    executor, AuthorizedContainerExecutor
                ):
                    result = executor.write_file(
                        arguments["path"], arguments["content"], timeout_s=remaining
                    )
                elif job_executor is None:
                    result = _tool_error(
                        "job_backend_unavailable",
                        "durable job tools were not bound by the trusted controller",
                    )
                else:
                    try:
                        result = job_executor.execute(
                            JOB_TOOL_OPERATIONS[tool_name], arguments,
                            context={
                                "session": "direct_" + hashlib.sha256(task.encode()).hexdigest()[:12],
                                "task": command_preview(task, 120),
                            },
                        )
                    except (ExecutionBoundaryError, KeyError, TypeError, ValueError) as exc:
                        result = _tool_error("execution_boundary", str(exc))
                if not isinstance(result, Mapping):
                    result = _tool_error(
                        "invalid_tool_result", "executor returned a non-object result"
                    )
            if progress is not None:
                progress(f"tool_step={tool_steps + 1} result {_progress_result(result)}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": bounded_tool_json(result, max_tool_result_bytes),
                }
            )
            if active_correction in messages:
                messages.remove(active_correction)
                active_correction = None
            persist()
            tool_steps += 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Drive conflux with one fixed-target remote-exec tool."
    )
    parser.add_argument("task", nargs="?", help="task text; reads stdin when omitted")
    parser.add_argument(
        "--endpoint", default="http://127.0.0.1:8055/v1/chat/completions"
    )
    parser.add_argument("--model", default="super")
    parser.add_argument("--vm")
    parser.add_argument("--project")
    parser.add_argument("--account")
    parser.add_argument("--zone")
    parser.add_argument(
        "--job-backend", choices=("gce", "docker"), default="gce",
        help="trusted operator selection of the durable-job adapter; "
             "never exposed to the agent as a tool argument",
    )
    parser.add_argument(
        "--docker-container",
        help="immutable container target for --job-backend docker",
    )
    parser.add_argument(
        "--container",
        help="pin all agent commands inside this container on the authorized VM",
    )
    parser.add_argument(
        "--container-workdir", default="/app",
        help="fixed working directory used with --container (default: /app)",
    )
    parser.add_argument("--max-steps", type=_positive_int, default=32)
    parser.add_argument(
        "--max-governor-retries", type=_positive_int, default=3,
        help="bounded automatic corrections after deterministic governor blocks",
    )
    parser.add_argument("--max-tokens", type=_positive_int, default=8192)
    parser.add_argument("--api-timeout-seconds", type=_positive_number, default=300.0)
    parser.add_argument("--ssh-timeout-seconds", type=_positive_number, default=900.0)
    parser.add_argument(
        "--total-timeout-seconds", type=_positive_number, default=14_400.0
    )
    parser.add_argument(
        "--max-tool-result-bytes", type=_positive_int, default=32_768
    )
    parser.add_argument(
        "--job-db",
        default=os.environ.get("CONFLUX_JOB_DB", "traces.db"),
        help="SQLite control-plane ledger shared with the graph UI",
    )
    parser.add_argument(
        "--transcript-file",
        help="atomic protocol checkpoint used to resume held or interrupted runs",
    )
    parser.add_argument(
        "--durable-only", action="store_true",
        help="expose only backend-neutral durable job operations to the agent",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    task = args.task if args.task is not None else sys.stdin.read()
    if not task.strip():
        parser.error("provide a task argument or non-empty stdin")
    try:
        if args.durable_only and args.container:
            parser.error("--durable-only and --container cannot be combined")
        if args.job_backend == "docker":
            # Docker adapter path: pure durable-job protocol against one
            # immutable container. No raw terminal tool, no GCE selectors.
            if not args.durable_only:
                parser.error("--job-backend docker requires --durable-only")
            if not args.docker_container:
                parser.error("--job-backend docker requires --docker-container")
            if args.container:
                parser.error("--job-backend docker and --container cannot be combined")
            docker_target = DockerAuthorizedTarget(args.docker_container)
            boundary = ExecutionBackendLock("docker", docker_target.descriptor)
            client = ChatCompletionsClient(
                args.endpoint,
                api_key=os.environ.get("CONFLUX_API_KEY"),
                timeout_s=args.api_timeout_seconds,
            )
            job_store = DurableJobStore(args.job_db)
            registry = FlowRegistry.load(
                Path(__file__).resolve().parents[1] / "agent_flows.yaml"
            )
            job_flow_runtime = SQLiteFlowRuntime(job_store.connection, registry)
            job_backend = DockerJobBackend(
                docker_target,
                job_store,
                boundary_fingerprint=boundary.fingerprint,
                exec_timeout_s=args.ssh_timeout_seconds,
                flow_runtime=job_flow_runtime,
            )
            result = run_tool_loop(
                task,
                model=args.model,
                client=client,
                executor=None,
                job_executor=LockedJobExecutor(boundary, job_backend),
                max_steps=args.max_steps,
                max_governor_retries=args.max_governor_retries,
                max_tokens=args.max_tokens,
                max_tool_result_bytes=args.max_tool_result_bytes,
                total_timeout_s=args.total_timeout_seconds,
                progress=lambda event: print(f"[direct-vm] {event}", file=sys.stderr),
                tool_definitions=JOB_TOOL_DEFINITIONS,
                initial_messages=(
                    load_transcript(Path(args.transcript_file), task)
                    if args.transcript_file else None
                ),
                checkpoint=(
                    (lambda messages: save_transcript(
                        Path(args.transcript_file), task, messages
                    )) if args.transcript_file else None
                ),
            )
            print(result.text)
            return 0
        for name in ("vm", "project", "account", "zone"):
            if not getattr(args, name):
                parser.error(f"--{name} is required with --job-backend gce")
        target = AuthorizedVM(args.vm, args.project, args.account, args.zone)
        client = ChatCompletionsClient(
            args.endpoint,
            api_key=os.environ.get("CONFLUX_API_KEY"),
            timeout_s=args.api_timeout_seconds,
        )
        job_target = GCEAuthorizedTarget(
            args.vm, args.project, args.account, args.zone
        )
        boundary = ExecutionBackendLock("gce", job_target.descriptor)
        vm_executor = AuthorizedVMExecutor(
            target, timeout_s=args.ssh_timeout_seconds, boundary=boundary
        )
        if args.container:
            container = AuthorizedContainer(args.container, args.container_workdir)
            container_boundary = ExecutionBackendLock(
                "gce_container",
                {
                    **job_target.descriptor,
                    "container": container.name,
                    "working_dir": container.working_dir,
                },
            )
            executor = AuthorizedContainerExecutor(
                vm_executor, container, boundary=container_boundary
            )
            job_executor = None
            exposed_tools = [
                CONTAINER_TOOL_DEFINITION,
                CONTAINER_WRITE_TOOL_DEFINITION,
            ]
        else:
            executor = vm_executor
            job_store = DurableJobStore(args.job_db)
            registry = FlowRegistry.load(
                Path(__file__).resolve().parents[1] / "agent_flows.yaml"
            )
            job_flow_runtime = SQLiteFlowRuntime(job_store.connection, registry)
            job_backend = GCEJobBackend(
                job_target,
                job_store,
                boundary_fingerprint=boundary.fingerprint,
                ssh_timeout_s=args.ssh_timeout_seconds,
                flow_runtime=job_flow_runtime,
            )
            job_executor = LockedJobExecutor(boundary, job_backend)
            exposed_tools = JOB_TOOL_DEFINITIONS if args.durable_only else None
        result = run_tool_loop(
            task,
            model=args.model,
            client=client,
            executor=executor,
            job_executor=job_executor,
            max_steps=args.max_steps,
            max_governor_retries=args.max_governor_retries,
            max_tokens=args.max_tokens,
            max_tool_result_bytes=args.max_tool_result_bytes,
            total_timeout_s=args.total_timeout_seconds,
            progress=lambda event: print(f"[direct-vm] {event}", file=sys.stderr),
            tool_definitions=exposed_tools,
            initial_messages=(
                load_transcript(Path(args.transcript_file), task)
                if args.transcript_file else None
            ),
            checkpoint=(
                (lambda messages: save_transcript(
                    Path(args.transcript_file), task, messages
                )) if args.transcript_file else None
            ),
        )
        final_text = result.text
    except (DirectClientError, ValueError) as exc:
        print(f"direct-vm-client: {exc}", file=sys.stderr)
        return 2
    print(final_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
