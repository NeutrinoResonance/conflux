"""Turn checkpointing: a supervisor crash (or hard stop) must not lose paid
work. Completed plan units are persisted per (session, prompt) key; when the
same request arrives again — a client retry after a crash, or the user
resending after a budget stop — the turn resumes from the first incomplete
unit instead of re-buying finished ones.

Checkpoints are deleted on successful turn completion and expire after
MAX_AGE_S regardless (a stale plan is worse than a fresh start).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

MAX_AGE_S = 24 * 3600


def turn_key(session: str, task_text: str) -> str:
    return hashlib.sha256(f"{session}\x00{task_text}".encode()).hexdigest()[:24]


class Checkpoints:
    def __init__(self, path: str | Path = "traces.db"):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS checkpoints (
                key TEXT PRIMARY KEY,
                ts REAL NOT NULL,
                state TEXT NOT NULL
            )"""
        )
        self._conn.commit()

    def save(self, key: str, state: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO checkpoints VALUES (?,?,?)",
            (key, time.time(), json.dumps(state, default=str)),
        )
        self._conn.commit()

    def load(self, key: str) -> dict[str, Any] | None:
        cur = self._conn.execute(
            "SELECT ts, state FROM checkpoints WHERE key=?", (key,))
        row = cur.fetchone()
        if not row:
            return None
        ts, state = row
        if time.time() - ts > MAX_AGE_S:
            self.delete(key)
            return None
        return json.loads(state)

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM checkpoints WHERE key=?", (key,))
        self._conn.commit()
