"""User intervention: in-band !commands and shared control state (SPEC §7.2).

Control messages are intercepted at the ingress and never forwarded to any
model. They work from inside any OSS client — no extra window required.
"""

from __future__ import annotations

from dataclasses import dataclass, field


PAUSED_NOTICE = (
    "[llm-super] supervisor is paused; no model was called. "
    "Send !resume, then resend the request to continue."
)

PAUSED_BOUNDARY_NOTICE = (
    "[llm-super] supervisor paused at the next execution boundary. "
    "An in-flight model call had already started, but no newly proposed tool "
    "action was released. Send !resume, then resend the request to continue."
)


@dataclass
class ControlState:
    paused: bool = False
    forced_executor: str | None = None
    budget_usd: float | None = None
    contract_enabled: bool = True
    contract_skip_once: bool = False   # skip checklist for the next turn only
    sandbox_backend: str | None = None  # None = models.yaml default; "off" disables
    plan_mode: str = "auto"            # auto | on (always plan) | off (never)
    # Answer strategy (§6.1): how a plain turn produces its answer.
    #   single  — one supervised executor (forced > learned > static routing)
    #   exploit — strictly the best-ranked executor from outcome history
    #   best    — N families in parallel, return the top-scoring candidate
    #   union   — N families, merge ALL distinct valid content (set union)
    #   fuse    — N families, synthesize keeping the strongest elements
    strategy: str = "single"
    ensemble_n: int = 0                # N for the multi-candidate strategies
    cutoff: float | None = None        # short-circuit: first candidate the
    # verifier scores >= cutoff wins immediately; remaining ones are cancelled
    breakpoints: list[str] = field(default_factory=list)
    # rules: "fm:<FM-ID>" | "budget:<usd>" | "escalation" (SPEC §7.1)
    gate_enabled: bool | None = None   # None = supervision.confirm_new_sessions
    history: list[str] = field(default_factory=list)

    def multi_mode(self) -> str:
        """Active multi-candidate mode ("best"/"union"/"fuse") or "".
        A bare ensemble_n >= 2 with strategy "single" counts as "fuse" —
        that keeps the original !ensemble semantics."""
        if self.strategy in ("best", "union", "fuse") and self.ensemble_n >= 2:
            return self.strategy
        if self.strategy == "single" and self.ensemble_n >= 2:
            return "fuse"
        return ""

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


def gate_warning(session: str, state: ControlState, cfg=None) -> str:
    """The new-conversation gate reply (SPEC §7): returned INSTEAD of calling
    any model when an unknown conversation sends its first non-command
    message. Continuing (or resending) confirms and runs normally."""
    strat = state.strategy + (f" ×{state.ensemble_n}" if state.multi_mode() else "")
    budget = (state.budget_usd if state.budget_usd is not None
              else cfg.supervision.budget_usd_per_task if cfg else 0.5)
    return (
        "[llm-super] ⚠ new-conversation gate — NO model was called and "
        "nothing was spent.\n\n"
        f"This request would start a NEW supervised conversation "
        f"(session {session[:12]}, strategy {strat}, budget "
        f"${budget:.2f}/task). Conversations are identified by their FIRST "
        "user message — a client that rewrites or annotates it silently "
        "starts a separate conversation each time.\n\n"
        "To proceed, resend or simply continue: the next message in this "
        "conversation runs normally. In-band commands never need "
        "confirmation and never call a model — !help lists them; "
        "!gate off disables this warning."
    )


HELP = """llm-super in-band commands (never forwarded to models):
  !status              show supervisor state
  !pause / !resume     pause or resume supervised execution
  !use <model>         force a specific executor (from models.yaml)
  !auto                return executor choice to the router
  !budget <usd>        set per-task budget cap
  !checklist on|off    enable/disable contract checklist extraction
  !checklist skip      skip the checklist for the NEXT turn only, then re-enable
  !sandbox gce|off|auto  verification backend (subject to operator lock)
  !plan auto|on|off    task decomposition for large prompts (auto = size heuristic)
  !strategy single|exploit|best <2-4>|union <2-4>|fuse <2-4>
                       how answers are produced: one routed model / the
                       history-ranked best model / top-of-N candidates /
                       set-union merge of N / synthesized fusion of N
  !cutoff <0-1>|off    short-circuit multi-candidate turns: first candidate
                       verified at or above this score wins immediately
  !ensemble <2-4>|off  alias for !strategy fuse <N> (the original §6.1 mode)
  !break fm:<FM-ID> | budget:<usd> | escalation   add a breakpoint (pause when hit)
  !break list / !break clear [rule]               show / remove breakpoints
  !checkpoints         list resumable checkpoints for this conversation
  !rewind <unit#>|all  forget a completed unit (or all) so resending re-runs it
  !edits               show this conversation's edit/rewind history (branches)
  !conversations       list recent conversations (id · age · turns · title)
  !attach <id-prefix>  continue an existing conversation from THIS client
                       thread (no model call; !attach off to detach)
  !gate on|off         confirmation gate for NEW conversations (on: first
                       message returns a warning, no model call; continuing confirms)
  !help                this message"""


def handle(text: str, state: ControlState, model_names: list[str],
           checkpoints=None, session: str | None = None,
           history=None, library=None,
           raw_session: str | None = None,
           execution_backend_lock: str | None = None) -> str | None:
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
            f"strategy={state.strategy}"
            f"{f' n={state.ensemble_n}' if state.multi_mode() else ''} "
            f"cutoff={'off' if state.cutoff is None else f'{state.cutoff:.2f}'} "
            f"gate={'default' if state.gate_enabled is None else ('on' if state.gate_enabled else 'off')} "
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
        if execution_backend_lock and arg not in {
            execution_backend_lock, "off", "auto"
        }:
            return (
                f"execution backend is operator-locked to {execution_backend_lock}; "
                f"refusing {arg or '<empty>'}"
            )
        if arg in ("gce", "off"):
            state.sandbox_backend = arg
            return f"code execution backend set to {arg}"
        if arg == "auto":
            state.sandbox_backend = None
            return "code execution backend returned to models.yaml default"
        return "usage: !sandbox gce|off|auto"
    if cmd == "strategy":
        mode, _, nstr = arg.partition(" ")
        if mode in ("single", "exploit"):
            state.strategy, state.ensemble_n = mode, 0
            return ("strategy: one supervised executor per turn "
                    "(forced > learned > static routing)" if mode == "single"
                    else "strategy: exploit — every turn uses the best-ranked "
                         "executor from outcome history (!strategy single to undo)")
        if mode in ("best", "union", "fuse"):
            try:
                n = int(nstr or state.ensemble_n or 3)
            except ValueError:
                return "usage: !strategy best|union|fuse <2-4>"
            if not 2 <= n <= 4:
                return "usage: !strategy best|union|fuse <2-4>"
            state.strategy, state.ensemble_n = mode, n
            desc = {
                "best": f"run {n} model families in parallel, verify each, "
                        "return the top-scoring candidate",
                "union": f"run {n} model families, merge every distinct valid "
                         "element from all candidates (set union), verify the merge",
                "fuse": f"run {n} model families, synthesize a fused answer "
                        "keeping the strongest elements, verify the fusion",
            }[mode]
            return (f"strategy: {mode} — {desc} — roughly "
                    f"{n + (0 if mode == 'best' else 1)}x the usual cost"
                    + ("" if state.cutoff is None else
                       f"; cutoff {state.cutoff:.2f} may end turns early"))
        return "usage: !strategy single | exploit | best <2-4> | union <2-4> | fuse <2-4>"
    if cmd == "conversations":
        if library is None:
            return "conversation list unavailable in this context"
        rows = library.sessions()
        if not rows:
            return "no conversations yet"
        import time as _time
        lines = []
        for r in rows[:15]:
            age_m = (_time.time() - r["last_ts"]) / 60
            age = f"{age_m:.0f}m" if age_m < 120 else f"{age_m / 60:.1f}h"
            here = "  ← you are here" if r["session"] == session else ""
            title = " ".join((r["title"] or "(untitled)").split())[:60]
            lines.append(f"- {r['session']} · {age} ago · {r['turns']} turn(s) · "
                         f"{title}{here}")
        return ("conversations (newest first; !attach <id-prefix> continues "
                "one from THIS client thread):\n" + "\n".join(lines))
    if cmd == "attach":
        if library is None:
            return "attach unavailable in this context"
        src = raw_session or session
        if not arg:
            return "usage: !attach <session-id-prefix> | off   (!conversations to list)"
        if arg in ("off", "detach"):
            return ("detached — this thread is its own conversation again"
                    if library.drop_alias(src)
                    else "this thread was not attached to anything")
        matches = [r for r in library.sessions() if r["session"].startswith(arg)]
        if not matches:
            return f"no conversation id starts with {arg!r} (!conversations to list)"
        if len(matches) > 1:
            return (f"{arg!r} matches {len(matches)} conversations — give more "
                    "characters (!conversations to list)")
        target = matches[0]["session"]
        if target in (session, src):
            return "already in that conversation"
        try:
            library.set_alias(src, target)
        except ValueError as e:
            return str(e)
        return (f"attached — messages in this client thread now continue "
                f"conversation {target} (\"{(matches[0]['title'] or '')[:50]}\"). "
                "Checkpoints, edit history, and context follow it; "
                "!attach off to detach")
    if cmd == "gate":
        if arg in ("on", "off"):
            state.gate_enabled = arg == "on"
            return ("new-conversation gate enabled — the first message of an "
                    "unknown conversation returns a warning instead of "
                    "calling a model" if state.gate_enabled else
                    "new-conversation gate disabled — new conversations run "
                    "immediately")
        return "usage: !gate on|off"
    if cmd == "cutoff":
        if arg == "off":
            state.cutoff = None
            return "short-circuit cutoff off — all candidates always run to completion"
        try:
            v = float(arg)
        except ValueError:
            return "usage: !cutoff <0-1> | off"
        if not 0 < v <= 1:
            return "usage: !cutoff <0-1> | off"
        state.cutoff = v
        return (f"short-circuit cutoff set to {v:.2f} — in best/union/fuse "
                "turns the first candidate the verifier scores at or above "
                "this wins immediately and the rest are cancelled")
    if cmd == "ensemble":
        if arg in ("off", "0"):
            state.ensemble_n = 0
            state.strategy = "single"
            return "ensemble mode off"
        try:
            n = int(arg)
        except ValueError:
            return "usage: !ensemble <2-4> | off"
        if not 2 <= n <= 4:
            return "usage: !ensemble <2-4> | off"
        state.ensemble_n = n
        state.strategy = "fuse"
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
