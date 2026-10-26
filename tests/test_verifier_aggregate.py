import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from conflux.config import load
from conflux.providers import ChatResult
from conflux.verifier import Verifier


class Client:
    """Scores every criterion T except the one whose name starts with `fail`."""
    def __init__(self, fail):
        self.fail, self.max_tokens = fail, []

    async def chat(self, model, messages, **kwargs):
        self.max_tokens.append(kwargs["max_tokens"])
        failing = f"Evaluation criterion: {self.fail}" in messages[0]["content"]
        return ChatResult("notes <score>" + ("A" if failing else "T") + "</score>", 1, 1, 0.0)


@pytest.mark.parametrize("aggregate, passed", [("min", False), ("mean", True)])
def test_one_failing_criterion_fails_the_verdict_unless_averaged(aggregate, passed):
    cfg = load(Path(__file__).parents[1] / "models.yaml")
    cfg.supervision = replace(cfg.supervision, criteria_aggregate=aggregate)
    client = Client("Errors")
    report = asyncio.run(Verifier(client, cfg).verify(
        task="t", output="o", contract=[], executor_family="deepseek", evidence="ran"))
    assert report.passed is passed
    assert set(client.max_tokens) == {cfg.supervision.verify_max_tokens}
    if not passed:
        assert "Errors" in report.feedback
