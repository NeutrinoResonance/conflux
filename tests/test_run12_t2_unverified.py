"""Acceptance test for run-12 transformation T2 (work item A).

In run 12, soundness checks that failed closed on HTTP 402 (Insufficient funds)
were stored as postcheck_failed. Identical re-checks were then held as a
"non-idempotent retry after failed postcondition" (act_f2e51f2cc42840a1).
A check that produced no verdict is missing evidence, not a failed check.
Evidence: tests/fixtures/run12_netbsd/manifest.json and
~/evidence/analysis/run12-netbsd/t2_replay.txt.
"""

import json
import tempfile
import unittest
from pathlib import Path

import pytest

from conflux.history import History
from conflux.orchestrator import ControlState, Orchestrator
from conflux.providers import ChatResult, ProviderError
from conflux.trace import Trace
from tests.test_action_governor import _Client, _body, _config, _response

APPROVE = {"verdict": "approve", "reason": "bounded build",
           "objection": "resource use", "arguments": None, "probe": None}


class _CheckerClient(_Client):
    """The action critic answers; the soundness checker gets `checker` instead."""

    def __init__(self, checker, **kwargs):
        super().__init__(**kwargs)
        self.checker = checker

    async def chat(self, model, messages, **kwargs) -> ChatResult:
        if "soundness-checker agent" not in messages[-1]["content"]:
            return await super().chat(model, messages, **kwargs)
        self.critic_calls += 1
        if self.checker == "402":
            raise ProviderError(model.name, 402, "Insufficient funds")
        return ChatResult(text=json.dumps(self.checker), tokens_in=13, tokens_out=5,
                          cost_usd=0.000018)


class SoundnessNoVerdictTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        db = str(Path(self.tmp.name) / "trace.db")
        self.trace, self.history = Trace(db), History(db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    async def check_then_retry(self, checker):
        client = _CheckerClient(checker, raw=[_response("make -j2"), _response("make -j2")],
                                critic_json=[APPROVE, APPROVE])
        orch = Orchestrator(_config(), client, self.trace, ControlState(),
                            history=self.history)
        await orch.run_tool_turn("session-t2", _body())
        _, _, pending = orch.governor.record_results("session-t2", "result-task", [{
            "role": "tool", "tool_call_id": "call-original", "content": "build complete",
        }])
        outcome = await orch.governor.begin_soundness_checks(
            "session-t2", "check-task", _body(), _config().models["executor"], pending)
        status = orch.action_store.get(pending[0])["status"]
        await orch.run_tool_turn("session-t2", _body())
        retry = next(a for a in orch.action_store.list() if a["action_id"] != pending[0])
        return outcome, status, retry

    @pytest.mark.xfail(strict=True, reason="T2: 402 no-verdict stored as postcheck_failed")
    async def test_provider_402_leaves_action_unverified_and_retry_not_held(self) -> None:
        outcome, status, retry = await self.check_then_retry("402")
        self.assertEqual(status, "unverified")
        self.assertIn('"soundness_decision": "unverified"', outcome.directives[0])
        self.assertIn("402", outcome.directives[0])
        self.assertEqual(retry["status"], "released")

    async def test_real_fail_verdict_still_holds_identical_retry(self) -> None:
        outcome, status, retry = await self.check_then_retry({
            "decision": "fail", "hypothesis": "build did not finish",
            "test_description": "artifact absent", "reason": "no artifact", "probe": None})
        self.assertEqual(status, "postcheck_failed")
        self.assertEqual(retry["status"], "human_pending")
        self.assertIn("failed its postcondition", json.dumps(retry["verdict"]))
