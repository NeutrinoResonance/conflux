from __future__ import annotations

import unittest

from conflux.config import Config, Execution, Model, Provider, Supervision
from conflux.control import ControlState
from conflux.orchestrator import Budget, Orchestrator, TurnOptions
from conflux.providers import ChatResult
from conflux.verifier import VerifyReport


class _History:
    def repair_stats(self):
        return []


class _Verifier:
    def __init__(self) -> None:
        self.calls = 0

    async def verify(self, **kwargs):
        self.calls += 1
        return VerifyReport(
            score=0.9, passed=True, verifier="independent-reviewer"
        )


class EnsembleWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_model_samples_keep_identity_temperature_and_union(self) -> None:
        provider = Provider("test", "https://invalid.test/v1", "env:TEST_KEY")
        model = Model(
            name="executor", provider="test", id="executor-id", family="family-a",
            roles=("executor",), logprobs=False, top_logprobs_max=5,
            price_in_per_m=1, price_out_per_m=1,
        )
        cfg = Config(
            providers={"test": provider}, models={"executor": model},
            default_executor="executor", utility="executor", verifier_pool=[],
            supervision=Supervision(confirm_new_sessions=False),
            execution=Execution(backend="off"), learned_routing=False,
        )
        orchestrator = object.__new__(Orchestrator)
        orchestrator.cfg = cfg
        orchestrator.control = ControlState()
        orchestrator.history = _History()
        orchestrator.verifier = _Verifier()
        calls = []

        async def execute(chain, messages, log, attempt, *, temperature=0.2):
            calls.append((chain[0].name, temperature, messages[-1]["content"]))
            return ChatResult(
                text=f"candidate at {temperature}", tokens_in=2, tokens_out=3,
                cost_usd=0.000005,
            ), chain[0]

        async def evidence(text, log, model=""):
            return None

        orchestrator._execute = execute
        orchestrator._run_evidence = evidence
        events = []
        options = TurnOptions(
            strategy="union", ensemble_n=3, candidate_mode="same_model",
            temperatures=(0.1, 0.7, 1.2),
        )
        result = await orchestrator._ensemble_turn(
            "session", "task", [{"role": "user", "content": "question"}],
            "question", [], Budget(1.0),
            lambda kind, **data: events.append((kind, data)),
            options=options, primary_model="executor",
        )

        samples = [event for event in events if event[0] == "ensemble_candidate"]
        self.assertEqual(sorted(event[1]["candidate_id"] for event in samples), [
            "candidate_1", "candidate_2", "candidate_3"
        ])
        self.assertEqual(sorted(event[1]["temperature"] for event in samples), [
            0.1, 0.7, 1.2
        ])
        self.assertTrue(all(event[1]["model"] == "executor" for event in samples))
        self.assertEqual([call[1] for call in calls[:3]], [0.1, 0.7, 1.2])
        self.assertIn("candidate at 0.1", calls[-1][2])
        self.assertIn("candidate at 0.7", calls[-1][2])
        self.assertIn("candidate at 1.2", calls[-1][2])
        self.assertTrue(result.executor.startswith("union("))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
