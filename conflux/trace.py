"""SQLite trace store: every supervision event, token count, and dollar."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .step_summaries import (
    derive_step_summary,
    ensure_schema as ensure_step_summary_schema,
    upsert_step_summary,
)


class Trace:
    def __init__(self, path: str | Path = "traces.db"):
        self.path = str(path)
        self._listeners: list = []
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        # Trace opens traces.db first (before History/Library/Checkpoints),
        # so this is the one moment the auto_vacuum migration can VACUUM.
        from .retention import ensure_auto_vacuum
        ensure_auto_vacuum(self._conn)
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
        # Full message payloads: every request/response through the proxy,
        # client-side and upstream-side. This is the ground truth the event
        # previews summarize.
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS exchanges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                session TEXT NOT NULL,
                task TEXT NOT NULL,
                kind TEXT NOT NULL,          -- client_request/client_response/upstream
                model TEXT,
                payload TEXT NOT NULL        -- full JSON
            )"""
        )
        ensure_step_summary_schema(self._conn)
        self._conn.commit()

    @property
    def connection(self) -> sqlite3.Connection:
        """Shared control-plane connection for additive durable ledgers.

        Flow and action state live beside trace events so a proxy restart
        cannot separate an approval or preflight from the proposal it gates.
        Callers keep database operations short and commit at graph boundaries.
        """
        return self._conn

    def add_listener(self, listener) -> None:
        """Register a callable invoked (from the writing thread) with each
        committed event dict. This is the live-update feed: the SSE channel
        subscribes here instead of re-polling the events table. Listener
        errors are swallowed — observers must never break the write path."""
        self._listeners.append(listener)

    def remove_listener(self, listener) -> None:
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

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
        ts = time.time()
        cur = self._conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                ts,
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
        event_id = cur.lastrowid
        self._conn.commit()
        if self._listeners:
            event = {
                "id": event_id, "ts": ts, "session": session, "task": task,
                "kind": kind, "model": model, "fm_id": fm_id,
                "tokens_in": tokens_in, "tokens_out": tokens_out,
                "cost_usd": cost_usd, "data": data or {},
            }
            for listener in list(self._listeners):
                try:
                    listener(event)
                except Exception:
                    pass

    def events_after(self, after_id: int, n: int = 500) -> list[dict[str, Any]]:
        """Cursor read for the live channel: events with rowid > after_id."""
        cur = self._conn.execute(
            """SELECT rowid AS id, ts, session, task, kind, model, fm_id,
                      tokens_in, tokens_out, cost_usd, data
                 FROM events WHERE rowid > ?
                ORDER BY rowid LIMIT ?""",
            (int(after_id), max(1, min(int(n), 2000))),
        )
        cols = [c[0] for c in cur.description]
        rows = []
        for raw in cur.fetchall():
            item = dict(zip(cols, raw))
            try:
                item["data"] = json.loads(item["data"]) if item.get("data") else {}
            except (json.JSONDecodeError, TypeError):
                item["data"] = {}
            rows.append(item)
        return rows

    def last_event_id(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM events").fetchone()
        return int(row[0] or 0)

    def recent(self, n: int = 50) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            """SELECT event.ts, event.session, event.task, event.kind,
                      event.model, event.fm_id, event.tokens_in,
                      event.tokens_out, event.cost_usd, event.data,
                      summary.short_summary, summary.node_label,
                      summary.long_summary
                 FROM events AS event
                 LEFT JOIN step_summaries AS summary
                   ON summary.session=event.session AND summary.task=event.task
                ORDER BY event.ts DESC, event.rowid DESC LIMIT ?""",
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

    def task_events(self, session: str, task: str,
                    n: int = 500) -> list[dict[str, Any]]:
        """Return one task's complete ordered event trail for product inspectors."""
        cur = self._conn.execute(
            """SELECT rowid AS id,ts,session,task,kind,model,fm_id,tokens_in,
                      tokens_out,cost_usd,data
                 FROM events WHERE session=? AND task=?
                ORDER BY ts,rowid LIMIT ?""",
            (session, task, max(1, min(int(n), 2000))),
        )
        cols = [column[0] for column in cur.description]
        rows = []
        for raw in cur.fetchall():
            item = dict(zip(cols, raw))
            try:
                item["data"] = json.loads(item["data"]) if item.get("data") else {}
            except (json.JSONDecodeError, TypeError):
                item["data"] = {"unparsed": str(item.get("data") or "")}
            rows.append(item)
        return rows

    MAX_PAYLOAD = 400_000  # chars; guards against pathological rows

    def record_exchange(self, session: str, task: str, kind: str,
                        model: str | None, payload: Any) -> None:
        blob = json.dumps(payload, default=str)
        if len(blob) > self.MAX_PAYLOAD:
            blob = json.dumps({"truncated": True, "chars": len(blob),
                               "head": blob[: self.MAX_PAYLOAD]})
        now = time.time()
        self._conn.execute(
            "INSERT INTO exchanges (ts, session, task, kind, model, payload) "
            "VALUES (?,?,?,?,?,?)",
            (now, session, task, kind, model, blob),
        )
        # A request creates immediately useful metadata for an in-flight task;
        # its paired response then upgrades the same row with what the prompt
        # elicited.  This is intentionally local and deterministic so tracing
        # can never cause another model call or provider spend.
        if task != "-" and kind in {"client_request", "client_response"}:
            try:
                if kind == "client_request":
                    request_payload = payload if isinstance(payload, dict) else {}
                    response_payload: dict[str, Any] = {}
                else:
                    row = self._conn.execute(
                        """SELECT payload FROM exchanges
                            WHERE session=? AND task=? AND kind='client_request'
                            ORDER BY id DESC LIMIT 1""",
                        (session, task),
                    ).fetchone()
                    try:
                        request_payload = json.loads(row[0]) if row else {}
                    except (json.JSONDecodeError, TypeError):
                        request_payload = {}
                    response_payload = payload if isinstance(payload, dict) else {}
                upsert_step_summary(
                    self._conn,
                    session,
                    task,
                    derive_step_summary(request_payload, response_payload),
                    timestamp=now,
                )
            except (sqlite3.Error, TypeError, ValueError):
                # Summary indexing is additive observability.  A malformed
                # legacy/provider payload must not drop its forensic exchange.
                pass
        self._conn.commit()

    def last_client_request(self, session: str) -> list[dict] | None:
        """The previous turn's full message prefix — the baseline for
        detecting client-side edits/rewinds (history.diff_prefix)."""
        row = self._conn.execute(
            "SELECT payload FROM exchanges WHERE session=? AND "
            "kind='client_request' ORDER BY id DESC LIMIT 1",
            (session,)).fetchone()
        if not row:
            return None
        try:
            msgs = json.loads(row[0]).get("messages")
        except (json.JSONDecodeError, AttributeError):
            return None
        return msgs if isinstance(msgs, list) else None

    def exchanges(self, task: str | None = None, session: str | None = None,
                  n: int = 100) -> list[dict[str, Any]]:
        q = (
            """SELECT exchange.id, exchange.ts, exchange.session, exchange.task,
                      exchange.kind, exchange.model, exchange.payload,
                      summary.short_summary, summary.node_label,
                      summary.long_summary
                 FROM exchanges AS exchange
                 LEFT JOIN step_summaries AS summary
                   ON summary.session=exchange.session
                  AND summary.task=exchange.task"""
        )
        cond, args = [], []
        if task:
            cond.append("exchange.task=?"); args.append(task)
        if session:
            cond.append("exchange.session=?"); args.append(session)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        q += " ORDER BY exchange.id DESC LIMIT ?"
        args.append(n)
        cur = self._conn.execute(q, args)
        cols = [c[0] for c in cur.description]
        rows = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            try:
                d["payload"] = json.loads(d["payload"])
            except json.JSONDecodeError:
                pass
            rows.append(d)
        return list(reversed(rows))

    def task_cost(self, session: str, task: str) -> float:
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM events WHERE session=? AND task=?",
            (session, task),
        )
        return float(cur.fetchone()[0])
