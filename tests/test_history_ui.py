from __future__ import annotations

import unittest

from llm_super import history_ui


class GeneratedSummaryPageContractTests(unittest.TestCase):
    def test_summary_context_is_rendered_across_history_views(self) -> None:
        page = history_ui.PAGE

        self.assertIn("compactContextHTML(item.context_summary)", page)
        self.assertIn('summaryCardHTML(d.context_summary, "Objective")', page)
        self.assertIn('summaryCardHTML(run.context_summary, "Run context")', page)
        self.assertIn('label: "Prompt context"', page)
        self.assertIn("summaryCoverageHTML(d.message_summary_coverage)", page)
        self.assertIn("summaryCoverageHTML(run.message_summary_coverage)", page)

    def test_every_timeline_summary_shape_has_a_prose_renderer(self) -> None:
        page = history_ui.PAGE

        self.assertIn("delta?.summaries", page)
        self.assertIn("item.response_summary", page)
        self.assertIn("tool?.result_summary", page)
        self.assertIn("item.provider_summaries", page)
        self.assertIn("item.summary_samples", page)
        self.assertIn("summaryStackHTML(stepSummaryEntries(item))", page)
        self.assertIn("summaryStackHTML(pollSummaryEntries(item))", page)

    def test_summary_fields_are_escaped_and_never_fall_back_to_json(self) -> None:
        page = history_ui.PAGE

        self.assertIn("${esc(headline)}", page)
        self.assertIn("${body ? esc(body) : \"\"}", page)
        self.assertIn("${esc(tags.join(\" · \"))}", page)
        self.assertIn("${esc(headline || \"Summary\")}", page)
        self.assertIn("${esc(text)}", page)
        self.assertNotIn("JSON.stringify(summary", page)
        self.assertNotIn("JSON.stringify(item.message_delta", page)
        self.assertEqual(page.count("JSON.stringify("), 1)
        self.assertIn("state.rawText = JSON.stringify(item.payload, null, 2)", page)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
