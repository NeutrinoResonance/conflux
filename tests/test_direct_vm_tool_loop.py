from __future__ import annotations

import copy
import json
import subprocess
import unittest
from unittest.mock import Mock

from scripts.direct_vm_tool_loop import (
    TOOL_DEFINITION,
    TOOL_NAME,
    AuthorizedVM,
    AuthorizedVMExecutor,
    BoundaryError,
    ChatCompletionsClient,
    LimitReached,
    bounded_tool_json,
    run_tool_loop,
)


TARGET = AuthorizedVM(
    vm="llmsuper-netbsd-arm64",
    project="project96-sar",
    account="gce-operator@example.com",
    zone="us-central1-a",
)


def _completion(message: dict) -> dict:
    return {
        "id": "chatcmpl-test",
        "choices": [{"index": 0, "message": message}],
    }


def _tool_message(call_id: str, arguments: str) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": TOOL_NAME, "arguments": arguments},
            }
        ],
    }


class _FakeClient:
    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.requests: list[tuple[dict, float | None]] = []

    def complete(self, body: dict, *, timeout_s: float | None = None) -> dict:
        self.requests.append((copy.deepcopy(body), timeout_s))
        return self.responses.pop(0)


class _FakeExecutor:
    def __init__(self, result: dict | None = None):
        self.result = result or {"ok": True, "exit_code": 0, "stdout": "ok\n"}
        self.calls: list[tuple[str, float | None]] = []

    def run(self, command: str, *, timeout_s: float | None = None) -> dict:
        self.calls.append((command, timeout_s))
        return self.result


class AuthorizedBoundaryTests(unittest.TestCase):
    def test_exact_gcloud_argv_keeps_remote_command_one_argument(self) -> None:
        runner = Mock(
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=b"x86_64\n", stderr=b""
            )
        )
        executor = AuthorizedVMExecutor(TARGET, timeout_s=90, runner=runner)
        remote_command = "uname -m; printf '%s\\n' still-remote"

        result = executor.run(remote_command, timeout_s=30)

        self.assertTrue(result["ok"])
        runner.assert_called_once_with(
            [
                "gcloud",
                "compute",
                "ssh",
                "llmsuper-netbsd-arm64",
                "--project",
                "project96-sar",
                "--account",
                "gce-operator@example.com",
                "--zone",
                "us-central1-a",
                "--quiet",
                "--command",
                remote_command,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            check=False,
            timeout=30,
        )

    def test_target_selectors_cannot_be_cli_options(self) -> None:
        with self.assertRaises(BoundaryError):
            AuthorizedVM(
                vm="--project=attacker-project",
                project=TARGET.project,
                account=TARGET.account,
                zone=TARGET.zone,
            )

    def test_only_command_is_exposed_to_model(self) -> None:
        self.assertEqual(TOOL_DEFINITION["function"]["name"], TOOL_NAME)
        parameters = TOOL_DEFINITION["function"]["parameters"]
        self.assertEqual(set(parameters["properties"]), {"command"})
        self.assertEqual(parameters["required"], ["command"])
        self.assertFalse(parameters["additionalProperties"])

    def test_tool_result_json_has_hard_utf8_boundary(self) -> None:
        content = bounded_tool_json(
            {
                "ok": True,
                "exit_code": 0,
                "stdout": 'quoted " output\n' * 10_000,
                "stderr": "warning\n" * 10_000,
            },
            512,
        )

        self.assertLessEqual(len(content.encode("utf-8")), 512)
        parsed = json.loads(content)
        self.assertTrue(parsed["result_truncated"])


class ToolLoopTests(unittest.TestCase):
    def test_malformed_tool_arguments_are_returned_without_execution(self) -> None:
        client = _FakeClient(
            [
                _completion(_tool_message("call-bad-json", "{not-json")),
                _completion({"role": "assistant", "content": "recovered"}),
            ]
        )
        executor = _FakeExecutor()

        result = run_tool_loop(
            "inspect the build",
            model="super",
            client=client,
            executor=executor,
            max_steps=2,
        )

        self.assertEqual(executor.calls, [])
        self.assertEqual(result.text, "recovered")
        tool_message = client.requests[1][0]["messages"][-1]
        self.assertEqual(tool_message["role"], "tool")
        self.assertEqual(tool_message["tool_call_id"], "call-bad-json")
        error = json.loads(tool_message["content"])
        self.assertFalse(error["ok"])
        self.assertEqual(error["error"]["kind"], "invalid_tool_arguments")

    def test_raw_assistant_message_and_tool_id_progress_unchanged(self) -> None:
        raw_assistant = _tool_message(
            "call-original-123", json.dumps({"command": "ps -p 266335 -o pid,ppid"})
        )
        raw_assistant["reasoning_details"] = [
            {"type": "reasoning.text", "text": "check process first"}
        ]
        raw_assistant["provider_extension"] = {"opaque": [1, 2, 3]}
        client = _FakeClient(
            [
                _completion(raw_assistant),
                _completion({"role": "assistant", "content": "still running"}),
            ]
        )
        executor = _FakeExecutor(
            {"ok": True, "exit_code": 0, "stdout": "x" * 20_000, "stderr": ""}
        )

        result = run_tool_loop(
            "watch every step",
            model="super",
            client=client,
            executor=executor,
            max_steps=3,
            max_tokens=2500,
            max_tool_result_bytes=512,
        )

        first_body = client.requests[0][0]
        self.assertEqual(first_body["messages"], [
            {"role": "user", "content": "watch every step"}
        ])
        self.assertNotIn("system", [m["role"] for m in first_body["messages"]])
        self.assertEqual(first_body["tools"], [TOOL_DEFINITION])
        self.assertFalse(first_body["stream"])
        self.assertEqual(first_body["max_tokens"], 2500)

        second_messages = client.requests[1][0]["messages"]
        self.assertEqual(second_messages[1], raw_assistant)
        self.assertEqual(second_messages[1]["tool_calls"][0]["id"], "call-original-123")
        tool_result = second_messages[2]
        self.assertEqual(tool_result["tool_call_id"], "call-original-123")
        self.assertLessEqual(len(tool_result["content"].encode("utf-8")), 512)
        self.assertTrue(json.loads(tool_result["content"])["result_truncated"])
        self.assertEqual(executor.calls[0][0], "ps -p 266335 -o pid,ppid")
        self.assertEqual(result.tool_steps, 1)
        self.assertEqual(result.text, "still running")

    def test_max_steps_stops_before_an_extra_remote_command(self) -> None:
        client = _FakeClient(
            [
                _completion(_tool_message("call-1", '{"command":"true"}')),
                _completion(_tool_message("call-2", '{"command":"false"}')),
            ]
        )
        executor = _FakeExecutor()

        with self.assertRaises(LimitReached):
            run_tool_loop(
                "bounded run",
                model="super",
                client=client,
                executor=executor,
                max_steps=1,
            )

        self.assertEqual([call[0] for call in executor.calls], ["true"])

    def test_progress_covers_each_boundary_without_prompt_output_or_secrets(self) -> None:
        secret = "do-not-log-this-token"
        command = (
            f"API_TOKEN={secret} curl --token {secret} https://example.test/status\n"
            "printf 'remote output is private'"
        )
        client = _FakeClient(
            [
                _completion(_tool_message(
                    "call-progress", json.dumps({"command": command})
                )),
                _completion({"role": "assistant", "content": "final private answer"}),
            ]
        )
        executor = _FakeExecutor(
            {"ok": False, "exit_code": 7, "stdout": "private remote output"}
        )
        events: list[str] = []

        run_tool_loop(
            "private user prompt",
            model="super",
            client=client,
            executor=executor,
            progress=events.append,
        )

        self.assertEqual(len(events), 4)
        self.assertEqual(events[0], "completion=1 decision=tool_calls count=1")
        self.assertIn("tool_step=1 tool=run_on_authorized_vm command=", events[1])
        self.assertIn("API_TOKEN=<redacted>", events[1])
        self.assertIn("--token=<redacted>", events[1])
        self.assertNotIn(secret, "\n".join(events))
        self.assertNotIn("private user prompt", "\n".join(events))
        self.assertNotIn("private remote output", "\n".join(events))
        self.assertNotIn("final private answer", "\n".join(events))
        self.assertNotIn("\n", events[1])
        self.assertLessEqual(len(events[1]), 220)
        self.assertEqual(
            events[2], "tool_step=1 result ok=false exit=7 timed_out=false"
        )
        self.assertEqual(events[3], "completion=2 decision=final")


class HTTPClientTests(unittest.TestCase):
    def test_nonstreaming_post_targets_exact_chat_completions_path(self) -> None:
        captured: dict = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit: int) -> bytes:
                captured["read_limit"] = limit
                return json.dumps(_completion({
                    "role": "assistant", "content": "done"
                })).encode()

        def opener(request, *, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return Response()

        client = ChatCompletionsClient(
            "http://127.0.0.1:8055/v1/chat/completions",
            api_key="test-key",
            timeout_s=12,
            max_response_bytes=4096,
            opener=opener,
        )
        body = {"model": "super", "messages": [], "stream": False}

        response = client.complete(body, timeout_s=7)

        request = captured["request"]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            request.full_url, "http://127.0.0.1:8055/v1/chat/completions"
        )
        self.assertEqual(json.loads(request.data), body)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(captured["timeout"], 7)
        self.assertEqual(captured["read_limit"], 4097)
        self.assertEqual(response["choices"][0]["message"]["content"], "done")


if __name__ == "__main__":
    unittest.main()
