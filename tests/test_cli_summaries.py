from __future__ import annotations

from contextlib import redirect_stdout
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
        self.assertIn("indexed 12 placements", output.getvalue())
        self.assertIn("4/4 distinct messages", output.getvalue())

    def test_progress_formatter_never_interpolates_untrusted_extra_fields(self) -> None:
        text = cli._summary_progress({
            "event": "batch_start", "batch": 2, "items": 5, "chars": 100,
            "message": "RAW_MESSAGE_MUST_NOT_LEAK",
        })
        self.assertNotIn("RAW_MESSAGE_MUST_NOT_LEAK", text)
        self.assertEqual(text, "batch 2 started · 5 messages · 100 sanitized characters")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
