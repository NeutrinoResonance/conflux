from __future__ import annotations

from contextlib import redirect_stdout
from contextlib import redirect_stderr
import io
import sys
import unittest
from unittest import mock

from llm_super import cli


class SummaryCliTest(unittest.TestCase):
    @mock.patch("llm_super.message_summaries.backfill")
    def test_summarize_history_defaults_to_sonnet_and_reports_counts(self, backfill) -> None:
        def result(_path, **kwargs):
            kwargs["progress"]({
                "event": "indexed", "occurrences": 12, "exchanges": 3, "unique": 4,
            })
            return {
                "summarized": 4, "unique": 4, "occurrences": 12,
                "generated": 4, "cost_usd": 0.25,
            }

        backfill.side_effect = result
        output = io.StringIO()
        with mock.patch.object(sys, "argv", [
            "llm-super", "summarize-history", "--db", "sample.db",
        ]), redirect_stdout(output):
            cli.main()

        self.assertEqual(backfill.call_args.args, ("sample.db",))
        self.assertEqual(backfill.call_args.kwargs["model"], "sonnet")
        self.assertEqual(backfill.call_args.kwargs["batch_size"], 8)
        self.assertEqual(backfill.call_args.kwargs["batch_chars"], 40_000)
        self.assertEqual(backfill.call_args.kwargs["max_budget_usd"], 0.75)
        self.assertIn("indexed 12 placements", output.getvalue())
        self.assertIn("4/4 distinct messages", output.getvalue())

    @mock.patch("llm_super.message_summaries.backfill", side_effect=KeyboardInterrupt)
    def test_interrupt_is_clean_and_keeps_conventional_exit_status(self, _backfill) -> None:
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", [
            "llm-super", "summarize-history", "--db", "sample.db",
        ]), redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            cli.main()
        self.assertEqual(raised.exception.code, 130)
        self.assertIn("validated batches remain committed", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_progress_formatter_never_interpolates_untrusted_extra_fields(self) -> None:
        text = cli._summary_progress({
            "event": "batch_start", "batch": 2, "items": 5, "chars": 100,
            "message": "RAW_MESSAGE_MUST_NOT_LEAK",
        })
        self.assertNotIn("RAW_MESSAGE_MUST_NOT_LEAK", text)
        self.assertEqual(text, "batch 2 started · 5 messages · 100 sanitized characters")

        split = cli._summary_progress({
            "event": "batch_split", "batch": "2a", "items": 8,
            "duration_ms": 1200, "cost_usd": 0.25,
        })
        self.assertIn("1.2s · $0.250000 reported", split)

    @mock.patch("llm_super.step_summary_backfill.backfill")
    def test_summarize_steps_defaults_to_haiku_and_reports_counts(self, backfill) -> None:
        def result(_path, **kwargs):
            kwargs["progress"]({
                "event": "indexed_steps", "steps": 12, "pending": 4,
            })
            return {
                "summarized": 12, "steps": 12, "generated": 4,
                "cost_usd": 0.08,
            }

        backfill.side_effect = result
        output = io.StringIO()
        with mock.patch.object(sys, "argv", [
            "llm-super", "summarize-steps", "--db", "sample.db",
        ]), redirect_stdout(output):
            cli.main()

        self.assertEqual(backfill.call_args.args, ("sample.db",))
        self.assertEqual(backfill.call_args.kwargs["model"], "haiku")
        self.assertEqual(backfill.call_args.kwargs["batch_size"], 8)
        self.assertEqual(backfill.call_args.kwargs["batch_chars"], 40_000)
        self.assertEqual(backfill.call_args.kwargs["max_budget_usd"], 0.75)
        self.assertIn("indexed 12 conversation steps", output.getvalue())
        self.assertIn("12/12 conversation steps", output.getvalue())

    def test_step_progress_formatter_never_interpolates_untrusted_fields(self) -> None:
        text = cli._summary_progress({
            "event": "step_batch_start", "batch": 2, "items": 5,
            "chars": 100, "message": "RAW_STEP_MUST_NOT_LEAK",
        })
        self.assertNotIn("RAW_STEP_MUST_NOT_LEAK", text)
        self.assertEqual(
            text,
            "step batch 2 started · 5 elements · 100 sanitized characters",
        )
        split = cli._summary_progress({
            "event": "step_batch_split", "batch": "2a", "items": 4,
            "duration_ms": 1200, "cost_usd": 0.25,
            "message": "RAW_STEP_MUST_NOT_LEAK",
        })
        self.assertNotIn("RAW_STEP_MUST_NOT_LEAK", split)
        self.assertIn("1.2s · $0.250000 reported", split)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
