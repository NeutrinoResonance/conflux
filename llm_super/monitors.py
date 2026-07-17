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
