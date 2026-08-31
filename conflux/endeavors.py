"""Durable endeavor / run / phase / step entities captured at write time.

history-ui-redesign Phase 1: the history hierarchy the user actually reasons
about (endeavor -> run/recovery epoch -> phase -> step) becomes first-class
rows written as the work happens, instead of being re-derived from raw trace
events on every page view.  The ledger subscribes to the Trace write path
(`Trace.add_listener`), so every component that records an event — supervised
turns, agentic tool loops, passthrough, governance, durable jobs — feeds the
same durable identity without per-call-site instrumentation.

The raw events/exchanges tables remain the forensic ground truth; these rows
are additive capture-time identity, never a replacement for the evidence.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any, Callable, Mapping

# Event kinds that end a step (and mirror onto the run status).
TERMINAL_KINDS = {"turn_end", "agent_end", "turn_timeout", "budget_stop",
                  "pause_stop"}
ERROR_KINDS = {"executor_error", "provider_error", "verify_error", "error",
               "contract_failed"}
# Session-level milestones (task='-') that must stay visible in history.
MILESTONE_KINDS = {"control", "gate", "server_start", "server_stop",
                   "pause_block", "retention_prune"}

# Operational phase per event kind. Steps keep the phase of their most
# advanced observed stage; unknown kinds leave the phase untouched.
PHASE_BY_KIND = {
    "contract": "specify", "contract_skipped": "specify",
    "contract_failed": "specify", "difficulty_route": "specify",
    "edit": "specify",
    "plan": "plan", "wave_start": "plan",
    "execute": "execute", "execute_code": "execute",
    "executor_error": "execute", "executor_fallback": "execute",
    "tool_step": "execute", "agent_turn": "execute",
    "unit_done": "execute", "ensemble_start": "execute",
    "ensemble_candidate": "execute", "ensemble_winner": "execute",
    "ensemble_degraded": "execute", "ensemble_fusion_rejected": "execute",
    "short_circuit": "execute", "passthrough": "execute",
    "synthesis": "merge",
    "verify": "verify", "verify_error": "verify",
    "soundness_check": "verify", "probe_result": "verify",
    "referee": "repair",
    "fm_event": "monitor", "breakpoint": "control",
    "turn_end": "finish", "agent_end": "finish",
}

_PHASE_ORDER = ("specify", "plan", "execute", "merge", "verify", "repair",
                "monitor", "control", "finish")


def _phase_rank(phase: str | None) -> int:
    try:
        return _PHASE_ORDER.index(phase or "")
    except ValueError:
        return -1


class EndeavorLedger:
    """Write-time capture of durable history entities.

    One ledger instance per server process. ``server_instance_id`` is the
    restart-provenance key: runs belonging to a different (dead) server
    instance that are still marked running are flipped to ``interrupted`` at
    startup, so nothing stays falsely running across a restart.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        server_instance_id: str | None = None,
        client_name: str = "",
        workspace_endeavor_for: Callable[[str], str | None] | None = None,
    ) -> None:
        self._conn = conn
        self.server_instance_id = server_instance_id or uuid.uuid4().hex[:12]
        self._client_name = client_name
        self._workspace_endeavor_for = workspace_endeavor_for
        self._explicit_endeavors: dict[str, str] = {}
        self._run_ids: dict[str, str] = {}
        self._ensure_schema()
        self._interrupt_stale_runs()

    # ------------------------------------------------------------------
    # Schema

    def _ensure_schema(self) -> None:
        statements = (
            """CREATE TABLE IF NOT EXISTS endeavors (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                title TEXT NOT NULL DEFAULT '',
                objective TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_ts REAL NOT NULL,
                last_ts REAL NOT NULL,
                completed_ts REAL,
                target_json TEXT NOT NULL DEFAULT '{}',
                tags_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )""",
            """CREATE TABLE IF NOT EXISTS endeavor_members (
                endeavor_id TEXT NOT NULL,
                session TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                relationship TEXT NOT NULL DEFAULT 'initial',
                attached_by TEXT NOT NULL DEFAULT 'capture',
                attached_ts REAL NOT NULL,
                PRIMARY KEY (endeavor_id, session)
            )""",
            """CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                endeavor_id TEXT NOT NULL,
                session TEXT NOT NULL,
                parent_run_id TEXT,
                client_name TEXT NOT NULL DEFAULT '',
                client_version TEXT NOT NULL DEFAULT '',
                server_instance_id TEXT NOT NULL DEFAULT '',
                executor TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'running',
                start_ts REAL NOT NULL,
                end_ts REAL,
                last_ts REAL NOT NULL,
                interruption_reason TEXT,
                resume_from_run_id TEXT,
                prompt_hash TEXT,
                tool_schema_hash TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS phases (
                run_id TEXT NOT NULL,
                phase TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                first_ts REAL NOT NULL,
                last_ts REAL NOT NULL,
                PRIMARY KEY (run_id, phase)
            )""",
            """CREATE TABLE IF NOT EXISTS steps (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                endeavor_id TEXT NOT NULL,
                session TEXT NOT NULL,
                task TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                phase TEXT,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'running',
                severity TEXT NOT NULL DEFAULT 'info',
                start_ts REAL NOT NULL,
                end_ts REAL,
                tokens_in INTEGER NOT NULL DEFAULT 0,
                tokens_out INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0.0,
                model TEXT,
                tool TEXT,
                first_event_id INTEGER,
                last_event_id INTEGER,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE (session, task)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_members_session "
            "ON endeavor_members(session)",
            "CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session)",
            "CREATE INDEX IF NOT EXISTS idx_runs_endeavor ON runs(endeavor_id)",
            "CREATE INDEX IF NOT EXISTS idx_steps_run ON steps(run_id, ordinal)",
            "CREATE INDEX IF NOT EXISTS idx_steps_endeavor "
            "ON steps(endeavor_id, start_ts)",
        )
        for statement in statements:
            self._conn.execute(statement)
        self._conn.commit()

    def _interrupt_stale_runs(self) -> None:
        """Restart provenance: a run owned by a dead server instance must not
        stay 'running' forever (redesign §5: never falsely running)."""
        self._conn.execute(
            """UPDATE runs SET status='interrupted',
                      interruption_reason='server restart',
                      end_ts=COALESCE(end_ts, last_ts)
                WHERE status='running' AND server_instance_id <> ?""",
            (self.server_instance_id,),
        )
        self._conn.execute(
            """UPDATE steps SET status='interrupted',
                      end_ts=COALESCE(end_ts, start_ts)
                WHERE status='running' AND run_id IN (
                    SELECT id FROM runs WHERE status='interrupted')""",
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Identity

    def set_explicit_endeavor(self, session: str, endeavor_id: str,
                              *, attached_by: str = "explicit_api") -> None:
        """Feature: explicit endeavor IDs accepted at API ingress."""
        self._explicit_endeavors[session] = endeavor_id
        now = time.time()
        self._conn.execute(
            """INSERT INTO endeavors (id, title, status, created_ts, last_ts)
               VALUES (?, '', 'active', ?, ?)
               ON CONFLICT(id) DO UPDATE SET last_ts=excluded.last_ts""",
            (endeavor_id, now, now),
        )
        self._attach_member(endeavor_id, session, attached_by=attached_by,
                            ts=now)
        self._conn.commit()

    def _endeavor_for(self, session: str, ts: float) -> str:
        explicit = self._explicit_endeavors.get(session)
        if explicit:
            return explicit
        row = self._conn.execute(
            "SELECT endeavor_id FROM endeavor_members WHERE session=? "
            "ORDER BY attached_ts LIMIT 1", (session,)
        ).fetchone()
        if row:
            return row[0]
        endeavor_id = None
        if self._workspace_endeavor_for is not None:
            try:
                endeavor_id = self._workspace_endeavor_for(session)
            except Exception:
                endeavor_id = None
        attached_by = "workspace" if endeavor_id else "capture"
        endeavor_id = endeavor_id or f"conversation:{session}"
        self._conn.execute(
            """INSERT INTO endeavors (id, title, status, created_ts, last_ts)
               VALUES (?, '', 'active', ?, ?)
               ON CONFLICT(id) DO UPDATE SET last_ts=excluded.last_ts""",
            (endeavor_id, ts, ts),
        )
        self._attach_member(endeavor_id, session, attached_by=attached_by,
                            ts=ts)
        return endeavor_id

    def _attach_member(self, endeavor_id: str, session: str, *,
                       attached_by: str, ts: float,
                       relationship: str | None = None) -> None:
        ordinal = self._conn.execute(
            "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM endeavor_members "
            "WHERE endeavor_id=?", (endeavor_id,)
        ).fetchone()[0]
        self._conn.execute(
            """INSERT OR IGNORE INTO endeavor_members
               (endeavor_id, session, ordinal, relationship, attached_by,
                attached_ts)
               VALUES (?,?,?,?,?,?)""",
            (endeavor_id, session, ordinal,
             relationship or ("initial" if ordinal == 1 else "continuation"),
             attached_by, ts),
        )

    def _run_for(self, session: str, endeavor_id: str, ts: float) -> str:
        cached = self._run_ids.get(session)
        if cached:
            return cached
        row = self._conn.execute(
            "SELECT id FROM runs WHERE session=? AND server_instance_id=? "
            "ORDER BY start_ts DESC LIMIT 1",
            (session, self.server_instance_id),
        ).fetchone()
        if row:
            self._run_ids[session] = row[0]
            return row[0]
        prior = self._conn.execute(
            "SELECT id FROM runs WHERE session=? ORDER BY start_ts DESC LIMIT 1",
            (session,),
        ).fetchone()
        run_id = uuid.uuid4().hex[:16]
        self._conn.execute(
            """INSERT INTO runs (id, endeavor_id, session, parent_run_id,
                                 client_name, server_instance_id, status,
                                 start_ts, last_ts, resume_from_run_id)
               VALUES (?,?,?,?,?,?, 'running', ?, ?, ?)""",
            (run_id, endeavor_id, session, prior[0] if prior else None,
             self._client_name, self.server_instance_id, ts, ts,
             prior[0] if prior else None),
        )
        self._run_ids[session] = run_id
        return run_id

    # ------------------------------------------------------------------
    # Write-time capture (Trace listener)

    def observe(self, event: Mapping[str, Any]) -> None:
        """Materialize durable identity for one committed trace event.

        Registered via ``Trace.add_listener``; runs in the writer's thread on
        the shared control-plane connection. Must never raise into the write
        path — Trace already guards, but stay conservative anyway.
        """
        try:
            self._observe(event)
        except Exception:
            self._conn.rollback()

    def _observe(self, event: Mapping[str, Any]) -> None:
        session = str(event.get("session") or "")
        task = str(event.get("task") or "")
        kind = str(event.get("kind") or "")
        ts = float(event.get("ts") or time.time())
        if not session or session == "-":
            return
        endeavor_id = self._endeavor_for(session, ts)
        run_id = self._run_for(session, endeavor_id, ts)
        self._conn.execute(
            "UPDATE endeavors SET last_ts=? WHERE id=? AND last_ts < ?",
            (ts, endeavor_id, ts),
        )
        self._conn.execute(
            "UPDATE runs SET last_ts=? WHERE id=?", (ts, run_id))

        if task == "-":
            if kind in MILESTONE_KINDS:
                self._milestone_step(event, endeavor_id, run_id, session,
                                     kind, ts)
            self._conn.commit()
            return

        phase = PHASE_BY_KIND.get(kind)
        row = self._conn.execute(
            "SELECT id, phase, status, severity FROM steps "
            "WHERE session=? AND task=?",
            (session, task),
        ).fetchone()
        tokens_in = int(event.get("tokens_in") or 0)
        tokens_out = int(event.get("tokens_out") or 0)
        cost = float(event.get("cost_usd") or 0.0)
        model = event.get("model")
        data = event.get("data") or {}
        tool = None
        if isinstance(data, Mapping):
            tool = data.get("tool") or data.get("tool_name")

        terminal = kind in TERMINAL_KINDS
        error = kind in ERROR_KINDS or bool(event.get("fm_id"))

        if row is None:
            ordinal = self._conn.execute(
                "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM steps "
                "WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            status = "running"
            if terminal:
                status = self._terminal_status(event)
            self._conn.execute(
                """INSERT INTO steps (id, run_id, endeavor_id, session, task,
                       ordinal, phase, kind, status, severity, start_ts,
                       end_ts, tokens_in, tokens_out, cost_usd, model, tool,
                       first_event_id, last_event_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (uuid.uuid4().hex[:16], run_id, endeavor_id, session, task,
                 ordinal, phase, kind, status,
                 "error" if error else "info", ts,
                 ts if terminal else None, tokens_in, tokens_out, cost,
                 model, tool, event.get("id"), event.get("id")),
            )
        else:
            step_id, old_phase, old_status, old_severity = row
            new_phase = (phase if _phase_rank(phase) > _phase_rank(old_phase)
                         else old_phase)
            severity = old_severity
            if error:
                severity = "error"
            status = old_status
            end_ts = None
            if terminal:
                status = self._terminal_status(event)
                if severity == "error" and status == "succeeded":
                    severity = "recovered"
                end_ts = ts
            elif old_status not in ("running",):
                # Late activity on a finished task re-opens the step.
                status = "running"
            self._conn.execute(
                """UPDATE steps SET phase=?, status=?, severity=?,
                       end_ts=COALESCE(?, end_ts),
                       tokens_in=tokens_in+?, tokens_out=tokens_out+?,
                       cost_usd=cost_usd+?,
                       model=COALESCE(?, model), tool=COALESCE(?, tool),
                       last_event_id=?
                   WHERE id=?""",
                (new_phase, status, severity, end_ts, tokens_in, tokens_out,
                 cost, model, tool, event.get("id"), step_id),
            )
        if phase:
            self._touch_phase(run_id, phase, ts)
        if terminal:
            self._conn.execute(
                "UPDATE runs SET status=?, end_ts=? WHERE id=?",
                (self._terminal_status(event), ts, run_id),
            )
        elif kind not in MILESTONE_KINDS:
            self._conn.execute(
                "UPDATE runs SET status='running', end_ts=NULL WHERE id=?",
                (run_id,),
            )
        self._conn.commit()

    def _terminal_status(self, event: Mapping[str, Any]) -> str:
        kind = event.get("kind")
        if kind == "turn_timeout":
            return "interrupted"
        if kind in ("budget_stop", "pause_stop"):
            return "paused"
        data = event.get("data") or {}
        if isinstance(data, Mapping):
            if data.get("error") or data.get("escalated"):
                return "failed"
            if data.get("passed", data.get("ok")) is False:
                return "failed"
        return "succeeded"

    def _milestone_step(self, event: Mapping[str, Any], endeavor_id: str,
                        run_id: str, session: str, kind: str,
                        ts: float) -> None:
        ordinal = self._conn.execute(
            "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM steps WHERE run_id=?",
            (run_id,),
        ).fetchone()[0]
        data = event.get("data") or {}
        summary = ""
        if isinstance(data, Mapping):
            summary = str(data.get("command") or data.get("preview") or "")[:200]
        self._conn.execute(
            """INSERT OR IGNORE INTO steps (id, run_id, endeavor_id, session,
                   task, ordinal, phase, kind, summary, status, severity,
                   start_ts, end_ts, first_event_id, last_event_id)
               VALUES (?,?,?,?,?,?, 'control', ?, ?, 'succeeded', 'info',
                       ?, ?, ?, ?)""",
            (uuid.uuid4().hex[:16], run_id, endeavor_id, session,
             f"milestone-{event.get('id') or uuid.uuid4().hex[:8]}",
             ordinal, kind, summary, ts, ts, event.get("id"),
             event.get("id")),
        )

    def _touch_phase(self, run_id: str, phase: str, ts: float) -> None:
        ordinal = self._conn.execute(
            "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM phases WHERE run_id=?",
            (run_id,),
        ).fetchone()[0]
        self._conn.execute(
            """INSERT INTO phases (run_id, phase, ordinal, first_ts, last_ts)
               VALUES (?,?,?,?,?)
               ON CONFLICT(run_id, phase) DO UPDATE SET
                   last_ts=excluded.last_ts""",
            (run_id, phase, ordinal, ts, ts),
        )

    # ------------------------------------------------------------------
    # Migration

    def migrate_grouping(self, grouping, *, run_statuses: Mapping[str, str]
                         | None = None) -> bool:
        """Persist a documented legacy EndeavorGrouping as durable rows.

        Exact-ID only, idempotent: does nothing when the endeavor id already
        exists. Statuses come from the grouping's documented run_statuses —
        no heuristics.
        """
        exists = self._conn.execute(
            "SELECT 1 FROM endeavors WHERE id=?", (grouping.id,)
        ).fetchone()
        if exists:
            return False
        now = time.time()
        self._conn.execute(
            """INSERT INTO endeavors (id, project_id, title, status,
                   created_ts, last_ts, target_json, metadata_json)
               VALUES (?,?,?,?,?,?,?,?)""",
            (grouping.id, grouping.project_id, grouping.title,
             grouping.status or "active", now, now,
             json.dumps(dict(grouping.target)),
             json.dumps({**dict(grouping.metadata),
                         "attached_by": "documented_migration_fixture"})),
        )
        statuses = dict(run_statuses or grouping.run_statuses or {})
        for ordinal, session in enumerate(grouping.sessions, start=1):
            relationship = grouping.relationship_by_session.get(
                session, "continuation" if ordinal > 1 else "initial")
            self._conn.execute(
                """INSERT OR IGNORE INTO endeavor_members
                   (endeavor_id, session, ordinal, relationship, attached_by,
                    attached_ts)
                   VALUES (?,?,?,?, 'documented_migration_fixture', ?)""",
                (grouping.id, session, ordinal, relationship, now),
            )
            status = statuses.get(session)
            if status:
                self._conn.execute(
                    """INSERT INTO runs (id, endeavor_id, session,
                           server_instance_id, status, start_ts, last_ts,
                           end_ts, interruption_reason)
                       VALUES (?,?,?, 'migration', ?, ?, ?, ?, ?)""",
                    (uuid.uuid4().hex[:16], grouping.id, session, status,
                     now, now, now,
                     "documented migration" if status == "interrupted"
                     else None),
                )
        self._conn.commit()
        return True
