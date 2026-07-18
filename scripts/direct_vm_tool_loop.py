#!/usr/bin/env python3
"""Small non-streaming llm-super client with one authorized remote-exec tool.

The model can choose only the remote command.  The Google Cloud identity and
target are immutable client inputs and are never copied from model output.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping


TOOL_NAME = "run_on_authorized_vm"
TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Run one shell command on the pre-authorized VM. The client fixes "
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

_SELECTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]*$")
_QUOTED_VALUE = re.compile(r"'(?:[^']*)'|\"(?:[^\"\\]|\\.)*\"|`(?:[^`]*)`")
_ASSIGNMENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)=[^\s;&|]+")
_SENSITIVE_FLAG = re.compile(
    r"(?i)(--?(?:api[-_]?key|authorization|password|passwd|secret|token))"
    r"(?:=|\s+)\S+"
)
_BEARER = re.compile(r"(?i)\bBearer\s+\S+")


class DirectClientError(RuntimeError):
    """A safe, user-facing failure in the direct client."""


class BoundaryError(DirectClientError):
    """The immutable remote-execution boundary is invalid."""


class ProtocolError(DirectClientError):
    """The completion server returned an unusable tool transcript."""


class LimitReached(DirectClientError):
    """A configured step or wall-clock limit was reached."""


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
    return (
        f"ok={str(bool(result.get('ok', False))).lower()} "
        f"exit={rendered_exit} "
        f"timed_out={str(bool(result.get('timed_out', False))).lower()}"
    )


class AuthorizedVMExecutor:
    """Execute only a fixed-target ``gcloud compute ssh`` subprocess."""

    def __init__(
        self,
        target: AuthorizedVM,
        *,
        timeout_s: float = 900.0,
        capture_limit_bytes: int = 1_048_576,
        runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    ) -> None:
        if timeout_s <= 0 or not math.isfinite(timeout_s):
            raise ValueError("timeout_s must be finite and greater than zero")
        if capture_limit_bytes < 1:
            raise ValueError("capture_limit_bytes must be greater than zero")
        self.target = target
        self.timeout_s = timeout_s
        self.capture_limit_bytes = capture_limit_bytes
        self._runner = runner

    def run(self, command: str, *, timeout_s: float | None = None) -> dict[str, Any]:
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
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_cut,
            "stderr_truncated": stderr_cut,
        }


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


def _assistant_message(response: Mapping[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProtocolError("completion response has no first choice")
    message = choices[0].get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise ProtocolError("completion response has no assistant message")
    return copy.deepcopy(message)


def _tool_error(kind: str, message: str) -> dict[str, Any]:
    clipped, truncated = _clip_utf8(message, 2048)
    result: dict[str, Any] = {
        "ok": False,
        "error": {"kind": kind, "message": clipped},
    }
    if truncated:
        result["error_truncated"] = True
    return result


def _parse_tool_call(call: Any) -> tuple[str, str | None, dict[str, Any] | None]:
    if not isinstance(call, dict):
        raise ProtocolError("assistant tool call was not an object")
    call_id = call.get("id")
    if not isinstance(call_id, str) or not call_id or len(call_id) > 512:
        raise ProtocolError("assistant tool call has no usable id")
    if call.get("type") != "function" or not isinstance(call.get("function"), dict):
        return call_id, None, _tool_error(
            "invalid_tool_call", "tool call must have type function"
        )
    function = call["function"]
    if function.get("name") != TOOL_NAME:
        return call_id, None, _tool_error(
            "unauthorized_tool", f"only {TOOL_NAME} is available"
        )
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        return call_id, None, _tool_error(
            "invalid_tool_arguments", "function arguments must be a JSON string"
        )
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return call_id, None, _tool_error(
            "invalid_tool_arguments", "function arguments are not valid JSON"
        )
    if not isinstance(parsed, dict) or set(parsed) != {"command"}:
        return call_id, None, _tool_error(
            "invalid_tool_arguments",
            "function arguments must contain exactly one command field",
        )
    command = parsed["command"]
    if not isinstance(command, str) or not command.strip() or "\x00" in command:
        return call_id, None, _tool_error(
            "invalid_tool_arguments", "command must be a non-empty string without NUL"
        )
    if len(command.encode("utf-8")) > 65_536:
        return call_id, None, _tool_error(
            "invalid_tool_arguments", "command exceeds the 65536-byte limit"
        )
    return call_id, command, None


def run_tool_loop(
    task: str,
    *,
    model: str,
    client: ChatCompletionsClient,
    executor: AuthorizedVMExecutor,
    max_steps: int = 32,
    max_tokens: int = 8192,
    max_tool_result_bytes: int = 32_768,
    total_timeout_s: float = 14_400.0,
    clock: Callable[[], float] = time.monotonic,
    progress: Callable[[str], None] | None = None,
) -> ToolLoopResult:
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be non-empty")
    if max_steps < 1 or max_tokens < 1:
        raise ValueError("max_steps and max_tokens must be greater than zero")
    if max_tool_result_bytes < 128:
        raise ValueError("max_tool_result_bytes must be at least 128")
    if total_timeout_s <= 0 or not math.isfinite(total_timeout_s):
        raise ValueError("total_timeout_s must be finite and greater than zero")

    # Deliberately no system message: in particular, no Hermes prompt is sent.
    messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
    deadline = clock() + total_timeout_s
    tool_steps = 0
    completion_steps = 0

    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise LimitReached("total tool-loop timeout reached")
        body = {
            "model": model,
            "messages": copy.deepcopy(messages),
            "tools": [copy.deepcopy(TOOL_DEFINITION)],
            "tool_choice": "auto",
            "stream": False,
            "max_tokens": max_tokens,
        }
        response = client.complete(body, timeout_s=remaining)
        completion_steps += 1
        assistant = _assistant_message(response)
        messages.append(assistant)
        tool_calls = assistant.get("tool_calls")
        if tool_calls is None or tool_calls == []:
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
            call_id, command, error = _parse_tool_call(call)
            if error is not None:
                result: Mapping[str, Any] = error
                if progress is not None:
                    progress(
                        f"tool_step={tool_steps + 1} tool={TOOL_NAME} "
                        "command=<invalid-or-rejected>"
                    )
            else:
                remaining = deadline - clock()
                if remaining <= 0:
                    raise LimitReached("total tool-loop timeout reached")
                assert command is not None
                if progress is not None:
                    progress(
                        f"tool_step={tool_steps + 1} tool={TOOL_NAME} "
                        f"command={command_preview(command)}"
                    )
                result = executor.run(command, timeout_s=remaining)
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
            tool_steps += 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Drive llm-super with one fixed-target remote-exec tool."
    )
    parser.add_argument("task", nargs="?", help="task text; reads stdin when omitted")
    parser.add_argument(
        "--endpoint", default="http://127.0.0.1:8055/v1/chat/completions"
    )
    parser.add_argument("--model", default="super")
    parser.add_argument("--vm", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--zone", required=True)
    parser.add_argument("--max-steps", type=_positive_int, default=32)
    parser.add_argument("--max-tokens", type=_positive_int, default=8192)
    parser.add_argument("--api-timeout-seconds", type=_positive_number, default=300.0)
    parser.add_argument("--ssh-timeout-seconds", type=_positive_number, default=900.0)
    parser.add_argument(
        "--total-timeout-seconds", type=_positive_number, default=14_400.0
    )
    parser.add_argument(
        "--max-tool-result-bytes", type=_positive_int, default=32_768
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    task = args.task if args.task is not None else sys.stdin.read()
    if not task.strip():
        parser.error("provide a task argument or non-empty stdin")
    try:
        target = AuthorizedVM(args.vm, args.project, args.account, args.zone)
        client = ChatCompletionsClient(
            args.endpoint,
            api_key=os.environ.get("LLM_SUPER_API_KEY"),
            timeout_s=args.api_timeout_seconds,
        )
        executor = AuthorizedVMExecutor(target, timeout_s=args.ssh_timeout_seconds)
        result = run_tool_loop(
            task,
            model=args.model,
            client=client,
            executor=executor,
            max_steps=args.max_steps,
            max_tokens=args.max_tokens,
            max_tool_result_bytes=args.max_tool_result_bytes,
            total_timeout_s=args.total_timeout_seconds,
            progress=lambda event: print(f"[direct-vm] {event}", file=sys.stderr),
        )
        final_text = result.text
    except (DirectClientError, ValueError) as exc:
        print(f"direct-vm-client: {exc}", file=sys.stderr)
        return 2
    print(final_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
