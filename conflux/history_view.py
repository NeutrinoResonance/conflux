"""Compact, read-only history projections over the legacy trace database.

The trace tables intentionally retain full transport payloads.  They are the
forensic ground truth, but they are a poor API for a history screen: agent
clients resend their complete message prefix on every request and providers
duplicate much of the same data at another boundary.  :class:`HistoryView`
derives endeavors, runs, and logical timeline steps without copying those raw
payloads into its return values or changing the existing schema.

This is a compatibility layer, not a migration.  Explicit endeavor groupings
are authoritative.  Unclaimed sessions are kept separate (except for explicit
``session_aliases``), so the fallback never guesses that unrelated work belongs
together.  Historical rows without an explicit terminal event are reported as
``interrupted`` or ``unknown`` -- never as indefinitely ``running``.
"""

from __future__ import annotations

import base64
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Mapping, Sequence


_ERROR_KINDS = {"executor_error", "provider_error", "error"}
_PROVIDER_ERROR_KINDS = {"executor_error", "provider_error"}
_TERMINAL_KINDS = {"agent_end", "turn_end"}
_WARNING_RE = re.compile(r"(?:warning|warn:|locale|setlocale)", re.IGNORECASE)

# category, safe display label, opaque fingerprint.  Raw warning lines are
# never carried into a public projection.
WarningKey = tuple[str, str, str]


@dataclass(frozen=True)
class ControlMilestone:
    """Exact identity of a legacy control event attached to an endeavor."""

    ts: float
    session: str
    command: str


@dataclass(frozen=True)
class AcceptanceAnchor:
    """A trace event that must exist before a migrated endeavor is accepted.

    Anchors deliberately use stable trace identity rather than prompt text or
    time-window heuristics.  Terminal anchors are required to be clean unless
    ``require_clean_terminal`` is disabled explicitly.
    """

    session: str
    kind: str
    task: str | None = None
    require_clean_terminal: bool = True


@dataclass(frozen=True)
class EndeavorGrouping:
    """An explicit mapping from legacy sessions to one user endeavor.

    ``run_statuses`` is useful only when old traces lack lifecycle events.  It
    should not be used to override newly recorded terminal states.  The
    ``relationship_by_session`` values are presentation metadata such as
    ``initial``, ``continuation``, ``recovery``, and ``audit``.
    """

    id: str
    title: str
    sessions: tuple[str, ...]
    status: str | None = None
    relationship_by_session: Mapping[str, str] = field(default_factory=dict)
    run_statuses: Mapping[str, str] = field(default_factory=dict)
    project_id: str | None = None
    target: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    recovered_errors: bool = False
    control_milestones: tuple[ControlMilestone, ...] = ()
    acceptance_anchors: tuple[AcceptanceAnchor, ...] = ()


# A deliberately isolated migration fixture for the one documented legacy
# endeavor.  It is exact-ID only: it cannot accidentally absorb a future
# session merely because its prompt happens to mention NetBSD or QEMU.
NETBSD_ARM64_ENDEAVOR = EndeavorGrouping(
    id="netbsd-arm64-acceptance-2026-07-18",
    title="NetBSD ARM64 acceptance",
    sessions=(
        "a7508c77800d",
        "a20239db146e",
        "c0904cb7dd7d",
        "a7ac14a9f48f",
        "a7cfccda0288",
        "dd8af54b87b2",
        "3e90d8f1cf59",
        "91f5e1ddd105",
    ),
    status="accepted",
    relationship_by_session={
        "a7508c77800d": "initial",
        "a20239db146e": "continuation",
        "c0904cb7dd7d": "broken_resume",
        "a7ac14a9f48f": "recovery",
        "a7cfccda0288": "monitoring",
        "dd8af54b87b2": "qemu_plan",
        "3e90d8f1cf59": "acceptance",
        "91f5e1ddd105": "audit",
    },
    run_statuses={
        "a7508c77800d": "failed",
        "a20239db146e": "interrupted",
        "c0904cb7dd7d": "interrupted",
        "a7ac14a9f48f": "interrupted",
        "a7cfccda0288": "succeeded",
        "dd8af54b87b2": "succeeded",
        "3e90d8f1cf59": "succeeded",
        "91f5e1ddd105": "succeeded",
    },
    project_id="default",
    target={
        "host_arch": "x86_64",
        "guest_arch": "aarch64",
        "emulator": "qemu-system-aarch64",
        "project": "project96-sar",
        "vm": "llmsuper-netbsd-arm64",
    },
    metadata={
        "attached_by": "documented_migration_fixture",
        "evidence": {
            "source_revision": "netbsd-10",
            "build_result": "release.exit=0 · Successful make release",
            "guest_result": (
                "NetBSD 10.1_STABLE · MACHINE=evbarm · ARCH=aarch64 · "
                "hw.machine_arch=aarch64 · QEMU_EXIT=0"
            ),
            "evidence_root": "/home/operator/llmsuper-netbsd-run",
            "artifacts": (
                {
                    "name": "arm64.img.gz",
                    "bytes": 303_656_165,
                    "sha256": "e241129af24cd3b52d0455aa3915d29c15c377adc8c6bf1a8be66a6d42beaff5",
                },
                {
                    "name": "netbsd-GENERIC64.gz",
                    "bytes": 7_389_749,
                    "sha256": "32fffc3db189222854740fc4e3bbac4066fbeb5c6e0198233a0dbb77a6373207",
                },
                {
                    "name": "qemu-command.txt",
                    "bytes": 450,
                    "sha256": "076f9deee675690a12eba55b40a6c6989e98585b5308bd5239049a3533161b32",
                },
                {
                    "name": "serial.log",
                    "bytes": 24_178,
                    "sha256": "b88140b9ebfbef2119bdcbd0ef6724eae375acdfec85a1149f4ada8b72032194",
                },
                {
                    "name": "validation.txt",
                    "bytes": 155,
                    "sha256": "c40e298115bd0a1c42248aa1a5ee181f1a31f1c0523696c93b46e00e67cd148a",
                },
            ),
        },
    },
    recovered_errors=True,
    acceptance_anchors=(
        AcceptanceAnchor("3e90d8f1cf59", "turn_end"),
        AcceptanceAnchor("91f5e1ddd105", "agent_end"),
    ),
    control_milestones=(
        ControlMilestone(1784357823.634658, "02ba2756803b", "!gate off"),
        ControlMilestone(1784357823.799840, "bc26500f1cb7", "!use glm-5.2"),
        ControlMilestone(1784357823.963490, "fba317c611bb", "!budget 1.00"),
        ControlMilestone(1784357860.976346, "138d4bc57b8e", "!auto"),
        ControlMilestone(1784357861.115395, "-", "ui:budget="),
        ControlMilestone(1784362717.928177, "02ba2756803b", "!gate off"),
        ControlMilestone(1784363426.339615, "02ba2756803b", "!gate off"),
    ),
)


class HistoryViewError(RuntimeError):
    """Raised when a history projection cannot be constructed safely."""


class HistoryView:
    """Read-only endeavor/run/timeline API backed by ``traces.db``.

    Public methods return ordinary JSON-serializable dictionaries:

    * :meth:`list_endeavors` -- cursor-paginated compact endeavor rows
    * :meth:`get_endeavor` -- one endeavor and its aggregate counters
    * :meth:`list_runs` -- cursor-paginated session/recovery epochs
    * :meth:`timeline` -- cursor-paginated logical steps with optional poll
      folding, message-delta metadata, and transport-boundary dedup metadata

    No method returns an exchange ``payload`` or event ``data`` field.
    """

    MAX_PAGE_SIZE = 200

    def __init__(
        self,
        path: str | Path = "traces.db",
        *,
        groupings: Iterable[EndeavorGrouping] = (),
        include_documented_fixtures: bool = True,
    ) -> None:
        db_path = Path(path)
        if not db_path.exists():
            raise FileNotFoundError(db_path)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA query_only=ON")
        self._require_tables("events", "exchanges", "sessions")

        supplied = list(groupings)
        if include_documented_fixtures:
            supplied.append(NETBSD_ARM64_ENDEAVOR)
        self._groupings = self._validate_groupings(supplied)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "HistoryView":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public projections

    def list_endeavors(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        query: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return compact endeavor rows, newest activity first."""
        rows = [self._endeavor_summary(e) for e in self._resolved_endeavors()]
        if project_id:
            rows = [r for r in rows if project_id in r["project_ids"]]
        if status:
            rows = [r for r in rows if r["status"] == status]
        if query:
            needle = query.casefold()
            rows = [
                r for r in rows
                if needle in r["title"].casefold()
                or needle in r["id"].casefold()
                or any(needle in sid.casefold() for sid in r["session_ids"])
                or needle in str((r.get("context_summary") or {}).get("headline", "")).casefold()
                or needle in str((r.get("context_summary") or {}).get("summary", "")).casefold()
            ]
        rows.sort(key=lambda r: (r["last_ts"], r["id"]), reverse=True)
        filter_scope = _hash_text(_canonical_json({
            "project_id": project_id,
            "status": status,
            "query": query.casefold() if query else None,
        }))
        return self._page(
            rows, cursor, limit, scope=f"endeavors:{filter_scope}"
        )

    def get_endeavor(self, endeavor_id: str) -> dict[str, Any]:
        resolved = self._find_endeavor(endeavor_id)
        result = self._endeavor_summary(resolved)
        result["relationships"] = {
            sid: resolved["relationship_by_session"].get(sid, "session")
            for sid in resolved["sessions"]
        }
        result["target"] = dict(resolved.get("target") or {})
        result["metadata"] = dict(resolved.get("metadata") or {})
        provenance = self._durable_run_provenance(resolved["sessions"])
        captured_steps = self._durable_step_map(resolved["sessions"])
        result["capture"] = {
            "durable": bool(provenance or captured_steps),
            "runs": sum(len(rows) for rows in provenance.values()),
            "steps": len(captured_steps),
        }
        return result

    def list_contexts(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return only containment identity, without aggregate summaries.

        The conversational workspace needs a fast endeavor switcher, not the
        token/cost/error rollups of :meth:`list_endeavors`.  Resolving the
        grouping once keeps this projection cheap even for a large trace DB.
        """
        limit = max(1, min(int(limit), self.MAX_PAGE_SIZE))
        records = self._session_records()
        rows = []
        for endeavor in self._resolved_endeavors():
            sessions = [str(value) for value in endeavor["sessions"]]
            last_ts = max(
                (float(records.get(session, {}).get("last_ts") or 0)
                 for session in sessions), default=0.0
            )
            rows.append({
                "id": str(endeavor["id"]),
                "title": str(endeavor["title"]),
                "status": str(endeavor.get("status") or "historical"),
                "conversation_ids": sessions,
                "conversation_count": len(sessions),
                "explicit_grouping": bool(endeavor.get("explicit")),
                "last_ts": last_ts,
            })
        rows.sort(key=lambda row: (row["last_ts"], row["id"]), reverse=True)
        return rows[:limit]

    def session_context(self, session: str) -> dict[str, Any]:
        """Return the containment context for one conversation session.

        Unlike ``list_endeavors(query=...)``, this does not compute summaries
        and aggregate metrics for every endeavor before finding the requested
        session.  It is the narrow projection used by cross-linked UIs.
        """
        session = str(session or "").strip()
        if not session or len(session) > 512:
            raise ValueError("invalid session id")
        for endeavor in self._resolved_endeavors():
            sessions = tuple(str(value) for value in endeavor["sessions"])
            if session not in sessions:
                continue
            return {
                "endeavor_id": str(endeavor["id"]),
                "endeavor_title": str(endeavor["title"]),
                "conversation_ids": list(sessions),
                "conversation_count": len(sessions),
                "relationship": str(
                    endeavor.get("relationship_by_session", {}).get(
                        session, "session"
                    )
                ),
                "explicit_grouping": bool(endeavor.get("explicit")),
            }
        raise KeyError(session)

    def list_runs(
        self,
        endeavor_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return one compact run per member session, in chronological order."""
        resolved = self._find_endeavor(endeavor_id)
        runs = [self._run_summary(resolved, sid) for sid in resolved["sessions"]]
        provenance = self._durable_run_provenance(resolved["sessions"])
        for run in runs:
            captured = provenance.get(run["session_id"])
            if captured:
                run["capture"] = captured
        runs.sort(key=lambda r: (r["start_ts"], r["session_id"]))
        counts = Counter(r["status"] for r in runs)
        return self._page(
            runs,
            cursor,
            limit,
            scope=f"runs:{endeavor_id}",
            summary={"status_counts": dict(sorted(counts.items()))},
        )

    def timeline(
        self,
        endeavor_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
        collapse_polling: bool = True,
    ) -> dict[str, Any]:
        """Return logical steps for an endeavor without raw trace payloads.

        Message arrays are represented by prefix/delta counts and hashes.
        Repeated client/upstream copies are represented by equality flags.
        Consecutive successful routine polls are folded into a single item.
        Pass ``collapse_polling=False`` to page through every derived step.
        """
        resolved = self._find_endeavor(endeavor_id)
        steps, result_warning_groups = self._timeline_steps(resolved)
        captured_steps = self._durable_step_map(resolved["sessions"])
        if captured_steps:
            for step in steps:
                identity = captured_steps.get(
                    (step.get("session_id"), step.get("task_id"))
                )
                if identity:
                    step["capture"] = identity
        raw_step_count = len(steps)
        control_count = sum(step["type"] == "control" for step in steps)
        workload_count = raw_step_count - control_count
        routine_count = sum(bool(s["routine_poll"]) for s in steps)
        poll_steps = [step for step in steps if step["poll_categories"]]
        polling_by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for step in poll_steps:
            polling_by_run[str(step["run_id"])].append(step)
        primary_poll_run = max(
            polling_by_run.items(), key=lambda item: len(item[1]), default=(None, [])
        )
        primary_polls = primary_poll_run[1]
        items = self._collapse_poll_steps(steps) if collapse_polling else steps
        collapsed = raw_step_count - len(items)
        return self._page(
            items,
            cursor,
            limit,
            scope=f"timeline:{endeavor_id}:{int(collapse_polling)}",
            summary={
                "raw_steps": raw_step_count,
                "workload_steps": workload_count,
                "control_milestones": control_count,
                "display_items": len(items),
                "poll_steps": len(poll_steps),
                "routine_poll_steps": routine_count,
                "collapsed_steps": collapsed,
                "warning_groups": result_warning_groups,
                "primary_poll_run": {
                    "run_id": primary_poll_run[0],
                    "steps": len(primary_polls),
                    "routine_steps": sum(step["routine_poll"] for step in primary_polls),
                    "unmatched_steps": sum(step["unmatched_tool_result"] for step in primary_polls),
                    "tokens_in": sum(step["tokens_in"] for step in primary_polls),
                    "tokens_out": sum(step["tokens_out"] for step in primary_polls),
                    "cost_usd": sum(step["cost_usd"] for step in primary_polls),
                } if primary_polls else None,
            },
        )

    def raw_exchange(self, exchange_id: int) -> dict[str, Any]:
        """Return one explicitly requested forensic exchange, including payload.

        This is intentionally separate from every summary method.  Callers
        should expose it only behind an explicit raw/drilldown action.
        """
        if isinstance(exchange_id, bool) or not isinstance(exchange_id, int):
            raise TypeError("exchange_id must be an integer")
        if not (1 <= exchange_id <= (1 << 63) - 1):
            raise ValueError("exchange_id must be a positive signed 64-bit integer")
        row = self._conn.execute(
            """SELECT id, ts, session, task, kind, model, payload
                 FROM exchanges WHERE id=?""",
            (exchange_id,),
        ).fetchone()
        if row is None:
            raise KeyError(exchange_id)
        try:
            payload: Any = json.loads(row["payload"])
        except json.JSONDecodeError:
            payload = row["payload"]
        summaries = self._step_summary_map((str(row["session"]),))
        step_summary = summaries.get((str(row["session"]), str(row["task"])))
        return {
            "id": int(row["id"]),
            "ts": float(row["ts"]),
            "session": row["session"],
            "task": row["task"],
            "kind": row["kind"],
            "model": row["model"],
            "payload_chars": len(row["payload"]),
            "payload": payload,
            "short_summary": (
                step_summary["short_summary"] if step_summary else None
            ),
            "node_label": step_summary["node_label"] if step_summary else None,
            "long_summary": step_summary["long_summary"] if step_summary else None,
        }

    # ------------------------------------------------------------------
    # Endeavor and run resolution

    def _require_tables(self, *names: str) -> None:
        found = {
            row[0]
            for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = [name for name in names if name not in found]
        if missing:
            raise HistoryViewError("missing trace tables: " + ", ".join(missing))

    @staticmethod
    def _validate_groupings(
        groupings: Sequence[EndeavorGrouping],
    ) -> tuple[EndeavorGrouping, ...]:
        ids: set[str] = set()
        claimed: dict[str, str] = {}
        for grouping in groupings:
            if not grouping.id or not grouping.sessions:
                raise ValueError("endeavor groupings require an id and sessions")
            if grouping.id in ids:
                raise ValueError(f"duplicate endeavor id: {grouping.id}")
            ids.add(grouping.id)
            member_ids = set(grouping.sessions)
            for anchor in grouping.acceptance_anchors:
                if anchor.session not in member_ids:
                    raise ValueError(
                        f"acceptance anchor session {anchor.session} is not a member "
                        f"of {grouping.id}"
                    )
                if not anchor.kind:
                    raise ValueError("acceptance anchors require an event kind")
            for sid in grouping.sessions:
                if sid in claimed:
                    raise ValueError(
                        f"session {sid} belongs to both {claimed[sid]} and {grouping.id}"
                    )
                claimed[sid] = grouping.id
        return tuple(groupings)

    def _session_records(self) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for row in self._conn.execute(
            "SELECT session, project_id, created_ts, last_ts, turns FROM sessions"
        ):
            records[row["session"]] = {
                "session": row["session"],
                "project_id": row["project_id"] or "default",
                "title": _safe_conversation_title(row["session"]),
                "created_ts": float(row["created_ts"]),
                "last_ts": float(row["last_ts"]),
                "turns": int(row["turns"] or 0),
            }

        # A crash can leave trace rows without a Library row.  Include those
        # sessions rather than silently hiding them, but ignore task='-'
        # control-only conversations.
        trace_rows = self._conn.execute(
            """SELECT session, MIN(ts) AS first_ts, MAX(ts) AS last_ts
                 FROM (
                   SELECT session, ts FROM events WHERE task <> '-'
                   UNION ALL
                   SELECT session, ts FROM exchanges WHERE task <> '-'
                 )
                WHERE session <> '-'
                GROUP BY session"""
        ).fetchall()
        for row in trace_rows:
            sid = row["session"]
            if sid in records:
                records[sid]["created_ts"] = min(
                    records[sid]["created_ts"], float(row["first_ts"])
                )
                records[sid]["last_ts"] = max(
                    records[sid]["last_ts"], float(row["last_ts"])
                )
                continue
            records[sid] = {
                "session": sid,
                "project_id": "default",
                "title": _safe_conversation_title(sid),
                "created_ts": float(row["first_ts"]),
                "last_ts": float(row["last_ts"]),
                "turns": 0,
            }
        return records

    def _durable_run_provenance(
        self, sessions: Sequence[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Capture-time run rows (restart/client provenance) per session."""
        if not sessions or not self._table_exists("runs"):
            return {}
        placeholders = ",".join("?" for _ in sessions)
        out: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in self._conn.execute(
            f"""SELECT id, session, status, client_name, server_instance_id,
                       start_ts, end_ts, interruption_reason,
                       resume_from_run_id
                  FROM runs WHERE session IN ({placeholders})
                 ORDER BY start_ts""",
            tuple(sessions),
        ):
            out[str(row["session"])].append({
                "run_id": str(row["id"]),
                "status": str(row["status"]),
                "client_name": str(row["client_name"] or ""),
                "server_instance_id": str(row["server_instance_id"] or ""),
                "start_ts": float(row["start_ts"]),
                "end_ts": float(row["end_ts"]) if row["end_ts"] else None,
                "interruption_reason": row["interruption_reason"],
                "resume_from_run_id": row["resume_from_run_id"],
            })
        return dict(out)

    def _durable_step_map(
        self, sessions: Sequence[str]
    ) -> dict[tuple[str, str], dict[str, Any]]:
        """Capture-time step identity keyed by (session, task)."""
        if not sessions or not self._table_exists("steps"):
            return {}
        placeholders = ",".join("?" for _ in sessions)
        out: dict[tuple[str, str], dict[str, Any]] = {}
        for row in self._conn.execute(
            f"""SELECT id, run_id, session, task, phase, status, severity,
                       ordinal
                  FROM steps WHERE session IN ({placeholders})""",
            tuple(sessions),
        ):
            out[(str(row["session"]), str(row["task"]))] = {
                "step_id": str(row["id"]),
                "run_id": str(row["run_id"]),
                "phase": row["phase"],
                "status": str(row["status"]),
                "severity": str(row["severity"]),
                "ordinal": int(row["ordinal"]),
            }
        return out

    def _durable_groupings(
        self, records: Mapping[str, Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        """Write-time endeavor identity (endeavors/endeavor_members tables).

        Capture-time rows are explicit and authoritative: they claim their
        sessions before the documented fixture constants and before any
        alias/fallback grouping. Databases that predate the ledger simply
        have no rows here and fall through to the compatibility paths.
        """
        if not (self._table_exists("endeavors")
                and self._table_exists("endeavor_members")):
            return []
        members: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in self._conn.execute(
            """SELECT endeavor_id, session, ordinal, relationship, attached_by
                 FROM endeavor_members ORDER BY endeavor_id, ordinal"""
        ):
            members[row["endeavor_id"]].append(row)
        run_statuses: dict[str, dict[str, str]] = defaultdict(dict)
        if self._table_exists("runs"):
            for row in self._conn.execute(
                """SELECT endeavor_id, session, status FROM runs
                    ORDER BY start_ts"""
            ):
                run_statuses[row["endeavor_id"]][row["session"]] = row["status"]
        out: list[dict[str, Any]] = []
        for row in self._conn.execute(
            """SELECT id, project_id, title, status, target_json,
                      metadata_json FROM endeavors"""
        ):
            rows = members.get(row["id"], [])
            present = tuple(
                str(m["session"]) for m in rows if m["session"] in records
            )
            if not present:
                continue
            title = str(row["title"] or "").strip()
            if not title:
                title = records[present[0]]["title"]
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except json.JSONDecodeError:
                metadata = {}
            try:
                target = json.loads(row["target_json"] or "{}")
            except json.JSONDecodeError:
                target = {}
            attached_by = {
                str(m["session"]): str(m["attached_by"]) for m in rows
            }
            out.append({
                "id": str(row["id"]),
                "title": title,
                "sessions": present,
                "status": row["status"] if row["status"] not in
                ("active", "") else None,
                "relationship_by_session": {
                    str(m["session"]): str(m["relationship"]) for m in rows
                },
                "run_statuses": dict(run_statuses.get(row["id"], {})),
                "project_id": row["project_id"],
                "target": target,
                "metadata": {**metadata, "attached_by_session": attached_by,
                             "captured": True},
                "recovered_errors": False,
                "control_milestones": (),
                "expected_session_count": len(rows),
                "missing_session_ids": tuple(
                    str(m["session"]) for m in rows
                    if m["session"] not in records
                ),
                "acceptance_anchors_satisfied": True,
                "explicit": True,
            })
        return out

    def _resolved_endeavors(self) -> list[dict[str, Any]]:
        records = self._session_records()
        claimed: set[str] = set()
        out: list[dict[str, Any]] = []

        durable_ids: set[str] = set()
        for durable in self._durable_groupings(records):
            durable_ids.add(durable["id"])
            claimed.update(durable["sessions"])
            out.append(durable)

        for grouping in self._groupings:
            if grouping.id in durable_ids:
                continue  # migrated to durable rows; those are authoritative
            present = tuple(sid for sid in grouping.sessions
                            if sid in records and sid not in claimed)
            if not present:
                continue
            missing = tuple(sid for sid in grouping.sessions if sid not in records)
            anchor_results = tuple(
                self._acceptance_anchor_present(anchor)
                for anchor in grouping.acceptance_anchors
            )
            anchors_satisfied = all(anchor_results)
            complete = not missing
            resolved_status = grouping.status
            if resolved_status == "accepted" and not (complete and anchors_satisfied):
                resolved_status = "unknown"
            claimed.update(present)
            out.append({
                "id": grouping.id,
                "title": grouping.title,
                "sessions": present,
                "status": resolved_status,
                "relationship_by_session": dict(grouping.relationship_by_session),
                "run_statuses": dict(grouping.run_statuses),
                "project_id": grouping.project_id,
                "target": dict(grouping.target),
                "metadata": {
                    **dict(grouping.metadata),
                    "mapping_complete": complete,
                    "missing_session_ids": list(missing),
                    "acceptance_anchors_satisfied": anchors_satisfied,
                },
                "recovered_errors": grouping.recovered_errors,
                "control_milestones": tuple(grouping.control_milestones),
                "expected_session_count": len(grouping.sessions),
                "missing_session_ids": missing,
                "acceptance_anchors_satisfied": anchors_satisfied,
                "explicit": True,
            })

        # ``!attach`` aliases are also explicit user intent, so they are safe
        # to honor.  No title/prompt/time similarity heuristic is used.
        unclaimed = set(records) - claimed
        parent = {sid: sid for sid in unclaimed}

        def find(sid: str) -> str:
            while parent[sid] != sid:
                parent[sid] = parent[parent[sid]]
                sid = parent[sid]
            return sid

        def union(left: str, right: str) -> None:
            a, b = find(left), find(right)
            if a != b:
                parent[max(a, b)] = min(a, b)

        if self._table_exists("session_aliases"):
            for row in self._conn.execute("SELECT alias, target FROM session_aliases"):
                if row["alias"] in unclaimed and row["target"] in unclaimed:
                    union(row["alias"], row["target"])

        components: dict[str, list[str]] = defaultdict(list)
        for sid in unclaimed:
            components[find(sid)].append(sid)
        for root, members in components.items():
            members.sort(key=lambda sid: (records[sid]["created_ts"], sid))
            canonical = min(members, key=lambda sid: (records[sid]["created_ts"], sid))
            identifier = (
                f"conversation:{canonical}" if len(members) > 1 else f"session:{canonical}"
            )
            out.append({
                "id": identifier,
                "title": records[canonical]["title"],
                "sessions": tuple(members),
                "status": None,
                "relationship_by_session": {
                    sid: ("initial" if sid == canonical else "attached")
                    for sid in members
                },
                "run_statuses": {},
                "project_id": None,
                "target": {},
                "metadata": {"attached_by": "session_alias" if len(members) > 1 else "fallback"},
                "recovered_errors": False,
                "control_milestones": (),
                "expected_session_count": len(members),
                "missing_session_ids": (),
                "acceptance_anchors_satisfied": True,
                "explicit": len(members) > 1,
            })
        return out

    def _acceptance_anchor_present(self, anchor: AcceptanceAnchor) -> bool:
        clauses = ["session=?", "kind=?", "task <> '-'"]
        args: list[Any] = [anchor.session, anchor.kind]
        if anchor.task is not None:
            clauses.append("task=?")
            args.append(anchor.task)
        rows = self._conn.execute(
            "SELECT data FROM events WHERE " + " AND ".join(clauses)
            + " ORDER BY ts DESC, rowid DESC",
            tuple(args),
        ).fetchall()
        if not rows:
            return False
        if not anchor.require_clean_terminal:
            return True
        return not _terminal_failure(_json_object(rows[0]["data"]))

    def _table_exists(self, name: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None

    def _summary_stats(self, sessions: Sequence[str]) -> dict[str, Any]:
        """Return generated-summary coverage without touching raw payloads."""
        if not (
            self._table_exists("message_summaries")
            and self._table_exists("message_summary_sources")
        ):
            return {
                "occurrences": 0,
                "unique": 0,
                "summarized": 0,
                "coverage": 0.0,
                "models": [],
            }
        placeholders = ",".join("?" for _ in sessions)
        row = self._conn.execute(
            f"""SELECT COUNT(*) AS occurrences,
                       COUNT(DISTINCT src.input_sha256) AS unique_messages,
                       COUNT(DISTINCT CASE WHEN EXISTS (
                         SELECT 1 FROM message_summaries AS summary
                          WHERE summary.input_sha256=src.input_sha256
                            AND summary.prompt_version=src.prompt_version
                       ) THEN src.input_sha256 END) AS summarized
                  FROM message_summary_sources AS src
                 WHERE src.session IN ({placeholders})""",
            tuple(sessions),
        ).fetchone()
        models = [
            str(model)
            for model, in self._conn.execute(
                f"""SELECT DISTINCT summary.model
                       FROM message_summaries AS summary
                       JOIN message_summary_sources AS src
                         ON src.input_sha256=summary.input_sha256
                        AND src.prompt_version=summary.prompt_version
                      WHERE src.session IN ({placeholders})
                      ORDER BY summary.model""",
                tuple(sessions),
            )
            if model
        ]
        unique = int(row["unique_messages"] or 0)
        summarized = int(row["summarized"] or 0)
        return {
            "occurrences": int(row["occurrences"] or 0),
            "unique": unique,
            "summarized": summarized,
            "coverage": round(summarized / unique, 6) if unique else 0.0,
            "models": models,
        }

    def _representative_summary(
        self, sessions: Sequence[str]
    ) -> dict[str, Any] | None:
        """Pick the earliest client user message as compact endeavor context."""
        if not (
            self._table_exists("message_summaries")
            and self._table_exists("message_summary_sources")
        ):
            return None
        placeholders = ",".join("?" for _ in sessions)
        row = self._conn.execute(
            f"""SELECT summary.role, summary.headline, summary.summary, summary.model,
                       summary.prompt_version
                  FROM message_summary_sources AS src
                  JOIN message_summaries AS summary
                    ON summary.input_sha256=src.input_sha256
                   AND summary.prompt_version=src.prompt_version
                 WHERE src.session IN ({placeholders})
                   AND src.boundary='client_request' AND src.role='user'
                 ORDER BY src.ts, src.exchange_id, src.ordinal,
                          summary.created_ts DESC
                 LIMIT 1""",
            tuple(sessions),
        ).fetchone()
        return _summary_row(row) if row else None

    def _summary_source_map(
        self, exchange_rows: Sequence[sqlite3.Row]
    ) -> dict[tuple[int, str], dict[str, Any]]:
        """Map exact exchange JSON pointers to their latest prose summary."""
        if not exchange_rows or not (
            self._table_exists("message_summaries")
            and self._table_exists("message_summary_sources")
        ):
            return {}
        exchange_ids = sorted({int(row["id"]) for row in exchange_rows})
        placeholders = ",".join("?" for _ in exchange_ids)
        rows = self._conn.execute(
            f"""SELECT src.exchange_id, src.json_pointer, src.boundary,
                       summary.role, summary.headline, summary.summary,
                       summary.model, summary.prompt_version, summary.created_ts
                  FROM message_summary_sources AS src
                  JOIN message_summaries AS summary
                    ON summary.input_sha256=src.input_sha256
                   AND summary.prompt_version=src.prompt_version
                 WHERE src.exchange_id IN ({placeholders})
                 ORDER BY src.exchange_id, src.ordinal, summary.created_ts DESC""",
            tuple(exchange_ids),
        )
        result: dict[tuple[int, str], dict[str, Any]] = {}
        for row in rows:
            key = (int(row["exchange_id"]), str(row["json_pointer"]))
            result.setdefault(key, _summary_row(row, boundary=row["boundary"]))
        return result

    def _step_summary_map(
        self, sessions: Sequence[str]
    ) -> dict[tuple[str, str], dict[str, str]]:
        """Load the additive per-task display summaries when available."""
        if not sessions or not self._table_exists("step_summaries"):
            return {}
        placeholders = ",".join("?" for _ in sessions)
        rows = self._conn.execute(
            f"""SELECT session, task, short_summary, node_label, long_summary
                   FROM step_summaries
                  WHERE session IN ({placeholders})""",
            tuple(sessions),
        )
        return {
            (str(row["session"]), str(row["task"])): {
                "short_summary": str(row["short_summary"] or ""),
                "node_label": str(row["node_label"] or "Conversation step"),
                "long_summary": str(row["long_summary"] or ""),
            }
            for row in rows
        }

    def _representative_step_summary(
        self, sessions: Sequence[str]
    ) -> dict[str, str] | None:
        """Use the earliest summarized task as run/endeavor-level context."""
        if not sessions or not self._table_exists("step_summaries"):
            return None
        placeholders = ",".join("?" for _ in sessions)
        row = self._conn.execute(
            f"""SELECT short_summary, node_label, long_summary
                   FROM step_summaries
                  WHERE session IN ({placeholders})
                  ORDER BY created_ts, session, task LIMIT 1""",
            tuple(sessions),
        ).fetchone()
        if row is None:
            return None
        return {
            "short_summary": str(row["short_summary"] or ""),
            "node_label": str(row["node_label"] or "Conversation step"),
            "long_summary": str(row["long_summary"] or ""),
        }

    def _find_endeavor(self, endeavor_id: str) -> dict[str, Any]:
        for endeavor in self._resolved_endeavors():
            if endeavor["id"] == endeavor_id:
                return endeavor
        raise KeyError(endeavor_id)

    def _endeavor_summary(self, endeavor: Mapping[str, Any]) -> dict[str, Any]:
        stats = self._stats(endeavor["sessions"])
        runs = [self._run_summary(endeavor, sid) for sid in endeavor["sessions"]]
        step_summary = self._representative_step_summary(endeavor["sessions"])
        status = endeavor.get("status") or self._rollup_status(runs)
        error_count = stats["error_count"]
        recovered = error_count if (
            endeavor.get("recovered_errors") and status == "accepted"
        ) else sum(
            r["errors"]["recovered"] for r in runs
        )
        recovered = min(recovered, error_count)
        controls = self._matched_controls(endeavor)
        return {
            "id": endeavor["id"],
            "title": endeavor["title"],
            "status": status,
            "explicit_grouping": bool(endeavor.get("explicit")),
            "project_ids": stats["project_ids"],
            "session_ids": list(endeavor["sessions"]),
            "run_count": len(endeavor["sessions"]),
            "session_count": len(endeavor["sessions"]),
            "expected_session_count": int(
                endeavor.get("expected_session_count", len(endeavor["sessions"]))
            ),
            "missing_session_count": len(endeavor.get("missing_session_ids", ())),
            "acceptance_anchors_satisfied": bool(
                endeavor.get("acceptance_anchors_satisfied", True)
            ),
            "task_count": stats["task_count"],
            "event_count": stats["event_count"],
            "control_event_count": len(controls),
            "exchange_count": stats["exchange_count"],
            "start_ts": stats["start_ts"],
            "last_ts": stats["last_ts"],
            "duration_seconds": max(0.0, stats["last_ts"] - stats["start_ts"]),
            "tokens_in": stats["tokens_in"],
            "tokens_out": stats["tokens_out"],
            "tokens_total": stats["tokens_total"],
            "cost_usd": round(stats["cost_usd"], 6),
            "payload_bytes": stats["payload_bytes"],
            "agent_turns": stats["agent_turns"],
            "tool_steps": stats["tool_steps"],
            "provider_errors": stats["provider_errors"],
            "monitor_findings": stats["monitor_findings"],
            "context_summary": self._representative_summary(endeavor["sessions"]),
            "short_summary": step_summary["short_summary"] if step_summary else None,
            "node_label": step_summary["node_label"] if step_summary else None,
            "long_summary": step_summary["long_summary"] if step_summary else None,
            "message_summary_coverage": self._summary_stats(endeavor["sessions"]),
            "errors": {
                "total": error_count,
                "recovered": recovered,
                "unrecovered": error_count - recovered,
            },
            "target": dict(endeavor.get("target") or {}),
        }

    def _stats(self, sessions: Sequence[str]) -> dict[str, Any]:
        placeholders = ",".join("?" for _ in sessions)
        args = tuple(sessions)
        event = self._conn.execute(
            f"""SELECT COUNT(*) AS n,
                       MIN(ts) AS first_ts, MAX(ts) AS last_ts,
                       COALESCE(SUM(tokens_in), 0) AS tokens_in,
                       COALESCE(SUM(tokens_out), 0) AS tokens_out,
                       COALESCE(SUM(cost_usd), 0) AS cost_usd,
                       COUNT(DISTINCT CASE WHEN task <> '-' THEN task END) AS tasks,
                       SUM(CASE WHEN kind IN ({','.join('?' for _ in _ERROR_KINDS)})
                                THEN 1 ELSE 0 END) AS errors
                  FROM events WHERE session IN ({placeholders})""",
            tuple(_ERROR_KINDS) + args,
        ).fetchone()
        exchange = self._conn.execute(
            f"""SELECT COUNT(*) AS n, MIN(ts) AS first_ts, MAX(ts) AS last_ts,
                       COUNT(DISTINCT CASE WHEN task <> '-' THEN task END) AS tasks
                  FROM exchanges WHERE session IN ({placeholders})""",
            args,
        ).fetchone()
        task_count = self._conn.execute(
            f"""SELECT COUNT(*) FROM (
                   SELECT task FROM events
                    WHERE session IN ({placeholders}) AND task <> '-'
                   UNION
                   SELECT task FROM exchanges
                    WHERE session IN ({placeholders}) AND task <> '-'
                 )""",
            args + args,
        ).fetchone()[0]
        projects = [
            row[0] or "default"
            for row in self._conn.execute(
                f"SELECT DISTINCT project_id FROM sessions WHERE session IN ({placeholders})",
                args,
            )
        ]
        exchange_bytes = self._conn.execute(
            f"SELECT COALESCE(SUM(LENGTH(payload)), 0) FROM exchanges "
            f"WHERE session IN ({placeholders})",
            args,
        ).fetchone()[0]
        kind_counts = {
            row["kind"]: int(row["n"])
            for row in self._conn.execute(
                f"SELECT kind, COUNT(*) AS n FROM events "
                f"WHERE session IN ({placeholders}) GROUP BY kind",
                args,
            )
        }
        starts = [r for r in (event["first_ts"], exchange["first_ts"]) if r is not None]
        ends = [r for r in (event["last_ts"], exchange["last_ts"]) if r is not None]
        return {
            "event_count": int(event["n"] or 0),
            "exchange_count": int(exchange["n"] or 0),
            "task_count": int(task_count or 0),
            "start_ts": float(min(starts)) if starts else 0.0,
            "last_ts": float(max(ends)) if ends else 0.0,
            "tokens_in": int(event["tokens_in"] or 0),
            "tokens_out": int(event["tokens_out"] or 0),
            "tokens_total": int(event["tokens_in"] or 0) + int(event["tokens_out"] or 0),
            "cost_usd": float(event["cost_usd"] or 0.0),
            "error_count": int(event["errors"] or 0),
            "provider_errors": sum(
                kind_counts.get(kind, 0) for kind in _PROVIDER_ERROR_KINDS
            ),
            "monitor_findings": kind_counts.get("fm_event", 0),
            "agent_turns": kind_counts.get("agent_turn", 0),
            "tool_steps": kind_counts.get("tool_step", 0),
            "payload_bytes": int(exchange_bytes or 0),
            "project_ids": sorted(set(projects or ["default"])),
        }

    def _run_summary(
        self, endeavor: Mapping[str, Any], session: str
    ) -> dict[str, Any]:
        stats = self._stats((session,))
        step_summary = self._representative_step_summary((session,))
        explicit_status = endeavor.get("run_statuses", {}).get(session)
        status, reason, observed_terminal = self._derive_run_status(session)
        if explicit_status and not observed_terminal:
            status, reason = explicit_status, "documented_legacy_mapping"
        error_count = stats["error_count"]
        recovered = error_count if status == "succeeded" else 0
        row = self._conn.execute(
            "SELECT project_id, turns FROM sessions WHERE session=?", (session,)
        ).fetchone()
        first_request = self._conn.execute(
            """SELECT id FROM exchanges
                WHERE session=? AND kind='client_request'
                ORDER BY id LIMIT 1""",
            (session,),
        ).fetchone()
        return {
            "id": f"run:{session}",
            "session_id": session,
            "title": _safe_run_title(session),
            "project_id": (row["project_id"] if row else None) or "default",
            "relationship": endeavor.get("relationship_by_session", {}).get(session, "session"),
            "status": status,
            "terminal_reason": reason,
            "start_ts": stats["start_ts"],
            "last_ts": stats["last_ts"],
            "duration_seconds": max(0.0, stats["last_ts"] - stats["start_ts"]),
            "task_count": stats["task_count"],
            "event_count": stats["event_count"],
            "exchange_count": stats["exchange_count"],
            "turn_count": int(row["turns"] or 0) if row else 0,
            "tokens_in": stats["tokens_in"],
            "tokens_out": stats["tokens_out"],
            "cost_usd": stats["cost_usd"],
            "tokens_total": stats["tokens_total"],
            "payload_bytes": stats["payload_bytes"],
            "agent_turns": stats["agent_turns"],
            "tool_steps": stats["tool_steps"],
            "provider_errors": stats["provider_errors"],
            "monitor_findings": stats["monitor_findings"],
            "context_summary": self._representative_summary((session,)),
            "short_summary": step_summary["short_summary"] if step_summary else None,
            "node_label": step_summary["node_label"] if step_summary else None,
            "long_summary": step_summary["long_summary"] if step_summary else None,
            "message_summary_coverage": self._summary_stats((session,)),
            "source_exchange_ids": [int(first_request["id"])] if first_request else [],
            "errors": {
                "total": error_count,
                "recovered": recovered,
                "unrecovered": error_count - recovered,
            },
        }

    def _derive_run_status(self, session: str) -> tuple[str, str, bool]:
        kinds = Counter(
            row[0]
            for row in self._conn.execute(
                "SELECT kind FROM events WHERE session=? AND task <> '-'", (session,)
            )
        )
        terminal = self._conn.execute(
            """SELECT kind, data FROM events
                WHERE session=? AND task <> '-' AND kind IN ('agent_end','turn_end')
                ORDER BY ts DESC, rowid DESC LIMIT 1""",
            (session,),
        ).fetchone()
        if terminal is not None:
            kind = str(terminal["kind"])
            if _terminal_failure(_json_object(terminal["data"])):
                return "failed", f"{kind}_failed", True
            return "succeeded", kind, True

        latest = self._conn.execute(
            """SELECT payload FROM exchanges
                WHERE session=? AND kind='client_response'
                ORDER BY id DESC LIMIT 1""",
            (session,),
        ).fetchone()
        latest_payload = _json_object(latest["payload"]) if latest else {}
        finish = _finish_reason(latest_payload)
        if finish == "stop":
            if _terminal_failure(latest_payload):
                return "failed", "final_response_failed", True
            return "succeeded", "final_response", True
        provider_errors = sum(kinds[kind] for kind in _PROVIDER_ERROR_KINDS)
        if provider_errors and not (kinds["tool_step"] or kinds["execute"]):
            return "failed", "provider_failure", True
        activity = sum(kinds.values()) or self._conn.execute(
            "SELECT COUNT(*) FROM exchanges WHERE session=?", (session,)
        ).fetchone()[0]
        if activity:
            if finish == "tool_calls":
                return "interrupted", "unmatched_tool_boundary", False
            return "interrupted", "trace_ended_without_terminal_event", False
        return "unknown", "no_trace_activity", False

    @staticmethod
    def _rollup_status(runs: Sequence[Mapping[str, Any]]) -> str:
        statuses = [r["status"] for r in runs]
        if statuses and all(s == "succeeded" for s in statuses):
            return "succeeded"
        if "interrupted" in statuses:
            return "interrupted"
        if statuses and all(s == "failed" for s in statuses):
            return "failed"
        if "failed" in statuses:
            return "failed"
        return "unknown"

    # ------------------------------------------------------------------
    # Timeline projection

    def _timeline_steps(
        self, endeavor: Mapping[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        sessions = tuple(endeavor["sessions"])
        placeholders = ",".join("?" for _ in sessions)
        event_rows = self._conn.execute(
            f"""SELECT rowid AS event_id, ts, session, task, kind, model, fm_id,
                       tokens_in, tokens_out, cost_usd, data
                  FROM events
                 WHERE session IN ({placeholders}) AND task <> '-'
                 ORDER BY ts, rowid""",
            sessions,
        ).fetchall()
        exchange_rows = self._conn.execute(
            f"""SELECT id, ts, session, task, kind, model, payload
                  FROM exchanges
                 WHERE session IN ({placeholders}) AND task <> '-'
                 ORDER BY id""",
            sessions,
        ).fetchall()

        events_by_task: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
        exchanges_by_task: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
        for row in event_rows:
            events_by_task[(row["session"], row["task"])].append(row)
        for row in exchange_rows:
            exchanges_by_task[(row["session"], row["task"])].append(row)

        summary_sources = self._summary_source_map(exchange_rows)
        delta_by_task = self._message_deltas(exchange_rows, summary_sources)
        result_by_call = self._tool_results(exchange_rows)
        result_summary_by_call = self._tool_result_summaries(
            exchange_rows, summary_sources
        )
        step_summaries = self._step_summary_map(sessions)
        keys = set(events_by_task) | set(exchanges_by_task)

        def first_ts(key: tuple[str, str]) -> tuple[float, str, str]:
            rows = [*events_by_task[key], *exchanges_by_task[key]]
            return min(float(r["ts"]) for r in rows), key[0], key[1]

        steps: list[dict[str, Any]] = []
        for key in sorted(keys, key=first_ts):
            sid, task = key
            step_summary = step_summaries.get(key)
            events = events_by_task[key]
            exchanges = exchanges_by_task[key]
            response_row = next(
                (row for row in exchanges if row["kind"] == "client_response"),
                None,
            )
            response = _json_object(response_row["payload"]) if response_row else {}
            response_summary = None
            if response_row is not None:
                response_summary = summary_sources.get(
                    (int(response_row["id"]), "/choices/0/message")
                ) or summary_sources.get((int(response_row["id"]), "/text"))
            calls = _tool_calls(response)
            call_meta = []
            warning_counts: Counter[WarningKey] = Counter()
            routine_categories: list[str] = []
            has_state_change = False
            has_failed_result = False
            unmatched = False
            for call in calls:
                result = result_by_call.get((sid, call["id"]))
                category = _poll_category(call)
                if category:
                    routine_categories.append(category)
                result_meta, warnings, state_change = _result_metadata(result)
                warning_counts.update(warnings)
                has_state_change = has_state_change or state_change
                if result_meta and (
                    result_meta.get("ok") is False
                    or result_meta.get("timed_out") is True
                    or result_meta.get("exit_code") not in (None, 0)
                ):
                    has_failed_result = True
                if result is None:
                    unmatched = True
                call_meta.append({
                    "id": call["id"],
                    "name": call["name"],
                    "argument_keys": sorted(call["arguments"]),
                    "arguments_chars": call["arguments_chars"],
                    "arguments_sha256": call["arguments_sha256"],
                    "result": result_meta,
                    "result_summary": result_summary_by_call.get((sid, call["id"])),
                    "poll_category": category,
                    "matched_result": result is not None,
                })

            event_kinds = Counter(row["kind"] for row in events)
            finish = _finish_reason(response)
            error_count = sum(event_kinds[k] for k in _ERROR_KINDS)
            monitor_finding_count = event_kinds["fm_event"]
            terminal_event = next(
                (row for row in reversed(events) if row["kind"] in _TERMINAL_KINDS),
                None,
            )
            terminal_failed = terminal_event is not None and _terminal_failure(
                _json_object(terminal_event["data"])
            )
            response_failed = finish == "stop" and _terminal_failure(response)
            if terminal_failed or response_failed:
                step_status = "failed"
            elif terminal_event is not None or finish == "stop":
                step_status = "succeeded"
            elif error_count and not calls:
                step_status = "failed"
            elif has_failed_result:
                step_status = "failed"
            elif calls and unmatched:
                step_status = "interrupted"
            elif calls:
                step_status = "succeeded"
            else:
                step_status = "unknown"
            severity = "error" if step_status == "failed" else (
                "warning" if error_count or monitor_finding_count or warning_counts else "info"
            )
            routine = bool(calls) and len(routine_categories) == len(calls)
            routine = routine and not (
                error_count or monitor_finding_count or has_failed_result
                or unmatched or has_state_change
            )
            rows = [*events, *exchanges]
            started = min(float(row["ts"]) for row in rows)
            ended = max(float(row["ts"]) for row in rows)
            models = sorted({str(row["model"]) for row in events if row["model"]})
            fm_ids = sorted({str(row["fm_id"]) for row in events if row["fm_id"]})
            steps.append({
                "type": "step",
                "id": f"step:{sid}:{task}",
                "run_id": f"run:{sid}",
                "session_id": sid,
                "task_id": task,
                "short_summary": (
                    step_summary["short_summary"] if step_summary else None
                ),
                "node_label": step_summary["node_label"] if step_summary else None,
                "long_summary": (
                    step_summary["long_summary"] if step_summary else None
                ),
                "status": step_status,
                "severity": severity,
                "start_ts": started,
                "end_ts": ended,
                "duration_seconds": max(0.0, ended - started),
                "event_kinds": dict(sorted(event_kinds.items())),
                "models": models,
                "fm_ids": fm_ids,
                "tokens_in": sum(int(row["tokens_in"] or 0) for row in events),
                "tokens_out": sum(int(row["tokens_out"] or 0) for row in events),
                "cost_usd": sum(float(row["cost_usd"] or 0.0) for row in events),
                "error_count": error_count,
                "monitor_finding_count": monitor_finding_count,
                "recovered_error_count": error_count if step_status == "succeeded" else 0,
                "tool_calls": call_meta,
                "tool_call_count": len(call_meta),
                "unmatched_tool_result": unmatched,
                "routine_poll": routine,
                "poll_categories": sorted(set(routine_categories)),
                "message_delta": delta_by_task.get(key),
                "response_summary": response_summary,
                "provider_summaries": _provider_response_summaries(
                    exchanges, summary_sources, exclude=response_summary
                ),
                "duplicate_boundaries": _duplicate_boundaries(exchanges),
                "source_event_ids": [int(row["event_id"]) for row in events],
                "source_exchange_ids": [int(row["id"]) for row in exchanges],
                "warning_groups": _warning_list(warning_counts),
                # Private aggregation state; stripped before returning.
                "_warning_counts": warning_counts,
            })
        steps.extend(self._control_steps(endeavor))
        steps.sort(key=lambda step: (step["start_ts"], step["id"]))
        return steps, _aggregate_result_warnings(result_by_call.values())

    def _matched_controls(
        self, endeavor: Mapping[str, Any]
    ) -> list[tuple[ControlMilestone, int]]:
        """Resolve only explicitly curated controls; never use a time window."""
        matched: list[tuple[ControlMilestone, int]] = []
        for milestone in endeavor.get("control_milestones", ()):
            rows = self._conn.execute(
                """SELECT rowid AS event_id, data FROM events
                    WHERE task='-' AND kind='control' AND session=?
                      AND ABS(ts - ?) < 0.000001""",
                (milestone.session, milestone.ts),
            ).fetchall()
            row = next(
                (
                    candidate for candidate in rows
                    if _json_object(candidate["data"]).get("command")
                    == milestone.command
                ),
                None,
            )
            if row is not None:
                matched.append((milestone, int(row["event_id"])))
        return matched

    def _control_steps(
        self, endeavor: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        for milestone, event_id in self._matched_controls(endeavor):
            digest = _hash_text(
                f"{milestone.ts:.6f}\0{milestone.session}\0{milestone.command}"
            )[:16]
            steps.append({
                "type": "control",
                "id": f"control:{digest}",
                "run_id": None,
                "session_id": milestone.session,
                "task_id": "-",
                "short_summary": f"Applied control command {milestone.command}.",
                "node_label": f"Control: {milestone.command}"[:72],
                "long_summary": (
                    f"The operator applied the control command "
                    f"{milestone.command} at this point in the endeavor."
                ),
                "status": "succeeded",
                "severity": "info",
                "start_ts": milestone.ts,
                "end_ts": milestone.ts,
                "duration_seconds": 0.0,
                "command": milestone.command,
                "event_kinds": {"control": 1},
                "models": [],
                "fm_ids": [],
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0.0,
                "error_count": 0,
                "monitor_finding_count": 0,
                "recovered_error_count": 0,
                "tool_calls": [],
                "tool_call_count": 0,
                "unmatched_tool_result": False,
                "routine_poll": False,
                "poll_categories": [],
                "message_delta": None,
                "duplicate_boundaries": None,
                "source_event_ids": [event_id],
                "source_exchange_ids": [],
                "warning_groups": [],
                "_warning_counts": Counter(),
            })
        return steps

    def _message_deltas(
        self,
        exchange_rows: Sequence[sqlite3.Row],
        summary_sources: Mapping[tuple[int, str], Mapping[str, Any]] | None = None,
    ) -> dict[tuple[str, str], dict[str, Any]]:
        summary_sources = summary_sources or {}
        by_session: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in exchange_rows:
            if row["kind"] == "client_request":
                by_session[row["session"]].append(row)
        result: dict[tuple[str, str], dict[str, Any]] = {}
        for sid, rows in by_session.items():
            previous_messages: list[Any] | None = None
            previous_system_hash: str | None = None
            previous_tools_hash: str | None = None
            for row in rows:
                payload = _json_object(row["payload"])
                messages = payload.get("messages")
                messages = messages if isinstance(messages, list) else []
                relation, prefix, removed = _prefix_relation(previous_messages, messages)
                delta = messages[prefix:]
                delta_summaries = []
                for index in range(prefix, len(messages)):
                    summary = summary_sources.get(
                        (int(row["id"]), f"/messages/{index}")
                    )
                    if summary:
                        delta_summaries.append(dict(summary))
                system = [m for m in messages if isinstance(m, dict) and m.get("role") == "system"]
                tools = payload.get("tools") if isinstance(payload.get("tools"), list) else []
                system_hash = _hash_json(system) if system else None
                tools_hash = _hash_json(tools) if tools else None
                result[(sid, row["task"])] = {
                    "relation": relation,
                    "total_messages": len(messages),
                    "common_prefix_messages": prefix,
                    "delta_messages": len(delta),
                    "removed_messages": removed,
                    "delta_roles": [
                        str(message.get("role", "unknown"))
                        if isinstance(message, dict) else "unknown"
                        for message in delta
                    ],
                    "summaries": delta_summaries,
                    "summarized_messages": len(delta_summaries),
                    "request_chars": len(row["payload"]),
                    "messages_sha256": _hash_json(messages),
                    "system_prompt_sha256": system_hash,
                    "system_prompt_changed": (
                        previous_messages is not None and system_hash != previous_system_hash
                    ),
                    "tool_schema_sha256": tools_hash,
                    "tool_schema_changed": (
                        previous_messages is not None and tools_hash != previous_tools_hash
                    ),
                }
                previous_messages = messages
                previous_system_hash = system_hash
                previous_tools_hash = tools_hash
        return result

    @staticmethod
    def _tool_results(
        exchange_rows: Sequence[sqlite3.Row],
    ) -> dict[tuple[str, str], Any]:
        results: dict[tuple[str, str], Any] = {}
        for row in exchange_rows:
            if row["kind"] != "client_request":
                continue
            payload = _json_object(row["payload"])
            messages = payload.get("messages")
            if not isinstance(messages, list):
                continue
            for message in messages:
                if not isinstance(message, dict) or message.get("role") != "tool":
                    continue
                call_id = message.get("tool_call_id")
                key = (row["session"], str(call_id))
                if call_id and key not in results:
                    results[key] = message.get("content")
        return results

    @staticmethod
    def _tool_result_summaries(
        exchange_rows: Sequence[sqlite3.Row],
        summary_sources: Mapping[tuple[int, str], Mapping[str, Any]],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        """Pair a summarized tool result back to the call that issued it."""
        results: dict[tuple[str, str], dict[str, Any]] = {}
        for row in exchange_rows:
            if row["kind"] != "client_request":
                continue
            payload = _json_object(row["payload"])
            messages = payload.get("messages")
            if not isinstance(messages, list):
                continue
            for index, message in enumerate(messages):
                if not isinstance(message, dict) or message.get("role") != "tool":
                    continue
                call_id = message.get("tool_call_id")
                summary = summary_sources.get(
                    (int(row["id"]), f"/messages/{index}")
                )
                key = (str(row["session"]), str(call_id))
                if call_id and summary and key not in results:
                    results[key] = dict(summary)
        return results

    @staticmethod
    def _collapse_poll_steps(steps: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []

        def flush() -> None:
            if not pending:
                return
            if len(pending) == 1:
                output.append(_public_step(pending[0]))
                pending.clear()
                return
            warnings: Counter[WarningKey] = Counter()
            categories: Counter[str] = Counter()
            for step in pending:
                warnings.update(step["_warning_counts"])
                categories.update(step["poll_categories"])
            first_short = next(
                (str(step["short_summary"]) for step in pending
                 if step.get("short_summary")),
                "",
            )
            last_short = next(
                (str(step["short_summary"]) for step in reversed(pending)
                 if step.get("short_summary")),
                "",
            )
            first_long = next(
                (str(step["long_summary"]) for step in pending
                 if step.get("long_summary")),
                "",
            )
            last_long = next(
                (str(step["long_summary"]) for step in reversed(pending)
                 if step.get("long_summary")),
                "",
            )
            short_summary = f"{len(pending)} routine checks were grouped."
            if first_short:
                short_summary += f" First: {first_short}"
            if last_short and last_short != first_short:
                short_summary += f" Last: {last_short}"
            long_summary = (
                f"This item groups {len(pending)} consecutive successful "
                "routine polling steps."
            )
            if first_long:
                long_summary += f" The opening check: {first_long}"
            if last_long and last_long != first_long:
                long_summary += f" The closing check: {last_long}"
            output.append({
                "type": "poll_group",
                "id": f"poll:{pending[0]['id']}:{pending[-1]['id']}",
                "run_id": pending[0]["run_id"] if len({p["run_id"] for p in pending}) == 1 else None,
                "short_summary": short_summary,
                "node_label": f"{len(pending)} routine status checks",
                "long_summary": long_summary,
                "status": "succeeded",
                "severity": "warning" if warnings else "info",
                "start_ts": pending[0]["start_ts"],
                "end_ts": pending[-1]["end_ts"],
                "duration_seconds": max(0.0, pending[-1]["end_ts"] - pending[0]["start_ts"]),
                "member_count": len(pending),
                "first_step_id": pending[0]["id"],
                "last_step_id": pending[-1]["id"],
                "poll_categories": dict(sorted(categories.items())),
                "tokens_in": sum(step["tokens_in"] for step in pending),
                "tokens_out": sum(step["tokens_out"] for step in pending),
                "cost_usd": sum(step["cost_usd"] for step in pending),
                "monitor_finding_count": sum(
                    step["monitor_finding_count"] for step in pending
                ),
                "source_event_ids": [
                    source_id
                    for step in pending
                    for source_id in step["source_event_ids"]
                ],
                "source_exchange_ids": [
                    source_id
                    for step in pending
                    for source_id in step["source_exchange_ids"]
                ],
                "warning_groups": _warning_list(warnings),
                "summary_samples": _poll_summary_samples(pending),
            })
            pending.clear()

        for step in steps:
            if step["routine_poll"]:
                # Do not collapse across run/recovery boundaries.
                if pending and pending[-1]["run_id"] != step["run_id"]:
                    flush()
                pending.append(step)
            else:
                flush()
                output.append(_public_step(step))
        flush()
        return output

    @staticmethod
    def _aggregate_warnings(steps: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        counts: Counter[WarningKey] = Counter()
        step_counts: Counter[WarningKey] = Counter()
        for step in steps:
            counts.update(step["_warning_counts"])
            for warning in step["_warning_counts"]:
                step_counts[warning] += 1
        return _warning_list(
            counts,
            occurrence_field="steps",
            occurrences=step_counts,
            repeated_only=True,
        )

    # ------------------------------------------------------------------
    # Cursor pagination

    def _page(
        self,
        items: Sequence[dict[str, Any]],
        cursor: str | None,
        limit: int,
        *,
        scope: str,
        summary: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not (1 <= limit <= self.MAX_PAGE_SIZE):
            raise ValueError(f"limit must be between 1 and {self.MAX_PAGE_SIZE}")
        offset = _decode_cursor(cursor, scope) if cursor else 0
        total = len(items)
        if offset > total:
            raise ValueError("cursor is beyond the available result set")
        page_items = list(items[offset: offset + limit])
        page_items = [_without_private(item) for item in page_items]
        next_offset = offset + len(page_items)
        return {
            "items": page_items,
            "total": total,
            "next_cursor": _encode_cursor(next_offset, scope) if next_offset < total else None,
            "summary": dict(summary or {}),
        }


# ----------------------------------------------------------------------
# Pure helpers


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_conversation_title(session: str) -> str:
    return f"Conversation {session}"


def _safe_run_title(session: str) -> str:
    return f"Run {session}"


def _terminal_failure(data: Mapping[str, Any]) -> bool:
    """Whether terminal metadata explicitly records a failed outcome."""
    escalated = data.get("escalated")
    if isinstance(escalated, str):
        if escalated.strip():
            return True
    elif escalated:
        return True
    return data.get("passed") is False


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _summary_row(
    row: Mapping[str, Any], *, boundary: str | None = None
) -> dict[str, Any]:
    item = {
        "role": str(row["role"] or "unknown"),
        "headline": str(row["headline"] or "Summary"),
        "summary": str(row["summary"] or ""),
        "model": str(row["model"] or "unknown"),
        "prompt_version": str(row["prompt_version"] or "unknown"),
    }
    if boundary:
        item["boundary"] = str(boundary)
    return item


def _provider_response_summaries(
    exchange_rows: Sequence[sqlite3.Row],
    summary_sources: Mapping[tuple[int, str], Mapping[str, Any]],
    *,
    exclude: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return provider-attempt prose, never provider request transcripts."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    if exclude:
        seen.add((
            str(exclude.get("headline", "")), str(exclude.get("summary", ""))
        ))
    for row in exchange_rows:
        if row["kind"] != "upstream":
            continue
        exchange_id = int(row["id"])
        for (source_id, pointer), summary in summary_sources.items():
            if source_id != exchange_id or not pointer.startswith(
                "/response/choices/"
            ) or not pointer.endswith("/message"):
                continue
            public = dict(summary)
            marker = (str(public.get("headline", "")), str(public.get("summary", "")))
            if marker not in seen:
                seen.add(marker)
                result.append(public)
    return result


def _poll_summary_samples(
    steps: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Keep one opening and one closing narrative for a folded poll run."""
    def candidates(step: Mapping[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for call in step.get("tool_calls") or []:
            if isinstance(call, Mapping) and isinstance(call.get("result_summary"), Mapping):
                items.append(dict(call["result_summary"]))
        if isinstance(step.get("response_summary"), Mapping):
            items.append(dict(step["response_summary"]))
        delta = step.get("message_delta")
        if isinstance(delta, Mapping):
            items.extend(
                dict(item) for item in (delta.get("summaries") or [])
                if isinstance(item, Mapping)
            )
        return items

    chosen: list[dict[str, Any]] = []
    for step in (steps[0], steps[-1]) if steps else ():
        available = candidates(step)
        if available:
            chosen.append(available[0])
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in chosen:
        marker = (str(item.get("headline", "")), str(item.get("summary", "")))
        if marker not in seen:
            seen.add(marker)
            result.append(item)
    return result


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()


def _hash_json(value: Any) -> str:
    return _hash_text(_canonical_json(value))


def _finish_reason(payload: Mapping[str, Any]) -> str | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    value = choices[0].get("finish_reason")
    return str(value) if value is not None else None


def _response_message(payload: Mapping[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return {}
    message = choices[0].get("message")
    return message if isinstance(message, dict) else {}


def _tool_calls(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    calls = _response_message(payload).get("tool_calls")
    if not isinstance(calls, list):
        return []
    result: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        raw_args = function.get("arguments")
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {"_unparsed": True}
            args_chars = len(raw_args)
            args_hash = _hash_text(raw_args)
        elif isinstance(raw_args, dict):
            args = raw_args
            encoded = _canonical_json(raw_args)
            args_chars = len(encoded)
            args_hash = _hash_text(encoded)
        else:
            args = {}
            args_chars = 0
            args_hash = _hash_text("")
        result.append({
            "id": str(call.get("id") or f"anonymous-{index}"),
            "name": str(function.get("name") or "unknown"),
            "arguments": args if isinstance(args, dict) else {"_value": True},
            "arguments_chars": args_chars,
            "arguments_sha256": args_hash,
        })
    return result


def _poll_category(call: Mapping[str, Any]) -> str | None:
    name = str(call.get("name", "")).casefold()
    args = call.get("arguments")
    args = args if isinstance(args, dict) else {}
    command = str(args.get("command") or args.get("cmd") or "")
    lowered = command.casefold()
    if name in {"wait", "poll", "process_wait"}:
        return "delayed_wait"
    if name == "process" and str(args.get("action", "")).casefold() in {"wait", "poll"}:
        return "process_wait"
    if not command or name not in {"terminal", "run_on_authorized_vm", "exec", "shell"}:
        return None
    # A setup command may contain '.exit', 'kill -0', or 'ps' in the script it
    # writes.  Reject mutations before applying the status-pattern rules.
    if re.search(r"\bcat\s*>|\becho\b[^;&|\n]*>", lowered) or re.search(
        r"\b(?:mkdir|nohup|chmod|apt-get)\b|\bgit\s+clone\b", lowered
    ):
        return None
    if re.search(r"(?:^|[;&|]\s*)sleep\s+\d", lowered):
        return "delayed_wait"
    if re.search(r"\btail\b", lowered):
        return "log_tail"
    if re.search(r"\b(?:ps|pgrep|kill\s+-0)\b", lowered):
        return "process_status"
    if re.search(r"(?:\.exit\b|\.pid\b|\b(?:stat|test\s+-[efs]|wc\s+-[lc])\b)", lowered):
        return "artifact_status"
    return None


def _result_metadata(
    value: Any,
) -> tuple[dict[str, Any] | None, Counter[WarningKey], bool]:
    if value is None:
        return None, Counter(), False
    text = value if isinstance(value, str) else _canonical_json(value)
    parsed: Any = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
    warnings: Counter[WarningKey] = Counter()
    candidate_texts = [text]
    if isinstance(parsed, dict):
        candidate_texts = [
            str(parsed.get(key) or "") for key in ("stdout", "stderr", "output")
        ]
    for candidate in candidate_texts:
        for raw_line in candidate.splitlines():
            line = " ".join(raw_line.split())
            if line and _WARNING_RE.search(line):
                normalized = _warning_key(line)
                if normalized:
                    warnings[normalized] += 1
    metadata: dict[str, Any] = {
        "chars": len(text),
        "sha256": _hash_text(text),
    }
    if isinstance(parsed, dict):
        for key in ("ok", "exit_code", "timed_out", "stdout_truncated", "stderr_truncated"):
            if key in parsed and isinstance(parsed[key], (bool, int, float, type(None))):
                metadata[key] = parsed[key]
    state_change = bool(re.search(
        r"(?:^|\n)(?:[^\n]{0,80})?(?:exit(?:_code)?\s*[=:]\s*0|successful make|finished|completed)(?:\b|$)",
        "\n".join(candidate_texts),
        re.IGNORECASE,
    ))
    return metadata, warnings, state_change


def _warning_list(
    counts: Mapping[WarningKey, int],
    *,
    occurrence_field: str | None = None,
    occurrences: Mapping[WarningKey, int] | None = None,
    repeated_only: bool = False,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for warning, count in sorted(
        counts.items(), key=lambda item: (-item[1], item[0])
    ):
        if repeated_only and count <= 1:
            continue
        category, label, fingerprint = warning
        item: dict[str, Any] = {
            "category": category,
            "label": label,
            # Compatibility for the first UI slice; unlike the old value this
            # is a fixed safe label, never a raw stderr/stdout line.
            "text": label,
            "fingerprint": fingerprint,
            "sha256": fingerprint,
            "count": count,
        }
        if occurrence_field and occurrences is not None:
            item[occurrence_field] = int(occurrences.get(warning, 0))
        result.append(item)
    return result


def _warning_key(line: str) -> WarningKey | None:
    lowered = line.casefold()
    if "cannot change locale" in lowered:
        # Two malformed fragments in the fixture begin with ':' and were not
        # emitted warning lines; excluding them reproduces the 128/82 audit.
        if line.lstrip().startswith(":"):
            return None
        category = "locale_initialization"
        label = "Locale initialization warning"
        return category, label, _hash_text(category)
    if re.search(r"(?:^|\s)[^\s:]+:\d+(?::\d+)?:\s*warning\b", line, re.IGNORECASE):
        category, label = "compiler", "Compiler warning"
    elif re.search(r"(?:^|\s)(?:bash|sh|zsh):\s*warning\b", line, re.IGNORECASE):
        category, label = "shell", "Shell warning"
    elif "requests did not succeed" in lowered:
        category, label = "request", "Request warning"
    else:
        category, label = "tool", "Tool warning"
    return category, label, _hash_text(f"{category}\0{line}")


def _aggregate_result_warnings(values: Iterable[Any]) -> list[dict[str, Any]]:
    counts: Counter[WarningKey] = Counter()
    result_counts: Counter[WarningKey] = Counter()
    for value in values:
        _, warnings, _ = _result_metadata(value)
        counts.update(warnings)
        for warning in warnings:
            result_counts[warning] += 1
    return _warning_list(
        counts,
        occurrence_field="results",
        occurrences=result_counts,
        repeated_only=True,
    )


def _first_exchange_payload(
    rows: Sequence[sqlite3.Row], kind: str
) -> dict[str, Any]:
    for row in rows:
        if row["kind"] == kind:
            return _json_object(row["payload"])
    return {}


def _prefix_relation(
    previous: Sequence[Any] | None, current: Sequence[Any]
) -> tuple[str, int, int]:
    if previous is None:
        return "initial", 0, 0
    common = 0
    for left, right in zip(previous, current):
        if left != right:
            break
        common += 1
    if common == len(previous) == len(current):
        return "identical", common, 0
    if common == len(previous) and len(current) > len(previous):
        return "continuation", common, 0
    if common == len(current) and len(current) < len(previous):
        return "rewind", common, len(previous) - len(current)
    return "edit", common, max(0, len(previous) - common)


def _duplicate_boundaries(rows: Sequence[sqlite3.Row]) -> dict[str, Any]:
    client_request = _first_exchange_payload(rows, "client_request")
    client_response = _first_exchange_payload(rows, "client_response")
    upstreams = [
        _json_object(row["payload"]) for row in rows if row["kind"] == "upstream"
    ]
    executor_upstream = next(
        (u for u in upstreams if isinstance(u.get("request"), dict)), {}
    )
    upstream_request = executor_upstream.get("request")
    upstream_request = upstream_request if isinstance(upstream_request, dict) else {}
    upstream_response = executor_upstream.get("response")
    upstream_response = upstream_response if isinstance(upstream_response, dict) else {}

    def equal_field(name: str) -> bool | None:
        if name not in client_request or name not in upstream_request:
            return None
        return client_request[name] == upstream_request[name]

    response_equal: bool | None = None
    if client_response and upstream_response:
        response_equal = client_response == upstream_response
    duplicate_count = 0
    if equal_field("messages") is True:
        duplicate_count += 1
    if equal_field("tools") is True:
        duplicate_count += 1
    if response_equal is True:
        duplicate_count += 1
    return {
        "raw_copy_count": len(rows),
        "request_messages_identical": equal_field("messages"),
        "request_tools_identical": equal_field("tools"),
        "response_identical": response_equal,
        "duplicate_components": duplicate_count,
    }


def _public_step(step: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in step.items() if not key.startswith("_")}


def _without_private(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_private(item)
            for key, item in value.items()
            if not key.startswith("_") and key not in {"payload", "data"}
        }
    if isinstance(value, list):
        return [_without_private(item) for item in value]
    return value


def _encode_cursor(offset: int, scope: str) -> str:
    payload = _canonical_json({"v": 1, "offset": offset, "scope": scope})
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str, scope: str) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("scope") != scope
            or isinstance(payload.get("offset"), bool)
            or not isinstance(payload.get("offset"), int)
            or payload["offset"] < 0
        ):
            raise ValueError
        return payload["offset"]
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid or mismatched history cursor") from exc


__all__ = [
    "AcceptanceAnchor",
    "ControlMilestone",
    "EndeavorGrouping",
    "HistoryView",
    "HistoryViewError",
    "NETBSD_ARM64_ENDEAVOR",
]
