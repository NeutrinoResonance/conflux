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
from dataclasses import dataclass, field

from .config import Config
from .providers import ChatResult, Client, chat_chain


@dataclass
class Unit:
    description: str
    depends_on: list[int] = field(default_factory=list)  # 0-based indices


_PROMPT = """You are a task planner. Decide whether the task below should be \
split into work units, each completable and checkable on its own.

Split ONLY if the task genuinely contains multiple separable deliverables or \
is too large to do well in one pass. Simple or single-deliverable tasks must \
NOT be split.

Reply with ONLY a JSON object:
- {{"units": []}} if the task should be done in one pass
- otherwise 2 to {max_units} units:
  {{"units": [{{"description": "...", "depends_on": []}}, \
{{"description": "...", "depends_on": [1]}}]}}
where depends_on lists the 1-based numbers of units whose OUTPUT this unit \
needs as input. Leave depends_on empty for independent units — independent \
units run in parallel. Each description must be self-contained (it is given \
to a model along with the original task).

Task:
{task}"""


async def plan(client: Client, cfg: Config, task: str) -> tuple[list[Unit], ChatResult | None]:
    try:
        res, _ = await chat_chain(
            client, cfg, cfg.utility,
            [{"role": "user", "content": _PROMPT.format(
                task=task[:10000], max_units=cfg.supervision.max_plan_units)}],
            max_tokens=1200,
            temperature=0.0,
        )
    except Exception:
        return [], None
    m = re.search(r"\{.*\}", res.text, re.DOTALL)
    if not m:
        return [], res
    try:
        raw = json.loads(m.group(0)).get("units", [])
    except (json.JSONDecodeError, AttributeError):
        return [], res

    units: list[Unit] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            units.append(Unit(description=item))
        elif isinstance(item, dict) and str(item.get("description", "")).strip():
            deps = [int(d) - 1 for d in item.get("depends_on", [])
                    if isinstance(d, (int, float)) and int(d) >= 1]
            units.append(Unit(description=str(item["description"]), depends_on=deps))
    units = units[: cfg.supervision.max_plan_units]
    # sanitize: drop forward/self/out-of-range deps so waves always terminate
    for i, u in enumerate(units):
        u.depends_on = sorted({d for d in u.depends_on if 0 <= d < i})
    if len(units) < 2:  # a 1-unit plan is just overhead
        return [], res
    return units, res


def waves(units: list[Unit]) -> list[list[int]]:
    """Group unit indices into dependency waves; each wave runs in parallel."""
    done: set[int] = set()
    out: list[list[int]] = []
    remaining = set(range(len(units)))
    while remaining:
        wave = [i for i in sorted(remaining) if set(units[i].depends_on) <= done]
        if not wave:  # cycle (shouldn't happen post-sanitize) — run the rest serially
            wave = [min(remaining)]
        out.append(wave)
        done.update(wave)
        remaining.difference_update(wave)
    return out
