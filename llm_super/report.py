"""Efficiency report (SPEC §8): where the dollars and tokens go.

Aggregates the trace event ledger into the two KPIs the cost model names:
- supervision overhead (contract + plan + verify + referee + synthesis)
  as a share of total spend — target < 15% of tokens;
- repair spend (execute attempts > 1, plus referee calls) vs first-pass —
  should trend down as routing priors learn.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

# event kind -> spend bucket; "execute" splits into first_pass/repair by
# the attempt number recorded in the event data
_BUCKETS = {
    "execute": "executor",
    "tool_step": "executor",
    "passthrough": "executor",
    "synthesis": "synthesis",
    "verify": "verify",
    "ensemble_candidate": "verify",   # candidate verification in best/union/fuse
    "contract": "contract",
    "plan": "plan",
    "referee": "referee",
}
OVERHEAD = ("verify", "contract", "plan", "referee", "synthesis")


def efficiency(path: str | Path, days: float = 30.0) -> dict[str, Any]:
    conn = sqlite3.connect(str(path))
    try:
        cur = conn.execute(
            "SELECT ts, kind, model, tokens_in, tokens_out, cost_usd, data "
            "FROM events WHERE ts >= ?", (time.time() - days * 86400,))
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()

    cost: dict[str, float] = {}
    tokens: dict[str, int] = {}
    per_model: dict[str, dict[str, float]] = {}
    daily: dict[str, dict[str, float]] = {}

    for ts, kind, model, tin, tout, usd, data in rows:
        bucket = _BUCKETS.get(kind)
        if bucket is None:
            continue
        usd = usd or 0.0
        tok = (tin or 0) + (tout or 0)
        if bucket == "executor":
            attempt = 1
            if data:
                try:
                    attempt = int(json.loads(data).get("attempt", 1) or 1)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
            bucket = "repair" if attempt > 1 else "first_pass"
        elif kind == "ensemble_candidate" and data:
            # the event names the CANDIDATE model but carries the VERIFIER's
            # spend — attribute per-model cost to the verifier
            try:
                model = json.loads(data).get("verifier") or model
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        cost[bucket] = cost.get(bucket, 0.0) + usd
        tokens[bucket] = tokens.get(bucket, 0) + tok
        if model:
            m = per_model.setdefault(model, {"cost_usd": 0.0, "tokens": 0})
            m["cost_usd"] += usd
            m["tokens"] += tok
        day = time.strftime("%Y-%m-%d", time.localtime(ts))
        d = daily.setdefault(day, {"first_pass": 0.0, "repair": 0.0})
        if bucket == "first_pass":
            d["first_pass"] += usd
        elif bucket in ("repair", "referee"):
            d["repair"] += usd

    total_cost = sum(cost.values())
    total_tokens = sum(tokens.values())
    overhead_cost = sum(cost.get(b, 0.0) for b in OVERHEAD)
    overhead_tokens = sum(tokens.get(b, 0) for b in OVERHEAD)
    work_cost = cost.get("first_pass", 0.0) + cost.get("repair", 0.0) \
        + cost.get("referee", 0.0)
    repair_cost = cost.get("repair", 0.0) + cost.get("referee", 0.0)

    return {
        "window_days": days,
        "by_role": {
            b: {"cost_usd": round(cost.get(b, 0.0), 4),
                "tokens": tokens.get(b, 0)}
            for b in ("first_pass", "repair", "verify", "contract", "plan",
                      "referee", "synthesis")
        },
        "per_model": {
            m: {"cost_usd": round(v["cost_usd"], 4), "tokens": int(v["tokens"])}
            for m, v in sorted(per_model.items(),
                               key=lambda kv: -kv[1]["cost_usd"])
        },
        "kpi": {
            # SPEC §8: supervision overhead < 15% of tokens
            "overhead_pct_tokens": round(100 * overhead_tokens / total_tokens, 1)
            if total_tokens else None,
            "overhead_pct_cost": round(100 * overhead_cost / total_cost, 1)
            if total_cost else None,
            # repair spend share of executor spend — should trend down
            "repair_pct_of_executor": round(100 * repair_cost / work_cost, 1)
            if work_cost else None,
        },
        "daily_repair_share": [
            {"day": day,
             "repair_pct": round(100 * v["repair"]
                                 / (v["first_pass"] + v["repair"]), 1)
             if (v["first_pass"] + v["repair"]) else None,
             "spend_usd": round(v["first_pass"] + v["repair"], 4)}
            for day, v in sorted(daily.items())
        ],
        "total_cost_usd": round(total_cost, 4),
        "total_tokens": total_tokens,
    }


def format_text(rep: dict[str, Any]) -> str:
    """Human-readable rendering for the CLI."""
    lines = [f"efficiency report — last {rep['window_days']:.0f} days: "
             f"${rep['total_cost_usd']:.4f}, {rep['total_tokens']:,} tokens"]
    lines.append("  spend by role:")
    for role, v in rep["by_role"].items():
        if v["cost_usd"] or v["tokens"]:
            lines.append(f"    {role:<11} ${v['cost_usd']:.4f}  "
                         f"{v['tokens']:>10,} tok")
    k = rep["kpi"]
    lines.append(
        f"  supervision overhead: "
        f"{k['overhead_pct_tokens'] if k['overhead_pct_tokens'] is not None else '—'}% "
        f"of tokens (target <15%), "
        f"{k['overhead_pct_cost'] if k['overhead_pct_cost'] is not None else '—'}% of cost")
    lines.append(
        f"  repair spend: "
        f"{k['repair_pct_of_executor'] if k['repair_pct_of_executor'] is not None else '—'}% "
        f"of executor spend (should trend down)")
    if rep["daily_repair_share"]:
        lines.append("  repair share by day:")
        for d in rep["daily_repair_share"][-14:]:
            pct = f"{d['repair_pct']}%" if d["repair_pct"] is not None else "—"
            lines.append(f"    {d['day']}  {pct:>6}  (${d['spend_usd']:.4f})")
    if rep["per_model"]:
        lines.append("  spend by model:")
        for m, v in list(rep["per_model"].items())[:10]:
            lines.append(f"    {m:<22} ${v['cost_usd']:.4f}  "
                         f"{v['tokens']:>10,} tok")
    return "\n".join(lines)
