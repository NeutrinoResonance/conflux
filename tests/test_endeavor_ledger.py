"""Durable endeavor/run/phase/step capture at write time (redesign Phase 1)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from conflux.endeavors import EndeavorLedger
from conflux.history_view import NETBSD_ARM64_ENDEAVOR, HistoryView
from conflux.library import Library
from conflux.trace import Trace


def _fresh(tmp, **kw):
    trace = Trace(Path(tmp) / "t.db")
    Library(Path(tmp) / "t.db")  # sessions table for HistoryView
    ledger = EndeavorLedger(trace.connection, **kw)
    trace.add_listener(ledger.observe)
    return trace, ledger


class LedgerCaptureTests(unittest.TestCase):
    def test_turn_creates_endeavor_run_phase_step_and_finalizes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace, ledger = _fresh(tmp)
            trace.record("sess-a", "task-1", "contract", model="util",
                         tokens_in=10, tokens_out=5, cost_usd=0.001)
            trace.record("sess-a", "task-1", "execute", model="exec",
                         tokens_in=100, tokens_out=50, cost_usd=0.01)
            conn = trace.connection
            step = conn.execute(
                "SELECT status, phase, tokens_in, tokens_out FROM steps "
                "WHERE session='sess-a' AND task='task-1'").fetchone()
            self.assertEqual(step[0], "running")
            self.assertEqual(step[1], "execute")
            self.assertEqual((step[2], step[3]), (110, 55))
            run = conn.execute(
                "SELECT status, server_instance_id FROM runs "
                "WHERE session='sess-a'").fetchone()
            self.assertEqual(run[0], "running")
            self.assertEqual(run[1], ledger.server_instance_id)
            member = conn.execute(
                "SELECT endeavor_id FROM endeavor_members "
                "WHERE session='sess-a'").fetchone()
            self.assertEqual(member[0], "conversation:sess-a")

            trace.record("sess-a", "task-1", "verify", model="ver")
            trace.record("sess-a", "task-1", "turn_end", score=0.93)
            step = conn.execute(
                "SELECT status, phase, end_ts FROM steps "
                "WHERE session='sess-a' AND task='task-1'").fetchone()
            self.assertEqual(step[0], "succeeded")
            self.assertEqual(step[1], "finish")
            self.assertIsNotNone(step[2])
            run = conn.execute(
                "SELECT status FROM runs WHERE session='sess-a'").fetchone()
            self.assertEqual(run[0], "succeeded")
            phases = [r[0] for r in conn.execute(
                "SELECT phase FROM phases ORDER BY ordinal")]
            self.assertEqual(phases, ["specify", "execute", "verify", "finish"])

    def test_error_then_success_marks_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace, _ = _fresh(tmp)
            trace.record("s", "t", "executor_error", error="boom")
            trace.record("s", "t", "execute", model="m2")
            trace.record("s", "t", "turn_end", score=0.9)
            row = trace.connection.execute(
                "SELECT status, severity FROM steps WHERE session='s'"
            ).fetchone()
            self.assertEqual(tuple(row), ("succeeded", "recovered"))

    def test_failed_terminal_marks_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace, _ = _fresh(tmp)
            trace.record("s", "t", "execute")
            trace.record("s", "t", "turn_end", passed=False)
            row = trace.connection.execute(
                "SELECT status FROM steps WHERE session='s'").fetchone()
            self.assertEqual(row[0], "failed")

    def test_control_event_becomes_milestone_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace, _ = _fresh(tmp)
            trace.record("s", "-", "control", command="!pause")
            row = trace.connection.execute(
                "SELECT kind, phase, summary FROM steps WHERE session='s'"
            ).fetchone()
            self.assertEqual(tuple(row), ("control", "control", "!pause"))

    def test_restart_interrupts_stale_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace, _ = _fresh(tmp, server_instance_id="first")
            trace.record("s", "t", "execute")  # left running
            EndeavorLedger(trace.connection, server_instance_id="second")
            run = trace.connection.execute(
                "SELECT status, interruption_reason FROM runs "
                "WHERE session='s'").fetchone()
            self.assertEqual(tuple(run), ("interrupted", "server restart"))
            step = trace.connection.execute(
                "SELECT status FROM steps WHERE session='s'").fetchone()
            self.assertEqual(step[0], "interrupted")

    def test_workspace_endeavor_mapping_wins_over_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace, _ = _fresh(
                tmp, workspace_endeavor_for=lambda s: "endeavor-42")
            trace.record("s", "t", "execute")
            member = trace.connection.execute(
                "SELECT endeavor_id FROM endeavor_members WHERE session='s'"
            ).fetchone()
            self.assertEqual(member[0], "endeavor-42")

    def test_explicit_endeavor_groups_conversations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace, ledger = _fresh(tmp)
            ledger.set_explicit_endeavor("s1", "big-goal")
            ledger.set_explicit_endeavor("s2", "big-goal")
            trace.record("s1", "t1", "execute")
            trace.record("s2", "t2", "execute")
            rows = trace.connection.execute(
                "SELECT session FROM endeavor_members WHERE endeavor_id="
                "'big-goal' ORDER BY ordinal").fetchall()
            self.assertEqual([r[0] for r in rows], ["s1", "s2"])

    def test_migration_is_exact_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace, ledger = _fresh(tmp)
            self.assertTrue(ledger.migrate_grouping(NETBSD_ARM64_ENDEAVOR))
            self.assertFalse(ledger.migrate_grouping(NETBSD_ARM64_ENDEAVOR))
            count = trace.connection.execute(
                "SELECT COUNT(*) FROM endeavor_members WHERE endeavor_id=?",
                (NETBSD_ARM64_ENDEAVOR.id,)).fetchone()[0]
            self.assertEqual(count, len(NETBSD_ARM64_ENDEAVOR.sessions))


class HistoryViewDurableTests(unittest.TestCase):
    def test_durable_grouping_replaces_derived_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace, ledger = _fresh(tmp)
            library = Library(Path(tmp) / "t.db")
            for sid in ("s1", "s2"):
                library.touch_session(sid, f"work in {sid}")
            ledger.set_explicit_endeavor("s1", "one-goal")
            ledger.set_explicit_endeavor("s2", "one-goal")
            trace.record("s1", "t1", "execute", model="m")
            trace.record("s1", "t1", "turn_end", score=0.9)
            trace.record("s2", "t2", "execute", model="m")
            view = HistoryView(Path(tmp) / "t.db")
            listing = view.list_endeavors()
            ids = [row["id"] for row in listing["items"]]
            self.assertIn("one-goal", ids)
            # Neither session may also appear as a fallback endeavor.
            self.assertNotIn("session:s1", ids)
            self.assertNotIn("session:s2", ids)
            merged = next(r for r in listing["items"] if r["id"] == "one-goal")
            self.assertEqual(sorted(merged["session_ids"]), ["s1", "s2"])

            detail = view.get_endeavor("one-goal")
            self.assertTrue(detail["capture"]["durable"])
            self.assertGreaterEqual(detail["capture"]["steps"], 2)

            runs = view.list_runs("one-goal")
            captured = [r for r in runs["items"] if r.get("capture")]
            self.assertEqual(len(captured), 2)
            self.assertEqual(
                captured[0]["capture"][0]["server_instance_id"],
                ledger.server_instance_id,
            )

            timeline = view.timeline("one-goal")
            step_items = [i for i in timeline["items"]
                          if i.get("type") == "step" and i.get("capture")]
            self.assertGreaterEqual(len(step_items), 1)
            self.assertIn(step_items[0]["capture"]["status"],
                          {"succeeded", "running"})


if __name__ == "__main__":
    unittest.main()
