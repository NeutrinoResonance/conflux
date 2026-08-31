from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace

from conflux import graph_ui, history_ui, proxy, ui
from conflux.durable_jobs import DurableJobStore
from conflux.flows import FlowRegistry, SQLiteFlowRuntime
from conflux.governance import (
    ActionStore,
    ActionVerdict,
    ToolManifest,
    assess_action,
    build_proposal,
)


class _Request:
    def __init__(self, body: dict):
        self.body = body

    async def json(self) -> dict:
        return self.body


class _Trace:
    def __init__(self) -> None:
        self.events = []

    def record(self, *args, **kwargs) -> None:
        self.events.append((args, kwargs))


class GraphUIContractTests(unittest.TestCase):
    def test_graph_studio_exposes_definition_run_overlay_and_human_queue(self) -> None:
        page = graph_ui.PAGE
        self.assertIn('href="/graphs" aria-current="page"', page)
        self.assertIn('id="graph" role="group"', page)
        self.assertIn('id="definitionMode"', page)
        self.assertIn('id="runMode"', page)
        self.assertIn('id="nodeInspector"', page)
        self.assertIn('id="mobileNodeInspector"', page)
        self.assertIn('id="approvalQueue"', page)
        self.assertIn('id="soundnessQueue"', page)
        self.assertIn('id="soundnessContext"', page)
        self.assertIn('id="soundnessSelected"', page)
        self.assertIn('id="soundnessAll"', page)
        self.assertIn('id="runPicker"', page)
        self.assertIn('id="endeavorLink"', page)
        self.assertIn('id="conversationLink"', page)
        self.assertIn('id="decisionMeta"', page)
        self.assertIn('Workflow definition', page)
        self.assertIn('Reusable workflow definition · not a conversation map', page)
        self.assertIn('Endeavor, conversation, task run, and decision event hierarchy', page)
        self.assertIn('Endeavor contains conversations · conversations trigger task runs · task runs record decision events', page)
        self.assertIn('Independent tests of claims—not an overall task grade.', page)
        self.assertIn('id="jobList"', page)
        self.assertIn('id="executionLock"', page)
        self.assertIn('id="decisionDialog"', page)
        self.assertIn('tabindex="0" role="button"', page)
        self.assertIn('/admin/graphs/runs/', page)
        self.assertIn('/admin/actions/', page)
        self.assertIn('/admin/jobs/', page)
        self.assertIn('function renderJobs()', page)
        self.assertIn('function chooseJob(id)', page)
        self.assertIn('prefers-reduced-motion:reduce', page)
        self.assertIn('aria-live="polite"', page)
        # Live updates ride the trace-fed SSE channel; the interval is only
        # a 30s safety net (the 2s full-refetch polling is gone).
        self.assertIn('new EventSource("/admin/events/stream")', page)
        self.assertIn('setInterval(refresh,30000)', page)
        self.assertNotIn('setInterval(refresh,2000)', page)

    def test_graph_workspace_contains_intrinsic_size_and_reveals_runtime_focus(self) -> None:
        page = graph_ui.PAGE
        self.assertIn('height:calc(100vh - 62px)', page)
        self.assertIn('grid-template-rows:max-content max-content max-content minmax(220px,1fr) max-content', page)
        self.assertIn('.canvas-frame{grid-row:4;width:100%;max-width:100%;min-width:0', page)
        self.assertIn('.canvas{width:100%;height:100%;max-width:100%;min-width:0', page)
        self.assertIn('.run-strip{grid-row:5;width:100%;max-width:100%;min-width:0', page)
        self.assertIn('function fitScale(flow)', page)
        self.assertIn('function focusNode(id,behavior="smooth")', page)
        self.assertIn('requestAnimationFrame(()=>focusNode(state.selectedNode))', page)
        self.assertIn('aria-pressed="true"', page)

    def test_runs_and_soundness_are_explicitly_bound_to_conversation_context(self) -> None:
        page = graph_ui.PAGE
        self.assertIn('function runTaskLabel(run)', page)
        self.assertIn('function runConversationLabel(run)', page)
        self.assertIn('function loadEndeavorContext(run)', page)
        self.assertIn('function renderScope()', page)
        self.assertIn('function chooseSoundnessRun(id)', page)
        self.assertIn('c.run_id===state.run.run_id', page)
        self.assertIn('View this check in its decision trail', page)
        self.assertIn('Open conversation history', page)
        self.assertIn('/history?q=', page)
        self.assertIn('selectedRunId=state.run?.run_id', page)
        self.assertIn('state.run?.run_id===selectedRunId', page)
        self.assertIn('/admin/history/sessions/${encodeURIComponent(session)}/context', page)
        self.assertIn('Single-conversation endeavor', page)

    def test_graph_nodes_are_draggable_and_canvas_is_pointer_pannable(self) -> None:
        page = graph_ui.PAGE
        self.assertIn('id="resetLayout"', page)
        self.assertIn('touch-action:none;user-select:none;cursor:grab', page)
        self.assertIn('function beginNodeDrag(e)', page)
        self.assertIn('function beginCanvasPan(e)', page)
        self.assertIn('function moveGesture(e)', page)
        self.assertIn('function finishGesture(e,cancelled=false)', page)
        self.assertIn('setPointerCapture(e.pointerId)', page)
        self.assertIn('data-edge-source=', page)
        self.assertIn('localStorage.setItem(positionKey', page)
        self.assertIn('graphCanvas.onpointerdown=beginCanvasPan', page)
        self.assertIn('signature===state.graphSignature', page)

    def test_graph_edges_explain_routes_and_open_a_detailed_inspector(self) -> None:
        page = graph_ui.PAGE
        self.assertIn('id="edgeLegend"', page)
        self.assertIn('forward route', page)
        self.assertIn('recovery loop', page)
        self.assertIn('class="edge-hit"', page)
        self.assertIn('class="edge-label-group', page)
        self.assertIn('function edgeCaption(edge)', page)
        self.assertIn('function edgeLabelPoint(a,b,loop)', page)
        self.assertIn('function edgeLabelLayout(flow,pos)', page)
        self.assertIn('function edgeRuntimeState(edge)', page)
        self.assertIn('function selectEdge(index)', page)
        self.assertIn('state.selectedEdge===index', page)
        self.assertIn('Observed transition', page)
        self.assertIn('Always continue after the source completes', page)
        self.assertIn('.node,.edge-hit,.edge-label-group', page)

    def test_every_primary_surface_links_to_agent_graphs(self) -> None:
        self.assertIn('<a href="/graphs">Agent Graphs</a>', ui.PAGE)
        self.assertIn('<a href="/graphs">Agent Graphs</a>', history_ui.PAGE)

    def test_definition_payload_is_serializable_for_the_browser(self) -> None:
        registry = FlowRegistry.load(Path(__file__).parents[1] / "agent_flows.yaml")
        runtime = SQLiteFlowRuntime(sqlite3.connect(":memory:"), registry)
        payload = registry.describe()
        self.assertEqual(payload["flows"][0]["id"], "supervised_tool_turn")
        self.assertEqual(len(payload["agents"]), 8)
        self.assertEqual(len(payload["flows"]), 2)
        self.assertEqual(runtime.compile("supervised_tool_turn")["edges"], 24)
        self.assertEqual(runtime.compile("durable_locked_job")["edges"], 10)


class GraphAdminRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.old_state = dict(proxy.state)
        proxy.state.clear()
        registry = FlowRegistry.load(Path(__file__).parents[1] / "agent_flows.yaml")
        self.runtime = SQLiteFlowRuntime(sqlite3.connect(":memory:"), registry)
        self.store = ActionStore(self.runtime.connection)
        self.job_store = DurableJobStore(self.runtime.connection)
        self.trace = _Trace()
        proxy.state.update(
            flow_runtime=self.runtime, action_store=self.store, trace=self.trace,
            job_store=self.job_store,
            cfg=SimpleNamespace(execution=SimpleNamespace(locked_backend="gce")),
        )

    def tearDown(self) -> None:
        proxy.state.clear()
        proxy.state.update(self.old_state)

    async def test_graph_and_run_routes_return_declared_and_observed_state(self) -> None:
        run_id = self.runtime.start(
            "supervised_tool_turn", {"goal": "route test"}, {},
            list(self.runtime.registry.flows["supervised_tool_turn"].capabilities),
            session="s", task="t",
        )
        self.runtime.transition(run_id, "executor", "executor_started")

        declared = await proxy.admin_graphs()
        runs = await proxy.admin_graph_runs(flow_id="supervised_tool_turn", limit=10)
        observed = await proxy.admin_graph_run(run_id)

        self.assertEqual(declared["flows"][0]["id"], "supervised_tool_turn")
        self.assertEqual(runs["items"][0]["run_id"], run_id)
        self.assertEqual(runs["items"][0]["input"]["goal"], "route test")
        self.assertEqual(runs["items"][0]["task_label"], "route test")
        self.assertEqual(runs["items"][0]["conversation_title"], "Conversation s")
        self.assertEqual(observed["current_node"], "executor")

    async def test_job_routes_expose_lock_state_and_durable_events(self) -> None:
        job_id = "job_0123456789abcdef01234567"
        self.job_store.create(
            job_id=job_id, backend="gce", boundary_fingerprint="a" * 64,
            target={"vm": "one", "zone": "us-central1-a"}, context={},
            label="route job", command="sleep 1", cwd="/tmp/conflux-agent",
            timeout_s=30, remote_dir=f"/tmp/conflux-agent/.jobs/{job_id}",
        )
        self.job_store.observe(
            job_id, {"state": "running", "pid": 77, "owned": True},
            kind="job_started", summary="Remote process started",
        )

        listing = await proxy.admin_jobs(limit=10)
        detail = await proxy.admin_job(job_id)
        events = await proxy.admin_job_events(job_id)

        self.assertEqual(listing["execution_lock"]["backend"], "gce")
        self.assertFalse(listing["execution_lock"]["agent_selectable"])
        self.assertEqual(detail["pid"], 77)
        self.assertEqual(events["items"][-1]["kind"], "job_started")

    async def test_operator_decision_is_durable_and_updates_the_graph(self) -> None:
        run_id = self.runtime.start(
            "supervised_tool_turn", {"goal": "write disk"}, {},
            list(self.runtime.registry.flows["supervised_tool_turn"].capabilities),
            session="session", task="task",
        )
        for node in ("executor", "policy_gate", "action_critic", "human_approval"):
            self.runtime.transition(run_id, node, f"entered_{node}")
        call = {"id": "call", "function": {
            "name": "terminal",
            "arguments": '{"command":"dd if=x of=/dev/nbd0p2"}',
        }}
        manifest = ToolManifest(name="terminal")
        proposal = build_proposal(call, {"content": "write disk"}, manifest)
        assessment = assess_action(proposal, manifest)
        self.store.put(
            "session", "task", run_id, proposal, assessment, manifest,
            "human_pending", {"choices": []},
            verdict=ActionVerdict("human", "raw disk write needs approval"),
        )

        listing = await proxy.admin_actions(status="human_pending", limit=10)
        self.assertEqual(listing["items"][0]["action_id"], proposal.action_id)
        self.assertNotIn("response", listing["items"][0])
        decided = await proxy.admin_action_decision(
            proposal.action_id, _Request({"decision": "approve", "note": "backup verified"})
        )

        self.assertEqual(decided["status"], "human_approved")
        self.assertEqual(self.runtime.inspect(run_id)["status"], "running")
        self.assertEqual(self.runtime.stream(run_id)[-1]["kind"], "flow_resumed")
        self.assertEqual(self.trace.events[-1][1]["verdict"], "approve")


if __name__ == "__main__":
    unittest.main()
