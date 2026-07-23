"""Live SSE channel: trace write path -> cursor-addressed event stream."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from llm_super import proxy
from llm_super.trace import Trace


class _StubRequest:
    def __init__(self, headers: dict | None = None):
        self.headers = headers or {}


class TraceListenerTests(unittest.TestCase):
    def test_record_notifies_listeners_with_durable_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace = Trace(Path(tmp) / "t.db")
            seen: list[dict] = []
            trace.add_listener(seen.append)
            trace.record("s", "t", "execute", model="m", tokens_in=3)
            trace.record("s", "t", "turn_end", score=0.9)
            self.assertEqual([e["kind"] for e in seen], ["execute", "turn_end"])
            self.assertEqual(seen[0]["id"] + 1, seen[1]["id"])
            self.assertEqual(seen[1]["data"], {"score": 0.9})
            trace.remove_listener(seen.append)  # unknown callable: no error

    def test_listener_errors_never_break_the_write_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace = Trace(Path(tmp) / "t.db")
            trace.add_listener(lambda e: (_ for _ in ()).throw(RuntimeError))
            trace.record("s", "t", "execute")
            self.assertEqual(len(trace.recent(5)), 1)

    def test_events_after_is_cursor_scoped_and_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace = Trace(Path(tmp) / "t.db")
            for i in range(5):
                trace.record("s", "t", f"k{i}")
            all_events = trace.events_after(0)
            self.assertEqual([e["kind"] for e in all_events],
                             ["k0", "k1", "k2", "k3", "k4"])
            cursor = all_events[2]["id"]
            tail = trace.events_after(cursor)
            self.assertEqual([e["kind"] for e in tail], ["k3", "k4"])
            self.assertEqual(trace.last_event_id(), all_events[-1]["id"])


class EventStreamRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.old_state = dict(proxy.state)
        proxy.state.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.trace = Trace(Path(self.tmp.name) / "t.db")
        proxy.state["trace"] = self.trace

    def tearDown(self) -> None:
        proxy.state.clear()
        proxy.state.update(self.old_state)
        self.tmp.cleanup()

    async def _read_message(self, gen) -> str:
        return await asyncio.wait_for(gen.__anext__(), timeout=5)

    async def test_replay_then_push(self) -> None:
        self.trace.record("s", "t", "past_event")
        response = await proxy.admin_events_stream(_StubRequest(), after_id=0)
        self.assertEqual(response.media_type, "text/event-stream")
        gen = response.body_iterator
        try:
            replayed = await self._read_message(gen)
            self.assertIn("past_event", replayed)
            self.assertTrue(replayed.startswith("id: "))
            connected = await self._read_message(gen)
            self.assertIn(": connected", connected)
            self.trace.record("s", "t", "fresh_event", score=1.0)
            pushed = await self._read_message(gen)
            self.assertIn("fresh_event", pushed)
            payload = json.loads(pushed.split("data: ", 1)[1])
            self.assertEqual(payload["kind"], "fresh_event")
            self.assertGreater(payload["id"], 0)
        finally:
            await gen.aclose()
        # The subscription must not outlive the connection.
        self.assertEqual(self.trace._listeners, [])

    async def test_negative_cursor_skips_history(self) -> None:
        self.trace.record("s", "t", "old_event")
        response = await proxy.admin_events_stream(_StubRequest(), after_id=-1)
        gen = response.body_iterator
        try:
            first = await self._read_message(gen)
            self.assertIn(": connected", first)
            self.assertNotIn("old_event", first)
        finally:
            await gen.aclose()

    async def test_last_event_id_header_wins(self) -> None:
        self.trace.record("s", "t", "e1")
        self.trace.record("s", "t", "e2")
        first_id = self.trace.events_after(0)[0]["id"]
        response = await proxy.admin_events_stream(
            _StubRequest({"last-event-id": str(first_id)}), after_id=-1)
        gen = response.body_iterator
        try:
            replayed = await self._read_message(gen)
            self.assertIn("e2", replayed)
        finally:
            await gen.aclose()


if __name__ == "__main__":
    unittest.main()
