"""Shared design tokens: one palette feeding all four dashboards."""

from __future__ import annotations

import re
import unittest

from llm_super import design_tokens, graph_ui, history_ui, ui, workspace_ui

PAGES = {
    "live": ui.PAGE,
    "history": history_ui.PAGE,
    "graphs": graph_ui.PAGE,
    "workspace": workspace_ui.PAGE,
}


class DesignTokenTests(unittest.TestCase):
    def test_every_page_embeds_canonical_tokens(self) -> None:
        for app, page in PAGES.items():
            self.assertNotIn(design_tokens.MARKER, page, app)
            self.assertIn("--ds-page:", page, app)
            self.assertIn("--ds-accent:", page, app)
            self.assertIn("--ds-font-ui:", page, app)

    def test_light_capable_pages_follow_theme_and_workspace_pins_dark(self) -> None:
        for app in ("live", "history", "graphs"):
            css = design_tokens.css_for(app)
            self.assertIn("prefers-color-scheme: dark", css, app)
            self.assertIn('data-theme="dark"', css, app)
            self.assertIn("color-scheme: light", css, app)
        workspace = design_tokens.css_for("workspace")
        self.assertIn("color-scheme: dark", workspace)
        self.assertNotIn("prefers-color-scheme", workspace)

    def test_dark_palette_differs_where_it_must(self) -> None:
        for key in ("page", "surface", "ink", "accent", "ok", "err"):
            self.assertNotEqual(design_tokens.LIGHT[key],
                                design_tokens.DARK[key], key)

    def test_no_page_uses_an_undefined_variable_without_fallback(self) -> None:
        """Drift guard: every var(--x) use (no fallback) must be defined."""
        for app, page in PAGES.items():
            defined = set(re.findall(r"(--[A-Za-z0-9-]+)\s*:", page))
            defined |= set(re.findall(
                r"setProperty\(\s*[\"'](--[A-Za-z0-9-]+)[\"']", page))
            uses = re.findall(r"var\((--[A-Za-z0-9-]+)\)", page)
            undefined = sorted({name for name in uses if name not in defined})
            self.assertEqual(undefined, [], f"{app}: {undefined}")

    def test_unknown_app_rejected_and_marker_required(self) -> None:
        with self.assertRaises(KeyError):
            design_tokens.css_for("nope")
        with self.assertRaises(ValueError):
            design_tokens.apply("<html></html>", "live")


if __name__ == "__main__":
    unittest.main()
