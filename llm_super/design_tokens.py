"""Shared design tokens for every llm-super surface.

One palette/type definition feeds Live (`ui.py`), History (`history_ui.py`),
Agent Graphs (`graph_ui.py`), and Workspace (`workspace_ui.py`). Each app
keeps its structural CSS and legacy variable names, but those names are
defined here as aliases of the canonical ``--ds-*`` tokens — so light/dark
values, type stacks, and status colors are changed in exactly one place and
the four dashboards stop drifting apart.

Rules (history-ui-redesign §10): neutral surfaces; one accent; status is
icon + text + color with red reserved for unrecovered errors, amber for
warnings/recovered, green for proven success; monospace only for IDs,
commands, paths, hashes, and raw payloads.

Workspace note: the workspace is deliberately a dark terminal-style surface
and still contains hardcoded dark hexes, so it pins the dark token values
instead of following the OS theme. Migrating it to theme-following is the
remaining step; its palette already comes from this file.
"""

from __future__ import annotations

# Canonical token values. Keys become `--ds-<key>` custom properties.
LIGHT: dict[str, str] = {
    "page": "#f6f6f2",
    "surface": "#fdfdfc",
    "surface-2": "#f0f1ed",
    "ink": "#151613",
    "ink-2": "#565952",
    "muted": "#7b7e76",
    "line": "#d9dbd3",
    "line-2": "#c8cbc1",
    "accent": "#225fba",
    "accent-soft": "#e8f0fc",
    "ok": "#18723a",
    "ok-soft": "#e7f5eb",
    "warn": "#8a5a00",
    "warn-soft": "#fff2d1",
    "err": "#a62d2d",
    "err-soft": "#fae9e7",
    "violet": "#7653d6",
    "cyan": "#0e7d97",
    "unknown": "#62655e",
    "shadow": "0 12px 40px rgba(26, 31, 23, .08)",
    "font-ui": ("Inter, ui-sans-serif, system-ui, -apple-system, "
                "'Segoe UI', sans-serif"),
    "font-mono": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
}

DARK: dict[str, str] = {
    **LIGHT,
    "page": "#111310",
    "surface": "#191c18",
    "surface-2": "#222620",
    "ink": "#f3f5ef",
    "ink-2": "#c4c8bd",
    "muted": "#94998e",
    "line": "#343931",
    "line-2": "#484e44",
    "accent": "#81aef0",
    "accent-soft": "#192c49",
    "ok": "#72ce8d",
    "ok-soft": "#173421",
    "warn": "#e3b557",
    "warn-soft": "#3d3014",
    "err": "#f08780",
    "err-soft": "#421f1c",
    "violet": "#a98afb",
    "cyan": "#55d5e8",
    "unknown": "#9a9e94",
    "shadow": "0 18px 50px rgba(0, 0, 0, .28)",
}

# Legacy variable names per app, defined in terms of the canonical tokens.
_APP_ALIASES: dict[str, dict[str, str]] = {
    "live": {
        "--page": "var(--ds-page)", "--surface": "var(--ds-surface)",
        "--ink": "var(--ds-ink)", "--ink-2": "var(--ds-ink-2)",
        "--muted": "var(--ds-muted)", "--grid": "var(--ds-line)",
        "--baseline": "var(--ds-line-2)", "--border": "var(--ds-line)",
        "--seq": "var(--ds-accent)", "--seq-track": "var(--ds-line)",
        "--good": "var(--ds-ok)", "--good-text": "var(--ds-ok)",
        "--warning": "var(--ds-warn)", "--serious": "var(--ds-warn)",
        "--critical": "var(--ds-err)", "--ok": "var(--ds-ok)",
    },
    "history": {
        "--page": "var(--ds-page)", "--surface": "var(--ds-surface)",
        "--surface-2": "var(--ds-surface-2)", "--ink": "var(--ds-ink)",
        "--ink-2": "var(--ds-ink-2)", "--muted": "var(--ds-muted)",
        "--line": "var(--ds-line)", "--line-2": "var(--ds-line-2)",
        "--accent": "var(--ds-accent)",
        "--accent-soft": "var(--ds-accent-soft)",
        "--good": "var(--ds-ok)", "--good-soft": "var(--ds-ok-soft)",
        "--warn": "var(--ds-warn)", "--warn-soft": "var(--ds-warn-soft)",
        "--bad": "var(--ds-err)", "--bad-soft": "var(--ds-err-soft)",
        "--unknown": "var(--ds-unknown)", "--shadow": "var(--ds-shadow)",
    },
    "graphs": {
        "--bg": "var(--ds-page)", "--panel": "var(--ds-surface)",
        "--panel-2": "var(--ds-surface-2)", "--ink": "var(--ds-ink)",
        "--ink-2": "var(--ds-ink-2)", "--muted": "var(--ds-muted)",
        "--line": "var(--ds-line)", "--line-2": "var(--ds-line-2)",
        "--blue": "var(--ds-accent)", "--blue-soft": "var(--ds-accent-soft)",
        "--green": "var(--ds-ok)", "--green-soft": "var(--ds-ok-soft)",
        "--amber": "var(--ds-warn)", "--amber-soft": "var(--ds-warn-soft)",
        "--red": "var(--ds-err)", "--red-soft": "var(--ds-err-soft)",
        "--violet": "var(--ds-violet)", "--shadow": "var(--ds-shadow)",
        "--mono": "var(--ds-font-mono)",
    },
    "workspace": {
        "--page": "var(--ds-page)", "--panel": "var(--ds-surface)",
        "--panel2": "var(--ds-surface-2)", "--panel3": "var(--ds-surface-2)",
        "--line": "var(--ds-line)", "--line2": "var(--ds-line-2)",
        "--ink": "var(--ds-ink)", "--ink2": "var(--ds-ink-2)",
        "--muted": "var(--ds-muted)", "--blue": "var(--ds-accent)",
        "--blue2": "var(--ds-accent)", "--blue-soft": "var(--ds-accent-soft)",
        "--green": "var(--ds-ok)", "--amber": "var(--ds-warn)",
        "--rose": "var(--ds-err)", "--violet": "var(--ds-violet)",
        "--cyan": "var(--ds-cyan)", "--shadow": "var(--ds-shadow)",
    },
}


def _decls(values: dict[str, str], indent: str = "  ") -> str:
    return "\n".join(f"{indent}--ds-{k}: {v};" for k, v in values.items())


def _alias_decls(app: str, indent: str = "  ") -> str:
    return "\n".join(f"{indent}{name}: {value};"
                     for name, value in _APP_ALIASES[app].items())


def css_for(app: str) -> str:
    """The complete token stylesheet for one app.

    Theme resolution: light is the default, the OS dark preference applies
    unless the page pins ``data-theme="light"``, and an explicit
    ``data-theme`` attribute always wins. The workspace pins dark values
    (see module docstring).
    """
    if app not in _APP_ALIASES:
        raise KeyError(f"unknown app {app!r}")
    aliases = _alias_decls(app)
    if app == "workspace":
        return (
            ":root {\n  color-scheme: dark;\n"
            + _decls(DARK) + "\n" + aliases + "\n}\n"
        )
    return (
        ":root {\n  color-scheme: light;\n"
        + _decls(LIGHT) + "\n" + aliases + "\n}\n"
        "@media (prefers-color-scheme: dark) {\n"
        "  :root:where(:not([data-theme=\"light\"])) {\n"
        "    color-scheme: dark;\n" + _decls(DARK, "    ") + "\n  }\n}\n"
        ":root[data-theme=\"dark\"] {\n  color-scheme: dark;\n"
        + _decls(DARK) + "\n}\n"
    )


MARKER = "/*__DESIGN_TOKENS__*/"


def apply(page: str, app: str) -> str:
    """Replace the marker in an app's HTML with its token stylesheet."""
    if MARKER not in page:
        raise ValueError(f"{app} page is missing the design-token marker")
    return page.replace(MARKER, css_for(app))
