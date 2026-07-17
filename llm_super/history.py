"""Cross-turn session history and per-model outcome stats.

The proxy sees one stateless completion call at a time, but several failure
modes only exist ACROSS calls: step repetition (FM-1.3), breadth thrash
(FM-X.2), conversation resets/truncation (FM-2.1/FM-1.4), and progress
stalls (SPEC §5.6). This store reconstructs the trajectory: one row per
supervised turn, keyed by the session id, plus running per-model outcome
stats that feed learned routing.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any


def _norm_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


def similarity(a: str, b: str) -> float:
    """Cheap lexical Jaccard similarity in [0,1]."""
    wa, wb = _norm_words(a), _norm_words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


class History:
    def __init__(self, path: str | Path = "traces.db"):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS turns (
                session TEXT NOT NULL,
                turn_no INTEGER NOT NULL,
                ts REAL NOT NULL,
                task TEXT,
                response TEXT,
                score REAL,
                fm_events TEXT,
                msg_count INTEGER,
                PRIMARY KEY (session, turn_no)
            )"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS model_stats (
                model TEXT PRIMARY KEY,
                turns INTEGER DEFAULT 0,
                score_sum REAL DEFAULT 0,
                attempts_sum INTEGER DEFAULT 0,
                fm_count INTEGER DEFAULT 0
            )"""
        )
        # Repair outcomes: which (model, strategy) fixed which failure mode.
        # fm_id "-" means the failure had no specific FM event (low verifier
        # score only). Feeds referee switch_model choice (SPEC §M4).
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS repairs (
                ts REAL NOT NULL,
                model TEXT NOT NULL,
                fm_id TEXT NOT NULL,
                strategy TEXT NOT NULL,
                success INTEGER NOT NULL
            )"""
        )
        self._conn.commit()

    # ---- turns ----

    def record_turn(self, session: str, task: str, response: str,
                    score: float | None, fm_events: list[str], msg_count: int) -> int:
        cur = self._conn.execute(
            "SELECT COALESCE(MAX(turn_no), 0) FROM turns WHERE session=?", (session,))
        turn_no = int(cur.fetchone()[0]) + 1
        self._conn.execute(
            "INSERT INTO turns VALUES (?,?,?,?,?,?,?,?)",
            (session, turn_no, time.time(), task[:2000], response[:2000],
             score, json.dumps(fm_events), msg_count),
        )
        self._conn.commit()
        return turn_no

    def recent_turns(self, session: str, n: int = 8) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT turn_no, ts, task, response, score, fm_events, msg_count "
            "FROM turns WHERE session=? ORDER BY turn_no DESC LIMIT ?",
            (session, n),
        )
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            r["fm_events"] = json.loads(r["fm_events"] or "[]")
        return list(reversed(rows))

    # ---- model outcome stats (feeds learned routing) ----

    def record_outcome(self, model: str, score: float | None,
                       attempts: int, fm_count: int) -> None:
        self._conn.execute(
            """INSERT INTO model_stats (model, turns, score_sum, attempts_sum, fm_count)
               VALUES (?,1,?,?,?)
               ON CONFLICT(model) DO UPDATE SET
                 turns=turns+1, score_sum=score_sum+excluded.score_sum,
                 attempts_sum=attempts_sum+excluded.attempts_sum,
                 fm_count=fm_count+excluded.fm_count""",
            (model, score or 0.0, attempts, fm_count),
        )
        self._conn.commit()

    def record_repair(self, model: str, fm_ids: list[str], strategy: str,
                      success: bool) -> None:
        """One row per failure mode the repair attempt was addressing."""
        now = time.time()
        self._conn.executemany(
            "INSERT INTO repairs VALUES (?,?,?,?,?)",
            [(now, model, fm, strategy, int(success))
             for fm in (fm_ids or ["-"])],
        )
        self._conn.commit()

    def repair_stats(self) -> list[dict[str, Any]]:
        """Per (model, fm_id) repair success rates — the referee's learned
        prior for choosing a switch target."""
        cur = self._conn.execute(
            """SELECT model, fm_id, COUNT(*), SUM(success)
               FROM repairs GROUP BY model, fm_id""")
        return [
            {"model": model, "fm_id": fm_id, "attempts": n,
             "success_rate": round((wins or 0) / n, 3) if n else 0.0}
            for model, fm_id, n, wins in cur.fetchall()
        ]

    def stats(self) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT model, turns, score_sum, attempts_sum, fm_count FROM model_stats")
        out = []
        for model, turns, score_sum, attempts_sum, fm_count in cur.fetchall():
            out.append({
                "model": model,
                "turns": turns,
                "avg_score": round(score_sum / turns, 3) if turns else None,
                "avg_attempts": round(attempts_sum / turns, 2) if turns else None,
                "fm_per_turn": round(fm_count / turns, 2) if turns else None,
            })
        return sorted(out, key=lambda r: -(r["avg_score"] or 0))
