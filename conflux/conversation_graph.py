"""Durable, editable conversation and per-message workflow graphs.

The existing trace database remains the forensic source of truth.  This
module adds a product-facing graph projection with explicit dependencies,
revisions, invalidation, workflow-instance overrides, and bounded knowledge
stores.  It deliberately stores no provider credentials: external store
connections are referenced by an operator-owned ``connection_ref`` only.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict
from typing import Any, Iterable, Mapping

from .flows import FlowRegistry, NODE_TYPES


WORKSPACE_NODE_KINDS = {
    "message", "context", "store_read", "store_write", "checkpoint",
}
WORKFLOW_EXTENSION_TYPES = {
    "ensemble", "context", "store_read", "store_write", "human_input",
}
WORKFLOW_NODE_TYPES = set(NODE_TYPES) | WORKFLOW_EXTENSION_TYPES
NODE_STATUSES = {
    "draft", "queued", "running", "awaiting_input", "awaiting_approval",
    "paused", "complete", "stale", "failed", "needs_attention", "cancelled",
}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")
MAX_TEXT = 400_000
VECTOR_DIMS = 96


def _now() -> float:
    return time.time()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _clean_id(value: str, field: str = "id") -> str:
    value = str(value or "").strip()
    if not ID_RE.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def _clean_text(value: Any, field: str = "text", *, limit: int = MAX_TEXT) -> str:
    value = str(value or "")
    if len(value) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return value


def _vector(text: str) -> list[float]:
    """Small deterministic local embedding used by the built-in store.

    This is intentionally provider-free and bounded.  The adapter contract
    keeps external vector databases possible without allowing an agent to
    supply or retarget connection credentials.
    """
    values = [0.0] * VECTOR_DIMS
    for token in TOKEN_RE.findall(text.casefold())[:20_000]:
        digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % VECTOR_DIMS
        sign = 1.0 if digest[4] & 1 else -1.0
        values[index] += sign * (1.0 + min(len(token), 20) / 20)
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [round(value / norm, 8) for value in values]


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


class ConversationGraphStore:
    """SQLite-backed graph store shared with the trace connection."""

    def __init__(self, connection: sqlite3.Connection, registry: FlowRegistry):
        self._conn = connection
        self.registry = registry
        self._lock = threading.RLock()
        self._ensure_schema()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def _ensure_schema(self) -> None:
        schema = (
            """CREATE TABLE IF NOT EXISTS workspace_endeavors (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS workspace_conversations (
                session TEXT PRIMARY KEY, endeavor_id TEXT NOT NULL,
                title TEXT NOT NULL, status TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS workspace_nodes (
                node_id TEXT PRIMARY KEY, endeavor_id TEXT NOT NULL,
                session TEXT NOT NULL, parent_id TEXT, ordinal INTEGER NOT NULL,
                kind TEXT NOT NULL, role TEXT NOT NULL, label TEXT NOT NULL,
                status TEXT NOT NULL, input_text TEXT NOT NULL,
                output_text TEXT NOT NULL, config_json TEXT NOT NULL,
                workflow_instance_id TEXT, run_id TEXT,
                position_x REAL, position_y REAL, revision INTEGER NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS workspace_edges (
                edge_id TEXT PRIMARY KEY, endeavor_id TEXT NOT NULL,
                session TEXT NOT NULL, source_id TEXT NOT NULL,
                target_id TEXT NOT NULL, kind TEXT NOT NULL,
                label TEXT NOT NULL, created_at REAL NOT NULL,
                UNIQUE(source_id, target_id, kind)
            )""",
            """CREATE TABLE IF NOT EXISTS workspace_node_revisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, node_id TEXT NOT NULL,
                revision INTEGER NOT NULL, input_text TEXT NOT NULL,
                output_text TEXT NOT NULL, config_json TEXT NOT NULL,
                reason TEXT NOT NULL, edited_at REAL NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS workspace_workflows (
                instance_id TEXT PRIMARY KEY, owner_node_id TEXT NOT NULL,
                flow_id TEXT NOT NULL, base_version INTEGER NOT NULL,
                revision INTEGER NOT NULL, graph_json TEXT NOT NULL,
                active_node TEXT, status TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS workspace_workflow_overrides (
                flow_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                graph_json TEXT NOT NULL, updated_at REAL NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS workspace_jobs (
                job_id TEXT PRIMARY KEY, session TEXT NOT NULL,
                root_node_id TEXT NOT NULL, kind TEXT NOT NULL,
                status TEXT NOT NULL, progress_json TEXT NOT NULL,
                error TEXT NOT NULL, created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS workspace_stores (
                store_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                description TEXT NOT NULL, adapter TEXT NOT NULL,
                connection_ref TEXT NOT NULL, status TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS workspace_store_records (
                record_id TEXT PRIMARY KEY, store_id TEXT NOT NULL,
                source_node_id TEXT, text TEXT NOT NULL,
                metadata_json TEXT NOT NULL, vector_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_workspace_nodes_session ON workspace_nodes(session, ordinal)",
            "CREATE INDEX IF NOT EXISTS idx_workspace_edges_source ON workspace_edges(source_id)",
            "CREATE INDEX IF NOT EXISTS idx_workspace_edges_target ON workspace_edges(target_id)",
            "CREATE INDEX IF NOT EXISTS idx_workspace_workflow_owner ON workspace_workflows(owner_node_id)",
            "CREATE INDEX IF NOT EXISTS idx_workspace_records_store ON workspace_store_records(store_id, created_at DESC)",
        )
        with self._lock:
            for statement in schema:
                self._conn.execute(statement)
            self._conn.commit()

    # ------------------------------------------------------------------
    # Endeavors and conversations

    def create_endeavor(self, title: str, *, endeavor_id: str | None = None,
                        status: str = "active") -> dict[str, Any]:
        title = _clean_text(title, "title", limit=200).strip() or "Untitled endeavor"
        endeavor_id = _clean_id(endeavor_id, "endeavor id") if endeavor_id else _id("end")
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO workspace_endeavors VALUES (?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET title=excluded.title, "
                "updated_at=excluded.updated_at",
                (endeavor_id, title, status, now, now),
            )
            self._conn.commit()
        return self.endeavor(endeavor_id)

    def endeavor(self, endeavor_id: str) -> dict[str, Any]:
        endeavor_id = _clean_id(endeavor_id, "endeavor id")
        cur = self._conn.execute(
            "SELECT id,title,status,created_at,updated_at FROM workspace_endeavors WHERE id=?",
            (endeavor_id,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(endeavor_id)
        item = dict(zip([column[0] for column in cur.description], row))
        item["conversations"] = self.conversations(endeavor_id)
        return item

    def rename_endeavor(self, endeavor_id: str, title: str) -> dict[str, Any]:
        endeavor_id = _clean_id(endeavor_id, "endeavor id")
        title = _clean_text(title, "title", limit=200).strip()
        if not title:
            raise ValueError("endeavor title cannot be empty")
        self.endeavor(endeavor_id)
        now = _now()
        with self._lock:
            self._conn.execute(
                "UPDATE workspace_endeavors SET title=?,updated_at=? WHERE id=?",
                (title, now, endeavor_id),
            )
            self._conn.commit()
        return self.endeavor(endeavor_id)

    def endeavors(self, limit: int = 100) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            """SELECT e.id,e.title,e.status,e.created_at,e.updated_at,
                      COUNT(c.session) AS conversation_count
                 FROM workspace_endeavors e
                 LEFT JOIN workspace_conversations c ON c.endeavor_id=e.id
                GROUP BY e.id ORDER BY e.updated_at DESC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        )
        cols = [column[0] for column in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def create_conversation(self, endeavor_id: str, title: str,
                            *, session: str | None = None,
                            status: str = "active") -> dict[str, Any]:
        endeavor_id = _clean_id(endeavor_id, "endeavor id")
        self.endeavor(endeavor_id)
        session = _clean_id(session, "conversation id") if session else _id("conv")
        title = _clean_text(title, "title", limit=200).strip() or "New conversation"
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO workspace_conversations VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(session) DO UPDATE SET endeavor_id=excluded.endeavor_id, "
                "title=excluded.title,updated_at=excluded.updated_at",
                (session, endeavor_id, title, status, now, now),
            )
            self._conn.execute(
                "UPDATE workspace_endeavors SET updated_at=? WHERE id=?",
                (now, endeavor_id),
            )
            self._conn.commit()
        return self.conversation(session)

    def conversation(self, session: str) -> dict[str, Any]:
        session = _clean_id(session, "conversation id")
        cur = self._conn.execute(
            """SELECT session,endeavor_id,title,status,created_at,updated_at
                 FROM workspace_conversations WHERE session=?""",
            (session,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(session)
        return dict(zip([column[0] for column in cur.description], row))

    def rename_conversation(self, session: str, title: str) -> dict[str, Any]:
        session = _clean_id(session, "conversation id")
        title = _clean_text(title, "title", limit=200).strip()
        if not title:
            raise ValueError("conversation title cannot be empty")
        conversation = self.conversation(session)
        now = _now()
        with self._lock:
            self._conn.execute(
                "UPDATE workspace_conversations SET title=?,updated_at=? WHERE session=?",
                (title, now, session),
            )
            self._conn.execute(
                "UPDATE workspace_endeavors SET updated_at=? WHERE id=?",
                (now, conversation["endeavor_id"]),
            )
            self._conn.commit()
        return self.conversation(session)

    def move_conversation(self, session: str, endeavor_id: str) -> dict[str, Any]:
        """Reparent a conversation and every denormalized graph row atomically."""
        session = _clean_id(session, "conversation id")
        endeavor_id = _clean_id(endeavor_id, "endeavor id")
        conversation = self.conversation(session)
        self.endeavor(endeavor_id)
        now = _now()
        with self._lock:
            self._conn.execute(
                "UPDATE workspace_conversations SET endeavor_id=?,updated_at=? WHERE session=?",
                (endeavor_id, now, session),
            )
            self._conn.execute(
                "UPDATE workspace_nodes SET endeavor_id=?,updated_at=? WHERE session=?",
                (endeavor_id, now, session),
            )
            self._conn.execute(
                "UPDATE workspace_edges SET endeavor_id=? WHERE session=?",
                (endeavor_id, session),
            )
            self._conn.execute(
                "UPDATE workspace_endeavors SET updated_at=? WHERE id IN (?,?)",
                (now, endeavor_id, conversation["endeavor_id"]),
            )
            self._conn.commit()
        return self.conversation(session)

    def conversations(self, endeavor_id: str) -> list[dict[str, Any]]:
        endeavor_id = _clean_id(endeavor_id, "endeavor id")
        cur = self._conn.execute(
            """SELECT c.session,c.endeavor_id,c.title,c.status,c.created_at,
                      c.updated_at,COUNT(n.node_id) AS node_count
                 FROM workspace_conversations c
                 LEFT JOIN workspace_nodes n ON n.session=c.session
                WHERE c.endeavor_id=? GROUP BY c.session
                ORDER BY c.updated_at DESC""",
            (endeavor_id,),
        )
        cols = [column[0] for column in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    # ------------------------------------------------------------------
    # Conversation dependency graph

    def _next_ordinal(self, session: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(ordinal),0)+1 FROM workspace_nodes WHERE session=?",
            (session,),
        ).fetchone()
        return int(row[0])

    def _insert_node(self, *, endeavor_id: str, session: str,
                     parent_id: str | None, kind: str, role: str, label: str,
                     status: str, input_text: str = "", output_text: str = "",
                     config: Mapping[str, Any] | None = None,
                     workflow_instance_id: str | None = None,
                     run_id: str | None = None, node_id: str | None = None,
                     ordinal: int | None = None) -> str:
        if kind not in WORKSPACE_NODE_KINDS:
            raise ValueError(f"unsupported conversation node kind {kind!r}")
        if status not in NODE_STATUSES:
            raise ValueError(f"unsupported node status {status!r}")
        node_id = _clean_id(node_id, "node id") if node_id else _id("msg" if kind == "message" else kind)
        now = _now()
        self._conn.execute(
            """INSERT INTO workspace_nodes
               (node_id,endeavor_id,session,parent_id,ordinal,kind,role,label,
                status,input_text,output_text,config_json,workflow_instance_id,
                run_id,position_x,position_y,revision,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (node_id, endeavor_id, session, parent_id,
             ordinal if ordinal is not None else self._next_ordinal(session),
             kind, role, _clean_text(label, "label", limit=160), status,
             _clean_text(input_text, "input"), _clean_text(output_text, "output"),
             _json(dict(config or {})), workflow_instance_id, run_id,
             None, None, 1, now, now),
        )
        return node_id

    def _insert_edge(self, endeavor_id: str, session: str, source_id: str,
                     target_id: str, *, kind: str = "depends_on",
                     label: str = "continues") -> str:
        source_id = _clean_id(source_id, "source node")
        target_id = _clean_id(target_id, "target node")
        if source_id == target_id:
            raise ValueError("a node cannot depend on itself")
        edge_id = _id("edge")
        self._conn.execute(
            """INSERT OR IGNORE INTO workspace_edges
               (edge_id,endeavor_id,session,source_id,target_id,kind,label,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (edge_id, endeavor_id, session, source_id, target_id,
             _clean_text(kind, "edge kind", limit=60),
             _clean_text(label, "edge label", limit=120), _now()),
        )
        return edge_id

    def latest_node(self, session: str) -> dict[str, Any] | None:
        session = _clean_id(session, "conversation id")
        row = self._conn.execute(
            "SELECT node_id FROM workspace_nodes WHERE session=? ORDER BY ordinal DESC LIMIT 1",
            (session,),
        ).fetchone()
        return self.node(row[0]) if row else None

    def create_message_pair(self, session: str, content: str, *,
                            parent_id: str | None = None,
                            flow_id: str = "supervised_tool_turn",
                            flow_decision: Mapping[str, Any] | None = None,
                            completed_output: str | None = None,
                            task_id: str | None = None) -> dict[str, Any]:
        conversation = self.conversation(session)
        endeavor_id = conversation["endeavor_id"]
        content = _clean_text(content, "message").strip()
        if not content:
            raise ValueError("message cannot be empty")
        if parent_id:
            parent = self.node(parent_id)
            if parent["session"] != session:
                raise ValueError("parent belongs to another conversation")
        else:
            latest = self.latest_node(session)
            parent_id = latest["node_id"] if latest else None
        with self._lock:
            user_id = self._insert_node(
                endeavor_id=endeavor_id, session=session, parent_id=parent_id,
                kind="message", role="user", label="You", status="complete",
                input_text=content, output_text=content,
                config={"output_inherited": True},
            )
            if parent_id:
                self._insert_edge(endeavor_id, session, parent_id, user_id,
                                  label="next message")
            assistant_id = self._insert_node(
                endeavor_id=endeavor_id, session=session, parent_id=user_id,
                kind="message", role="assistant", label="Assistant",
                status="complete" if completed_output is not None else "queued",
                input_text=content, output_text=completed_output or "",
                config={
                    "input_inherited": True, "task_id": task_id or "",
                    **({"flow_decision": dict(flow_decision)} if flow_decision else {}),
                },
            )
            self._insert_edge(endeavor_id, session, user_id, assistant_id,
                              label="responds")
            instance_id = self.create_workflow_instance(
                assistant_id, flow_id=flow_id, commit=False
            )
            self._conn.execute(
                "UPDATE workspace_nodes SET workflow_instance_id=? WHERE node_id=?",
                (instance_id, assistant_id),
            )
            now = _now()
            self._conn.execute(
                "UPDATE workspace_conversations SET updated_at=? WHERE session=?",
                (now, session),
            )
            self._conn.execute(
                "UPDATE workspace_endeavors SET updated_at=? WHERE id=?",
                (now, endeavor_id),
            )
            self._conn.commit()
        return {
            "user": self.node(user_id),
            "assistant": self.node(assistant_id),
            "workflow": self.workflow(instance_id),
        }

    def add_node(self, session: str, *, kind: str, label: str, input_text: str,
                 parent_id: str | None = None, target_id: str | None = None,
                 config: Mapping[str, Any] | None = None) -> dict[str, Any]:
        conversation = self.conversation(session)
        if kind not in WORKSPACE_NODE_KINDS - {"message"}:
            raise ValueError("use the message endpoint for message nodes")
        if parent_id:
            parent = self.node(parent_id)
            if parent["session"] != session:
                raise ValueError("parent belongs to another conversation")
        with self._lock:
            node_id = self._insert_node(
                endeavor_id=conversation["endeavor_id"], session=session,
                parent_id=parent_id, kind=kind,
                role="system" if kind in {"context", "store_read"} else "tool",
                label=label, status="complete" if kind == "context" else "draft",
                input_text=input_text,
                output_text=input_text if kind == "context" else "",
                config=config,
            )
            if parent_id:
                if target_id:
                    self._conn.execute(
                        "DELETE FROM workspace_edges WHERE source_id=? AND target_id=?",
                        (parent_id, target_id),
                    )
                self._insert_edge(conversation["endeavor_id"], session,
                                  parent_id, node_id, label="provides context")
            if target_id:
                target = self.node(target_id)
                if target["session"] != session:
                    raise ValueError("target belongs to another conversation")
                self._insert_edge(conversation["endeavor_id"], session,
                                  node_id, target_id, label="affects")
            self._conn.commit()
        return self.node(node_id)

    def node(self, node_id: str) -> dict[str, Any]:
        node_id = _clean_id(node_id, "node id")
        cur = self._conn.execute(
            """SELECT node_id,endeavor_id,session,parent_id,ordinal,kind,role,
                      label,status,input_text,output_text,config_json,
                      workflow_instance_id,run_id,position_x,position_y,revision,
                      created_at,updated_at FROM workspace_nodes WHERE node_id=?""",
            (node_id,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(node_id)
        item = dict(zip([column[0] for column in cur.description], row))
        item["config"] = _load(item.pop("config_json"), {})
        return item

    def nodes(self, session: str) -> list[dict[str, Any]]:
        session = _clean_id(session, "conversation id")
        rows = self._conn.execute(
            "SELECT node_id FROM workspace_nodes WHERE session=? ORDER BY ordinal,node_id",
            (session,),
        ).fetchall()
        return [self.node(row[0]) for row in rows]

    def edges(self, session: str) -> list[dict[str, Any]]:
        session = _clean_id(session, "conversation id")
        cur = self._conn.execute(
            """SELECT edge_id,endeavor_id,session,source_id,target_id,kind,label,created_at
                 FROM workspace_edges WHERE session=? ORDER BY created_at,edge_id""",
            (session,),
        )
        cols = [column[0] for column in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def add_edge(self, session: str, source_id: str, target_id: str, *,
                 kind: str = "feeds", label: str = "feeds") -> dict[str, Any]:
        """Wire one node's output into another as an explicit input.

        Only ``feeds`` edges may be user-created: structural lineage stays
        owned by the message endpoints.  The wire is a real dependency, so
        the target and its dependents are invalidated for recalculation.
        """
        conversation = self.conversation(session)
        if kind != "feeds":
            raise ValueError("only explicit 'feeds' wires can be added directly")
        source = self.node(source_id)
        target = self.node(target_id)
        if source["session"] != session or target["session"] != session:
            raise ValueError("both nodes must belong to this conversation")
        if source["node_id"] == target["node_id"]:
            raise ValueError("a node cannot feed itself")
        if source["node_id"] in self.descendants(target["node_id"]):
            raise ValueError("this wire would create a dependency cycle")
        duplicate = self._conn.execute(
            "SELECT 1 FROM workspace_edges WHERE source_id=? AND target_id=?",
            (source["node_id"], target["node_id"]),
        ).fetchone()
        if duplicate:
            raise ValueError("these nodes are already connected")
        with self._lock:
            edge_id = self._insert_edge(
                conversation["endeavor_id"], session, source["node_id"],
                target["node_id"], kind="feeds",
                label=label.strip() or "feeds",
            )
            self._conn.commit()
        if target["role"] == "assistant" and target["status"] not in {"running", "queued"}:
            self.set_node_status(target["node_id"], "stale")
        self.invalidate_descendants(target["node_id"])
        return {
            "edge_id": edge_id, "session": session,
            "source_id": source["node_id"], "target_id": target["node_id"],
            "kind": "feeds", "label": label.strip() or "feeds",
        }

    def delete_edge(self, edge_id: str) -> dict[str, Any]:
        edge_id = _clean_id(edge_id, "edge id")
        row = self._conn.execute(
            "SELECT edge_id,session,source_id,target_id,kind FROM workspace_edges WHERE edge_id=?",
            (edge_id,),
        ).fetchone()
        if not row:
            raise KeyError(edge_id)
        if row[4] != "feeds":
            raise ValueError("only explicit 'feeds' wires can be removed")
        with self._lock:
            self._conn.execute(
                "DELETE FROM workspace_edges WHERE edge_id=?", (edge_id,)
            )
            self._conn.commit()
        target = self.node(row[3])
        if target["role"] == "assistant" and target["status"] not in {"running", "queued"}:
            self.set_node_status(target["node_id"], "stale")
        self.invalidate_descendants(target["node_id"])
        return {
            "deleted": edge_id, "session": row[1],
            "source_id": row[2], "target_id": row[3],
        }

    def descendants(self, node_id: str) -> list[str]:
        node_id = _clean_id(node_id, "node id")
        rows = self._conn.execute(
            """WITH RECURSIVE downstream(node_id,depth) AS (
                   SELECT target_id,1 FROM workspace_edges WHERE source_id=?
                   UNION
                   SELECT edge.target_id,downstream.depth+1
                     FROM workspace_edges edge JOIN downstream
                       ON edge.source_id=downstream.node_id
                    WHERE downstream.depth < 500
               ) SELECT node_id,MIN(depth) AS depth FROM downstream
                  GROUP BY node_id ORDER BY depth,node_id""",
            (node_id,),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def ancestors(self, node_id: str,
                  *, exclude_kinds: tuple[str, ...] = ()) -> list[str]:
        node_id = _clean_id(node_id, "node id")
        kind_filter = ""
        if exclude_kinds:
            placeholders = ",".join("?" for _ in exclude_kinds)
            kind_filter = f" AND kind NOT IN ({placeholders})"
        rows = self._conn.execute(
            f"""WITH RECURSIVE upstream(node_id,depth) AS (
                   SELECT source_id,1 FROM workspace_edges
                    WHERE target_id=?{kind_filter}
                   UNION
                   SELECT edge.source_id,upstream.depth+1
                     FROM workspace_edges edge JOIN upstream
                       ON edge.target_id=upstream.node_id
                    WHERE upstream.depth < 500{kind_filter.replace('kind', 'edge.kind')}
               ) SELECT node_id,MAX(depth) AS depth FROM upstream
                  GROUP BY node_id ORDER BY depth DESC,node_id""",
            (node_id, *exclude_kinds, *exclude_kinds),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def lineage_ancestors(self, node_id: str) -> list[str]:
        """Prompt lineage: everything upstream via structural edges only.

        A ``feeds`` edge is a selective, non-lineage input — its source is
        injected explicitly and must never pull that source's own ancestry
        into the prompt.
        """
        return self.ancestors(node_id, exclude_kinds=("feeds",))

    def feeds_sources(self, node_id: str) -> list[dict[str, Any]]:
        """Direct explicit-input wires into one node."""
        node_id = _clean_id(node_id, "node id")
        cur = self._conn.execute(
            """SELECT edge_id,source_id,label FROM workspace_edges
                WHERE target_id=? AND kind='feeds' ORDER BY created_at,edge_id""",
            (node_id,),
        )
        return [
            {"edge_id": row[0], "source_id": row[1], "label": row[2]}
            for row in cur.fetchall()
        ]

    def invalidate_descendants(self, node_id: str) -> list[str]:
        descendants = self.descendants(node_id)
        if not descendants:
            return []
        placeholders = ",".join("?" for _ in descendants)
        now = _now()
        with self._lock:
            self._conn.execute(
                f"UPDATE workspace_nodes SET status='stale',updated_at=? "
                f"WHERE node_id IN ({placeholders}) AND status NOT IN ('paused','cancelled')",
                (now, *descendants),
            )
            self._conn.execute(
                f"UPDATE workspace_workflows SET status='stale',active_node=NULL,updated_at=? "
                f"WHERE owner_node_id IN ({placeholders})",
                (now, *descendants),
            )
            self._conn.commit()
        return descendants

    def update_node(self, node_id: str, patch: Mapping[str, Any], *,
                    reason: str = "user edit", invalidate: bool = True) -> dict[str, Any]:
        before = self.node(node_id)
        allowed = {"label", "input_text", "output_text", "config", "position_x", "position_y"}
        unknown = set(patch) - allowed
        if unknown:
            raise ValueError("unsupported node fields: " + ", ".join(sorted(unknown)))
        config = dict(before["config"])
        if "config" in patch:
            if not isinstance(patch["config"], Mapping):
                raise ValueError("config must be an object")
            config.update(dict(patch["config"]))
        if "input_text" in patch and before["role"] == "assistant":
            config["input_inherited"] = False
        input_text = _clean_text(patch.get("input_text", before["input_text"]), "input")
        output_text = _clean_text(patch.get("output_text", before["output_text"]), "output")
        if (before["role"] == "user" and "input_text" in patch
                and before["config"].get("output_inherited")
                and "output_text" not in patch):
            output_text = input_text
        label = _clean_text(patch.get("label", before["label"]), "label", limit=160)
        revision = int(before["revision"]) + 1
        now = _now()
        with self._lock:
            self._conn.execute(
                """INSERT INTO workspace_node_revisions
                   (node_id,revision,input_text,output_text,config_json,reason,edited_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (node_id, before["revision"], before["input_text"], before["output_text"],
                 _json(before["config"]), _clean_text(reason, "reason", limit=200), now),
            )
            self._conn.execute(
                """UPDATE workspace_nodes SET label=?,input_text=?,output_text=?,
                   config_json=?,position_x=?,position_y=?,revision=?,status=?,updated_at=?
                   WHERE node_id=?""",
                (label, input_text, output_text, _json(config),
                 patch.get("position_x", before["position_x"]),
                 patch.get("position_y", before["position_y"]), revision,
                 "complete" if before["status"] == "stale" and before["role"] != "assistant"
                 else before["status"], now, node_id),
            )
            self._conn.commit()
        stale = self.invalidate_descendants(node_id) if invalidate else []
        item = self.node(node_id)
        item["invalidated_node_ids"] = stale
        return item

    def set_node_status(self, node_id: str, status: str, *,
                        output_text: str | None = None,
                        run_id: str | None = None,
                        config_patch: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if status not in NODE_STATUSES:
            raise ValueError(f"unsupported node status {status!r}")
        node = self.node(node_id)
        config = dict(node["config"])
        config.update(dict(config_patch or {}))
        with self._lock:
            self._conn.execute(
                """UPDATE workspace_nodes SET status=?,output_text=?,run_id=?,
                   config_json=?,updated_at=? WHERE node_id=?""",
                (status,
                 _clean_text(output_text, "output") if output_text is not None else node["output_text"],
                 run_id if run_id is not None else node["run_id"],
                 _json(config), _now(), node_id),
            )
            self._conn.commit()
        return self.node(node_id)

    def set_position(self, node_id: str, x: float | None, y: float | None) -> None:
        node_id = _clean_id(node_id, "node id")
        with self._lock:
            self._conn.execute(
                "UPDATE workspace_nodes SET position_x=?,position_y=?,updated_at=? WHERE node_id=?",
                (float(x) if x is not None else None,
                 float(y) if y is not None else None, _now(), node_id),
            )
            self._conn.commit()

    def revisions(self, node_id: str) -> list[dict[str, Any]]:
        node_id = _clean_id(node_id, "node id")
        cur = self._conn.execute(
            """SELECT revision,input_text,output_text,config_json,reason,edited_at
                 FROM workspace_node_revisions WHERE node_id=? ORDER BY revision DESC""",
            (node_id,),
        )
        cols = [column[0] for column in cur.description]
        out = []
        for row in cur.fetchall():
            item = dict(zip(cols, row))
            item["config"] = _load(item.pop("config_json"), {})
            out.append(item)
        return out

    def prompt_messages(self, assistant_node_id: str) -> list[dict[str, str]]:
        node = self.node(assistant_node_id)
        if node["role"] != "assistant":
            raise ValueError("prompt messages are only defined for assistant nodes")
        ids = self.lineage_ancestors(assistant_node_id)
        nodes = sorted((self.node(value) for value in ids), key=lambda item: item["ordinal"])
        messages: list[dict[str, str]] = []
        for item in nodes:
            if item["kind"] == "context":
                text = item["output_text"] or item["input_text"]
                if text:
                    messages.append({"role": "system", "content": text})
            elif item["kind"] == "message" and item["role"] in {"user", "assistant"}:
                text = item["output_text"] or item["input_text"]
                if text:
                    messages.append({"role": item["role"], "content": text})
        if not node["config"].get("input_inherited", True) and node["input_text"]:
            if messages and messages[-1]["role"] == "user":
                messages[-1] = {"role": "user", "content": node["input_text"]}
            else:
                messages.append({"role": "user", "content": node["input_text"]})
        # Explicitly wired inputs: the wired node's output enters the prompt
        # even though (and only because) it is outside the lineage.  Wires
        # into the paired user message count as wires into this turn.
        edges = self.feeds_sources(assistant_node_id)
        if node["parent_id"]:
            edges += self.feeds_sources(node["parent_id"])
        lineage = set(ids)
        feeds: list[dict[str, str]] = []
        seen_sources: set[str] = set()
        for edge in edges:
            source_id = edge["source_id"]
            if source_id in seen_sources or source_id in lineage:
                continue
            seen_sources.add(source_id)
            source = self.node(source_id)
            text = source["output_text"] or source["input_text"]
            if text:
                feeds.append({
                    "role": "system",
                    "content": (
                        f"Explicitly wired input from \"{source['label']}\" "
                        f"({source_id}):\n{text}"
                    ),
                })
        if feeds:
            insert_at = len(messages)
            for index in range(len(messages) - 1, -1, -1):
                if messages[index]["role"] == "user":
                    insert_at = index
                    break
            messages[insert_at:insert_at] = feeds
        return messages

    def graph(self, session: str) -> dict[str, Any]:
        conversation = self.conversation(session)
        endeavor = self.endeavor(conversation["endeavor_id"])
        nodes = self.nodes(session)
        instance_ids = [node["workflow_instance_id"] for node in nodes
                        if node.get("workflow_instance_id")]
        workflows = [self.workflow(value) for value in instance_ids]
        jobs = self.jobs(session=session)
        return {
            "endeavor": endeavor,
            "conversation": conversation,
            "nodes": nodes,
            "edges": self.edges(session),
            "workflows": workflows,
            "jobs": jobs,
            "stores": self.stores(),
        }

    # ------------------------------------------------------------------
    # Per-message workflow instances

    def _base_workflow_graph(self, flow_id: str) -> dict[str, Any]:
        flow_id = _clean_id(flow_id, "flow id")
        override = self._conn.execute(
            "SELECT graph_json FROM workspace_workflow_overrides WHERE flow_id=?",
            (flow_id,),
        ).fetchone()
        if override:
            return _load(override[0], {})
        if flow_id not in self.registry.flows:
            raise KeyError(flow_id)
        graph = self.registry.flows[flow_id].as_dict()
        graph["nodes"] = [
            {**node, "runtime_status": "idle"}
            for node in graph.get("nodes", [])
        ]
        graph["instance_schema"] = 1
        return graph

    def create_workflow_instance(self, owner_node_id: str, *,
                                 flow_id: str = "supervised_tool_turn",
                                 commit: bool = True) -> str:
        graph = self._base_workflow_graph(flow_id)
        flow = self.registry.flows.get(flow_id)
        version = flow.version if flow else int(graph.get("version", 1))
        instance_id = _id("wf")
        now = _now()
        self._conn.execute(
            """INSERT INTO workspace_workflows
               (instance_id,owner_node_id,flow_id,base_version,revision,graph_json,
                active_node,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (instance_id, owner_node_id, flow_id, version, 1, _json(graph),
             None, "idle", now, now),
        )
        if commit:
            self._conn.commit()
        return instance_id

    def retarget_workflow(self, instance_id: str, flow_id: str) -> dict[str, Any]:
        """Point one message's workflow instance at a different declared flow.

        Used when send-time flow matching refines the pre-send prediction.
        Only registered flows (or their global overrides) are reachable here;
        arbitrary graphs go through ``apply_synthesized_workflow``.
        """
        current = self.workflow(instance_id)
        if current["flow_id"] == flow_id:
            return current
        graph = self._base_workflow_graph(flow_id)
        flow = self.registry.flows.get(flow_id)
        version = flow.version if flow else int(graph.get("version", 1))
        with self._lock:
            self._conn.execute(
                """UPDATE workspace_workflows SET flow_id=?,base_version=?,
                   revision=revision+1,graph_json=?,active_node=NULL,
                   status='idle',updated_at=? WHERE instance_id=?""",
                (flow_id, version, _json(graph), _now(), instance_id),
            )
            self._conn.commit()
        return self.workflow(instance_id)

    def apply_synthesized_workflow(self, instance_id: str,
                                   graph: Mapping[str, Any]) -> dict[str, Any]:
        """Install a validated synthesized graph as this instance's route.

        The synthesized graph lives only in this message's instance row; the
        declared registry is never modified.
        """
        current = self.workflow(instance_id)
        clean = self.validate_workflow_graph(graph)
        clean["synthesized"] = True
        flow_id = _clean_id(str(graph.get("id") or "synthesized"), "flow id")
        version = int(graph.get("version", 1) or 1)
        with self._lock:
            self._conn.execute(
                """UPDATE workspace_workflows SET flow_id=?,base_version=?,
                   revision=?,graph_json=?,active_node=NULL,status='idle',
                   updated_at=? WHERE instance_id=?""",
                (flow_id, version, int(current["revision"]) + 1, _json(clean),
                 _now(), instance_id),
            )
            self._conn.commit()
        return self.workflow(instance_id)

    def workflow(self, instance_id: str) -> dict[str, Any]:
        instance_id = _clean_id(instance_id, "workflow instance id")
        cur = self._conn.execute(
            """SELECT instance_id,owner_node_id,flow_id,base_version,revision,
                      graph_json,active_node,status,created_at,updated_at
                 FROM workspace_workflows WHERE instance_id=?""",
            (instance_id,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(instance_id)
        item = dict(zip([column[0] for column in cur.description], row))
        item["graph"] = _load(item.pop("graph_json"), {})
        return item

    @staticmethod
    def validate_workflow_graph(graph: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(graph, Mapping):
            raise ValueError("workflow graph must be an object")
        clean = dict(graph)
        raw_nodes = clean.get("nodes")
        raw_edges = clean.get("edges")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise ValueError("workflow graph requires nodes")
        if not isinstance(raw_edges, list):
            raise ValueError("workflow graph edges must be a list")
        seen: set[str] = set()
        nodes: list[dict[str, Any]] = []
        for raw in raw_nodes:
            if not isinstance(raw, Mapping):
                raise ValueError("workflow node must be an object")
            node = dict(raw)
            node_id = _clean_id(str(node.get("id", "")), "workflow node id")
            if node_id in seen:
                raise ValueError(f"duplicate workflow node {node_id!r}")
            seen.add(node_id)
            node_type = str(node.get("type", ""))
            if node_type not in WORKFLOW_NODE_TYPES:
                raise ValueError(f"unsupported workflow node type {node_type!r}")
            node["id"] = node_id
            node["label"] = _clean_text(node.get("label", node_id), "label", limit=160)
            node["description"] = _clean_text(node.get("description", ""), "description", limit=2000)
            node["config"] = dict(node.get("config") or {})
            node["runtime_status"] = str(node.get("runtime_status", "idle"))
            nodes.append(node)
        entry = _clean_id(str(clean.get("entry", "")), "workflow entry")
        if entry not in seen:
            raise ValueError("workflow entry is not a node")
        edges: list[dict[str, Any]] = []
        edge_seen: set[tuple[str, str, str]] = set()
        for raw in raw_edges:
            if not isinstance(raw, Mapping):
                raise ValueError("workflow edge must be an object")
            edge = dict(raw)
            source = _clean_id(str(edge.get("source", "")), "edge source")
            target = _clean_id(str(edge.get("target", "")), "edge target")
            if source not in seen or target not in seen:
                raise ValueError("workflow edge references an unknown node")
            key = (source, target, str(edge.get("condition", "")))
            if key in edge_seen:
                raise ValueError("duplicate workflow edge")
            edge_seen.add(key)
            edge["source"], edge["target"] = source, target
            edge["label"] = _clean_text(edge.get("label", ""), "edge label", limit=120)
            edge["condition"] = _clean_text(edge.get("condition", ""), "edge condition", limit=500)
            edge["loop"] = bool(edge.get("loop", False))
            edges.append(edge)
        clean["entry"] = entry
        clean["nodes"] = nodes
        clean["edges"] = edges
        clean["instance_schema"] = 1
        return clean

    def save_workflow(self, instance_id: str, graph: Mapping[str, Any], *,
                      apply_globally: bool = False) -> dict[str, Any]:
        current = self.workflow(instance_id)
        clean = self.validate_workflow_graph(graph)
        now = _now()
        revision = int(current["revision"]) + 1
        updated_instances = 1
        with self._lock:
            self._conn.execute(
                """UPDATE workspace_workflows SET graph_json=?,revision=?,
                   active_node=NULL,status='idle',updated_at=? WHERE instance_id=?""",
                (_json(clean), revision, now, instance_id),
            )
            if apply_globally:
                row = self._conn.execute(
                    "SELECT revision FROM workspace_workflow_overrides WHERE flow_id=?",
                    (current["flow_id"],),
                ).fetchone()
                global_revision = int(row[0]) + 1 if row else 1
                self._conn.execute(
                    """INSERT INTO workspace_workflow_overrides
                       (flow_id,revision,graph_json,updated_at) VALUES (?,?,?,?)
                       ON CONFLICT(flow_id) DO UPDATE SET revision=excluded.revision,
                       graph_json=excluded.graph_json,updated_at=excluded.updated_at""",
                    (current["flow_id"], global_revision, _json(clean), now),
                )
                cursor = self._conn.execute(
                    """UPDATE workspace_workflows SET graph_json=?,revision=revision+1,
                       active_node=NULL,status='idle',updated_at=?
                       WHERE flow_id=? AND instance_id<>? AND owner_node_id NOT IN
                         (SELECT node_id FROM workspace_nodes WHERE status='running')""",
                    (_json(clean), now, current["flow_id"], instance_id),
                )
                updated_instances += max(0, cursor.rowcount)
            self._conn.commit()
        result = self.workflow(instance_id)
        result["apply_scope"] = "global" if apply_globally else "instance"
        result["updated_instances"] = updated_instances
        return result

    def add_workflow_node(self, instance_id: str, *, node_type: str, label: str,
                          after_node_id: str, config: Mapping[str, Any] | None = None,
                          apply_globally: bool = False) -> dict[str, Any]:
        workflow = self.workflow(instance_id)
        graph = workflow["graph"]
        if node_type not in WORKFLOW_NODE_TYPES:
            raise ValueError(f"unsupported workflow node type {node_type!r}")
        if not any(node["id"] == after_node_id for node in graph["nodes"]):
            raise KeyError(after_node_id)
        node_id = _id(node_type).replace("-", "_")
        agent_id = {
            "ensemble": "ensemble_coordinator",
            "verifier": "verifier",
        }.get(node_type, "")
        agent = self.registry.agents.get(agent_id) if agent_id else None
        node = {
            "id": node_id,
            "label": _clean_text(label, "label", limit=160) or node_type.replace("_", " ").title(),
            "type": node_type,
            "description": "User-defined workflow instance node",
            "agent": agent_id,
            "capabilities": list(agent.capabilities) if agent else [],
            "config": dict(config or {}),
            "runtime_status": "idle",
        }
        outgoing = [edge for edge in graph["edges"] if edge["source"] == after_node_id
                    and not edge.get("loop")]
        graph["edges"] = [edge for edge in graph["edges"] if edge not in outgoing]
        graph["nodes"].append(node)
        graph["edges"].append({
            "source": after_node_id, "target": node_id,
            "label": "continue", "condition": "", "loop": False,
        })
        for edge in outgoing:
            graph["edges"].append({**edge, "source": node_id})
        saved = self.save_workflow(instance_id, graph, apply_globally=apply_globally)
        saved["added_node_id"] = node_id
        return saved

    def update_workflow_node(self, instance_id: str, node_id: str,
                             patch: Mapping[str, Any], *,
                             apply_globally: bool = False) -> dict[str, Any]:
        workflow = self.workflow(instance_id)
        graph = workflow["graph"]
        target = next((node for node in graph["nodes"] if node["id"] == node_id), None)
        if not target:
            raise KeyError(node_id)
        allowed = {"label", "description", "config"}
        if set(patch) - allowed:
            raise ValueError("workflow node id and type are immutable")
        if "label" in patch:
            target["label"] = _clean_text(patch["label"], "label", limit=160)
        if "description" in patch:
            target["description"] = _clean_text(patch["description"], "description", limit=2000)
        if "config" in patch:
            if not isinstance(patch["config"], Mapping):
                raise ValueError("config must be an object")
            target["config"] = dict(patch["config"])
        return self.save_workflow(instance_id, graph, apply_globally=apply_globally)

    def delete_workflow_node(self, instance_id: str, node_id: str, *,
                             apply_globally: bool = False) -> dict[str, Any]:
        workflow = self.workflow(instance_id)
        graph = workflow["graph"]
        if graph["entry"] == node_id:
            raise ValueError("the workflow entry node cannot be deleted")
        target = next((node for node in graph["nodes"] if node["id"] == node_id), None)
        if not target:
            raise KeyError(node_id)
        incoming = [edge for edge in graph["edges"] if edge["target"] == node_id and not edge.get("loop")]
        outgoing = [edge for edge in graph["edges"] if edge["source"] == node_id and not edge.get("loop")]
        graph["nodes"] = [node for node in graph["nodes"] if node["id"] != node_id]
        graph["edges"] = [edge for edge in graph["edges"]
                          if edge["source"] != node_id and edge["target"] != node_id]
        for before in incoming:
            for after in outgoing:
                graph["edges"].append({
                    "source": before["source"], "target": after["target"],
                    "label": after.get("label") or before.get("label") or "continue",
                    "condition": after.get("condition", ""), "loop": False,
                })
        return self.save_workflow(instance_id, graph, apply_globally=apply_globally)

    def set_workflow_runtime(self, instance_id: str, *, status: str,
                             active_node: str | None = None,
                             node_status: str | None = None) -> dict[str, Any]:
        workflow = self.workflow(instance_id)
        graph = workflow["graph"]
        if active_node and not any(node["id"] == active_node for node in graph["nodes"]):
            active_node = None
        if node_status and active_node:
            for node in graph["nodes"]:
                if node["id"] == active_node:
                    node["runtime_status"] = node_status
        with self._lock:
            self._conn.execute(
                """UPDATE workspace_workflows SET graph_json=?,active_node=?,status=?,
                   updated_at=? WHERE instance_id=?""",
                (_json(graph), active_node, status, _now(), instance_id),
            )
            self._conn.commit()
        return self.workflow(instance_id)

    def workflow_plan(self, instance_id: str) -> dict[str, Any]:
        graph = self.workflow(instance_id)["graph"]
        enabled = [node for node in graph["nodes"]
                   if (node.get("config") or {}).get("enabled", True)]
        ensemble = next((node for node in enabled if node["type"] == "ensemble"), None)
        human = next((node for node in enabled if node["type"] == "human_input"
                      and (node.get("config") or {}).get("required", True)
                      and not (node.get("config") or {}).get("satisfied", False)), None)
        executor_prompts = [
            str((node.get("config") or {}).get("prompt", "")).strip()
            for node in enabled if node["type"] in {"agent", "context"}
            and str((node.get("config") or {}).get("prompt", "")).strip()
        ]
        verification_prompts = [
            str((node.get("config") or {}).get("prompt", "")).strip()
            for node in enabled if node["type"] in {"policy", "critic", "probe", "checker", "verifier", "postcheck"}
            and str((node.get("config") or {}).get("prompt", "")).strip()
        ]
        return {
            "ensemble": dict(ensemble.get("config") or {}) if ensemble else None,
            "ensemble_node_id": ensemble["id"] if ensemble else None,
            "human_input_node_id": human["id"] if human else None,
            "executor_prompts": executor_prompts,
            "verification_prompts": verification_prompts,
            "store_reads": [node for node in enabled if node["type"] == "store_read"],
            "store_writes": [node for node in enabled if node["type"] == "store_write"],
        }

    # ------------------------------------------------------------------
    # Execution/recalculation jobs

    def create_job(self, session: str, root_node_id: str, kind: str) -> dict[str, Any]:
        session = _clean_id(session, "conversation id")
        root_node_id = _clean_id(root_node_id, "root node id")
        job_id = _id("work")
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO workspace_jobs VALUES (?,?,?,?,?,?,?,?,?)",
                (job_id, session, root_node_id, _clean_text(kind, "job kind", limit=60),
                 "queued", _json({"completed": 0, "total": 0}), "", now, now),
            )
            self._conn.commit()
        return self.job(job_id)

    def update_job(self, job_id: str, *, status: str | None = None,
                   progress: Mapping[str, Any] | None = None,
                   error: str | None = None) -> dict[str, Any]:
        job = self.job(job_id)
        with self._lock:
            self._conn.execute(
                """UPDATE workspace_jobs SET status=?,progress_json=?,error=?,updated_at=?
                   WHERE job_id=?""",
                (status or job["status"], _json(progress if progress is not None else job["progress"]),
                 _clean_text(error if error is not None else job["error"], "job error", limit=4000),
                 _now(), job_id),
            )
            self._conn.commit()
        return self.job(job_id)

    def job(self, job_id: str) -> dict[str, Any]:
        job_id = _clean_id(job_id, "job id")
        cur = self._conn.execute(
            """SELECT job_id,session,root_node_id,kind,status,progress_json,error,
                      created_at,updated_at FROM workspace_jobs WHERE job_id=?""",
            (job_id,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(job_id)
        item = dict(zip([column[0] for column in cur.description], row))
        item["progress"] = _load(item.pop("progress_json"), {})
        return item

    def jobs(self, *, session: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = "SELECT job_id FROM workspace_jobs"
        args: list[Any] = []
        if session:
            query += " WHERE session=?"
            args.append(_clean_id(session, "conversation id"))
        query += " ORDER BY updated_at DESC LIMIT ?"
        args.append(max(1, min(int(limit), 200)))
        return [self.job(row[0]) for row in self._conn.execute(query, args).fetchall()]

    # ------------------------------------------------------------------
    # Backend-neutral knowledge stores

    def create_store(self, name: str, *, description: str = "",
                     adapter: str = "sqlite-vector",
                     connection_ref: str = "local") -> dict[str, Any]:
        adapter = str(adapter or "sqlite-vector")
        if adapter not in {"sqlite-vector", "external-vector"}:
            raise ValueError("unsupported store adapter")
        store_id = _id("store")
        now = _now()
        status = "ready" if adapter == "sqlite-vector" else "operator_setup_required"
        with self._lock:
            self._conn.execute(
                "INSERT INTO workspace_stores VALUES (?,?,?,?,?,?,?,?)",
                (store_id, _clean_text(name, "store name", limit=120).strip() or "Knowledge store",
                 _clean_text(description, "store description", limit=1000), adapter,
                 _clean_text(connection_ref, "connection reference", limit=200),
                 status, now, now),
            )
            self._conn.commit()
        return self.store(store_id)

    def store(self, store_id: str) -> dict[str, Any]:
        store_id = _clean_id(store_id, "store id")
        cur = self._conn.execute(
            """SELECT store_id,name,description,adapter,connection_ref,status,
                      created_at,updated_at FROM workspace_stores WHERE store_id=?""",
            (store_id,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(store_id)
        item = dict(zip([column[0] for column in cur.description], row))
        item["record_count"] = int(self._conn.execute(
            "SELECT COUNT(*) FROM workspace_store_records WHERE store_id=?",
            (store_id,),
        ).fetchone()[0])
        return item

    def stores(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT store_id FROM workspace_stores ORDER BY updated_at DESC"
        ).fetchall()
        return [self.store(row[0]) for row in rows]

    def save_record(self, store_id: str, text: str, *,
                    source_node_id: str | None = None,
                    metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
        store = self.store(store_id)
        if store["adapter"] != "sqlite-vector":
            raise ValueError("external store requires operator adapter setup")
        text = _clean_text(text, "record text")
        if not text.strip():
            raise ValueError("record text cannot be empty")
        record_id = _id("record")
        created_at = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO workspace_store_records VALUES (?,?,?,?,?,?,?)",
                (record_id, store_id, source_node_id, text,
                 _json(dict(metadata or {})), _json(_vector(text)), created_at),
            )
            self._conn.execute(
                "UPDATE workspace_stores SET updated_at=? WHERE store_id=?",
                (created_at, store_id),
            )
            self._conn.commit()
        return {
            "record_id": record_id, "store_id": store_id,
            "source_node_id": source_node_id, "text": text,
            "metadata": dict(metadata or {}), "created_at": created_at,
        }

    def query_store(self, store_id: str, query: str, *, top_k: int = 5,
                    query_prompt: str = "") -> list[dict[str, Any]]:
        store = self.store(store_id)
        if store["adapter"] != "sqlite-vector":
            raise ValueError("external store requires operator adapter setup")
        query = _clean_text(query, "store query", limit=20_000)
        query_prompt = _clean_text(query_prompt, "query prompt", limit=10_000)
        qvec = _vector((query_prompt + "\n" + query).strip())
        cur = self._conn.execute(
            """SELECT record_id,source_node_id,text,metadata_json,vector_json,created_at
                 FROM workspace_store_records WHERE store_id=?
                 ORDER BY created_at DESC LIMIT 2000""",
            (store_id,),
        )
        out = []
        for record_id, source, text, metadata, vector, created_at in cur.fetchall():
            out.append({
                "record_id": record_id, "source_node_id": source, "text": text,
                "metadata": _load(metadata, {}), "created_at": created_at,
                "score": round(_cosine(qvec, _load(vector, [])), 6),
            })
        out.sort(key=lambda item: (item["score"], item["created_at"]), reverse=True)
        return out[:max(1, min(int(top_k), 20))]

    # ------------------------------------------------------------------
    # Existing trace import

    def import_trace_conversation(self, endeavor_id: str, endeavor_title: str,
                                  session: str, conversation_title: str,
                                  exchanges: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        """Idempotently project one existing trace conversation into the UI."""
        try:
            self.endeavor(endeavor_id)
        except KeyError:
            self.create_endeavor(endeavor_title, endeavor_id=endeavor_id, status="historical")
        try:
            self.conversation(session)
        except KeyError:
            self.create_conversation(endeavor_id, conversation_title, session=session,
                                     status="historical")
        if self.latest_node(session):
            return self.graph(session)
        by_task: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for exchange in exchanges:
            task = str(exchange.get("task") or "-")
            if task not in by_task:
                by_task[task] = {}
                order.append(task)
            by_task[task][str(exchange.get("kind") or "")] = exchange.get("payload")
        for task in order:
            request = by_task[task].get("client_request") or {}
            response = by_task[task].get("client_response") or {}
            messages = request.get("messages") if isinstance(request, Mapping) else []
            user_text = ""
            for message in reversed(messages or []):
                if isinstance(message, Mapping) and message.get("role") == "user":
                    user_text = str(message.get("content") or "")
                    break
            if not user_text:
                continue
            output = ""
            if isinstance(response, Mapping):
                output = str(response.get("text") or "")
                if not output:
                    choices = response.get("choices") or []
                    if choices and isinstance(choices[0], Mapping):
                        output = str((choices[0].get("message") or {}).get("content") or "")
            self.create_message_pair(
                session, user_text, completed_output=output,
                task_id=task,
            )
        return self.graph(session)
