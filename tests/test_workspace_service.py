from __future__ import annotations

import asyncio
import sqlite3
import unittest
from pathlib import Path

from llm_super.conversation_graph import ConversationGraphStore
from llm_super.flows import FlowRegistry
from llm_super.orchestrator import TurnReport
from llm_super.workspace import WorkspaceService


class _Library:
    def __init__(self) -> None:
        self.touched = []
        self.titles = []

    def touch_session(self, session: str, title: str) -> None:
        self.touched.append((session, title))

    def set_session_title(self, session: str, title: str) -> None:
        self.titles.append((session, title))


class _Orchestrator:
    def __init__(self) -> None:
        self.calls = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False
        self.report_text = "A verified workspace response"
        self.report_escalated = ""
        self.require_approval = False
        self.generated_title = "Agent-Named Conversation"
        self.title_calls = []
        self.action_store = _ActionStore()

    async def generate_conversation_title(self, session, user_text, assistant_text):
        self.title_calls.append((session, user_text, assistant_text))
        return self.generated_title

    async def run_turn(self, session, messages, *, options, event_hook):
        self.calls.append((session, messages, options))
        event_hook("ensemble_start" if options.ensemble_n else "execute", {
            "ensemble": bool(options.ensemble_n)
        })
        self.started.set()
        if self.block:
            await self.release.wait()
        event_hook("verify", {"stage": "final"})
        event_hook("turn_end", {})
        if self.require_approval:
            self.action_store.pending = [{
                "action_id": "act-workspace", "session": session,
                "task": f"task-{len(self.calls)}", "status": "human_pending",
            }]
        return TurnReport(
            text=self.report_text, task_id=f"task-{len(self.calls)}",
            executor="executor", attempts=max(1, options.ensemble_n), verify=None,
            cost_usd=0.01, escalated=self.report_escalated,
        )


class _ActionStore:
    def __init__(self) -> None:
        self.pending = []

    def list(self, *, status=None, limit=100):
        return [
            item for item in self.pending
            if status is None or item["status"] == status
        ][:limit]


class WorkspaceServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        registry = FlowRegistry.load(Path(__file__).parents[1] / "agent_flows.yaml")
        self.store = ConversationGraphStore(connection, registry)
        endeavor = self.store.create_endeavor("Public release")
        self.conversation = self.store.create_conversation(
            endeavor["id"], "Unified workspace"
        )
        self.orchestrator = _Orchestrator()
        self.library = _Library()
        self.service = WorkspaceService(
            self.store, self.orchestrator, self.library, trace=None
        )

    async def _await_job(self, job_id: str) -> None:
        task = self.service._tasks_by_job[job_id]
        await task

    async def test_per_message_ensemble_runs_same_model_with_varied_temperatures(self) -> None:
        pair = self.store.create_message_pair(
            self.conversation["session"], "Union several perspectives",
            completed_output="placeholder",
        )
        self.store.set_node_status(pair["assistant"]["node_id"], "paused")
        instance = pair["workflow"]["instance_id"]
        self.store.add_workflow_node(
            instance, node_type="ensemble", label="Sample three",
            after_node_id="ingress",
            config={
                "mode": "union", "candidate_count": 3,
                "candidate_mode": "same_model", "temperatures": [0.1, 0.8, 1.3],
            },
        )

        resumed = self.service.resume(pair["assistant"]["node_id"])
        await self._await_job(resumed["job"]["job_id"])

        assistant = self.store.node(pair["assistant"]["node_id"])
        options = self.orchestrator.calls[0][2]
        self.assertEqual(assistant["status"], "complete")
        self.assertEqual(assistant["output_text"], "A verified workspace response")
        self.assertEqual(options.strategy, "union")
        self.assertEqual(options.ensemble_n, 3)
        self.assertEqual(options.candidate_mode, "same_model")
        self.assertEqual(options.temperatures, (0.1, 0.8, 1.3))
        self.assertEqual(self.library.touched[0][0], self.conversation["session"])

    async def test_first_response_gets_an_llm_title_but_human_title_wins(self) -> None:
        untitled_endeavor = self.store.create_endeavor("")
        untitled = self.store.create_conversation(
            untitled_endeavor["id"], ""
        )
        queued = self.service.send(untitled["session"], "Design the launch page")
        await self._await_job(queued["job"]["job_id"])

        self.assertEqual(
            self.store.conversation(untitled["session"])["title"],
            "Agent-Named Conversation",
        )
        self.assertEqual(
            self.store.endeavor(untitled_endeavor["id"])["title"],
            "Agent-Named Conversation",
        )
        self.assertEqual(self.orchestrator.title_calls[0][1], "Design the launch page")
        self.assertEqual(
            self.library.titles[-1],
            (untitled["session"], "Agent-Named Conversation"),
        )

        human_named = self.store.create_conversation(
            self.conversation["endeavor_id"], "Release command center"
        )
        queued = self.service.send(human_named["session"], "Keep this title")
        await self._await_job(queued["job"]["job_id"])
        self.assertEqual(
            self.store.conversation(human_named["session"])["title"],
            "Release command center",
        )
        self.assertEqual(len(self.orchestrator.title_calls), 1)

        human_named_endeavor = self.store.create_endeavor("Human objective")
        second_untitled = self.store.create_conversation(
            human_named_endeavor["id"], ""
        )
        queued = self.service.send(second_untitled["session"], "Name only the chat")
        await self._await_job(queued["job"]["job_id"])
        self.assertEqual(
            self.store.endeavor(human_named_endeavor["id"])["title"],
            "Human objective",
        )
        self.assertEqual(
            self.store.conversation(second_untitled["session"])["title"],
            "Agent-Named Conversation",
        )

        third_endeavor = self.store.create_endeavor("")
        human_named_chat = self.store.create_conversation(
            third_endeavor["id"], "Human chat title"
        )
        queued = self.service.send(human_named_chat["session"], "Use my chat title")
        await self._await_job(queued["job"]["job_id"])
        self.assertEqual(
            self.store.endeavor(third_endeavor["id"])["title"],
            "Human chat title",
        )

    async def test_human_input_node_pauses_before_any_model_call(self) -> None:
        pair = self.store.create_message_pair(
            self.conversation["session"], "Wait for me", completed_output="placeholder"
        )
        self.store.set_node_status(pair["assistant"]["node_id"], "paused")
        self.store.add_workflow_node(
            pair["workflow"]["instance_id"], node_type="human_input",
            label="Confirm direction", after_node_id="ingress",
            config={"required": True, "satisfied": False},
        )
        resumed = self.service.resume(pair["assistant"]["node_id"])
        await self._await_job(resumed["job"]["job_id"])

        assistant = self.store.node(pair["assistant"]["node_id"])
        workflow = self.store.workflow(pair["workflow"]["instance_id"])
        self.assertEqual(assistant["status"], "awaiting_input")
        self.assertEqual(workflow["status"], "awaiting_input")
        self.assertEqual(self.orchestrator.calls, [])

    async def test_edit_automatically_recalculates_dependent_assistant_nodes(self) -> None:
        first = self.store.create_message_pair(
            self.conversation["session"], "First prompt", completed_output="Old first"
        )
        second = self.store.create_message_pair(
            self.conversation["session"], "Dependent prompt", completed_output="Old second"
        )
        result = self.service.edit_node(
            first["user"]["node_id"], {"input_text": "Edited first prompt"}
        )
        await self._await_job(result["job"]["job_id"])

        self.assertEqual(
            self.store.node(first["assistant"]["node_id"])["output_text"],
            "A verified workspace response",
        )
        self.assertEqual(
            self.store.node(second["assistant"]["node_id"])["output_text"],
            "A verified workspace response",
        )
        self.assertEqual(self.store.node(second["user"]["node_id"])["status"], "complete")
        self.assertEqual(len(self.orchestrator.calls), 2)

    async def test_pause_cancels_in_flight_message_without_releasing_output(self) -> None:
        self.orchestrator.block = True
        queued = self.service.send(self.conversation["session"], "Long-running turn")
        await self.orchestrator.started.wait()
        node_id = queued["pair"]["assistant"]["node_id"]
        self.service.pause(node_id)
        task = self.service._tasks_by_job.get(queued["job"]["job_id"])
        if task:
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.store.node(node_id)["status"], "paused")
        self.assertEqual(self.store.node(node_id)["output_text"], "")

    async def test_provider_outage_is_failed_not_verified_completion(self) -> None:
        self.orchestrator.report_text = ""
        self.orchestrator.report_escalated = "all executors failed (provider outage?)"
        queued = self.service.send(self.conversation["session"], "Unavailable model")
        await self._await_job(queued["job"]["job_id"])

        assistant = self.store.node(queued["pair"]["assistant"]["node_id"])
        workflow = self.store.workflow(assistant["workflow_instance_id"])
        job = self.store.jobs(session=self.conversation["session"])[0]
        self.assertEqual(assistant["status"], "failed")
        self.assertIn("provider outage", assistant["output_text"])
        self.assertEqual(workflow["status"], "failed")
        self.assertEqual(workflow["active_node"], "blocked")
        self.assertEqual(job["status"], "failed")

    async def test_durable_pending_action_pauses_at_inline_human_approval(self) -> None:
        self.orchestrator.require_approval = True
        self.orchestrator.report_text = (
            "[llm-super] Human approval is required. Review this in Agent Graphs."
        )

        queued = self.service.send(
            self.conversation["session"], "Perform a high-risk action"
        )
        await self._await_job(queued["job"]["job_id"])

        assistant = self.store.node(queued["pair"]["assistant"]["node_id"])
        workflow = self.store.workflow(assistant["workflow_instance_id"])
        job = self.store.job(queued["job"]["job_id"])
        self.assertEqual(assistant["status"], "awaiting_approval")
        self.assertEqual(assistant["config"]["pending_action_ids"], ["act-workspace"])
        self.assertNotIn("Agent Graphs", assistant["output_text"])
        self.assertEqual(workflow["status"], "awaiting_approval")
        self.assertEqual(workflow["active_node"], "human_approval")
        self.assertEqual(job["status"], "awaiting_approval")

    async def test_drag_position_does_not_invalidate_or_reexecute_the_graph(self) -> None:
        first = self.store.create_message_pair(
            self.conversation["session"], "First", completed_output="One"
        )
        second = self.store.create_message_pair(
            self.conversation["session"], "Second", completed_output="Two"
        )
        revision = first["user"]["revision"]

        result = self.service.edit_node(
            first["user"]["node_id"], {"position_x": 420.0, "position_y": 180.0},
            auto_recalculate=False,
        )

        self.assertIsNone(result["job"])
        self.assertEqual(result["node"]["revision"], revision)
        self.assertEqual(result["node"]["position_x"], 420.0)
        self.assertEqual(self.store.node(second["assistant"]["node_id"])["status"], "complete")
        self.assertEqual(self.orchestrator.calls, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
