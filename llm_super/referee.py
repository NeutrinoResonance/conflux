"""Referee (SPEC §3/§4): on verification failure, diagnose and pick a repair
strategy — {retry with targeted feedback | switch model | escalate
verification | decompose | ask user}.

Cost posture is "rare, on-failure only": the first failure is repaired with
targeted feedback (a rule, no referee call); the LLM referee convenes once
feedback repair has already been tried, and the §4 anti-loop rule is enforced
in code, not by the model — from the second failure on, plain retry is no
longer on the menu and something structural must change.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .config import Config
from .providers import Client, chat_chain

STRATEGIES = ("retry_feedback", "switch_model", "escalate_verification",
              "decompose", "ask_user")


@dataclass
class Decision:
    strategy: str
    target_model: str = ""     # for switch_model
    question: str = ""         # for ask_user
    rationale: str = ""
    source: str = "rule"       # rule (deterministic) | llm
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


_PROMPT = """You are the referee in a supervised multi-model ensemble. An \
executor model has produced work that failed independent verification \
{attempts} time(s). Plain retry-with-feedback has already been tried, so you \
must change something structural. Diagnose the failure and choose ONE repair \
strategy from exactly these options:

{options}

Failure evidence:
- Task (truncated): {task}
- Executor models already tried: {tried}
- Failure-mode events detected: {fm_events}
- Verifier feedback: {feedback}
- Tail of the failing output: {output_tail}

Reply with ONLY a JSON object:
{{"strategy": "<one of the options>", "target_model": "<only for \
switch_model, one of the candidates listed>", "question": "<only for \
ask_user: the concrete question the user must answer>", "rationale": "<one \
sentence>"}}"""

_OPTION_HELP = {
    "switch_model": ("switch_model — reroute to a different model family; "
                     "candidates (ordered by how uncorrelated their known "
                     "failure priors are with the observed failures): {cands}"),
    "escalate_verification": ("escalate_verification — the output may actually "
                              "be fine and the verifier wrong (or the unit is "
                              "high-risk): retry once and re-judge at the "
                              "adversarial verification tier (more repeats, "
                              "criteria decomposed, refutation-framed)"),
    "decompose": ("decompose — the task is too large for one pass: split it "
                  "into supervised units and re-run"),
    "ask_user": ("ask_user — the task is ambiguous or blocked on information "
                 "only the user has: stop and ask (this parks the task; "
                 "prefer it over guessing)"),
}


def switch_candidates(cfg: Config, models_tried: list[str],
                      fm_events: list[str],
                      repair_stats: list[dict] | None = None) -> list[str]:
    """Executor models in families not yet tried, ordered by (a) learned
    repair success on the observed failure modes, when we have it, then
    (b) fewest failure priors shared with the observed events — the SPEC's
    uncorrelated-failure-priors rule applied to rerouting."""
    tried_families = {cfg.models[m].family for m in models_tried
                      if m in cfg.models}
    fmset = set(fm_events)
    learned: dict[str, float] = {}
    for row in repair_stats or []:
        if row["fm_id"] in fmset or row["fm_id"] == "-":
            cur = learned.get(row["model"])
            learned[row["model"]] = max(cur or 0.0, row["success_rate"])
    scored = []
    for pos, (name, m) in enumerate(cfg.models.items()):
        if "executor" not in m.roles or m.family in tried_families:
            continue
        overlap = len(fmset & set(m.failure_priors))
        scored.append((-(learned.get(name, 0.0)), overlap, pos, name))
    return [name for *_, name in sorted(scored)]


async def decide(
    client: Client,
    cfg: Config,
    *,
    task: str,
    output_tail: str,
    fm_events: list[str],
    verify_feedback: str,
    attempts: int,
    models_tried: list[str],
    allow_decompose: bool,
    tier: str,
    repair_stats: list[dict] | None = None,
) -> Decision:
    # While the model still has feedback retries left (§4: at most
    # max_repairs repair attempts before a structural change), the decision
    # is a rule — targeted feedback retry, no referee spend. Exception:
    # FM-1.3 (the attempt repeated itself despite feedback) proves more
    # feedback is pointless, so the ladder goes structural immediately.
    if attempts <= cfg.supervision.max_repairs and "FM-1.3" not in fm_events:
        return Decision("retry_feedback", source="rule")

    candidates = switch_candidates(cfg, models_tried, fm_events, repair_stats)
    options = []
    if candidates:
        options.append(_OPTION_HELP["switch_model"].format(
            cands=", ".join(candidates)))
    if tier != "adversarial":
        options.append(_OPTION_HELP["escalate_verification"])
    if allow_decompose:
        options.append(_OPTION_HELP["decompose"])
    options.append(_OPTION_HELP["ask_user"])
    allowed = {o.split(" ", 1)[0] for o in options}

    fallback = (Decision("switch_model", target_model=candidates[0],
                         rationale="referee unavailable; rerouting to the "
                                   "least-correlated untried family",
                         source="rule")
                if candidates else
                Decision("ask_user",
                         question=("Repeated repair attempts failed "
                                   f"({verify_feedback[:200] or 'low verifier score'}). "
                                   "How should I proceed?"),
                         source="rule"))
    try:
        res, _ = await chat_chain(
            client, cfg, cfg.referee or cfg.default_executor,
            [{"role": "user", "content": _PROMPT.format(
                attempts=attempts,
                options="\n".join(f"- {o}" for o in options),
                task=task[:3000],
                tried=", ".join(models_tried) or "(unknown)",
                fm_events=", ".join(sorted(set(fm_events))) or "(none)",
                feedback=verify_feedback[:1200] or "(none)",
                output_tail=output_tail[-1500:],
            )}],
            max_tokens=600, temperature=0.0)
    except Exception:
        return fallback

    fallback.cost_usd = res.cost_usd
    fallback.tokens_in = res.tokens_in
    fallback.tokens_out = res.tokens_out
    m = re.search(r"\{.*\}", res.text, re.DOTALL)
    if not m:
        return fallback
    try:
        raw = json.loads(m.group(0))
    except json.JSONDecodeError:
        return fallback
    strategy = str(raw.get("strategy", ""))
    if strategy not in allowed:
        return fallback
    target = str(raw.get("target_model", ""))
    if strategy == "switch_model" and target not in candidates:
        target = candidates[0]
    return Decision(
        strategy=strategy,
        target_model=target if strategy == "switch_model" else "",
        question=str(raw.get("question", "")) if strategy == "ask_user" else "",
        rationale=str(raw.get("rationale", ""))[:300],
        source="llm",
        cost_usd=res.cost_usd,
        tokens_in=res.tokens_in,
        tokens_out=res.tokens_out,
    )
