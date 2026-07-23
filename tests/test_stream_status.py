"""Streamed supervisor status lines during supervised streaming turns."""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from pathlib import Path

from llm_super import proxy
from llm_super.config import Config, Execution, Model, Provider, Supervision
from llm_super.control import ControlState
from llm_super.orchestrator import TurnReport
from llm_super.trace import Trace


def _config(stream_status: str = "comments") -> Config:
    model = Model(
        name="direct", provider="test", id="m", family="test",
        roles=("executor",), logprobs=False, top_logprobs_max=5,
        price_in_per_m=1.0, price_out_per_m=2.0,
    )
    return Config(
        providers={"test": Provider("test", "https://x.test/v1", "env:K")},
        models={"direct": model}, default_executor="direct", utility="direct",
        verifier_pool=[],
        supervision=Supervision(stream_status=stream_status,
                                confirm_new_sessions=False),
        execution=Execution(backend="off", locked_backend=None),
    )


class _Request:
    def __init__(self, body: dict):
        self.body = body
        self.headers: dict = {}

    async def json(self) -> dict:
        return self.body


class _Library:
    def resolve_alias(self, session: str) -> str:
        return session

    def touch_session(self, session: str, title: str) -> None:
        pass

    def has_session(self, session: str) -> bool:
        return True


class _History:
    def recent_turns(self, *args, **kwargs) -> list:
        return []


class _StagedOrchestrator:
    """Records realistic stage events on the shared trace mid-turn."""

    def __init__(self, trace: Trace, session: str):
        self.trace = trace
        self.session = session

    async def run_turn(self, session: str, messages: list[dict]) -> TurnReport:
        self.trace.record(self.session, "t1", "contract")
        self.trace.record(self.session, "t1", "execute", model="direct")
        self.trace.record(self.session, "t1", "verify", model="judge",
                          score=0.91)
        self.trace.record(self.session, "t1", "turn_end", score=0.91)
        return TurnReport(
            text="final answer", task_id="t1", executor="direct", attempts=1,
            verify=None, tokens_in=10, tokens_out=5,
        )


class StreamStatusTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.old_state = dict(proxy.state)
        proxy.state.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.trace = Trace(Path(self.tmp.name) / "t.db")
        self.messages = [{"role": "user", "content": "do the work"}]
        self.session = proxy._session_id(self.messages)

    def tearDown(self) -> None:
        proxy.state.clear()
        proxy.state.update(self.old_state)
        self.tmp.cleanup()

    def _arm(self, stream_status: str) -> None:
        proxy.state.update(
            cfg=_config(stream_status), control=ControlState(),
            library=_Library(), trace=self.trace, history=_History(),
            checkpoints=object(), armed_sessions={self.session},
            orch=_StagedOrchestrator(self.trace, self.session),
        )

    async def _stream_text(self) -> str:
        response = await proxy.chat_completions(_Request(
            {"model": "super", "stream": True, "messages": self.messages}))
        parts = []
        async for raw in response.body_iterator:
            parts.append(raw.decode() if isinstance(raw, bytes) else raw)
        return "".join(parts)

    async def test_comment_mode_streams_progress_without_touching_content(self) -> None:
        self._arm("comments")
        text = await self._stream_text()
        self.assertIn(": [llm-super] executing on direct\n\n", text)
        self.assertIn(": [llm-super] verified 0.91 by judge\n\n", text)
        # Status must not leak into message content deltas.
        self.assertNotIn('"content": "[llm-super]', text)
        self.assertIn("final answer", text)
        # Subscription must not outlive the stream.
        self.assertEqual(self.trace._listeners, [])

    async def test_content_mode_emits_visible_delimited_lines(self) -> None:
        self._arm("content")
        text = await self._stream_text()
        self.assertIn("[llm-super] executing on direct", text)
        self.assertNotIn(": [llm-super] executing", text)

    async def test_off_mode_streams_no_status(self) -> None:
        self._arm("off")
        text = await self._stream_text()
        self.assertNotIn("[llm-super] executing", text)
        self.assertIn("final answer", text)

    async def test_status_lines_are_session_scoped(self) -> None:
        self._arm("comments")

        class _NoisyOrchestrator(_StagedOrchestrator):
            async def run_turn(self, session, messages):
                self.trace.record("other-session", "tX", "execute",
                                  model="direct")
                return await super().run_turn(session, messages)

        proxy.state["orch"] = _NoisyOrchestrator(self.trace, self.session)
        text = await self._stream_text()
        self.assertEqual(text.count(": [llm-super] executing on direct"), 1)

    def test_status_line_vocabulary(self) -> None:
        cases = {
            ("contract", None, ()): "contract extracted",
            ("execute", "m1", ()): "executing on m1",
            ("execute_code", None, ()): "running generated code in the sandbox",
            ("referee", None, (("strategy", "switch_model"),)):
                "referee chose switch_model",
            ("fm_event", None, ()): None,
            ("client_request", None, ()): None,
        }
        for (kind, model, data), expected in cases.items():
            event = {"kind": kind, "model": model, "data": dict(data)}
            self.assertEqual(proxy._status_line(event), expected, kind)


if __name__ == "__main__":
    unittest.main()
