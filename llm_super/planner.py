"""Task decomposition for intense prompts (SPEC §4 planner stage).

Large or multi-part tasks fail in characteristic ways when attempted in one
shot: premature termination (FM-3.1) on the tail parts, and effort collapse
(FM-X.1) spread thin across all of them. Decomposing into units lets each
unit get its own execution, monitoring, verification, and repair budget.

The planner is a cheap utility-model call, triggered only for tasks above a
size threshold (or forced with !plan on). It must return either an empty
list — "do it in one shot" — or 2..max_units self-contained unit
descriptions. Planning failures are non-fatal: we fall back to single-shot.
"""

from __future__ import annotations

import json
import re

from .config import Config
from .providers import ChatResult, Client, chat_chain

_PROMPT = """You are a task planner. Decide whether the task below should be \
split into sequential work units, each completable and checkable on its own.

Split ONLY if the task genuinely contains multiple separable deliverables or \
is too large to do well in one pass. Simple or single-deliverable tasks must \
NOT be split.

Reply with ONLY a JSON object:
- {{"units": []}} if the task should be done in one pass
- {{"units": ["unit 1 description", ...]}} with 2 to {max_units} units otherwise.
Each unit description must be self-contained (it will be given to a model \
along with the original task).

Task:
{task}"""


async def plan(client: Client, cfg: Config, task: str) -> tuple[list[str], ChatResult | None]:
    try:
        res, _ = await chat_chain(
            client, cfg, cfg.utility,
            [{"role": "user", "content": _PROMPT.format(
                task=task[:10000], max_units=cfg.supervision.max_plan_units)}],
            max_tokens=900,
            temperature=0.0,
        )
    except Exception:
        return [], None
    m = re.search(r"\{.*\}", res.text, re.DOTALL)
    if not m:
        return [], res
    try:
        units = json.loads(m.group(0)).get("units", [])
    except (json.JSONDecodeError, AttributeError):
        return [], res
    units = [str(u) for u in units if isinstance(u, str) and u.strip()]
    if len(units) < 2:  # a 1-unit plan is just overhead
        return [], res
    return units[: cfg.supervision.max_plan_units], res
