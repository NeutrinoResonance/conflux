from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException, Response

from llm_super import history_ui, proxy, ui
from llm_super.library import Library
from llm_super.trace import Trace


def _contains_forbidden_summary_key(value) -> bool:
    if isinstance(value, dict):
        return any(
            key in {"payload", "data", "messages", "logprobs", "reasoning"}
            or _contains_forbidden_summary_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_summary_key(item) for item in value)
    return False


class HistoryRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.old_state = dict(proxy.state)
        proxy.state.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "trace.db")
        trace = Trace(self.db)
        library = Library(self.db)
        self.session = "session-alpha"
        self.task = "task-1"
        library.touch_session(self.session, "Compile a small target")
        trace.record_exchange(
            self.session, self.task, "client_request", None,
            {"messages": [{"role": "user", "content": "compile it"}]},
        )
        trace.record(
            self.session, self.task, "execute", model="executor",
            tokens_in=11, tokens_out=3, cost_usd=0.1234567,
        )
        trace.record(self.session, self.task, "turn_end", score=1.0)
        trace.record_exchange(
            self.session, self.task, "client_response", "executor",
            {"choices": [{"message": {"role": "assistant", "content": "done"},
                          "finish_reason": "stop"}]},
        )
        proxy.state["trace_path"] = self.db

    def tearDown(self) -> None:
        proxy.state.clear()
        proxy.state.update(self.old_state)
        self.tmp.cleanup()

    async def test_scoped_routes_paginate_and_raw_is_explicit(self) -> None:
        listing = await proxy.admin_history_endeavors(limit=1)
        self.assertEqual(listing["total"], 1)
        self.assertIsNone(listing["next_cursor"])
        self.assertEqual(len(listing["items"]), 1)
        self.assertFalse(_contains_forbidden_summary_key(listing))

        endeavor_id = listing["items"][0]["id"]
        detail = await proxy.admin_history_endeavor(endeavor_id)
        self.assertEqual(detail["status"], "succeeded")
        self.assertEqual(detail["cost_usd"], 0.123457)
        self.assertFalse(_contains_forbidden_summary_key(detail))

        runs = await proxy.admin_history_runs(endeavor_id, limit=10)
        self.assertEqual(runs["total"], 1)
        self.assertEqual(runs["items"][0]["session_id"], self.session)

        timeline = await proxy.admin_history_timeline(
            endeavor_id, routine="collapse", limit=10
        )
        self.assertEqual(timeline["summary"]["workload_steps"], 1)
        self.assertFalse(_contains_forbidden_summary_key(timeline))
        exchange_id = timeline["items"][0]["source_exchange_ids"][0]

        response = Response()
        raw = await proxy.admin_history_raw_exchange(exchange_id, response)
        self.assertIn("payload", raw)
        self.assertEqual(raw["payload"]["messages"][0]["content"], "compile it")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["Pragma"], "no-cache")

    async def test_bad_filter_cursor_and_missing_rows_are_http_errors(self) -> None:
        with self.assertRaises(HTTPException) as bad_mode:
            await proxy.admin_history_timeline("session:session-alpha", routine="maybe")
        self.assertEqual(bad_mode.exception.status_code, 400)

        with self.assertRaises(HTTPException) as missing:
            await proxy.admin_history_endeavor("missing")
        self.assertEqual(missing.exception.status_code, 404)

        with self.assertRaises(HTTPException) as bad_limit:
            await proxy.admin_history_endeavors(limit=0)
        self.assertEqual(bad_limit.exception.status_code, 400)

        with self.assertRaises(HTTPException) as huge_exchange_id:
            await proxy.admin_history_raw_exchange(1 << 80, Response())
        self.assertEqual(huge_exchange_id.exception.status_code, 400)


class HistoryPageContractTests(unittest.TestCase):
    def test_page_is_separate_accessible_and_does_not_poll(self) -> None:
        page = history_ui.PAGE
        self.assertIn('href="/history" aria-current="page"', page)
        self.assertIn('role="tablist"', page)
        self.assertIn('aria-live="polite"', page)
        self.assertIn('@media (prefers-reduced-motion: reduce)', page)
        self.assertIn('/admin/history/endeavors', page)
        self.assertIn('/timeline?', page)
        self.assertIn('/raw', page)
        self.assertNotIn('setInterval(', page)
        self.assertEqual(page.count('id="rawBody"'), 1)
        self.assertIn('showing ${state.timeline.length} of ${state.timelineTotal}', page)
        self.assertIn('Load more verification evidence', page)
        self.assertIn('serial !== state.timelineSerial', page)
        self.assertIn('serial !== state.rawSerial', page)
        self.assertIn('$("#rawBody").textContent = ""', page)
        self.assertIn('esc(stepLabel(item))', page)
        self.assertIn('["ArrowUp","ArrowDown","Home","End"]', page)
        self.assertIn('poll decisions summarized', page)
        self.assertIn('Build and boot proof', page)

    def test_live_page_links_to_history_without_removing_existing_dashboard(self) -> None:
        self.assertIn('<a href="/history">History</a>', ui.PAGE)
        self.assertIn('id="tasks"', ui.PAGE)
        self.assertIn('id="settings"', ui.PAGE)
        self.assertIn('id="stats"', ui.PAGE)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
