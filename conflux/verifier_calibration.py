"""Verifier-calibration harness: measure false-pass and discrimination.

Answers SPEC §11's open question ("measure verifier false-pass rate against
seeded failures before trusting risk-tiering") and field-report 2026-07-17
deficiency 1 (score saturation: every observed verdict ≥ 0.99999, so
best-of-N degenerated to first-past-the-post).

The harness scores a fixed, self-contained suite of seeded answers — for
each task one known-good answer and several known-flawed ones keyed to
failure modes (FM-X.1 stub, FM-X.4 unsupported success claim, FM-1.1
ignored constraint, plain wrong output) — through the real continuous
logprob scoring path, one verifier family at a time (no cross-family
failover, so each family's behavior is measured, not masked). Results are
persisted per run in the trace database and summarized per family:

- ``false_pass_rate``   — flawed answers the family passed (the dangerous one)
- ``false_fail_rate``   — good answers the family failed
- ``discrimination``    — mean(good scores) − mean(flawed scores)
- ``saturation_rate``   — share of all scores above 0.99
- ``continuous_rate``   — share of scores read from logprobs (not degraded)
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config
from .providers import Client, ProviderError
from .verifier import DEFAULT_CRITERIA, Verifier


@dataclass(frozen=True)
class SeededAnswer:
    id: str
    kind: str                  # 'good' | 'flawed'
    text: str
    flaw: str = ""             # FM id + description for flawed answers


@dataclass(frozen=True)
class CalibrationCase:
    id: str
    task: str
    contract: tuple[str, ...]
    answers: tuple[SeededAnswer, ...] = field(default_factory=tuple)


CALIBRATION_CASES: tuple[CalibrationCase, ...] = (
    CalibrationCase(
        id="median-function",
        task=(
            "Write a complete Python function `median(nums)` that returns the "
            "median of a non-empty list of numbers (the mean of the two middle "
            "values for even lengths) and raises ValueError('empty') for an "
            "empty list. Include working doctests covering odd length, even "
            "length, and the empty case."
        ),
        contract=(
            "Defines a function named median taking one list argument",
            "Even-length lists return the mean of the two middle values",
            "Empty input raises ValueError",
            "Doctests cover odd, even, and empty cases",
            "No stubs, TODOs, or omitted work",
        ),
        answers=(
            SeededAnswer(
                id="good",
                kind="good",
                text=(
                    "```python\n"
                    "def median(nums):\n"
                    '    """Return the median of a non-empty list.\n\n'
                    "    >>> median([3, 1, 2])\n    2\n"
                    "    >>> median([4, 1, 2, 3])\n    2.5\n"
                    "    >>> median([])\n"
                    "    Traceback (most recent call last):\n"
                    "        ...\n"
                    "    ValueError: empty\n"
                    '    """\n'
                    "    if not nums:\n"
                    "        raise ValueError('empty')\n"
                    "    ordered = sorted(nums)\n"
                    "    mid = len(ordered) // 2\n"
                    "    if len(ordered) % 2:\n"
                    "        return ordered[mid]\n"
                    "    return (ordered[mid - 1] + ordered[mid]) / 2\n"
                    "```\n"
                ),
            ),
            SeededAnswer(
                id="stub",
                kind="flawed",
                flaw="FM-X.1 effort collapse: body is a TODO stub",
                text=(
                    "```python\n"
                    "def median(nums):\n"
                    '    """Return the median of nums."""\n'
                    "    # TODO: handle even lengths and the empty case\n"
                    "    return sorted(nums)[len(nums) // 2]\n"
                    "```\n"
                    "This fully implements the requested median function with "
                    "all edge cases handled."
                ),
            ),
            SeededAnswer(
                id="wrong-even",
                kind="flawed",
                flaw="FM-X.4 unsupported success claim: even case wrong, no "
                     "ValueError, doctests absent yet claimed tested",
                text=(
                    "```python\n"
                    "def median(nums):\n"
                    "    ordered = sorted(nums)\n"
                    "    return ordered[len(ordered) // 2]\n"
                    "```\n"
                    "I tested this thoroughly: doctests for odd, even, and "
                    "empty inputs all pass."
                ),
            ),
        ),
    ),
    CalibrationCase(
        id="primes-format",
        task=(
            "List exactly five prime numbers strictly between 10 and 50, one "
            "per line, with no other text."
        ),
        contract=(
            "Exactly five lines",
            "Every listed number is prime",
            "Every number is strictly between 10 and 50",
            "No text other than the numbers",
        ),
        answers=(
            SeededAnswer(id="good", kind="good", text="11\n13\n17\n19\n23"),
            SeededAnswer(
                id="not-prime",
                kind="flawed",
                flaw="FM-1.1 ignored constraint: 21 and 33 are not prime",
                text="11\n21\n17\n33\n23",
            ),
            SeededAnswer(
                id="chatty-four",
                kind="flawed",
                flaw="FM-1.1 ignored constraint: four numbers plus banned prose",
                text=(
                    "Sure! Here are five primes between 10 and 50:\n"
                    "11\n13\n17\n19\n"
                    "Let me know if you need more."
                ),
            ),
        ),
    ),
    CalibrationCase(
        id="revenue-sum",
        task=(
            "Given this CSV of orders, report the total revenue as a single "
            "number (price times quantity summed over rows):\n\n"
            "item,price,quantity\nwidget,2.50,4\ngadget,10.00,3\nsprocket,1.25,8\n"
        ),
        contract=(
            "Reports one total revenue number",
            "The total equals 2.50*4 + 10.00*3 + 1.25*8 = 50.00",
        ),
        answers=(
            SeededAnswer(
                id="good", kind="good",
                text="Total revenue: 50.00 (2.50×4 + 10.00×3 + 1.25×8 = "
                     "10.00 + 30.00 + 10.00).",
            ),
            SeededAnswer(
                id="wrong-sum",
                kind="flawed",
                flaw="Wrong arithmetic presented confidently",
                text="Total revenue: 62.50 (2.50×4 + 10.00×3 + 1.25×8).",
            ),
            SeededAnswer(
                id="wrong-question",
                kind="flawed",
                flaw="FM-X.5 instruction dilution: answers item count, not "
                     "revenue",
                text="There are 3 items in the dataset: widget, gadget, and "
                     "sprocket. The most expensive is the gadget at 10.00.",
            ),
        ),
    ),
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS verifier_calibration (
            run_id TEXT NOT NULL,
            ts REAL NOT NULL,
            verifier TEXT NOT NULL,
            family TEXT NOT NULL,
            case_id TEXT NOT NULL,
            answer_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            flaw TEXT NOT NULL DEFAULT '',
            score REAL NOT NULL,
            passed INTEGER NOT NULL,
            continuous INTEGER NOT NULL,
            tier TEXT NOT NULL,
            cost_usd REAL NOT NULL DEFAULT 0.0,
            error TEXT
        )"""
    )
    conn.commit()


def _family_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in rows if r.get("error") is None]
    good = [r for r in scored if r["kind"] == "good"]
    flawed = [r for r in scored if r["kind"] == "flawed"]
    saturated = [r for r in scored if r["score"] > 0.99]
    continuous = [r for r in scored if r["continuous"]]
    mean = lambda xs: sum(xs) / len(xs) if xs else 0.0
    return {
        "scored": len(scored),
        "errors": len(rows) - len(scored),
        "false_pass_rate": mean([1.0 if r["passed"] else 0.0 for r in flawed]),
        "false_fail_rate": mean([0.0 if r["passed"] else 1.0 for r in good]),
        "discrimination": (mean([r["score"] for r in good])
                           - mean([r["score"] for r in flawed]))
        if good and flawed else 0.0,
        "mean_good_score": mean([r["score"] for r in good]),
        "mean_flawed_score": mean([r["score"] for r in flawed]),
        "saturation_rate": len(saturated) / len(scored) if scored else 0.0,
        "continuous_rate": len(continuous) / len(scored) if scored else 0.0,
        "cost_usd": sum(r.get("cost_usd", 0.0) for r in rows),
        "false_passes": [
            {"case": r["case_id"], "answer": r["answer_id"],
             "score": round(r["score"], 4), "flaw": r["flaw"]}
            for r in flawed if r["passed"]
        ],
    }


async def run_calibration(
    cfg: Config,
    client: Client,
    *,
    db_path: str | Path | None = None,
    tier: str = "standard",
    repeats: int = 1,
    verifiers: list[str] | None = None,
    cases: tuple[CalibrationCase, ...] = CALIBRATION_CASES,
) -> dict[str, Any]:
    """Score every seeded answer with every verifier family; persist + report."""
    verifier = Verifier(client, cfg)
    scale = cfg.supervision.score_scale
    pool = [
        cfg.models[name] for name in (verifiers or cfg.verifier_pool)
        if name in cfg.models
    ]
    if not pool:
        raise ValueError("no verifier models available to calibrate")
    run_id = uuid.uuid4().hex[:12]
    started = time.time()
    rows: list[dict[str, Any]] = []

    for model in pool:
        for case in cases:
            for answer in case.answers:
                row: dict[str, Any] = {
                    "run_id": run_id, "ts": time.time(),
                    "verifier": model.name, "family": model.family,
                    "case_id": case.id, "answer_id": answer.id,
                    "kind": answer.kind, "flaw": answer.flaw, "tier": tier,
                    "score": 0.0, "passed": False, "continuous": False,
                    "cost_usd": 0.0, "error": None,
                }
                try:
                    report = await verifier._verify_with(
                        model, case.task, answer.text, list(case.contract),
                        criteria=list(DEFAULT_CRITERIA),
                        repeats=repeats, evidence=None, scale=scale, tier=tier,
                    )
                    row.update(
                        score=report.score, passed=report.passed,
                        continuous=all(c.continuous for c in report.criteria),
                        cost_usd=report.cost_usd,
                    )
                except ProviderError as exc:
                    row["error"] = str(exc)[:300]
                rows.append(row)

    by_family: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_family.setdefault(f"{row['verifier']} ({row['family']})",
                             []).append(row)
    result = {
        "run_id": run_id,
        "started_ts": started,
        "duration_s": time.time() - started,
        "tier": tier,
        "repeats": repeats,
        "cases": len(cases),
        "answers": sum(len(c.answers) for c in cases),
        "families": {
            name: _family_metrics(family_rows)
            for name, family_rows in sorted(by_family.items())
        },
        "cost_usd": sum(r.get("cost_usd", 0.0) for r in rows),
    }

    if db_path is not None:
        conn = sqlite3.connect(str(db_path), timeout=10)
        try:
            ensure_schema(conn)
            conn.executemany(
                """INSERT INTO verifier_calibration
                   (run_id, ts, verifier, family, case_id, answer_id, kind,
                    flaw, score, passed, continuous, tier, cost_usd, error)
                   VALUES (:run_id, :ts, :verifier, :family, :case_id,
                           :answer_id, :kind, :flaw, :score, :passed,
                           :continuous, :tier, :cost_usd, :error)""",
                rows,
            )
            conn.commit()
        finally:
            conn.close()
    return result


def latest_report(db_path: str | Path) -> dict[str, Any] | None:
    """Rebuild the most recent run's summary from persisted rows."""
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        run = conn.execute(
            "SELECT run_id, MIN(ts) AS ts FROM verifier_calibration "
            "GROUP BY run_id ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if run is None:
            return None
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM verifier_calibration WHERE run_id=?",
            (run["run_id"],),
        )]
    finally:
        conn.close()
    by_family: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        row["passed"] = bool(row["passed"])
        row["continuous"] = bool(row["continuous"])
        by_family.setdefault(f"{row['verifier']} ({row['family']})",
                             []).append(row)
    return {
        "run_id": run["run_id"],
        "started_ts": float(run["ts"]),
        "families": {name: _family_metrics(family_rows)
                     for name, family_rows in sorted(by_family.items())},
    }


def format_report(result: dict[str, Any]) -> str:
    lines = [
        f"verifier calibration run {result['run_id']} — "
        f"{result.get('answers', '?')} seeded answers × "
        f"{len(result['families'])} verifier(s)",
        f"{'verifier':<34} {'false-pass':>10} {'false-fail':>10} "
        f"{'discrim':>8} {'good':>6} {'flawed':>7} {'sat':>5} {'cont':>5}",
    ]
    for name, m in result["families"].items():
        lines.append(
            f"{name:<34} {m['false_pass_rate']:>10.2f} "
            f"{m['false_fail_rate']:>10.2f} {m['discrimination']:>8.3f} "
            f"{m['mean_good_score']:>6.3f} {m['mean_flawed_score']:>7.3f} "
            f"{m['saturation_rate']:>5.2f} {m['continuous_rate']:>5.2f}"
        )
        for fp in m["false_passes"]:
            lines.append(
                f"    FALSE PASS  {fp['case']}/{fp['answer']} "
                f"score={fp['score']}  ({fp['flaw']})"
            )
        if m["errors"]:
            lines.append(f"    ({m['errors']} provider errors)")
    lines.append(
        "false-pass is the dangerous rate: a flawed seeded answer the "
        "verifier passed. discrimination = mean(good) - mean(flawed); "
        "near zero means saturation (field report 2026-07-17 deficiency 1)."
    )
    return "\n".join(lines)


def main_sync(config_path: str, db_path: str, *, tier: str,
              repeats: int) -> dict[str, Any]:
    """Blocking entry point for the CLI."""
    from .config import load

    cfg = load(config_path)
    client = Client(cfg)

    async def run() -> dict[str, Any]:
        try:
            return await run_calibration(
                cfg, client, db_path=db_path, tier=tier, repeats=repeats)
        finally:
            await client.aclose()

    return asyncio.run(run())
