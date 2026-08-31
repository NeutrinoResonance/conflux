from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from conflux import proxy, workspace_ui
from conflux.conversation_graph import ConversationGraphStore
from conflux.flows import FlowRegistry
from conflux.library import Library
from conflux.trace import Trace


class _Request:
    def __init__(self, body: dict):
        self.body = body

    async def json(self) -> dict:
        return dict(self.body)


class _FlowRuntime:
    def __init__(self, registry) -> None:
        self.registry = registry
        self.resumed = []
        self.transitions = []
        self.runs = {}

    def resume(self, run_id, data) -> None:
        self.resumed.append((run_id, data))

    def transition(self, *args, **kwargs) -> None:
        self.transitions.append((args, kwargs))

    def recent_runs(self, flow_id=None, limit=50):
        rows = [dict(item) for item in self.runs.values()
                if flow_id is None or item.get("flow_id") == flow_id]
        return rows[:limit]

    def inspect(self, run_id):
        if run_id not in self.runs:
            raise KeyError(run_id)
        return dict(self.runs[run_id])


class _Actions:
    def __init__(self, action: dict) -> None:
        self.action = dict(action)

    def list(self, *, status=None, limit=100):
        if status and self.action["status"] != status:
            return []
        return [dict(self.action)][:limit]

    def soundness_checks(self, **kwargs):
        return []

    def get(self, action_id):
        return dict(self.action) if action_id == self.action["action_id"] else None

    def decide(self, action_id, decision, note=""):
        if action_id != self.action["action_id"]:
            raise KeyError(action_id)
        if self.action["status"] != "human_pending":
            raise ValueError("action is not waiting for human approval")
        self.action["status"] = "human_approved" if decision == "approve" else "human_denied"
        self.action["human_note"] = note
        return dict(self.action)


class _WorkspaceService:
    def __init__(self) -> None:
        self.resumed = []

    def resume(self, node_id):
        self.resumed.append(node_id)
        return {"node": {"node_id": node_id}, "job": {"status": "queued"}}


class WorkspaceRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.old_state = dict(proxy.state)
        proxy.state.clear()
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "trace.db"
        trace = Trace(path)
        self.trace = trace
        library = Library(path)
        self.library = library
        registry = FlowRegistry.load(Path(__file__).parents[1] / "agent_flows.yaml")
        runtime = _FlowRuntime(registry)
        self.runtime = runtime
        store = ConversationGraphStore(trace.connection, registry)
        self.store = store
        proxy.state.update(
            trace_path=str(path), trace=trace, library=library,
            workspace_store=store,
            flow_runtime=runtime,
            cfg=SimpleNamespace(
                models={},
                path=Path("models.yaml"),
                execution=SimpleNamespace(
                    locked_backend="gce",
                    gcloud_project="project-test",
                    gcloud_account="operator@example.com",
                    gcloud_zone="us-central1-a",
                    gcloud_machine_type="e2-micro",
                ),
            ),
        )

    def tearDown(self) -> None:
        proxy.state.clear()
        proxy.state.update(self.old_state)
        self.tmp.cleanup()

    async def test_bootstrap_creation_graph_and_store_routes(self) -> None:
        endeavor = await proxy.admin_workspace_create_endeavor(
            _Request({"title": "Release workspace"})
        )
        conversation = await proxy.admin_workspace_create_conversation(
            endeavor["id"], _Request({"title": "Main conversation"})
        )
        context = await proxy.admin_workspace_add_conversation_node(
            conversation["session"], _Request({
                "kind": "context", "label": "Constraint",
                "input_text": "Keep the active workflow visible.",
            })
        )
        knowledge = await proxy.admin_workspace_create_store(
            _Request({"name": "Decisions", "adapter": "sqlite-vector"})
        )
        await proxy.admin_workspace_store_record(
            knowledge["store_id"], _Request({"text": "The graph grows downward."})
        )
        found = await proxy.admin_workspace_query_store(
            knowledge["store_id"], _Request({"query": "graph direction"})
        )
        bootstrap = await proxy.admin_workspace_bootstrap(
            endeavor_id=endeavor["id"], conversation_id=conversation["session"]
        )

        self.assertEqual(bootstrap["graph"]["endeavor"]["id"], endeavor["id"])
        self.assertEqual(
            bootstrap["graph"]["conversation"]["session"], conversation["session"]
        )
        self.assertEqual(bootstrap["graph"]["nodes"][0]["node_id"], context["node_id"])
        self.assertEqual(bootstrap["execution_lock"], {
            "backend": "gce", "agent_selectable": False,
            "local_workload_spawn": False,
            "target": {
                "project": "project-test",
                "account": "operator@example.com",
                "zone": "us-central1-a",
                "machine_type": "e2-micro",
            },
            "provisioning": "Spot",
            "lifecycle": "ephemeral · delete after execution",
            "configuration_source": "models.yaml",
        })
        self.assertEqual(found["items"][0]["text"], "The graph grows downward.")
        self.assertTrue(bootstrap["agents"])

    async def test_workflow_execution_exposes_path_counts_and_lazy_model_io(self) -> None:
        endeavor = self.store.create_endeavor("Visible execution")
        conversation = self.store.create_conversation(endeavor["id"], "Inspect the run")
        pair = self.store.create_message_pair(
            conversation["session"], "Explain the execution",
            completed_output="Observed answer", task_id="task-visible",
        )
        instance = pair["workflow"]["instance_id"]
        self.runtime.runs["run-visible"] = {
            "run_id": "run-visible", "flow_id": "supervised_tool_turn",
            "flow_version": 1, "session": conversation["session"],
            "task": "task-visible", "status": "completed",
            "current_node": "completed", "input": {"goal": "Explain the execution"},
            "events": [
                {"id": 1, "ts": 1.0, "node_id": "ingress", "kind": "flow_started",
                 "status": "running", "summary": "Entered the graph", "data": {}},
                {"id": 2, "ts": 2.0, "node_id": "executor", "kind": "execute",
                 "status": "running", "summary": "Generated an answer", "data": {}},
                {"id": 3, "ts": 3.0, "node_id": "final_verifier", "kind": "verify",
                 "status": "running", "summary": "Checked the answer", "data": {}},
                {"id": 4, "ts": 4.0, "node_id": "completed", "kind": "flow_completed",
                 "status": "completed", "summary": "Released the answer", "data": {}},
            ],
        }
        self.trace.record_exchange(
            conversation["session"], "task-visible", "upstream", "executor-test",
            {"request": {"messages": [{"role": "user", "content": "Explain"}]},
             "response": {"content": "Observed answer"}},
        )
        self.trace.record(
            conversation["session"], "task-visible", "execute",
            model="executor-test", tokens_in=8, tokens_out=3, temperature=0.2,
        )

        graph = await proxy.admin_workspace_conversation(conversation["session"])
        summary = graph["workflows"][0]["execution_summary"]
        detail = await proxy.admin_workspace_workflow_execution(instance)

        self.assertEqual(summary["run_id"], "run-visible")
        self.assertEqual(summary["model_step_count"], 1)
        self.assertEqual(
            summary["observed_nodes"],
            ["ingress", "executor", "final_verifier", "completed"],
        )
        self.assertNotIn("model_steps", summary)
        self.assertEqual(detail["model_steps"][0]["node_id"], "executor")
        self.assertEqual(
            detail["model_steps"][0]["input"]["messages"][0]["content"],
            "Explain",
        )
        self.assertEqual(detail["model_steps"][0]["tokens_in"], 8)

    async def test_untitled_conversation_is_created_then_renameable(self) -> None:
        endeavor = await proxy.admin_workspace_create_endeavor(
            _Request({"title": "Product work"})
        )
        conversation = await proxy.admin_workspace_create_conversation(
            endeavor["id"], _Request({})
        )
        renamed = await proxy.admin_workspace_rename_conversation(
            conversation["session"], _Request({"title": "Editable chat title"})
        )

        self.assertEqual(conversation["title"], "New conversation")
        self.assertEqual(renamed["session"], conversation["session"])
        self.assertEqual(renamed["title"], "Editable chat title")
        self.assertEqual(
            self.store.conversation(conversation["session"])["title"],
            "Editable chat title",
        )

    async def test_new_endeavor_opens_with_a_starter_conversation_and_is_renameable(self) -> None:
        endeavor = await proxy.admin_workspace_create_endeavor(
            _Request({"create_conversation": True})
        )
        conversation = endeavor["conversation"]
        renamed = await proxy.admin_workspace_rename_endeavor(
            endeavor["id"], _Request({"title": "Editable objective title"})
        )

        self.assertEqual(endeavor["title"], "Untitled endeavor")
        self.assertEqual(conversation["title"], "New conversation")
        self.assertEqual(conversation["endeavor_id"], endeavor["id"])
        self.assertEqual(renamed["title"], "Editable objective title")
        self.assertEqual(
            renamed["conversations"][0]["session"], conversation["session"]
        )

    async def test_workspace_page_is_served_as_the_primary_product_surface(self) -> None:
        response = await proxy.workspace_dashboard()
        self.assertIn("Unified", workspace_ui.__doc__ or "Unified")
        self.assertIn("Downward-growing conversation graph", response.body.decode())

    async def test_workspace_conversation_is_not_duplicated_as_history_endeavor(self) -> None:
        endeavor = await proxy.admin_workspace_create_endeavor(
            _Request({"title": "One hierarchy"})
        )
        conversation = await proxy.admin_workspace_create_conversation(
            endeavor["id"], _Request({"title": "One conversation"})
        )
        self.trace.record_exchange(
            conversation["session"], "task-1", "client_request", None,
            {"messages": [{"role": "user", "content": "Hello"}]},
        )
        self.trace.record_exchange(
            conversation["session"], "task-1", "supervisor_response", None,
            {"content": "Hi"},
        )

        bootstrap = await proxy.admin_workspace_bootstrap(
            endeavor_id=endeavor["id"], conversation_id=conversation["session"]
        )

        ids = [item["id"] for item in bootstrap["endeavors"]]
        self.assertEqual(ids, [endeavor["id"]])

    async def test_ungrouped_history_is_a_conversation_not_an_endeavor(self) -> None:
        endeavor = await proxy.admin_workspace_create_endeavor(
            _Request({"title": "Explicit product objective"})
        )
        current = await proxy.admin_workspace_create_conversation(
            endeavor["id"], _Request({"title": "Current thread"})
        )
        archived_session = "archived-thread"
        self.library.touch_session(archived_session, "Archived thread")
        self.trace.record_exchange(
            archived_session, "old-task", "client_request", None,
            {"messages": [{"role": "user", "content": "Earlier question"}]},
        )
        self.trace.record_exchange(
            archived_session, "old-task", "client_response", None,
            {"text": "Earlier answer"},
        )

        listing = await proxy.admin_workspace_bootstrap(
            endeavor_id=endeavor["id"], conversation_id=current["session"]
        )
        self.assertNotIn(
            f"session:{archived_session}",
            [item["id"] for item in listing["endeavors"]],
        )
        self.assertEqual(
            [item["session"] for item in listing["unassigned_conversations"]],
            [archived_session],
        )

        opened = await proxy.admin_workspace_bootstrap(
            history_conversation_id=archived_session
        )
        self.assertEqual(opened["graph"]["endeavor"]["id"], "end_unassigned_history")
        self.assertEqual(opened["graph"]["conversation"]["session"], archived_session)
        parent = next(
            item for item in opened["endeavors"]
            if item["id"] == "end_unassigned_history"
        )
        self.assertEqual(
            [item["session"] for item in parent["conversations"]],
            [archived_session],
        )

    async def test_workspace_scopes_pending_action_and_continues_after_decision(self) -> None:
        endeavor = self.store.create_endeavor("Approval objective")
        conversation = self.store.create_conversation(endeavor["id"], "Risky work")
        pair = self.store.create_message_pair(
            conversation["session"], "Perform exact action",
            completed_output="Operator approval is required", task_id="task-pending",
        )
        self.store.set_node_status(pair["assistant"]["node_id"], "awaiting_approval")
        action = {
            "action_id": "act-inline", "session": conversation["session"],
            "task": "task-pending", "run_id": "run-pending", "call_id": "call-1",
            "tool_name": "terminal", "risk": "high", "status": "human_pending",
            "proposal": {
                "targets": ["gce://worker"], "arguments": {"command": "run"},
                "postcondition": {"description": "job started"},
                "invariants": ["GCE only"], "rollback": "stop the job",
            },
            "assessment": {"reasons": ["process spawn"]}, "manifest": {},
            "verdict": {"reason": "operator review"}, "probe": {},
            "probe_result": {}, "human_note": "", "created_at": 1.0,
            "updated_at": 1.0,
        }
        actions = _Actions(action)
        service = _WorkspaceService()
        proxy.state.update(action_store=actions, workspace_service=service)

        graph = await proxy.admin_workspace_conversation(conversation["session"])
        self.assertEqual(graph["pending_actions"][0]["action_id"], "act-inline")
        self.assertEqual(
            graph["pending_actions"][0]["workspace_node_id"],
            pair["assistant"]["node_id"],
        )
        decided = await proxy.admin_workspace_action_decision(
            "act-inline", _Request({"decision": "approve", "note": "GCE target verified"})
        )
        self.assertEqual(decided["action"]["status"], "human_approved")
        self.assertEqual(service.resumed, [pair["assistant"]["node_id"]])
        self.assertEqual(self.runtime.resumed[0][0], "run-pending")

    async def test_flow_preview_predicts_the_route_before_send(self) -> None:
        endeavor = self.store.create_endeavor("Routing")
        conversation = self.store.create_conversation(endeavor["id"], "Preview")
        session = conversation["session"]

        auto = await proxy.admin_workspace_flow_preview(
            session, _Request({"content": "Summarize this file", "flow_id": "auto"})
        )
        self.assertEqual(auto["mode"], "auto")
        self.assertEqual(auto["flow_id"], "supervised_tool_turn")
        self.assertEqual(auto["method"], "heuristic")

        durable = await proxy.admin_workspace_flow_preview(
            session, _Request({"content": "keep the long-running job running overnight"})
        )
        self.assertEqual(durable["flow_id"], "durable_locked_job")

        manual = await proxy.admin_workspace_flow_preview(
            session, _Request({"content": "x", "flow_id": "durable_locked_job"})
        )
        self.assertEqual(manual["mode"], "manual")

        synthesize = await proxy.admin_workspace_flow_preview(
            session, _Request({"content": "x", "flow_id": "synthesize"})
        )
        self.assertEqual(synthesize["mode"], "synthesize")
        self.assertIsNone(synthesize["flow_id"])

        with self.assertRaises(proxy.HTTPException):
            await proxy.admin_workspace_flow_preview(
                session, _Request({"content": "x", "flow_id": "not_a_flow"})
            )

    async def test_feeds_edges_can_be_wired_and_removed_over_the_api(self) -> None:
        endeavor = self.store.create_endeavor("Wiring")
        conversation = self.store.create_conversation(endeavor["id"], "Wires")
        session = conversation["session"]
        first = self.store.create_message_pair(
            session, "First", completed_output="One"
        )
        second = self.store.create_message_pair(
            session, "Second", parent_id=first["assistant"]["node_id"],
            completed_output="Two",
        )
        third = self.store.create_message_pair(
            session, "Third", parent_id=first["assistant"]["node_id"],
            completed_output="Three",
        )

        edge = await proxy.admin_workspace_add_edge(session, _Request({
            "source_id": second["assistant"]["node_id"],
            "target_id": third["assistant"]["node_id"],
        }))
        self.assertEqual(edge["kind"], "feeds")
        kinds = {e["kind"] for e in self.store.edges(session)}
        self.assertIn("feeds", kinds)

        with self.assertRaises(proxy.HTTPException):
            await proxy.admin_workspace_add_edge(session, _Request({
                "source_id": third["assistant"]["node_id"],
                "target_id": second["assistant"]["node_id"],
            }))

        removed = await proxy.admin_workspace_delete_edge(edge["edge_id"])
        self.assertEqual(removed["deleted"], edge["edge_id"])
        with self.assertRaises(proxy.HTTPException):
            await proxy.admin_workspace_delete_edge(edge["edge_id"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
