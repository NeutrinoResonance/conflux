from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from conflux.history_view import HistoryView
from conflux.library import Library
from conflux.step_summaries import derive_step_summary
from conflux.trace import Trace


class StepSummaryDerivationTests(unittest.TestCase):
    def test_text_response_produces_all_three_bounded_levels(self) -> None:
        summary = derive_step_summary(
            {"messages": [{"role": "user", "content": "Please check NetBSD support."}]},
            {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "NetBSD can run in the normal world.",
                        "reasoning": "PRIVATE_REASONING_MUST_NOT_LEAK",
                    }
                }]
            },
        )
        self.assertEqual(summary.node_label, "Check NetBSD support")
        self.assertIn("Prompted with", summary.short_summary)
        self.assertIn("NetBSD can run", summary.long_summary)
        self.assertNotIn("PRIVATE_REASONING", repr(summary))

    def test_tool_response_names_actions_without_copying_argument_values(self) -> None:
        summary = derive_step_summary(
            {"messages": [{"role": "user", "content": "Inspect the VM"}]},
            {
                "choices": [{"message": {"tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "run_on_authorized_vm",
                        "arguments": json.dumps({
                            "command": "secret-command-value",
                            "timeout": 30,
                        }),
                    },
                }]}}]
            },
        )
        self.assertEqual(summary.node_label, "Run on authorized vm")
        self.assertIn("command, timeout", summary.long_summary)
        self.assertNotIn("secret-command-value", summary.long_summary)


class StepSummaryPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "traces.db"
        self.trace = Trace(self.db)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_request_creates_pending_summary_and_response_updates_it(self) -> None:
        session, task = "session-a", "task-a"
        request = {"messages": [{"role": "user", "content": "Inspect the VM"}]}
        self.trace.record_exchange(session, task, "client_request", None, request)
        self.trace.record(session, task, "agent_turn")

        pending = self.trace.recent(1)[0]
        self.assertEqual(pending["node_label"], "Inspect the VM")
        self.assertIn("has been recorded", pending["long_summary"])

        response = {
            "choices": [{"message": {"role": "assistant", "content": "VM is healthy."}}]
        }
        self.trace.record_exchange(
            session, task, "client_response", "model-a", response
        )
        event = self.trace.recent(1)[0]
        self.assertIn("VM is healthy", event["short_summary"])
        exchanges = self.trace.exchanges(task=task)
        self.assertEqual(len(exchanges), 2)
        self.assertTrue(all(row["node_label"] == "Inspect the VM" for row in exchanges))

        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT generator,prompt_version FROM step_summaries "
            "WHERE session=? AND task=?",
            (session, task),
        ).fetchone()
        conn.close()
        self.assertEqual(row, ("deterministic", "step-summary-v1"))

    def test_history_exposes_levels_on_endeavor_run_timeline_and_raw(self) -> None:
        session, task = "session-history", "task-history"
        library = Library(self.db)
        library.touch_session(session, "Inspect the guest")
        self.trace.record_exchange(
            session,
            task,
            "client_request",
            None,
            {"messages": [{"role": "user", "content": "Inspect the guest"}]},
        )
        self.trace.record(session, task, "turn_end", model="model-a")
        self.trace.record_exchange(
            session,
            task,
            "client_response",
            "model-a",
            {"text": "The guest booted successfully."},
        )

        with HistoryView(self.db, include_documented_fixtures=False) as view:
            endeavor = view.list_endeavors(limit=10)["items"][0]
            self.assertEqual(endeavor["node_label"], "Inspect the guest")
            run = view.list_runs(endeavor["id"], limit=10)["items"][0]
            self.assertIn("guest booted", run["long_summary"])
            step = view.timeline(
                endeavor["id"], collapse_polling=False, limit=10
            )["items"][0]
            self.assertIn("elicited", step["short_summary"])
            raw = view.raw_exchange(step["source_exchange_ids"][-1])
            self.assertEqual(raw["node_label"], "Inspect the guest")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
