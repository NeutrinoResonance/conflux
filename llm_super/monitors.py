"""Heuristic runtime monitors keyed to failure-mode IDs (docs/failure-taxonomy.md).

Cheap, non-LLM detectors that run on every executor output. Each hit becomes
an FMEvent and, downstream, targeted repair feedback. LLM-based monitors
(contract checking) live in contract.py / verifier.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FMEvent:
    fm_id: str
    confidence: float          # 0..1, heuristic
    evidence: str              # short quote from the output
    feedback: str              # instruction for the repair attempt


_STUB_PATTERNS = [
    r"\bTODO\b",
    r"\bFIXME\b",
    r"rest of (the )?(code|implementation|file)",
    r"omitted for brevity",
    r"left as an exercise",
    r"implement (this|the rest) (yourself|later)",
    r"\.\.\.\s*(rest|remaining|more code)",
    r"^\s*pass\s*#",
    r"# (your|actual) (code|logic|implementation) here",
    r"</?placeholder>",
]

_UNEVIDENCED_CLAIMS = [
    r"all tests pass",
    r"tests? (now )?pass(es)? successfully",
    r"verified (that|the) .{0,40}works",
    r"I have (thoroughly )?tested",
]

_REFUSAL_LAZINESS = [
    r"I (cannot|can't|won't) (write|complete|implement) the (entire|whole|full)",
    r"this (would be|is) too (long|complex) to",
    r"you can (easily )?(do|implement|add) th(is|e rest)",
]


def _scan(text: str, patterns: list[str]) -> str | None:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            start = max(0, m.start() - 40)
            return text[start : m.end() + 40].strip()
    return None


def run_monitors(output: str, prompt: str) -> list[FMEvent]:
    events: list[FMEvent] = []

    if ev := _scan(output, _STUB_PATTERNS):
        events.append(
            FMEvent(
                "FM-X.1",
                0.8,
                ev,
                "The response contains stubs/placeholders instead of complete work. "
                "Produce the full implementation with nothing omitted.",
            )
        )

    if ev := _scan(output, _UNEVIDENCED_CLAIMS):
        events.append(
            FMEvent(
                "FM-X.4",
                0.6,
                ev,
                "The response claims success (e.g. passing tests) without showing "
                "evidence. Remove unsupported claims or show the actual results.",
            )
        )

    if ev := _scan(output, _REFUSAL_LAZINESS):
        events.append(
            FMEvent(
                "FM-X.1",
                0.7,
                ev,
                "The response defers work back to the user. Complete the task "
                "fully as requested.",
            )
        )

    # Premature termination heuristic: substantial ask, tiny answer.
    if len(prompt) > 400 and len(output.strip()) < 80:
        events.append(
            FMEvent(
                "FM-3.1",
                0.5,
                output.strip()[:80],
                "The response is far shorter than the task warrants; it appears "
                "to have stopped before completing the objective.",
            )
        )

    return events


def run_session_monitors(
    history: list[dict], task: str, msg_count: int
) -> list[FMEvent]:
    """Cross-turn monitors over the reconstructed trajectory (SPEC §5.3/5.6/5.9).

    These are ADVISORY: they observe the client-side agent's behavior across
    turns, so they surface in the trailer and trace rather than triggering
    repairs (the failing party is usually the driving agent, not this turn's
    executor).
    """
    from .history import similarity

    events: list[FMEvent] = []
    if not history:
        return events

    # FM-1.3 step repetition: current task highly similar to recent tasks.
    repeats = [t for t in history[-4:] if similarity(task, t["task"] or "") > 0.6]
    if len(repeats) >= 2:
        events.append(FMEvent(
            "FM-1.3", 0.6,
            f"{len(repeats)} recent turns with near-identical requests",
            "The driving agent appears to be repeating the same step across "
            "turns without incorporating results.",
        ))

    # FM-X.2 breadth thrash: many rapid turns, mutually dissimilar tasks,
    # none reaching a passing score — shallow exploration without depth.
    recent = history[-5:]
    if len(recent) >= 4:
        span = recent[-1]["ts"] - recent[0]["ts"]
        sims = [similarity(recent[i]["task"] or "", recent[i + 1]["task"] or "")
                for i in range(len(recent) - 1)]
        low_scores = [t for t in recent if (t["score"] or 0) < 0.7]
        if span < 900 and sims and max(sims) < 0.4 and len(low_scores) >= 3:
            events.append(FMEvent(
                "FM-X.2", 0.5,
                f"{len(recent)} dissimilar low-scoring turns in {span:.0f}s",
                "The driving agent is hopping between unrelated approaches "
                "without carrying any of them to a working state.",
            ))

    # FM-1.4 / FM-2.1 context loss: the conversation shrank versus what we
    # have seen — client-side truncation or an unexpected reset.
    max_msgs = max((t["msg_count"] or 0) for t in history)
    if msg_count < max_msgs:
        events.append(FMEvent(
            "FM-1.4", 0.7,
            f"conversation shrank from {max_msgs} to {msg_count} messages",
            "Conversation history was truncated or reset; earlier context "
            "may have been lost.",
        ))

    # Progress stall (SPEC §5.6, advisory only — the paper's success/fail
    # correlation gap is modest): verifier scores flat-or-declining across
    # several turns.
    scores = [t["score"] for t in history[-4:] if t["score"] is not None]
    if len(scores) >= 3 and all(s < 0.7 for s in scores) and scores[-1] <= scores[0]:
        events.append(FMEvent(
            "FM-2.3", 0.4,
            f"verifier scores not improving: {[round(s, 2) for s in scores]}",
            "Task progress appears stalled across turns; consider changing "
            "approach or intervening (!status, !use <model>, !plan on).",
        ))

    return events
