"""Shared design tokens for every conflux surface.

One palette/type definition feeds Live (`ui.py`), History (`history_ui.py`),
Agent Graphs (`graph_ui.py`), and Workspace (`workspace_ui.py`). Each app
keeps its structural CSS and legacy variable names, but those names are
defined here as aliases of the canonical ``--ds-*`` tokens — so light/dark
values, type stacks, and status colors are changed in exactly one place and
the four dashboards stop drifting apart.

Design language ("codec console", after the conversation-tree mockup):
warm-charcoal surfaces, one moss-green accent, sand for warnings, clay for
errors, water/violet as auxiliary hues. Geometry is strictly rectilinear —
no rounded corners, no pills, no chevron arrowheads; squares and straight
lines only. Chrome and labels are monospace; long-form message prose uses
the ``font-prose`` sans stack.

Rules (history-ui-redesign §10, adapted): neutral surfaces; one accent;
status is icon + text + color with clay reserved for unrecovered errors,
sand for warnings/recovered, moss for proven success; prose sans only for
rendered message bodies.

Workspace note: the workspace is deliberately a dark terminal-style surface,
so it pins the dark token values instead of following the OS theme.
"""

from __future__ import annotations

# Canonical token values. Keys become `--ds-<key>` custom properties.
LIGHT: dict[str, str] = {
    "page": "#e9e9e3",
    "surface": "#f4f4ef",
    "surface-2": "#dedfd7",
    "ink": "#1b1d19",
    "ink-2": "#4c4f48",
    "muted": "#70746e",
    "line": "#c6c8bf",
    "line-2": "#adb0a5",
    "accent": "#5c7a35",
    "accent-ink": "#f4f6ee",
    "accent-soft": "#e3ead2",
    "ok": "#4c7a33",
    "ok-soft": "#e2ecd6",
    "warn": "#96702f",
    "warn-soft": "#f0e6cf",
    "err": "#a1493a",
    "err-soft": "#f2ddd7",
    "violet": "#6b5a91",
    "cyan": "#3f7a75",
    "unknown": "#70746e",
    "shadow": "0 10px 30px rgba(27, 29, 25, .10)",
    "font-ui": ("ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "
                "'Liberation Mono', monospace"),
    "font-mono": ("ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "
                  "'Liberation Mono', monospace"),
    "font-prose": ("ui-sans-serif, system-ui, -apple-system, "
                   "'Helvetica Neue', Arial, sans-serif"),
}

DARK: dict[str, str] = {
    **LIGHT,
    "page": "#08090a",
    "surface": "#17191c",
    "surface-2": "#1d2024",
    "ink": "#e4e4df",
    "ink-2": "#a1a29e",
    "muted": "#696c6d",
    "line": "#26292c",
    "line-2": "#34383b",
    "accent": "#a9c878",
    "accent-ink": "#151a0e",
    "accent-soft": "#222a1c",
    "ok": "#91aa6b",
    "ok-soft": "#1d2418",
    "warn": "#c4a474",
    "warn-soft": "#2a241a",
    "err": "#c47f70",
    "err-soft": "#2a1d1a",
    "violet": "#988ab5",
    "cyan": "#73a6a1",
    "unknown": "#9a9e94",
    "shadow": "0 14px 40px rgba(0, 0, 0, .5)",
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
