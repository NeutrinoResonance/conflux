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
    contract_enabled: bool = True
    contract_skip_once: bool = False   # skip checklist for the next turn only
    sandbox_backend: str | None = None  # None = models.yaml default; "off" disables
    plan_mode: str = "auto"            # auto | on (always plan) | off (never)
    history: list[str] = field(default_factory=list)

    def consume_contract_enabled(self) -> bool:
        """Whether the *current* turn should extract a contract checklist."""
        if self.contract_skip_once:
            self.contract_skip_once = False
            return False
        return self.contract_enabled


HELP = """llm-super in-band commands (never forwarded to models):
  !status              show supervisor state
  !pause / !resume     pause or resume supervised execution
  !use <model>         force a specific executor (from models.yaml)
  !auto                return executor choice to the router
  !budget <usd>        set per-task budget cap
  !checklist on|off    enable/disable contract checklist extraction
  !checklist skip      skip the checklist for the NEXT turn only, then re-enable
  !sandbox local|gcloud|off|auto   where to execute code for verification
  !plan auto|on|off    task decomposition for large prompts (auto = size heuristic)
  !help                this message"""


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
        checklist = "off" if not state.contract_enabled else (
            "skip-next-turn" if state.contract_skip_once else "on")
        return (
            f"paused={state.paused} "
            f"executor={'auto' if not state.forced_executor else state.forced_executor} "
            f"budget={'default' if state.budget_usd is None else f'${state.budget_usd:.2f}'} "
            f"checklist={checklist} "
            f"sandbox={state.sandbox_backend or 'auto'} "
            f"plan={state.plan_mode}"
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
    if cmd in ("checklist", "contract"):
        if arg == "on":
            state.contract_enabled, state.contract_skip_once = True, False
            return "checklist extraction enabled"
        if arg == "off":
            state.contract_enabled = False
            return "checklist extraction disabled until !checklist on"
        if arg == "skip":
            state.contract_enabled, state.contract_skip_once = True, True
            return "checklist will be skipped for the next turn, then re-enabled"
        return "usage: !checklist on|off|skip"
    if cmd == "plan":
        if arg in ("auto", "on", "off"):
            state.plan_mode = arg
            return f"planning mode set to {arg}"
        return "usage: !plan auto|on|off"
    if cmd == "sandbox":
        if arg in ("local", "gcloud", "off"):
            state.sandbox_backend = arg
            return f"code execution backend set to {arg}"
        if arg == "auto":
            state.sandbox_backend = None
            return "code execution backend returned to models.yaml default"
        return "usage: !sandbox local|gcloud|off|auto"
    return f"unknown command !{cmd} — try !help"
