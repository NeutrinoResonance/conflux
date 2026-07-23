from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from llm_super.conversation_graph import ConversationGraphStore
from llm_super.flows import FlowRegistry


class ConversationGraphStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        registry = FlowRegistry.load(Path(__file__).parents[1] / "agent_flows.yaml")
        self.store = ConversationGraphStore(self.connection, registry)
        self.endeavor = self.store.create_endeavor("Ship the product")
        self.conversation = self.store.create_conversation(
            self.endeavor["id"], "Design the interaction"
        )

    def test_messages_grow_downward_as_dependencies_and_contain_workflows(self) -> None:
        first = self.store.create_message_pair(
            self.conversation["session"], "Draft the interface",
            completed_output="Initial draft",
        )
        second = self.store.create_message_pair(
            self.conversation["session"], "Make it release quality",
            completed_output="Polished draft",
        )
        graph = self.store.graph(self.conversation["session"])

        self.assertEqual(len(graph["nodes"]), 4)
        self.assertEqual(len(graph["edges"]), 3)
        self.assertEqual(graph["endeavor"]["id"], self.endeavor["id"])
        self.assertEqual(graph["conversation"]["session"], self.conversation["session"])
        self.assertEqual(len(graph["workflows"]), 2)
        self.assertEqual(
            second["user"]["parent_id"], first["assistant"]["node_id"]
        )
        self.assertEqual(
            graph["workflows"][0]["flow_id"], "supervised_tool_turn"
        )

    def test_reparenting_updates_conversation_nodes_and_edges_atomically(self) -> None:
        pair = self.store.create_message_pair(
            self.conversation["session"], "Archive me", completed_output="Archived"
        )
        destination = self.store.create_endeavor("Unassigned conversations")

        moved = self.store.move_conversation(
            self.conversation["session"], destination["id"]
        )
        graph = self.store.graph(self.conversation["session"])

        self.assertEqual(moved["endeavor_id"], destination["id"])
        self.assertEqual(graph["endeavor"]["id"], destination["id"])
        self.assertTrue(all(
            node["endeavor_id"] == destination["id"] for node in graph["nodes"]
        ))
        rows = self.connection.execute(
            "SELECT DISTINCT endeavor_id FROM workspace_edges WHERE session=?",
            (self.conversation["session"],),
        ).fetchall()
        self.assertEqual(rows, [(destination["id"],)])
        self.assertEqual(pair["assistant"]["session"], self.conversation["session"])

    def test_conversation_can_be_renamed_without_changing_its_identity(self) -> None:
        renamed = self.store.rename_conversation(
            self.conversation["session"], "Human-readable release plan"
        )

        self.assertEqual(renamed["session"], self.conversation["session"])
        self.assertEqual(renamed["endeavor_id"], self.conversation["endeavor_id"])
        self.assertEqual(renamed["title"], "Human-readable release plan")
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            self.store.rename_conversation(self.conversation["session"], "   ")

    def test_endeavor_can_be_renamed_without_changing_its_children(self) -> None:
        renamed = self.store.rename_endeavor(
            self.endeavor["id"], "Human-readable objective"
        )

        self.assertEqual(renamed["id"], self.endeavor["id"])
        self.assertEqual(renamed["title"], "Human-readable objective")
        self.assertEqual(
            renamed["conversations"][0]["session"], self.conversation["session"]
        )
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            self.store.rename_endeavor(self.endeavor["id"], "   ")

    def test_edit_revisions_and_invalidates_every_dependent_node(self) -> None:
        first = self.store.create_message_pair(
            self.conversation["session"], "Original", completed_output="Answer one"
        )
        second = self.store.create_message_pair(
            self.conversation["session"], "Follow up", completed_output="Answer two"
        )

        edited = self.store.update_node(
            first["user"]["node_id"], {"input_text": "Edited original"}
        )

        self.assertEqual(edited["output_text"], "Edited original")
        self.assertEqual(
            set(edited["invalidated_node_ids"]),
            {
                first["assistant"]["node_id"], second["user"]["node_id"],
                second["assistant"]["node_id"],
            },
        )
        self.assertTrue(all(
            self.store.node(node_id)["status"] == "stale"
            for node_id in edited["invalidated_node_ids"]
        ))
        revision = self.store.revisions(first["user"]["node_id"])[0]
        self.assertEqual(revision["input_text"], "Original")
        self.assertEqual(revision["reason"], "user edit")

    def test_workflow_nodes_can_be_added_deleted_and_applied_globally(self) -> None:
        pair = self.store.create_message_pair(
            self.conversation["session"], "Compare approaches",
            completed_output="Result",
        )
        instance_id = pair["workflow"]["instance_id"]
        added = self.store.add_workflow_node(
            instance_id, node_type="ensemble", label="Three-way union",
            after_node_id="ingress",
            config={
                "mode": "union", "candidate_count": 3,
                "candidate_mode": "same_model", "temperatures": [0.2, 0.7, 1.0],
            },
            apply_globally=True,
        )
        added_id = added["added_node_id"]
        graph = added["graph"]
        ensemble_node = next(node for node in graph["nodes"] if node["id"] == added_id)

        self.assertTrue(any(node["id"] == added_id for node in graph["nodes"]))
        self.assertEqual(ensemble_node["agent"], "ensemble_coordinator")
        self.assertEqual(
            ensemble_node["capabilities"],
            ["generate_candidates", "merge_candidates"],
        )
        self.assertTrue(any(
            edge["source"] == "ingress" and edge["target"] == added_id
            for edge in graph["edges"]
        ))
        self.assertTrue(any(
            edge["source"] == added_id and edge["target"] == "executor"
            for edge in graph["edges"]
        ))
        plan = self.store.workflow_plan(instance_id)
        self.assertEqual(plan["ensemble"]["candidate_mode"], "same_model")

        another = self.store.create_message_pair(
            self.conversation["session"], "Use the global workflow",
            completed_output="Global result",
        )
        inherited = another["workflow"]["graph"]
        self.assertTrue(any(node["id"] == added_id for node in inherited["nodes"]))

        deleted = self.store.delete_workflow_node(instance_id, added_id)
        self.assertFalse(any(node["id"] == added_id for node in deleted["graph"]["nodes"]))
        self.assertTrue(any(
            edge["source"] == "ingress" and edge["target"] == "executor"
            for edge in deleted["graph"]["edges"]
        ))

    def test_context_edges_and_vector_store_are_real_prompt_inputs(self) -> None:
        knowledge = self.store.create_store(
            "Release decisions", description="Accepted product decisions"
        )
        self.store.save_record(
            knowledge["store_id"], "The release must use a downward graph.",
            metadata={"kind": "decision"},
        )
        results = self.store.query_store(
            knowledge["store_id"], "Which direction should the graph grow?"
        )
        self.assertEqual(results[0]["metadata"]["kind"], "decision")
        self.assertGreater(results[0]["score"], -1.0)

        context = self.store.add_node(
            self.conversation["session"], kind="context",
            label="Release constraint", input_text="Never hide the active agent.",
        )
        pair = self.store.create_message_pair(
            self.conversation["session"], "Review the graph",
            completed_output="Reviewed",
        )
        messages = self.store.prompt_messages(pair["assistant"]["node_id"])
        self.assertEqual(messages[0], {
            "role": "system", "content": "Never hide the active agent."
        })
        self.assertEqual(messages[-1]["content"], "Review the graph")
        self.assertEqual(pair["user"]["parent_id"], context["node_id"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
