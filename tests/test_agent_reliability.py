from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from llm_super.checkpoint import Checkpoints
from llm_super.config import Config, Execution, Model, Provider, Supervision
from llm_super.control import PAUSED_BOUNDARY_NOTICE, PAUSED_NOTICE, ControlState
from llm_super.history import History
from llm_super.library import Library
from llm_super.orchestrator import Orchestrator
from llm_super import proxy
from llm_super.providers import ChatResult
from llm_super.trace import Trace
from llm_super.verifier import VerifyReport


def _config(*, budget: float = 0.50) -> Config:
    provider = Provider(
        name="test", base_url="https://invalid.test/v1", key_source="env:TEST_KEY"
    )
    model = Model(
        name="executor", provider="test", id="executor-id", family="test-family",
        roles=("executor",), logprobs=False, top_logprobs_max=5,
        price_in_per_m=1.0, price_out_per_m=1.0,
    )
    return Config(
        providers={"test": provider}, models={"executor": model},
        default_executor="executor", utility="executor", verifier_pool=[],
        supervision=Supervision(
            confirm_new_sessions=True, budget_usd_per_task=budget,
            turn_timeout_s=10, stateful_chat_endpoint=True,
        ),
        execution=Execution(backend="off"),
        learned_routing=False,
    )


def _response(*, content: str = "done", tool_calls: list[dict] | None = None,
              prompt_tokens: int = 2, completion_tokens: int = 3) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-test", "object": "chat.completion", "created": 1,
        "model": "executor-id",
        "choices": [{"index": 0, "message": message,
                     "finish_reason": "tool_calls" if tool_calls else "stop"}],
        "usage": {"prompt_tokens": prompt_tokens,
                  "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
    }


class _Request:
    def __init__(self, body: dict):
        self._body = body

    async def json(self) -> dict:
        return self._body


class _ProxyOrchestrator:
    def __init__(self):
        self.calls = 0

    async def run_tool_turn(self, session: str, body: dict, **_kw) -> dict:
        self.calls += 1
        return _response(tool_calls=[{
            "id": "call-1", "type": "function",
            "function": {"name": "terminal", "arguments": "{}"},
        }])

    async def run_turn(self, session: str, messages: list[dict],
                       **_kw):  # pragma: no cover
        raise AssertionError("plain supervised path was not expected")


class _RawClient:
    def __init__(self, responses: list[dict], control: ControlState | None = None,
                 pause_during_call: bool = False):
        self.responses = list(responses)
        self.control = control
        self.pause_during_call = pause_during_call
        self.calls = 0

    async def raw_chat(self, model: Model, body: dict) -> dict:
        self.calls += 1
        if self.pause_during_call and self.control is not None:
            self.control.paused = True
        return self.responses.pop(0)


class _PlainClient:
    def __init__(self, result: ChatResult) -> None:
        self.result = result
        self.calls = 0

    async def chat(self, *args, **kwargs) -> ChatResult:
        self.calls += 1
        return self.result


class _Verifier:
    def __init__(self, *, error: Exception | None = None,
                 reports: list[VerifyReport] | None = None):
        self.error = error
        self.reports = list(reports or [])
        self.calls = 0

    async def verify(self, **kwargs) -> VerifyReport:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.reports.pop(0)


class ProxyGateAndPauseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._old_state = dict(proxy.state)
        proxy.state.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "trace.db")
        trace = Trace(self.db)
        history = History(self.db)
        library = Library(self.db)
        checkpoints = Checkpoints(self.db)
        self.cfg = _config()
        self.control = ControlState()
        self.orch = _ProxyOrchestrator()
        proxy.state.update(
            cfg=self.cfg, control=self.control, trace=trace, history=history,
            library=library, checkpoints=checkpoints, armed_sessions=set(),
            orch=self.orch,
        )

    def tearDown(self) -> None:
        proxy.state.clear()
        proxy.state.update(self._old_state)
        self._tmp.cleanup()

    @staticmethod
    def _body(first_user: str = "compile NetBSD") -> dict:
        return {
            "model": "super", "stream": False,
            "messages": [{"role": "user", "content": first_user}],
            "tools": [{"type": "function", "function": {
                "name": "terminal", "parameters": {"type": "object"},
            }}],
        }

    async def test_persisted_agent_session_is_known_after_restart(self) -> None:
        body = self._body()
        session = proxy._session_id(body["messages"])

        # Accepted agent steps create a durable library row even though they
        # intentionally do not create History.turns rows mid-tool-loop.
        proxy.state["library"].touch_session(session, "compile NetBSD")
        self.assertEqual(proxy.state["history"].recent_turns(session), [])

        # Reopen the library and clear process-local gate state: the conditions
        # a fresh proxy lifespan sees after restart.
        proxy.state["library"] = Library(self.db)
        proxy.state["armed_sessions"] = set()
        response = await proxy.chat_completions(_Request(body))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.orch.calls, 1)
        payload = json.loads(response.body)
        self.assertEqual(payload["choices"][0]["finish_reason"], "tool_calls")

    async def test_fresh_session_still_hits_confirmation_gate(self) -> None:
        response = await proxy.chat_completions(_Request(self._body("brand new")))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.orch.calls, 0)
        payload = json.loads(response.body)
        self.assertIn("new-conversation gate", payload["choices"][0]["message"]["content"])
        self.assertEqual(payload["usage"], {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        })

    async def test_control_command_reports_zero_usage(self) -> None:
        response = await proxy.chat_completions(_Request(self._body("!status")))

        self.assertEqual(self.orch.calls, 0)
        payload = json.loads(response.body)
        self.assertEqual(payload["usage"], {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        })

    async def test_paused_virtual_agent_request_spends_nothing_then_resumes(self) -> None:
        body = self._body("pause boundary")
        self.control.paused = True

        response = await proxy.chat_completions(_Request(body))

        self.assertEqual(self.orch.calls, 0)
        payload = json.loads(response.body)
        self.assertEqual(payload["choices"][0]["message"]["content"], PAUSED_NOTICE)
        self.assertEqual(payload["usage"], {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        })
        self.assertEqual(proxy.state["trace"].recent(1)[0]["kind"], "pause_block")

        self.control.paused = False
        session = proxy._session_id(body["messages"])
        proxy.state["library"].touch_session(session, "pause boundary")
        await proxy.chat_completions(_Request(body))
        self.assertEqual(self.orch.calls, 1)

    async def test_paused_streaming_agent_request_is_blocked_before_orchestrator(self) -> None:
        body = self._body("streaming pause boundary")
        body["stream"] = True
        self.control.paused = True

        response = await proxy.chat_completions(_Request(body))
        chunks = [chunk async for chunk in response.body_iterator]
        stream_text = "".join(
            chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks
        )

        self.assertEqual(self.orch.calls, 0)
        self.assertIn(PAUSED_NOTICE, stream_text)
        self.assertIn("data: [DONE]", stream_text)


class PlainTurnUsageTests(unittest.IsolatedAsyncioTestCase):
    async def test_turn_report_matches_executor_and_verifier_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "trace.db")
            trace = Trace(db)
            client = _PlainClient(ChatResult(
                text="verified answer", tokens_in=13, tokens_out=8,
                cost_usd=0.000021,
            ))
            control = ControlState(contract_enabled=False, plan_mode="off")
            orch = Orchestrator(
                _config(), client, trace, control,
                checkpoints=Checkpoints(db), history=History(db),
            )
            orch.verifier = _Verifier(reports=[VerifyReport(
                score=0.9, passed=True, verifier="reviewer",
                cost_usd=0.000022, tokens_in=19, tokens_out=3,
            )])

            report = await orch.run_turn(
                "session-1", [{"role": "user", "content": "answer this"}]
            )

            self.assertEqual((report.tokens_in, report.tokens_out), (32, 11))
            spent_events = [
                event for event in trace.recent(50)
                if event["task"] == report.task_id
                and event["kind"] in {"execute", "verify"}
            ]
            self.assertEqual(
                sum(event["tokens_in"] for event in spent_events),
                report.tokens_in,
            )
            self.assertEqual(
                sum(event["tokens_out"] for event in spent_events),
                report.tokens_out,
            )


class ToolTurnFinalizationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "trace.db")
        self.trace = Trace(self.db)
        self.history = History(self.db)
        self.body = {
            "model": "super",
            "messages": [{"role": "user", "content": "finish the task"}],
            "tools": [{"type": "function", "function": {
                "name": "terminal", "parameters": {"type": "object"},
            }}],
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _orch(self, client: _RawClient, *, budget: float = 0.50,
              control: ControlState | None = None,
              verifier: _Verifier | None = None) -> Orchestrator:
        orch = Orchestrator(
            _config(budget=budget), client, self.trace,
            control or ControlState(), history=self.history,
        )
        orch.verifier = verifier or _Verifier(reports=[VerifyReport(
            score=0.9, passed=True, verifier="reviewer",
        )])
        return orch

    def _assert_one_final_record(self, expected_text: str) -> None:
        exchanges = self.trace.exchanges(session="session-1")
        self.assertEqual([e["kind"] for e in exchanges],
                         ["client_request", "client_response"])
        turns = self.history.recent_turns("session-1")
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["response"], expected_text)

    async def test_already_paused_direct_call_makes_no_upstream_request(self) -> None:
        control = ControlState(paused=True)
        client = _RawClient([])
        result = await self._orch(client, control=control).run_tool_turn(
            "session-1", self.body
        )

        self.assertEqual(client.calls, 0)
        self.assertEqual(result["choices"][0]["message"]["content"], PAUSED_NOTICE)
        self._assert_one_final_record(PAUSED_NOTICE)

    async def test_pause_during_upstream_suppresses_new_tool_call(self) -> None:
        control = ControlState()
        tool_response = _response(tool_calls=[{
            "id": "call-1", "type": "function",
            "function": {"name": "terminal", "arguments": "{}"},
        }])
        client = _RawClient(
            [tool_response], control=control, pause_during_call=True
        )
        result = await self._orch(client, control=control).run_tool_turn(
            "session-1", self.body
        )

        self.assertEqual(client.calls, 1)
        self.assertNotIn("tool_calls", result["choices"][0]["message"])
        self.assertEqual(result["choices"][0]["message"]["content"],
                         PAUSED_BOUNDARY_NOTICE)
        self._assert_one_final_record(PAUSED_BOUNDARY_NOTICE)

    async def test_budget_exit_records_final_exchange_and_history(self) -> None:
        client = _RawClient([_response(content="budget answer")])
        verifier = _Verifier(error=AssertionError("verifier must not run"))
        result = await self._orch(
            client, budget=0.000001, verifier=verifier
        ).run_tool_turn("session-1", self.body)

        self.assertEqual(result["choices"][0]["message"]["content"], "budget answer")
        self.assertEqual(verifier.calls, 0)
        self._assert_one_final_record("budget answer")

    async def test_verifier_error_records_final_exchange_and_history(self) -> None:
        client = _RawClient([_response(content="unverified answer")])
        verifier = _Verifier(error=RuntimeError("reviewer unavailable"))
        result = await self._orch(client, verifier=verifier).run_tool_turn(
            "session-1", self.body
        )

        self.assertEqual(result["choices"][0]["message"]["content"],
                         "unverified answer")
        self.assertEqual(verifier.calls, 1)
        self._assert_one_final_record("unverified answer")

    async def test_exhausted_repair_loop_records_only_best_final(self) -> None:
        reports = [
            VerifyReport(score=0.4, passed=False, feedback="missing evidence",
                         verifier="reviewer"),
            VerifyReport(score=0.6, passed=False, feedback="still incomplete",
                         verifier="reviewer"),
        ]
        client = _RawClient([
            _response(content="first attempt"),
            _response(content="better second attempt"),
        ])
        result = await self._orch(
            client, verifier=_Verifier(reports=reports)
        ).run_tool_turn("session-1", self.body)

        self.assertEqual(client.calls, 2)
        self.assertEqual(result["choices"][0]["message"]["content"],
                         "better second attempt")
        self._assert_one_final_record("better second attempt")

    async def test_passed_final_records_history_but_tool_step_does_not(self) -> None:
        passed = VerifyReport(score=0.9, passed=True, verifier="reviewer")
        client = _RawClient([_response(content="verified answer")])
        await self._orch(
            client, verifier=_Verifier(reports=[passed])
        ).run_tool_turn("session-1", self.body)
        self._assert_one_final_record("verified answer")

        tool_trace = Trace(str(Path(self._tmp.name) / "tool.db"))
        tool_history = History(str(Path(self._tmp.name) / "tool.db"))
        tool_client = _RawClient([_response(tool_calls=[{
            "id": "call-2", "type": "function",
            "function": {"name": "terminal", "arguments": "{}"},
        }])])
        tool_orch = Orchestrator(
            _config(), tool_client, tool_trace, ControlState(), history=tool_history
        )
        await tool_orch.run_tool_turn("tool-session", self.body)
        self.assertEqual(tool_history.recent_turns("tool-session"), [])
        self.assertEqual(
            [e["kind"] for e in tool_trace.exchanges(session="tool-session")],
            ["client_request", "client_response"],
        )


if __name__ == "__main__":
    unittest.main()
