"""Declarative agent graphs and a small durable runtime contract.

The runtime deliberately owns graph mechanics, not product policy.  Risk
classification, evidence interpretation, model-family selection, and OpenAI
compatibility remain conflux concerns.  This module gives those concerns a
validated, inspectable state machine and a framework-neutral event ledger.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml


NODE_TYPES = {
    "ingress", "agent", "policy", "critic", "probe", "approval", "tool",
    "postcheck", "checker", "verifier", "router", "checkpoint", "terminal",
    "ensemble", "context", "store_read", "store_write", "human_input",
}
TERMINAL_TYPES = {"terminal"}


@dataclass(frozen=True)
class AgentSpec:
    id: str
    label: str
    role: str
    description: str
    model_selector: str = ""
    family_rule: str = ""
    capabilities: tuple[str, ...] = ()
    accent: str = "slate"
    icon: str = "agent"


@dataclass(frozen=True)
class NodeSpec:
    id: str
    label: str
    type: str
    description: str = ""
    agent: str = ""
    capabilities: tuple[str, ...] = ()
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EdgeSpec:
    source: str
    target: str
    label: str = ""
    condition: str = ""
    loop: bool = False


@dataclass(frozen=True)
class FlowSpec:
    id: str
    version: int
    label: str
    description: str
    entry: str
    nodes: tuple[NodeSpec, ...]
    edges: tuple[EdgeSpec, ...]
    capabilities: tuple[str, ...] = ()
    budgets: dict[str, Any] = field(default_factory=dict)

    @property
    def node_map(self) -> dict[str, NodeSpec]:
        return {node.id: node for node in self.nodes}

    def validate(self, agents: dict[str, AgentSpec]) -> None:
        if not self.id or self.version < 1:
            raise ValueError("flow id is required and version must be positive")
        node_ids = [node.id for node in self.nodes]
        if not node_ids or len(node_ids) != len(set(node_ids)):
            raise ValueError(f"flow {self.id!r} has no nodes or duplicate node ids")
        if self.entry not in set(node_ids):
            raise ValueError(f"flow {self.id!r} entry {self.entry!r} is not a node")
        allowed_caps = set(self.capabilities)
        for node in self.nodes:
            if node.type not in NODE_TYPES:
                raise ValueError(
                    f"flow {self.id!r} node {node.id!r} has unsupported type {node.type!r}"
                )
            if node.agent and node.agent not in agents:
                raise ValueError(
                    f"flow {self.id!r} node {node.id!r} references unknown agent {node.agent!r}"
                )
            undeclared = set(node.capabilities) - allowed_caps
            if undeclared:
                raise ValueError(
                    f"flow {self.id!r} node {node.id!r} requests undeclared capabilities: "
                    + ", ".join(sorted(undeclared))
                )
            if node.agent:
                agent_caps = set(agents[node.agent].capabilities)
                excess = set(node.capabilities) - agent_caps
                if excess:
                    raise ValueError(
                        f"flow {self.id!r} node {node.id!r} exceeds agent capabilities: "
                        + ", ".join(sorted(excess))
                    )
        node_set = set(node_ids)
        seen_edges: set[tuple[str, str, str]] = set()
        for edge in self.edges:
            if edge.source not in node_set or edge.target not in node_set:
                raise ValueError(
                    f"flow {self.id!r} edge {edge.source!r}->{edge.target!r} has unknown node"
                )
            key = (edge.source, edge.target, edge.condition)
            if key in seen_edges:
                raise ValueError(f"flow {self.id!r} has duplicate edge {key!r}")
            seen_edges.add(key)

        # Dynamic loops must be visually and mechanically explicit.  A DFS
        # back-edge is accepted only when that edge is marked as a loop and a
        # hard flow iteration budget exists.
        outgoing: dict[str, list[EdgeSpec]] = {node: [] for node in node_ids}
        for edge in self.edges:
            outgoing[edge.source].append(edge)
        visiting: set[str] = set()
        visited: set[str] = set()

        def walk(node_id: str) -> None:
            visiting.add(node_id)
            for edge in outgoing[node_id]:
                if edge.target in visiting:
                    if not edge.loop or int(self.budgets.get("max_iterations", 0)) < 1:
                        raise ValueError(
                            f"flow {self.id!r} cycle {edge.source!r}->{edge.target!r} "
                            "needs loop: true and max_iterations"
                        )
                    continue
                if edge.target not in visited:
                    walk(edge.target)
            visiting.remove(node_id)
            visited.add(node_id)

        walk(self.entry)
        unreachable = node_set - visited
        if unreachable:
            raise ValueError(
                f"flow {self.id!r} has unreachable nodes: {', '.join(sorted(unreachable))}"
            )
        if not any(node.type in TERMINAL_TYPES for node in self.nodes):
            raise ValueError(f"flow {self.id!r} has no terminal node")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class FlowRegistry:
    def __init__(self, agents: dict[str, AgentSpec], flows: dict[str, FlowSpec],
                 *, source: str = ""):
        self.agents = agents
        self.flows = flows
        self.source = source
        if len(agents) != len(set(agents)) or len(flows) != len(set(flows)):
            raise ValueError("duplicate agent or flow id")
        for flow in flows.values():
            flow.validate(agents)

    @classmethod
    def load(cls, path: str | Path) -> "FlowRegistry":
        source = Path(path)
        raw = yaml.safe_load(source.read_text()) or {}
        agents: dict[str, AgentSpec] = {}
        for item in raw.get("agents", []):
            spec = AgentSpec(
                id=str(item["id"]), label=str(item["label"]),
                role=str(item.get("role", item["id"])),
                description=str(item.get("description", "")),
                model_selector=str(item.get("model_selector", "")),
                family_rule=str(item.get("family_rule", "")),
                capabilities=tuple(item.get("capabilities", ())),
                accent=str(item.get("accent", "slate")),
                icon=str(item.get("icon", "agent")),
            )
            if spec.id in agents:
                raise ValueError(f"duplicate agent id {spec.id!r}")
            agents[spec.id] = spec

        flows: dict[str, FlowSpec] = {}
        for item in raw.get("flows", []):
            nodes = tuple(NodeSpec(
                id=str(node["id"]), label=str(node["label"]),
                type=str(node["type"]), description=str(node.get("description", "")),
                agent=str(node.get("agent", "")),
                capabilities=tuple(node.get("capabilities", ())),
                config=dict(node.get("config", {})),
            ) for node in item.get("nodes", ()))
            edges = tuple(EdgeSpec(
                source=str(edge["source"]), target=str(edge["target"]),
                label=str(edge.get("label", "")),
                condition=str(edge.get("condition", "")),
                loop=bool(edge.get("loop", False)),
            ) for edge in item.get("edges", ()))
            spec = FlowSpec(
                id=str(item["id"]), version=int(item.get("version", 1)),
                label=str(item["label"]), description=str(item.get("description", "")),
                entry=str(item["entry"]), nodes=nodes, edges=edges,
                capabilities=tuple(item.get("capabilities", ())),
                budgets=dict(item.get("budgets", {})),
            )
            if spec.id in flows:
                raise ValueError(f"duplicate flow id {spec.id!r}")
            flows[spec.id] = spec
        return cls(agents, flows, source=str(source))

    def describe(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "agents": [asdict(agent) for agent in self.agents.values()],
            "flows": [flow.as_dict() for flow in self.flows.values()],
        }


class FlowRuntime(Protocol):
    """Small framework boundary proposed by the orchestration evaluation."""

    def compile(self, flow_id: str) -> dict[str, Any]: ...
    def start(self, flow_id: str, input: dict[str, Any], budgets: dict[str, Any],
              capabilities: list[str], **identity: str) -> str: ...
    def stream(self, run_id: str, after: int = 0) -> list[dict[str, Any]]: ...
    def interrupt(self, run_id: str, reason: str) -> None: ...
    def resume(self, run_id: str, input_or_approval: dict[str, Any]) -> None: ...
    def checkpoint(self, run_id: str) -> str: ...
    def inspect(self, run_id: str) -> dict[str, Any]: ...
    def replay(self, run_id: str) -> dict[str, Any]: ...


class SQLiteFlowRuntime:
    """Durable graph/run ledger with strict transition validation.

    This is intentionally a compact reference runtime.  LangGraph or another
    framework can implement the same interface without changing the policy,
    trace vocabulary, API, or graph UI.
    """

    def __init__(self, connection: sqlite3.Connection, registry: FlowRegistry):
        self._conn = connection
        self.registry = registry
        self._lock = threading.RLock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS flow_runs (
                run_id TEXT PRIMARY KEY,
                flow_id TEXT NOT NULL,
                flow_version INTEGER NOT NULL,
                graph_hash TEXT NOT NULL,
                session TEXT NOT NULL,
                task TEXT NOT NULL,
                status TEXT NOT NULL,
                current_node TEXT,
                input_json TEXT NOT NULL,
                state_json TEXT NOT NULL,
                budgets_json TEXT NOT NULL,
                capabilities_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS flow_run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                ts REAL NOT NULL,
                node_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                summary TEXT,
                model TEXT,
                risk TEXT,
                verdict TEXT,
                evidence_json TEXT NOT NULL,
                data_json TEXT NOT NULL,
                cost_usd REAL NOT NULL DEFAULT 0,
                latency_ms REAL NOT NULL DEFAULT 0,
                FOREIGN KEY(run_id) REFERENCES flow_runs(run_id)
            )"""
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_flow_events_run ON flow_run_events(run_id, id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_flow_runs_updated ON flow_runs(updated_at DESC)"
        )
        self._conn.commit()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def compile(self, flow_id: str) -> dict[str, Any]:
        flow = self.registry.flows[flow_id]
        flow.validate(self.registry.agents)
        payload = json.dumps(flow.as_dict(), sort_keys=True, separators=(",", ":"))
        return {
            "flow_id": flow.id,
            "version": flow.version,
            "graph_hash": hashlib.sha256(payload.encode()).hexdigest()[:20],
            "nodes": len(flow.nodes),
            "edges": len(flow.edges),
        }

    def start(self, flow_id: str, input: dict[str, Any], budgets: dict[str, Any],
              capabilities: list[str], **identity: str) -> str:
        compiled = self.compile(flow_id)
        flow = self.registry.flows[flow_id]
        requested = set(capabilities)
        if not requested.issubset(set(flow.capabilities)):
            raise ValueError("run requests capabilities outside the compiled flow")
        run_id = identity.get("run_id") or f"run_{uuid.uuid4().hex[:16]}"
        now = time.time()
        with self._lock:
            self._conn.execute(
                """INSERT INTO flow_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, flow.id, flow.version, compiled["graph_hash"],
                 identity.get("session", "-"), identity.get("task", "-"),
                 "running", None, json.dumps(input, default=str), "{}",
                 json.dumps(budgets, default=str), json.dumps(sorted(requested)),
                 now, now),
            )
            self._conn.commit()
        self.transition(run_id, flow.entry, "flow_started", status="running",
                        summary="Run entered the declared graph")
        return run_id

    def _run_row(self, run_id: str) -> sqlite3.Row | tuple:
        row = self._conn.execute(
            "SELECT flow_id, status, current_node, state_json FROM flow_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if not row:
            raise KeyError(run_id)
        return row

    def transition(self, run_id: str, node_id: str, kind: str, *,
                   status: str = "running", summary: str = "", model: str = "",
                   risk: str = "", verdict: str = "", evidence: list[Any] | None = None,
                   data: dict[str, Any] | None = None, cost_usd: float = 0.0,
                   latency_ms: float = 0.0, allow_jump: bool = False) -> int:
        with self._lock:
            flow_id, run_status, current, state_json = self._run_row(run_id)
            flow = self.registry.flows[flow_id]
            if node_id not in flow.node_map:
                raise ValueError(f"node {node_id!r} is not in flow {flow_id!r}")
            if current and current != node_id and not allow_jump:
                valid = any(edge.source == current and edge.target == node_id
                            for edge in flow.edges)
                if not valid:
                    raise ValueError(
                        f"invalid flow transition {current!r}->{node_id!r} in {flow_id!r}"
                    )
            state = json.loads(state_json or "{}")
            if data:
                state.update(data.get("state_patch", {}))
            now = time.time()
            cur = self._conn.execute(
                """INSERT INTO flow_run_events
                   (run_id,ts,node_id,kind,status,summary,model,risk,verdict,
                    evidence_json,data_json,cost_usd,latency_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, now, node_id, kind, status, summary, model, risk, verdict,
                 json.dumps(evidence or [], default=str),
                 json.dumps(data or {}, default=str), float(cost_usd or 0),
                 float(latency_ms or 0)),
            )
            terminal = flow.node_map[node_id].type in TERMINAL_TYPES
            next_status = "completed" if terminal and status not in {"blocked", "failed"} else status
            self._conn.execute(
                """UPDATE flow_runs SET status=?, current_node=?, state_json=?, updated_at=?
                   WHERE run_id=?""",
                (next_status, node_id, json.dumps(state, default=str), now, run_id),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def stream(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            """SELECT id,ts,node_id,kind,status,summary,model,risk,verdict,
                      evidence_json,data_json,cost_usd,latency_ms
                 FROM flow_run_events WHERE run_id=? AND id>? ORDER BY id""",
            (run_id, int(after)),
        )
        cols = [column[0] for column in cur.description]
        rows = []
        for raw in cur.fetchall():
            item = dict(zip(cols, raw))
            item["evidence"] = json.loads(item.pop("evidence_json"))
            item["data"] = json.loads(item.pop("data_json"))
            rows.append(item)
        return rows

    def interrupt(self, run_id: str, reason: str) -> None:
        flow_id, _, current, _ = self._run_row(run_id)
        node_id = current or self.registry.flows[flow_id].entry
        self.transition(run_id, node_id, "flow_interrupted", status="interrupted",
                        summary=reason)

    def resume(self, run_id: str, input_or_approval: dict[str, Any]) -> None:
        flow_id, _, current, _ = self._run_row(run_id)
        node_id = current or self.registry.flows[flow_id].entry
        self.transition(run_id, node_id, "flow_resumed", status="running",
                        summary="Run resumed", data={"state_patch": input_or_approval})

    def checkpoint(self, run_id: str) -> str:
        flow_id, _, current, state_json = self._run_row(run_id)
        node_id = current or self.registry.flows[flow_id].entry
        checkpoint_id = f"ckpt_{uuid.uuid4().hex[:16]}"
        self.transition(run_id, node_id, "checkpoint_saved", status="running",
                        summary="Durable checkpoint saved",
                        data={"checkpoint_id": checkpoint_id,
                              "state": json.loads(state_json or "{}")})
        return checkpoint_id

    def inspect(self, run_id: str) -> dict[str, Any]:
        cur = self._conn.execute(
            """SELECT run_id,flow_id,flow_version,graph_hash,session,task,status,
                      current_node,input_json,state_json,budgets_json,
                      capabilities_json,created_at,updated_at
                 FROM flow_runs WHERE run_id=?""", (run_id,))
        row = cur.fetchone()
        if not row:
            raise KeyError(run_id)
        item = dict(zip([column[0] for column in cur.description], row))
        for key in ("input_json", "state_json", "budgets_json", "capabilities_json"):
            item[key[:-5]] = json.loads(item.pop(key))
        item["events"] = self.stream(run_id)
        return item

    def recent_runs(self, flow_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        q = ("SELECT run_id,flow_id,flow_version,session,task,status,current_node,"
             "input_json,created_at,updated_at FROM flow_runs")
        args: list[Any] = []
        if flow_id:
            q += " WHERE flow_id=?"
            args.append(flow_id)
        q += " ORDER BY updated_at DESC LIMIT ?"
        args.append(max(1, min(int(limit), 200)))
        cur = self._conn.execute(q, args)
        cols = [column[0] for column in cur.description]
        rows = []
        for row in cur.fetchall():
            item = dict(zip(cols, row))
            item["input"] = json.loads(item.pop("input_json"))
            rows.append(item)
        return rows

    def replay(self, run_id: str) -> dict[str, Any]:
        snapshot = self.inspect(run_id)
        return {
            "flow_id": snapshot["flow_id"],
            "flow_version": snapshot["flow_version"],
            "graph_hash": snapshot["graph_hash"],
            "input": snapshot["input"],
            "events": snapshot["events"],
        }
