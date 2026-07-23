from __future__ import annotations

import unittest

from llm_super import history_ui, ui


class GeneratedSummaryPageContractTests(unittest.TestCase):
    def test_three_summary_layers_drive_live_and_history_widgets(self) -> None:
        for page in (ui.PAGE, history_ui.PAGE):
            self.assertIn("short_summary", page)
            self.assertIn("node_label", page)
            self.assertIn("long_summary", page)

        self.assertIn("taskStoryHTML(evs)", ui.PAGE)
        self.assertIn("taskPresentation(evs)", ui.PAGE)
        self.assertIn("conversationFlowHTML", history_ui.PAGE)
        self.assertIn("itemFlowHTML(item)", history_ui.PAGE)

    def test_exchange_inspectors_are_visual_first_with_json_fallback(self) -> None:
        self.assertIn('class="chat-thread"', ui.PAGE)
        self.assertIn('aria-label="Model request and response"', ui.PAGE)
        self.assertIn('id="visualRaw"', history_ui.PAGE)
        self.assertIn('id="jsonRaw"', history_ui.PAGE)
        self.assertIn("visualRawHTML(state.rawItem)", history_ui.PAGE)
        self.assertIn('id="rawJSON" hidden', history_ui.PAGE)

    def test_summary_context_is_rendered_across_history_views(self) -> None:
        page = history_ui.PAGE

        self.assertIn("compactContextHTML(item.context_summary)", page)
        self.assertIn('summaryCardHTML(d.context_summary, "Objective")', page)
        self.assertIn('summaryCardHTML(run.context_summary, "Conversation context")', page)
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
        self.assertIn("providerSummariesHTML(item)", page)
        self.assertIn("summaryStackHTML(pollSummaryEntries(item))", page)

    def test_default_views_reduce_system_and_provider_review_noise(self) -> None:
        page = history_ui.PAGE

        self.assertIn('summary?.role || ""', page)
        self.assertIn('=== "system") continue', page)
        self.assertIn('<details class="provider-summaries">', page)
        self.assertIn("providers.length} provider attempt", page)
        self.assertIn('aria-label="${esc(accessibleLabel)}"', page)

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

    def test_endeavor_conversation_task_run_hierarchy_is_explicit(self) -> None:
        page = history_ui.PAGE

        self.assertIn('aria-label="History containment model"', page)
        self.assertIn('How the records fit together', page)
        self.assertIn('<b>Endeavor</b><span>broader objective</span>', page)
        self.assertIn('<b>Conversation</b><span>one chat thread</span>', page)
        self.assertIn('<b>Task run</b><span>one workflow execution</span>', page)
        self.assertIn('<b>Decision event</b><span>one recorded step</span>', page)
        self.assertIn('class="organizing-arrow">contains →', page)
        self.assertIn('class="organizing-arrow">triggers →', page)
        self.assertIn('class="organizing-arrow">records →', page)
        self.assertIn('An endeavor contains one or more conversations.', page)
        self.assertIn('metric("Conversations"', page)
        self.assertIn('Conversations in this endeavor', page)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
