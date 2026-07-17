"""Contract extraction: turn a task prompt into a checklist of explicit,
checkable constraints (targets FM-1.1 — 41.8% of failures in MAST are
specification failures, so we spend cheap tokens making the spec explicit).
"""

from __future__ import annotations

import json
import re

from .config import Config
from .providers import ChatResult, Client, chat_chain

_PROMPT = """Extract the explicit requirements from the task below as a JSON \
array of short, individually checkable constraints (strings). Include format \
requirements, scope requirements, and any prohibitions. Do not invent \
requirements that are not stated or clearly implied. Reply with ONLY the JSON \
array.

Task:
{task}"""


async def extract(client: Client, cfg: Config, task: str) -> tuple[list[str], ChatResult | None]:
    try:
        res, _ = await chat_chain(
            client, cfg, cfg.utility,
            [{"role": "user", "content": _PROMPT.format(task=task[:6000])}],
            max_tokens=800,
            temperature=0.0,
        )
    except Exception:
        return [], None
    m = re.search(r"\[.*\]", res.text, re.DOTALL)
    if not m:
        return [], res
    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError:
        return [], res
    return [str(x) for x in items if isinstance(x, (str, int, float))][:20], res
