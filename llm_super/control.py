"""User intervention: in-band !commands and shared control state (SPEC §7.2).

Control messages are intercepted at the ingress and never forwarded to any
model. They work from inside any OSS client — no extra window required.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ControlState:
    paused: bool = False
    forced_executor: str | None = None
    budget_usd: float | None = None
    history: list[str] = field(default_factory=list)


HELP = """llm-super in-band commands (never forwarded to models):
  !status          show supervisor state
  !pause / !resume pause or resume supervised execution
  !use <model>     force a specific executor (from models.yaml)
  !auto            return executor choice to the router
  !budget <usd>    set per-task budget cap
  !help            this message"""


def handle(text: str, state: ControlState, model_names: list[str]) -> str | None:
    """If `text` is a control command, apply it and return the reply.
    Returns None for normal (non-control) messages."""
    stripped = text.strip()
    if not stripped.startswith("!"):
        return None
    cmd, _, arg = stripped[1:].partition(" ")
    cmd, arg = cmd.lower(), arg.strip()
    state.history.append(stripped)

    if cmd == "help":
        return HELP
    if cmd == "status":
        return (
            f"paused={state.paused} "
            f"executor={'auto' if not state.forced_executor else state.forced_executor} "
            f"budget={'default' if state.budget_usd is None else f'${state.budget_usd:.2f}'}"
        )
    if cmd == "pause":
        state.paused = True
        return "paused — supervised turns will not execute until !resume"
    if cmd == "resume":
        state.paused = False
        return "resumed"
    if cmd == "use":
        if arg not in model_names:
            return f"unknown model {arg!r}; available: {', '.join(model_names)}"
        state.forced_executor = arg
        return f"executor forced to {arg}"
    if cmd == "auto":
        state.forced_executor = None
        return "executor returned to automatic routing"
    if cmd == "budget":
        try:
            state.budget_usd = float(arg)
        except ValueError:
            return f"could not parse {arg!r} as a dollar amount"
        return f"per-task budget set to ${state.budget_usd:.2f}"
    return f"unknown command !{cmd} — try !help"
