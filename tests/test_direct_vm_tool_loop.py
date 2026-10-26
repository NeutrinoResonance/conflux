from __future__ import annotations

import copy
import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts.direct_vm_tool_loop import (
    CONTAINER_TOOL_DEFINITION,
    CONTAINER_TOOL_NAME,
    CONTAINER_WRITE_TOOL_DEFINITION,
    CONTAINER_WRITE_TOOL_NAME,
    TOOL_DEFINITION,
    TOOL_DEFINITIONS,
    TOOL_NAME,
    START_JOB_TOOL,
    AuthorizedContainer,
    AuthorizedContainerExecutor,
    AuthorizedVM,
    AuthorizedVMExecutor,
    BoundaryError,
    ChatCompletionsClient,
    DirectClientError,
    LimitReached,
    bounded_tool_json,
    load_transcript,
    require_supervised_virtual_model,
    ToolLoopResult,
    resolve_hold_with_senate,
    run_tool_loop,
    save_transcript,
)


TARGET = AuthorizedVM(
    vm="conflux-netbsd-arm64",
    project="project96-sar",
    account="gce-operator@example.com",
    zone="us-central1-a",
)


def _completion(message: dict) -> dict:
    return {
        "id": "chatcmpl-test",
        "choices": [{"index": 0, "message": message}],
    }


def _tool_message(call_id: str, arguments: str, name: str = TOOL_NAME) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
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


class _FakeJobExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, operation, arguments, *, context=None):
        self.calls.append((operation, copy.deepcopy(arguments), dict(context or {})))
        return {
            "ok": True, "state": "running",
            "job_id": "job_0123456789abcdef01234567",
            "stdout_cursor": 0, "stderr_cursor": 0,
        }


class AuthorizedBoundaryTests(unittest.TestCase):
    def test_explicit_provider_model_is_rejected_before_tool_exposure(self) -> None:
        require_supervised_virtual_model("super")
        with self.assertRaisesRegex(BoundaryError, "unsupervised passthrough"):
            require_supervised_virtual_model("deepseek-v4-pro-go")

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
                "conflux-netbsd-arm64",
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
        for tool in TOOL_DEFINITIONS:
            props = tool["function"]["parameters"]["properties"]
            self.assertNotIn("backend", props)
            self.assertNotIn("target", props)

    def test_locked_container_wraps_only_the_fixed_remote_namespace(self) -> None:
        runner = Mock(
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=b"clean\n", stderr=b""
            )
        )
        transport = AuthorizedVMExecutor(TARGET, timeout_s=90, runner=runner)
        executor = AuthorizedContainerExecutor(
            transport,
            AuthorizedContainer("tb-fix-git", "/app/personal-site"),
        )

        result = executor.run("git status --short", timeout_s=30)

        remote_command = runner.call_args.args[0][-1]
        self.assertEqual(
            remote_command,
            "sudo docker exec --workdir /app/personal-site tb-fix-git "
            "bash -lc 'git status --short'",
        )
        self.assertEqual(result["execution"]["backend"], "gce_container")
        self.assertEqual(result["execution"]["container"], "tb-fix-git")
        self.assertEqual(result["execution"]["working_dir"], "/app/personal-site")
        self.assertTrue(result["execution"]["remote_only"])

    def test_locked_container_tool_exposes_no_selectors(self) -> None:
        self.assertEqual(
            CONTAINER_TOOL_DEFINITION["function"]["name"], CONTAINER_TOOL_NAME
        )
        parameters = CONTAINER_TOOL_DEFINITION["function"]["parameters"]
        self.assertEqual(set(parameters["properties"]), {"command"})
        self.assertEqual(parameters["required"], ["command"])
        self.assertFalse(parameters["additionalProperties"])

    def test_locked_container_writer_exposes_only_path_and_content(self) -> None:
        self.assertEqual(
            CONTAINER_WRITE_TOOL_DEFINITION["function"]["name"],
            CONTAINER_WRITE_TOOL_NAME,
        )
        parameters = CONTAINER_WRITE_TOOL_DEFINITION["function"]["parameters"]
        self.assertEqual(set(parameters["properties"]), {"path", "content"})
        self.assertEqual(set(parameters["required"]), {"path", "content"})
        self.assertFalse(parameters["additionalProperties"])
        for selector in ("backend", "vm", "project", "account", "zone", "container"):
            self.assertNotIn(selector, parameters["properties"])

    def test_locked_container_writer_constructs_atomic_remote_operation(self) -> None:
        runner = Mock(
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=b"/app/gpt2.c 22\n0123456789abcdef  /app/gpt2.c\n",
                stderr=b"",
            )
        )
        executor = AuthorizedContainerExecutor(
            AuthorizedVMExecutor(TARGET, timeout_s=90, runner=runner),
            AuthorizedContainer("tb-gpt2-codegolf", "/app"),
        )
        content = "int main(void){return 0;}\n"

        result = executor.write_file("/app/gpt2.c", content, timeout_s=30)

        remote_command = runner.call_args.args[0][-1]
        self.assertIn("sudo docker exec --workdir /app tb-gpt2-codegolf", remote_command)
        self.assertIn("base64 -d", remote_command)
        self.assertIn(base64.b64encode(content.encode()).decode(), remote_command)
        self.assertNotIn(content, remote_command)
        self.assertIn("/app/gpt2.c.conflux-write-tmp", remote_command)
        self.assertEqual(result["write"]["path"], "/app/gpt2.c")
        self.assertEqual(result["write"]["bytes"], len(content.encode()))
        self.assertTrue(result["write"]["atomic_replace"])
        self.assertEqual(result["execution"]["backend"], "gce_container")

    def test_locked_container_writer_rejects_escaped_or_ambiguous_paths(self) -> None:
        runner = Mock()
        executor = AuthorizedContainerExecutor(
            AuthorizedVMExecutor(TARGET, runner=runner),
            AuthorizedContainer("tb-gpt2-codegolf", "/app"),
        )
        for path in ("relative.c", "/tmp/gpt2.c", "/app/../tmp/gpt2.c", "/app"):
            with self.subTest(path=path):
                with self.assertRaises(BoundaryError):
                    executor.write_file(path, "content")
        runner.assert_not_called()

    def test_container_selector_and_workdir_fail_closed(self) -> None:
        with self.assertRaises(BoundaryError):
            AuthorizedContainer("--privileged", "/app")
        with self.assertRaises(BoundaryError):
            AuthorizedContainer("task", "relative/path")

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
    def test_human_hold_is_removed_from_resumable_protocol_checkpoint(self) -> None:
        notice = (
            "[conflux] Human approval is required before this action can run. "
            "Review pending action act_test in the operator interface."
        )
        client = _FakeClient([
            _completion({"role": "assistant", "content": notice}),
        ])
        snapshots: list[list[dict]] = []

        result = run_tool_loop(
            "approve exactly", model="super", client=client,
            executor=_FakeExecutor(), checkpoint=snapshots.append,
        )

        self.assertEqual(result.text, notice)
        self.assertEqual(snapshots[-1], [
            {"role": "user", "content": "approve exactly"}
        ])
        self.assertEqual(result.transcript, snapshots[-1])

    def test_transcript_checkpoint_is_atomic_and_task_bound(self) -> None:
        messages = [{"role": "user", "content": "task"}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.json"
            tools = [{"type": "function", "function": {"name": "recorded", "parameters": {}}}]
            save_transcript(path, "task", messages, tools=tools)

            self.assertEqual(load_transcript(path, "task"), messages)
            self.assertEqual(json.loads(path.read_text())["tools"], tools)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(
                DirectClientError, "does not match this task or is malformed"
            ):
                load_transcript(path, "different task")

    def test_deterministic_governor_block_is_bounded_correction_context(self) -> None:
        blocked = (
            "[conflux] Action blocked: a trailing command masks the meaningful "
            "process exit status"
        )
        client = _FakeClient([
            _completion({"role": "assistant", "content": blocked}),
            _completion(_tool_message(
                "call-corrected", '{"command":"git status --short"}',
                CONTAINER_TOOL_NAME,
            )),
            _completion({"role": "assistant", "content": "verified"}),
        ])
        executor = _FakeExecutor()
        executor.tool_name = CONTAINER_TOOL_NAME
        events: list[str] = []

        result = run_tool_loop(
            "recover the repository", model="super", client=client,
            executor=executor, tool_definitions=[CONTAINER_TOOL_DEFINITION],
            progress=events.append,
        )

        retry_messages = client.requests[1][0]["messages"]
        self.assertEqual(
            retry_messages[0],
            {"role": "user", "content": "recover the repository"},
        )
        self.assertEqual(retry_messages[-1]["role"], "user")
        self.assertEqual(retry_messages[-1]["name"], "conflux_governor")
        self.assertIn("rejection is not task completion", retry_messages[-1]["content"])
        self.assertNotIn(blocked, [
            message.get("content") for message in retry_messages
            if message.get("role") == "assistant"
        ])
        messages_after_correction = client.requests[2][0]["messages"]
        self.assertEqual(
            [m["content"] for m in messages_after_correction if m["role"] == "user"],
            ["recover the repository"],
        )
        self.assertFalse(any(
            str(m.get("content") or "").startswith("conflux governor correction:")
            for m in messages_after_correction
        ))
        self.assertEqual(executor.calls[0][0], "git status --short")
        self.assertTrue(any(
            "decision=governor_retry attempt=1" in event for event in events
        ))
        self.assertEqual(result.text, "verified")

    def test_correction_budget_resets_after_an_executed_action(self) -> None:
        blocked = {"role": "assistant", "content": "[conflux] Action blocked: rejected"}
        client = _FakeClient([
            _completion(blocked),
            _completion(_tool_message("call-1", '{"command":"true"}')),
            _completion(blocked),
            _completion({"role": "assistant", "content": "done"}),
        ])
        result = run_tool_loop(
            "two separate corrections", model="super", client=client,
            executor=_FakeExecutor(), max_governor_retries=1,
        )
        self.assertEqual(result.text, "done")

    def test_proxy_incomplete_resends_the_request_and_is_bounded(self) -> None:
        incomplete = {"role": "assistant", "content": "[conflux] Incomplete: bounded reconsideration exhausted"}
        client = _FakeClient([
            _completion(incomplete),
            _completion(_tool_message("call-1", '{"command":"true"}')),
            _completion(incomplete),
            _completion({"role": "assistant", "content": "done"}),
        ])
        result = run_tool_loop("resumable", model="super", client=client,
                               executor=_FakeExecutor(), max_incomplete_retries=1)
        self.assertEqual(result.text, "done")
        self.assertFalse(any(str(m.get("content") or "").startswith("[conflux] Incomplete")
                             for m in result.transcript))
        client = _FakeClient([_completion(incomplete), _completion(incomplete)])
        with self.assertRaisesRegex(LimitReached, "proxy remained incomplete"):
            run_tool_loop("stuck", model="super", client=client,
                          executor=_FakeExecutor(), max_incomplete_retries=1)

    def test_governor_correction_attempts_are_bounded(self) -> None:
        blocked = "[conflux] Action blocked: rejected"
        client = _FakeClient([
            _completion({"role": "assistant", "content": blocked}),
            _completion({"role": "assistant", "content": blocked}),
        ])
        snapshots: list[list[dict]] = []

        with self.assertRaisesRegex(
            LimitReached, "maximum governor correction attempts reached"
        ):
            run_tool_loop(
                "bounded correction", model="super", client=client,
                executor=_FakeExecutor(), max_governor_retries=1,
                checkpoint=snapshots.append,
            )
        self.assertEqual(snapshots[-1][-1]["role"], "user")
        self.assertEqual(snapshots[-1][-1]["name"], "conflux_governor")
        self.assertTrue(snapshots[-1][-1]["content"].startswith(
            "conflux governor correction:"
        ))
        self.assertFalse(any(
            str(message.get("content") or "").startswith("[conflux] Action blocked")
            for message in snapshots[-1]
        ))

    def test_empty_assistant_response_is_corrected_not_accepted_as_final(self) -> None:
        client = _FakeClient([
            _completion({"role": "assistant", "content": None}),
            _completion({
                "role": "assistant", "content": "Evidence-based final answer",
            }),
        ])
        events: list[str] = []

        result = run_tool_loop(
            "diagnose safely", model="super", client=client,
            executor=_FakeExecutor(), max_governor_retries=2,
            progress=events.append,
        )

        self.assertEqual(result.text, "Evidence-based final answer")
        self.assertEqual(result.tool_steps, 0)
        self.assertIn("completion=1 decision=protocol_retry attempt=1", events)
        self.assertFalse(any(
            message.get("role") == "assistant"
            and message.get("content") is None
            and not message.get("tool_calls")
            for message in result.transcript
        ))
        self.assertEqual(result.transcript[-2].get("name"), "conflux_governor")

    def test_resume_discards_empty_reply_after_active_correction(self) -> None:
        task = "resume corrected answer"
        initial = [
            {"role": "user", "content": task},
            {
                "role": "user", "name": "conflux_governor",
                "content": (
                    "conflux governor correction: Answer without another "
                    "tool call."
                ),
            },
            {"role": "assistant", "content": None},
        ]
        client = _FakeClient([
            _completion({"role": "assistant", "content": "Recovered final answer"}),
        ])

        result = run_tool_loop(
            task, model="super", client=client, executor=_FakeExecutor(),
            initial_messages=initial,
        )

        self.assertEqual(result.text, "Recovered final answer")
        request_messages = client.requests[0][0]["messages"]
        self.assertEqual(request_messages[-1].get("name"), "conflux_governor")
        self.assertFalse(any(
            message.get("role") == "assistant"
            and message.get("content") is None
            for message in request_messages
        ))

    def test_container_tool_dispatches_only_through_container_executor(self) -> None:
        client = _FakeClient([
            _completion(_tool_message(
                "call-container", '{"command":"git status --short"}',
                CONTAINER_TOOL_NAME,
            )),
            _completion({"role": "assistant", "content": "container checked"}),
        ])
        executor = _FakeExecutor()
        executor.tool_name = CONTAINER_TOOL_NAME

        result = run_tool_loop(
            "inspect the task container", model="super", client=client,
            executor=executor, tool_definitions=[CONTAINER_TOOL_DEFINITION],
        )

        self.assertEqual(executor.calls[0][0], "git status --short")
        self.assertEqual(result.text, "container checked")

    def test_container_writer_dispatches_without_logging_file_content(self) -> None:
        secret_content = "int main(void){return 731;}\n"
        client = _FakeClient([
            _completion(_tool_message(
                "call-write",
                json.dumps({"path": "/app/gpt2.c", "content": secret_content}),
                CONTAINER_WRITE_TOOL_NAME,
            )),
            _completion({"role": "assistant", "content": "source written"}),
        ])
        runner = Mock(
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=b"written\n", stderr=b""
            )
        )
        executor = AuthorizedContainerExecutor(
            AuthorizedVMExecutor(TARGET, runner=runner),
            AuthorizedContainer("tb-gpt2-codegolf", "/app"),
        )
        events: list[str] = []

        result = run_tool_loop(
            "write the source", model="super", client=client, executor=executor,
            tool_definitions=[
                CONTAINER_TOOL_DEFINITION, CONTAINER_WRITE_TOOL_DEFINITION,
            ],
            progress=events.append,
        )

        self.assertEqual(result.text, "source written")
        self.assertTrue(any(
            "tool=write_file_in_locked_container path=/app/gpt2.c" in event
            and f"bytes={len(secret_content.encode())}" in event
            for event in events
        ))
        self.assertNotIn(secret_content, "\n".join(events))
        self.assertEqual(runner.call_count, 1)

    def test_durable_start_dispatches_through_locked_job_executor(self) -> None:
        client = _FakeClient([
            _completion(_tool_message(
                "call-job",
                json.dumps({"command": "sleep 10", "label": "build",
                            "timeout_s": 30}),
                START_JOB_TOOL,
            )),
            _completion({"role": "assistant", "content": "job started"}),
        ])
        executor = _FakeExecutor()
        jobs = _FakeJobExecutor()

        result = run_tool_loop(
            "start the background build", model="super", client=client,
            executor=executor, job_executor=jobs,
        )

        self.assertEqual(executor.calls, [])
        self.assertEqual(jobs.calls[0][0], "start")
        self.assertEqual(jobs.calls[0][1]["command"], "sleep 10")
        self.assertTrue(jobs.calls[0][2]["session"].startswith("direct_"))
        self.assertEqual(result.text, "job started")

    def test_durable_only_capability_set_rejects_raw_shell_fallback(self) -> None:
        from conflux.durable_jobs import JOB_TOOL_DEFINITIONS

        client = _FakeClient([
            _completion(_tool_message("call-shell", '{"command":"ps aux"}')),
            _completion({"role": "assistant", "content": "fallback refused"}),
        ])
        executor = _FakeExecutor()
        result = run_tool_loop(
            "typed jobs only", model="super", client=client, executor=executor,
            tool_definitions=JOB_TOOL_DEFINITIONS,
        )
        self.assertEqual(executor.calls, [])
        error = json.loads(client.requests[1][0]["messages"][-1]["content"])
        self.assertEqual(error["error"]["kind"], "unauthorized_tool")
        self.assertEqual(result.text, "fallback refused")

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
        self.assertEqual(first_body["tools"], TOOL_DEFINITIONS)
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

    def test_before_tool_observes_each_call_before_it_runs(self) -> None:
        client = _FakeClient(
            [
                _completion(_tool_message("call-1", '{"command":"ls /tmp"}')),
                _completion({"role": "assistant", "content": "done"}),
            ]
        )
        executor = _FakeExecutor()
        seen = []

        def before_tool(step, tool, arguments, messages):
            seen.append((step, tool, dict(arguments), len(executor.calls), messages[-1]["role"]))

        run_tool_loop(
            "observed run", model="super", client=client, executor=executor,
            before_tool=before_tool,
        )

        self.assertEqual(seen, [(1, TOOL_NAME, {"command": "ls /tmp"}, 0, "assistant")])
        self.assertEqual([call[0] for call in executor.calls], ["ls /tmp"])

    def test_hold_notice_ids_cover_single_and_batch_holds(self) -> None:
        from scripts.direct_vm_tool_loop import _HOLD_IDS

        single = "Review pending action act_1 in the operator interface."
        batch = "Review pending actions act_1, act_2 in the operator interface."
        self.assertEqual(_HOLD_IDS.search(single).group(1), "act_1")
        self.assertEqual(_HOLD_IDS.search(batch).group(1), "act_1, act_2")

    def test_senate_resolves_holds_through_operator_endpoint(self) -> None:
        import scripts.direct_vm_tool_loop as loop

        class _Verdict:
            def __init__(self, danger, how):
                self.danger, self.how = danger, how
                self.objections = [] if how in ("", "none") else [
                    type("R", (), {"model": "glm-5.2", "normalized": danger or 0.0, "how": how})()]

            def approves(self, below, method="max", quorum=1):
                return None if self.danger is None else self.danger < below

        hold = {"role": "assistant", "content": (
            "[conflux] Human approval is required before this action can run. "
            "Review pending action act_1 in the operator interface.")}
        transcript = [{"role": "user", "content": "task"}]
        for danger, expected in ((0.2, "approve"), (0.9, "deny")):
            posted = []

            def admin(endpoint, path, body=None):
                if body is None:
                    return {"items": [{"action_id": "act_1", "proposal": {
                        "tool_name": TOOL_NAME, "arguments": {"command": "rm -rf ~/x"}}}]}
                posted.append((path, body))
                return {}

            original = loop._admin_json
            loop._admin_json = admin
            try:
                messages = resolve_hold_with_senate(
                    ToolLoopResult(hold, transcript, 0),
                    senate=lambda step, tool, args, msgs: _Verdict(danger, "deletes work"),
                    endpoint="http://127.0.0.1:1/v1/chat/completions",
                    approve_below=0.5, step=3, progress=lambda event: None,
                )
            finally:
                loop._admin_json = original
            self.assertEqual(posted[0][0], "/admin/actions/act_1/decision")
            self.assertEqual(posted[0][1]["decision"], expected)
            self.assertEqual(messages, transcript)
            self.assertEqual(posted[0][1]["concerns"][0]["model"], "glm-5.2")
            self.assertEqual(posted[0][1]["concerns"][0]["how"], "deletes work")

    def test_senate_outage_is_retried_before_failing_closed(self) -> None:
        import scripts.direct_vm_tool_loop as loop

        class _Verdict:
            def __init__(self, danger, how):
                self.danger, self.how = danger, how
                self.objections = [] if how in ("", "none") else [
                    type("R", (), {"model": "glm-5.2", "normalized": danger or 0.0, "how": how})()]

            def approves(self, below, method="max", quorum=1):
                return None if self.danger is None else self.danger < below

        hold = {"role": "assistant", "content": (
            "Review pending action act_1 in the operator interface.")}
        transcript = [{"role": "user", "content": "task"}]

        def admin_into(posted):
            def admin(endpoint, path, body=None):
                if body is None:
                    return {"items": [{"action_id": "act_1", "proposal": {
                        "tool_name": TOOL_NAME, "arguments": {"command": "ls"}}}]}
                posted.append(body)
                return {}
            return admin

        for answers, expected, waits in (
            ([None, _Verdict(None, ""), _Verdict(0.1, "none")], "approve", [60.0, 120.0]),
            ([None] * 5, "deny", [60.0, 120.0, 240.0, 480.0]),
        ):
            posted, slept, queue = [], [], list(answers)
            original = loop._admin_json
            loop._admin_json = admin_into(posted)
            try:
                resolve_hold_with_senate(
                    ToolLoopResult(hold, transcript, 0),
                    senate=lambda *a: queue.pop(0),
                    endpoint="http://127.0.0.1:1/v1/chat/completions",
                    approve_below=0.5, step=1, progress=lambda event: None,
                    sleep=slept.append,
                )
            finally:
                loop._admin_json = original
            self.assertEqual(posted[0]["decision"], expected)
            self.assertEqual(slept, waits)

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
        self.assertIn("tool_step=1 tool=run_on_authorized_gce_vm command=", events[1])
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
    def test_client_sends_one_stable_conversation_id(self) -> None:
        from scripts.direct_vm_tool_loop import run_conversation_id

        seen = []

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, limit):
                return json.dumps(_completion({"role": "assistant", "content": "ok"})).encode()

        def opener(request, timeout):
            seen.append(request.get_header("X-conflux-conversation"))
            return _Response()

        conversation = run_conversation_id("task", "/tmp/t.json")
        self.assertEqual(conversation, run_conversation_id("task", "/tmp/t.json"))
        self.assertNotEqual(conversation, run_conversation_id("task", "/tmp/u.json"))
        client = ChatCompletionsClient(
            "http://127.0.0.1:1/v1/chat/completions", opener=opener,
            conversation_id=conversation,
        )
        client.complete({"model": "super"})
        client.complete({"model": "super"})
        self.assertEqual(seen, [conversation, conversation])

    def test_unavailable_proxy_is_retried_with_backoff_then_fails(self) -> None:
        import urllib.error

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit: int) -> bytes:
                return json.dumps(_completion({"role": "assistant", "content": "done"})).encode()

        outcomes = [503, 503, None]

        def opener(request, timeout):
            code = outcomes.pop(0)
            if code:
                raise urllib.error.HTTPError(request.full_url, code, "unavailable", {}, None)
            return Response()

        waits: list[float] = []
        client = ChatCompletionsClient("http://127.0.0.1:1/v1/chat/completions", opener=opener)
        client._sleep = waits.append
        self.assertEqual(client.complete({"model": "super"})["choices"][0]["message"]["content"], "done")
        self.assertEqual(waits, [60.0, 120.0])
        outcomes[:] = [503] * 3
        client.unavailable_retries = 2
        with self.assertRaisesRegex(DirectClientError, "completion HTTP 503"):
            client.complete({"model": "super"})

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


class InterruptedResumeTests(unittest.TestCase):
    def test_unanswered_released_calls_get_an_explicit_interrupted_result(self) -> None:
        from scripts.direct_vm_tool_loop import close_interrupted_calls, INTERRUPTED_RESULT
        call = lambda i: {"id": i, "type": "function", "function": {"name": "run", "arguments": "{}"}}
        messages = [{"role": "user", "content": "task"},
                    {"role": "assistant", "content": None, "tool_calls": [call("a"), call("b")]},
                    {"role": "tool", "tool_call_id": "a", "content": "done"}]
        closed = close_interrupted_calls(list(messages))
        self.assertEqual(closed[-1], {"role": "tool", "tool_call_id": "b", "content": INTERRUPTED_RESULT})
        self.assertEqual(close_interrupted_calls(list(closed)), closed)
