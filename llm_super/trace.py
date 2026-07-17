"""SQLite trace store: every supervision event, token count, and dollar."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class Trace:
    def __init__(self, path: str | Path = "traces.db"):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS events (
                ts REAL NOT NULL,
                session TEXT NOT NULL,
                task TEXT NOT NULL,
                kind TEXT NOT NULL,
                model TEXT,
                fm_id TEXT,
                tokens_in INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0,
                data TEXT
            )"""
        )
        self._conn.commit()

    def record(
        self,
        session: str,
        task: str,
        kind: str,
        *,
        model: str | None = None,
        fm_id: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        **data: Any,
    ) -> None:
        self._conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                time.time(),
                session,
                task,
                kind,
                model,
                fm_id,
                tokens_in,
                tokens_out,
                cost_usd,
                json.dumps(data, default=str) if data else None,
            ),
        )
        self._conn.commit()

    def recent(self, n: int = 50) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT ts, session, task, kind, model, fm_id, tokens_in, tokens_out, cost_usd, data "
            "FROM events ORDER BY ts DESC LIMIT ?",
            (n,),
        )
        cols = [c[0] for c in cur.description]
        rows = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            if d.get("data"):
                d["data"] = json.loads(d["data"])
            rows.append(d)
        return rows

    def task_cost(self, session: str, task: str) -> float:
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM events WHERE session=? AND task=?",
            (session, task),
        )
        return float(cur.fetchone()[0])
