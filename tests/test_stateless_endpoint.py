"""The default /v1/chat/completions contract: one stateless supervised turn.

Legacy stateful behavior (hash identity, alias, gate, in-band !commands,
transcript-diff bookkeeping) is opt-in via supervision.stateful_chat_endpoint
and covered by the existing proxy tests; these tests pin the new default.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from llm_super import proxy
from llm_super.checkpoint import Checkpoints
from llm_super.config import Config, Execution, Model, Provider, Supervision
from llm_super.control import IN_BAND_RETIRED_NOTICE, ControlState
from llm_super.history import History
from llm_super.library import Library
from llm_super.orchestrator import TurnReport
from llm_super.trace import Trace


def _config() -> Config:
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
        # Defaults on purpose: stateful_chat_endpoint stays False and the
        # gate flag is True, proving the gate never fires in stateless mode.
        supervision=Supervision(confirm_new_sessions=True, turn_timeout_s=10),
        execution=Execution(backend="off"),
        learned_routing=False,
    )


class _Request:
    def __init__(self, body: dict, headers: dict | None = None):
        self._body = body
        self.headers = dict(headers or {})

    async def json(self) -> dict:
        return self._body


class _Orchestrator:
    def __init__(self) -> None:
        self.sessions: list[str] = []
        self.stateless_flags: list[bool] = []

    async def run_turn(self, session: str, messages: list[dict], *,
                       stateless: bool = False, **_kw) -> TurnReport:
        self.sessions.append(session)
        self.stateless_flags.append(stateless)
        return TurnReport(
            text="stateless answer", task_id="task-1", executor="executor",
            attempts=1, verify=None, cost_usd=0.0,
        )


class _PassthroughClient:
    def __init__(self) -> None:
        self.calls = 0

    async def raw_chat(self, model: Model, body: dict) -> dict:
        self.calls += 1
        return {
            "id": "chatcmpl-x", "object": "chat.completion", "created": 1,
            "model": model.id,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "raw"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                      "total_tokens": 2},
        }


class StatelessEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._old_state = dict(proxy.state)
        proxy.state.clear()
        self._tmp = tempfile.TemporaryDirectory()
        db = str(Path(self._tmp.name) / "trace.db")
        self.library = Library(db)
        self.control = ControlState()
        self.orch = _Orchestrator()
        proxy.state.update(
            cfg=_config(), control=self.control, trace=Trace(db),
            history=History(db), library=self.library,
            checkpoints=Checkpoints(db), armed_sessions=set(),
            orch=self.orch,
        )

    def tearDown(self) -> None:
        proxy.state.clear()
        proxy.state.update(self._old_state)
        self._tmp.cleanup()

    @staticmethod
    def _body(text: str = "one supervised turn") -> dict:
        return {"model": "super", "stream": False,
                "messages": [{"role": "user", "content": text}]}

    async def test_identical_requests_get_distinct_sessions_and_no_gate(self) -> None:
        first = await proxy.chat_completions(_Request(self._body()))
        second = await proxy.chat_completions(_Request(self._body()))

        self.assertEqual(len(self.orch.sessions), 2)
        self.assertNotEqual(self.orch.sessions[0], self.orch.sessions[1])
        for session in self.orch.sessions:
            self.assertTrue(session.startswith("oneshot_"))
        self.assertEqual(self.orch.stateless_flags, [True, True])
        for response in (first, second):
            content = json.loads(response.body)["choices"][0]["message"]["content"]
            self.assertIn("stateless answer", content)
            self.assertNotIn("new-conversation gate", content)
        # Minted sessions never become navigable library conversations.
        for session in self.orch.sessions:
            self.assertFalse(self.library.has_session(session))

    async def test_bang_message_returns_retirement_notice_without_spend(self) -> None:
        response = await proxy.chat_completions(_Request(self._body("!pause")))

        payload = json.loads(response.body)
        self.assertEqual(payload["choices"][0]["message"]["content"],
                         IN_BAND_RETIRED_NOTICE)
        self.assertEqual(payload["usage"]["total_tokens"], 0)
        self.assertEqual(self.orch.sessions, [])
        self.assertFalse(self.control.paused)

    async def test_explicit_conversation_header_keeps_continuity(self) -> None:
        request = _Request(self._body(),
                           headers={"x-llm-super-conversation": "conv-abc"})
        await proxy.chat_completions(request)
        await proxy.chat_completions(_Request(
            self._body("a different prompt entirely"),
            headers={"x-llm-super-conversation": "conv-abc"}))

        self.assertEqual(self.orch.sessions, ["conv-abc", "conv-abc"])
        self.assertTrue(self.library.has_session("conv-abc"))

    async def test_registry_passthrough_is_unaffected(self) -> None:
        client = _PassthroughClient()
        proxy.state["client"] = client
        body = {"model": "executor", "stream": False,
                "messages": [{"role": "user", "content": "raw please"}],
                "tools": [{"type": "function", "function": {
                    "name": "t", "parameters": {"type": "object"}}}]}

        response = await proxy.chat_completions(_Request(body))

        self.assertEqual(client.calls, 1)
        payload = json.loads(response.body)
        self.assertEqual(payload["choices"][0]["message"]["content"], "raw")
        self.assertEqual(self.orch.sessions, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
