"""Contract extraction: turn a task prompt into a checklist of explicit,
checkable constraints (targets FM-1.1 — 41.8% of failures in MAST are
specification failures, so we spend cheap tokens making the spec explicit).

The same call also classifies task difficulty (SPEC §8: the router chooses
executor tier by estimated difficulty — a small-model classifier over the
contract). One utility call buys both.
"""

from __future__ import annotations

import json
import re

from .config import Config
from .providers import ChatResult, Client, chat_chain

DIFFICULTIES = ("trivial", "routine", "hard")

_PROMPT = """Analyze the task below.

1. Extract its explicit requirements as short, individually checkable \
constraints (strings). Include format requirements, scope requirements, and \
any prohibitions. Do not invent requirements that are not stated or clearly \
implied.
2. Classify its difficulty:
- "trivial": mechanical, single-step, no real design or reasoning \
(reformatting, renaming, a one-line answer, a simple lookup)
- "routine": ordinary coding or writing a competent model does in one pass
- "hard": genuinely difficult — multi-component design, tricky algorithms, \
subtle correctness requirements, or high cost of being wrong

Reply with ONLY a JSON object:
{{"constraints": ["...", "..."], "difficulty": "trivial|routine|hard"}}

Task:
{task}"""


async def extract(client: Client, cfg: Config, task: str
                  ) -> tuple[list[str], str, ChatResult | None]:
    """Returns (constraints, difficulty, chat result). Failures degrade to
    ([], "routine", ...) — the turn proceeds unrouted rather than dying."""
    try:
        res, _ = await chat_chain(
            client, cfg, cfg.utility,
            [{"role": "user", "content": _PROMPT.format(task=task[:6000])}],
            max_tokens=800,
            temperature=0.0,
        )
    except Exception:
        return [], "routine", None
    m = re.search(r"\{.*\}", res.text, re.DOTALL)
    if not m:
        return [], "routine", res
    try:
        raw = json.loads(m.group(0))
    except json.JSONDecodeError:
        return [], "routine", res
    items = raw.get("constraints", [])
    if not isinstance(items, list):
        items = []
    difficulty = str(raw.get("difficulty", "routine")).lower()
    if difficulty not in DIFFICULTIES:
        difficulty = "routine"
    constraints = [str(x) for x in items
                   if isinstance(x, (str, int, float))][:20]
    return constraints, difficulty, res
