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
    ensemble_n: int = 0                # >=2: best-of-N families + fusion (§6.1)
    breakpoints: list[str] = field(default_factory=list)
    # rules: "fm:<FM-ID>" | "budget:<usd>" | "escalation" (SPEC §7.1)
    history: list[str] = field(default_factory=list)

    def consume_contract_enabled(self) -> bool:
        """Whether the *current* turn should extract a contract checklist."""
        if self.contract_skip_once:
            self.contract_skip_once = False
            return False
        return self.contract_enabled

    def breakpoint_hit(self, *, fm_ids: tuple[str, ...] | list[str] = (),
                       spent: float = 0.0, escalation: bool = False) -> str | None:
        """First matching breakpoint rule, or None. The caller pauses the
        supervisor and parks the task at its checkpoint."""
        for rule in self.breakpoints:
            if rule.startswith("fm:") and rule[3:] in fm_ids:
                return rule
            if rule.startswith("budget:"):
                try:
                    if spent >= float(rule[7:]):
                        return rule
                except ValueError:
                    continue
            if rule == "escalation" and escalation:
                return rule
        return None


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
  !ensemble <2-4>|off  best-of-N across model families + verified fusion (costly)
  !break fm:<FM-ID> | budget:<usd> | escalation   add a breakpoint (pause when hit)
  !break list / !break clear [rule]               show / remove breakpoints
  !checkpoints         list resumable checkpoints for this conversation
  !rewind <unit#>|all  forget a completed unit (or all) so resending re-runs it
  !edits               show this conversation's edit/rewind history (branches)
  !help                this message"""


def handle(text: str, state: ControlState, model_names: list[str],
           checkpoints=None, session: str | None = None,
           history=None) -> str | None:
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
            f"plan={state.plan_mode} "
            f"ensemble={'off' if not state.ensemble_n else state.ensemble_n} "
            f"breakpoints={','.join(state.breakpoints) or 'none'}"
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
    if cmd == "ensemble":
        if arg in ("off", "0"):
            state.ensemble_n = 0
            return "ensemble mode off"
        try:
            n = int(arg)
        except ValueError:
            return "usage: !ensemble <2-4> | off"
        if not 2 <= n <= 4:
            return "usage: !ensemble <2-4> | off"
        state.ensemble_n = n
        return (f"ensemble mode: every plain turn samples {n} model families "
                "in parallel, verifies each, and returns a verified fusion — "
                f"roughly {n + 1}x the usual cost (!ensemble off to stop)")
    if cmd == "break":
        if arg == "list" or not arg:
            return ("breakpoints: " + ", ".join(state.breakpoints)
                    if state.breakpoints else "no breakpoints set")
        if arg.startswith("clear"):
            _, _, which = arg.partition(" ")
            which = which.strip()
            if not which:
                n = len(state.breakpoints)
                state.breakpoints.clear()
                return f"cleared {n} breakpoint(s)"
            if which in state.breakpoints:
                state.breakpoints.remove(which)
                return f"cleared breakpoint {which}"
            return f"no such breakpoint {which!r} (!break list)"
        valid = (arg == "escalation"
                 or (arg.startswith("fm:") and len(arg) > 3)
                 or arg.startswith("budget:"))
        if arg.startswith("budget:"):
            try:
                float(arg[7:])
            except ValueError:
                return f"could not parse {arg[7:]!r} as a dollar amount"
        if not valid:
            return "usage: !break fm:<FM-ID> | budget:<usd> | escalation | list | clear [rule]"
        if arg not in state.breakpoints:
            state.breakpoints.append(arg)
        return (f"breakpoint set: {arg} — the supervisor will pause when it "
                "hits (then !resume and resend to continue from checkpoint)")
    if cmd == "checkpoints":
        if checkpoints is None or session is None:
            return "checkpoints unavailable in this context"
        rows = checkpoints.for_session(session)
        if not rows:
            return "no checkpoints for this conversation"
        lines = []
        for r in rows:
            done = ", ".join(str(i + 1) for i in r["completed"]) or "none"
            age_m = r["age_s"] / 60
            lines.append(
                f"- {len(r['completed'])}/{len(r['units'])} units done "
                f"(units {done}) · ${r['spent']:.3f} spent · {age_m:.0f}m old")
            for i, u in enumerate(r["units"]):
                mark = "✓" if i in r["completed"] else "·"
                lines.append(f"    {mark} unit {i+1}: {u['description'][:90]}")
        return ("checkpoints (resend the same request to resume; "
                "!rewind <unit#> to re-run a unit):\n" + "\n".join(lines))
    if cmd == "edits":
        if history is None or session is None:
            return "edit history unavailable in this context"
        rows = history.edits(session)
        if not rows:
            return "no edits detected in this conversation"
        import time as _time
        lines = []
        for r in rows:
            age_m = (_time.time() - r["ts"]) / 60
            what = (f"message {r['position'] + 1} ({r['role']}) edited: "
                    f"\"{(r['old_text'] or '')[:70]}\" → \"{(r['new_text'] or '')[:70]}\""
                    if r["kind"] == "edit" else
                    f"rewound to before message {r['position'] + 1} "
                    f"(dropped: \"{(r['old_text'] or '')[:70]}\")")
            lines.append(f"- branch {r['branch']} · {age_m:.0f}m ago · {what}")
        return ("edit history (each divergence forked a branch; superseded "
                "turns remain in the trace):\n" + "\n".join(lines))
    if cmd == "rewind":
        if checkpoints is None or session is None:
            return "rewind unavailable in this context"
        rows = checkpoints.for_session(session)
        if not rows:
            return "no checkpoints for this conversation"
        key = rows[0]["key"]  # newest
        if arg == "all":
            checkpoints.delete(key)
            return ("checkpoint deleted — resending the request starts the "
                    "turn from scratch")
        try:
            unit_no = int(arg) - 1
        except ValueError:
            return "usage: !rewind <unit#> | all"
        if checkpoints.drop_unit(key, unit_no):
            return (f"unit {arg} forgotten — resend the same request and it "
                    "will re-run (other completed units are kept)")
        return f"unit {arg} is not a completed unit in the checkpoint (!checkpoints)"
    return f"unknown command !{cmd} — try !help"
