from __future__ import annotations

import unittest
from pathlib import Path

from conflux import flow_match
from conflux.flow_synthesis import validate_synthesized
from conflux.flows import FlowRegistry


def _registry() -> FlowRegistry:
    return FlowRegistry.load(Path(__file__).parents[1] / "agent_flows.yaml")


def _catalog(registry: FlowRegistry) -> list[dict]:
    return [
        {"id": flow.id, "label": flow.label, "description": flow.description}
        for flow in registry.flows.values()
    ]


class HeuristicMatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.flows = _catalog(_registry())

    def test_generic_prompt_routes_to_the_default_flow(self) -> None:
        match = flow_match.heuristic_match(
            "Summarize this paragraph in two sentences", self.flows
        )
        self.assertEqual(match["flow_id"], flow_match.DEFAULT_FLOW_ID)
        self.assertEqual(match["method"], "heuristic")

    def test_durable_keywords_route_to_the_locked_job_flow(self) -> None:
        match = flow_match.heuristic_match(
            "Start the training run and keep it running overnight; "
            "monitor the long-running background job for me", self.flows
        )
        self.assertEqual(match["flow_id"], "durable_locked_job")
        self.assertIn("matched", match["reason"])

    def test_empty_catalog_still_returns_a_flow_id(self) -> None:
        match = flow_match.heuristic_match("anything", [])
        self.assertEqual(match["flow_id"], flow_match.DEFAULT_FLOW_ID)


class SynthesisValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = _registry()

    def _raw(self, **overrides) -> dict:
        raw = {
            "label": "Research and verify",
            "description": "A bespoke two-stage route",
            "entry": "ingress",
            "nodes": [
                {"id": "ingress", "label": "Intake", "type": "ingress"},
                {"id": "work", "label": "Do the work", "type": "agent",
                 "agent": "executor",
                 "capabilities": ["synthesize", "launch_missiles"]},
                {"id": "check", "label": "Review", "type": "verifier",
                 "agent": "verifier", "capabilities": ["review_outcome"]},
                {"id": "done", "label": "Done", "type": "terminal"},
            ],
            "edges": [
                {"source": "ingress", "target": "work"},
                {"source": "work", "target": "check"},
                {"source": "check", "target": "done"},
            ],
            "budgets": {"max_iterations": 2},
        }
        raw.update(overrides)
        return raw

    def test_valid_graph_passes_and_becomes_instance_ready(self) -> None:
        graph = validate_synthesized(self._raw(), self.registry,
                                     source_prompt="build me a route")
        self.assertTrue(graph["synthesized"])
        self.assertEqual(graph["entry"], "ingress")
        self.assertTrue(graph["id"].startswith("synthesized_"))
        self.assertEqual(graph["instance_schema"], 1)
        self.assertEqual(graph["source_prompt"], "build me a route")
        for node in graph["nodes"]:
            self.assertEqual(node["runtime_status"], "idle")

    def test_capabilities_the_agent_lacks_are_dropped_never_granted(self) -> None:
        graph = validate_synthesized(self._raw(), self.registry)
        work = next(node for node in graph["nodes"] if node["id"] == "work")
        self.assertEqual(list(work["capabilities"]), ["synthesize"])
        self.assertNotIn("launch_missiles", graph["capabilities"])

    def test_unknown_agent_is_rejected(self) -> None:
        raw = self._raw()
        raw["nodes"][1]["agent"] = "shadow_agent"
        with self.assertRaises(ValueError):
            validate_synthesized(raw, self.registry)

    def test_graph_without_a_terminal_is_rejected(self) -> None:
        raw = self._raw()
        raw["nodes"] = [node for node in raw["nodes"] if node["id"] != "done"]
        raw["edges"] = [edge for edge in raw["edges"] if edge["target"] != "done"]
        with self.assertRaises(ValueError):
            validate_synthesized(raw, self.registry)

    def test_unbudgeted_cycle_is_rejected(self) -> None:
        raw = self._raw()
        raw["edges"].append({"source": "check", "target": "work"})
        raw["budgets"] = {}
        with self.assertRaises(ValueError):
            validate_synthesized(raw, self.registry)

    def test_unsupported_node_type_is_rejected(self) -> None:
        raw = self._raw()
        raw["nodes"][1]["type"] = "shell_spawner"
        with self.assertRaises(ValueError):
            validate_synthesized(raw, self.registry)


if __name__ == "__main__":
    unittest.main()
