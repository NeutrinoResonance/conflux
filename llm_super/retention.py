"""Retention: keep traces.db from growing without bound.

Full message payloads (exchanges) dominate growth — an agent conversation
stores ~17k tokens per step. Policy: age out exchanges first, events and turn
history later; session/project metadata is never pruned (the sidebar still
lists old conversations — export before expiry to keep their contents).
A value of 0 days means "keep forever" for that table.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

DEFAULT_RETENTION: dict[str, Any] = {
    "exchanges_days": 14,   # full payloads (largest rows)
    "events_days": 90,      # trace events (small, power the timeline)
    "turns_days": 90,       # cross-turn history (monitors only read recent)
    "vacuum": True,         # reclaim file space after pruning
}

_TABLES = {  # settings key -> (table, timestamp column)
    "exchanges_days": ("exchanges", "ts"),
    "events_days": ("events", "ts"),
    "turns_days": ("turns", "ts"),
}

_INCREMENTAL = 2  # PRAGMA auto_vacuum value


def ensure_auto_vacuum(conn: sqlite3.Connection) -> bool:
    """Migrate the db to auto_vacuum=INCREMENTAL so prune can reclaim file
    space while other connections stay open (full VACUUM can't).

    On an existing db the setting only takes effect after a VACUUM rebuild,
    which needs the file to itself — call this before opening the other
    long-lived connections (Trace does, at server startup). Returns True if
    incremental vacuum is enabled after the call.
    """
    if conn.execute("PRAGMA auto_vacuum").fetchone()[0] == _INCREMENTAL:
        return True
    try:
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        conn.execute("VACUUM")
        return conn.execute("PRAGMA auto_vacuum").fetchone()[0] == _INCREMENTAL
    except sqlite3.OperationalError:
        return False  # db busy — migrates on a later startup


def stats(path: str | Path) -> dict[str, Any]:
    """Row counts per table and the db file size, for the dashboard."""
    out: dict[str, Any] = {"db_bytes": 0, "tables": {}}
    p = Path(path)
    if p.exists():
        out["db_bytes"] = p.stat().st_size + sum(
            (p.parent / (p.name + sfx)).stat().st_size
            for sfx in ("-wal", "-shm")
            if (p.parent / (p.name + sfx)).exists()
        )
    conn = sqlite3.connect(str(path))
    try:
        for table, _col in _TABLES.values():
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                oldest = conn.execute(f"SELECT MIN(ts) FROM {table}").fetchone()[0]
            except sqlite3.OperationalError:
                n, oldest = 0, None
            out["tables"][table] = {
                "rows": n,
                "oldest_days": round((time.time() - oldest) / 86400, 1) if oldest else None,
            }
    finally:
        conn.close()
    return out


def prune(path: str | Path, settings: dict[str, Any]) -> dict[str, Any]:
    """Delete rows older than the configured ages. Returns a report."""
    now = time.time()
    report: dict[str, Any] = {"deleted": {}, "reclaimed_bytes": 0}
    before = stats(path)["db_bytes"]
    conn = sqlite3.connect(str(path))
    try:
        for key, (table, col) in _TABLES.items():
            days = float(settings.get(key, DEFAULT_RETENTION[key]) or 0)
            if days <= 0:
                report["deleted"][table] = 0
                continue
            cutoff = now - days * 86400
            try:
                cur = conn.execute(f"DELETE FROM {table} WHERE {col} < ?", (cutoff,))
                report["deleted"][table] = cur.rowcount
            except sqlite3.OperationalError:
                report["deleted"][table] = 0
        conn.commit()
        if settings.get("vacuum", True) and any(report["deleted"].values()):
            try:
                if conn.execute("PRAGMA auto_vacuum").fetchone()[0] == _INCREMENTAL:
                    # frees the deleted pages without exclusive access, so it
                    # works while the server's other connections are open;
                    # the pragma yields mid-run — drain it to free everything
                    conn.execute("PRAGMA incremental_vacuum").fetchall()
                else:
                    # legacy db (pre-auto_vacuum): full rebuild, and enable
                    # incremental for future passes while we have the lock
                    conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
                    conn.execute("VACUUM")
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                report["vacuumed"] = True
            except sqlite3.OperationalError:
                # a live turn holds the db — space reclaims on a later pass
                report["vacuumed"] = False
    finally:
        conn.close()
    report["reclaimed_bytes"] = max(0, before - stats(path)["db_bytes"])
    return report
