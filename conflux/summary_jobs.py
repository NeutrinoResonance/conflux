"""Durable per-run ledger for summary-generation jobs + incremental runner.

Closes two recorded deficiencies (history-ui-redesign):

- "summary generation is an invoked maintenance command, not yet an
  automatic incremental job for newly captured messages" — the proxy can now
  run the same resumable backfills on a timer (``summaries.incremental``,
  disabled by default because it spends model budget);
- "no durable per-backfill job ledger exists yet ... run-level retry/cost
  telemetry currently lives only in the operator report" — every run, manual
  or incremental, lands one row in ``summary_jobs`` with scope, trigger,
  model, outcome, generated counts, and reported cost.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from . import message_summaries, step_summary_backfill


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS summary_jobs (
            id TEXT PRIMARY KEY,
            scope TEXT NOT NULL,          -- 'messages' | 'steps'
            trigger TEXT NOT NULL,        -- 'manual' | 'incremental'
            model TEXT NOT NULL,
            status TEXT NOT NULL,         -- 'running' | 'succeeded' | 'failed'
            started_ts REAL NOT NULL,
            finished_ts REAL,
            generated INTEGER NOT NULL DEFAULT 0,
            summarized INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0.0,
            error TEXT,
            detail_json TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    conn.commit()


def _connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def run_summary_job(
    path: str | Path,
    scope: str,
    *,
    trigger: str = "manual",
    model: str | None = None,
    progress: Callable | None = None,
    **backfill_kwargs: Any,
) -> dict[str, Any]:
    """Run one messages/steps backfill with a durable job row around it.

    The job row is committed as 'running' before any model work, so an
    interrupted process still leaves an honest record; completion updates it
    with generated counts and the reported (lower-bound) cost. Exceptions
    propagate to the caller after the failure is recorded.
    """
    if scope == "messages":
        runner = message_summaries.backfill
        model = model or message_summaries.DEFAULT_MODEL
    elif scope == "steps":
        runner = step_summary_backfill.backfill
        model = model or step_summary_backfill.DEFAULT_MODEL
    else:
        raise ValueError(f"unknown summary scope {scope!r}")

    job_id = uuid.uuid4().hex[:16]
    conn = _connect(path)
    try:
        ensure_schema(conn)
        conn.execute(
            """INSERT INTO summary_jobs (id, scope, trigger, model, status,
                                         started_ts)
               VALUES (?,?,?,?, 'running', ?)""",
            (job_id, scope, trigger, model, time.time()),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        result = runner(path, model=model, progress=progress,
                        **backfill_kwargs)
    except BaseException as exc:
        _finish(path, job_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    total_key = "steps" if scope == "steps" else "unique"
    _finish(
        path, job_id, status="succeeded",
        generated=int(result.get("generated", 0)),
        summarized=int(result.get("summarized", 0)),
        total=int(result.get(total_key, 0)),
        cost_usd=float(result.get("cost_usd", 0.0)),
        detail=result,
    )
    result["job_id"] = job_id
    return result


def _finish(path: str | Path, job_id: str, *, status: str,
            generated: int = 0, summarized: int = 0, total: int = 0,
            cost_usd: float = 0.0, error: str | None = None,
            detail: dict | None = None) -> None:
    conn = _connect(path)
    try:
        detail_json = "{}"
        if detail is not None:
            try:
                detail_json = json.dumps(
                    {k: v for k, v in detail.items()
                     if isinstance(v, (int, float, str, bool))},
                )
            except (TypeError, ValueError):
                detail_json = "{}"
        conn.execute(
            """UPDATE summary_jobs
                  SET status=?, finished_ts=?, generated=?, summarized=?,
                      total=?, cost_usd=?, error=?, detail_json=?
                WHERE id=?""",
            (status, time.time(), generated, summarized, total, cost_usd,
             error, detail_json, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_jobs(path: str | Path, *, limit: int = 50) -> list[dict[str, Any]]:
    conn = _connect(path)
    try:
        ensure_schema(conn)
        rows = conn.execute(
            """SELECT id, scope, trigger, model, status, started_ts,
                      finished_ts, generated, summarized, total, cost_usd,
                      error, detail_json
                 FROM summary_jobs ORDER BY started_ts DESC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["detail"] = json.loads(item.pop("detail_json") or "{}")
        except json.JSONDecodeError:
            item["detail"] = {}
        out.append(item)
    return out


def pending_counts(path: str | Path) -> dict[str, int]:
    """Cheap check whether an incremental run has anything to do."""
    conn = _connect(path)
    try:
        counts = {"messages": 0, "steps": 0}
        try:
            step_summary_backfill.ensure_schema(conn)
            steps = step_summary_backfill.collect_steps(conn)
            done = {
                (str(row["session"]), str(row["task"]))
                for row in conn.execute(
                    "SELECT session, task FROM step_summaries "
                    "WHERE prompt_version=?",
                    (step_summary_backfill.PROMPT_VERSION,),
                )
            }
            counts["steps"] = sum(
                1 for item in steps if (item["session"], item["task"]) not in done
            )
        except sqlite3.OperationalError:
            pass
        try:
            row = conn.execute(
                """SELECT COUNT(*) FROM message_summary_sources AS src
                     LEFT JOIN message_summaries AS s
                       ON s.input_sha256=src.input_sha256
                      AND s.prompt_version=src.prompt_version
                    WHERE src.prompt_version=? AND s.input_sha256 IS NULL""",
                (message_summaries.PROMPT_VERSION,),
            ).fetchone()
            counts["messages"] = int(row[0] or 0)
        except sqlite3.OperationalError:
            pass
        return counts
    finally:
        conn.close()
