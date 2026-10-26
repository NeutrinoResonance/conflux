"""Fake-only integration of decision panels with the fixed action pipeline."""
import asyncio
import json
from dataclasses import replace

import pytest

from conflux.control import ControlState
from conflux.conversation_graph import ConversationGraphStore
from conflux.decider import DeciderUnavailable
from conflux.flow_synthesis import validate_synthesized
from conflux.orchestrator import Orchestrator
from conflux.providers import ProviderError
from conflux.trace import Trace
from conflux.verifier import VerifyReport
from tests.test_action_governor import _body, _response, _tool_call
from tests.test_decider import FakeClient, config, decision


class FakeVerifier:
    def __init__(self, report=None):
        self.report = report or VerifyReport(1, True, verifier="fake-verifier")
        self.calls = 0

    async def verify(self, **kwargs):
        self.calls += 1
        if isinstance(self.report, Exception):
            raise self.report
        return self.report


def harness(tmp_path, client, cfg=None, filename="trace.db"):
    cfg = cfg or config()
    trace = Trace(str(tmp_path / filename))
    orch = Orchestrator(cfg, client, trace, ControlState())
    orch.verifier = FakeVerifier()
    return orch


def final(text="The observation is ready."):
    r = _response("cat /tmp/item")
    r["choices"][0] = {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
    return r


def test_deciders_precede_executor_and_preserve_tool_pairing(tmp_path):
    client = FakeClient(raw=[_response("cat /tmp/item")])
    orch = harness(tmp_path, client)
    result = asyncio.run(orch.run_tool_turn("session", _body()))
    assert [c[0] for c in client.calls] == ["decider", "decider", "executor"]
    assert result["choices"][0]["message"]["tool_calls"][0]["id"] == "call-original"
    sent = client.calls[-1][2]["messages"]
    assert sent[:-1] == _body()["messages"]
    assert "Conflux decision" in sent[-1]["content"]
    action = orch.action_store.list()[0]
    assert action["proposal"]["decision_id"]


def test_decider_receives_request_tool_contracts(tmp_path):
    body = _body()
    body["tools"][0]["function"]["description"] = "Inspect the sandbox using a command"
    client = FakeClient(raw=[_response("cat /tmp/item")])
    orch = harness(tmp_path, client)
    asyncio.run(orch.run_tool_turn("session", body))
    for call in client.calls[:2]:
        prompt = call[2][0]["content"]
        context = json.loads(prompt.split("---\n")[3])
        assert context["tools"] == [body["tools"][0]["function"]]


def _results(body, response, content="verified data"):
    message = response["choices"][0]["message"]
    return _body(body["messages"] + [message] + [
        {"role": "tool", "tool_call_id": c["id"], "content": content}
        for c in message["tool_calls"]])


def _finish_checks(orch, body, result):
    for _ in range(12):
        if not result.get("conflux_checks"):
            return result
        body = _results(body, result)
        result = asyncio.run(orch.run_tool_turn("session", body))
    pytest.fail("completion checks did not finish")


def test_done_without_checks_reconsults_and_never_generates_a_final_answer(tmp_path):
    cfg = config(max_decisions_per_request=2)
    unchecked = decision(True)
    unchecked["check"] = []
    client = FakeClient({m: [unchecked, decision()] for m in cfg.decider.members},
                        raw=[_response("stat /tmp/item")])
    orch = harness(tmp_path, client, cfg)
    result = asyncio.run(orch.run_tool_turn("session", _body()))
    assert result["choices"][0]["message"].get("tool_calls")
    assert [c[0] for c in client.calls] == ["decider"] * 4 + ["executor"]
    assert "completion_evidence" in client.calls[2][2][0]["content"]
    assert "unchecked" in client.calls[2][2][0]["content"]
    assert {o["status"] for o in orch.decision_store.obligations("session")} == {"unchecked"}
    assert orch.verifier.calls == 0


def test_unchecked_done_exhaustion_is_incomplete_without_executor_calls(tmp_path):
    cfg = config(max_decisions_per_request=2)
    unchecked = decision(True)
    unchecked["check"] = []
    client = FakeClient({m: [unchecked, unchecked] for m in cfg.decider.members})
    orch = harness(tmp_path, client, cfg)
    result = asyncio.run(orch.run_tool_turn("session", _body()))
    assert result["conflux"]["status"] == "incomplete"
    assert result["conflux"]["reason"] == "bounded reconsideration exhausted"
    assert [c[0] for c in client.calls] == ["decider"] * 4
    assert orch.verifier.calls == 0


def test_all_done_members_claims_and_invariants_pass_before_final_after_restart(tmp_path):
    cfg = config(max_checks_per_turn=1)
    invariant = decision(True, resource="/tmp/start", claim="initial data is unchanged")
    invariant["check"][0].update(arguments={"command": "cat /tmp/start"},
                                 predicate={"type": "contains", "value": "initial data"})
    client = FakeClient({"executor": [decision(True)], "second": [invariant]})
    orch = harness(tmp_path, client, cfg)
    body = _body()
    first = asyncio.run(orch.run_tool_turn("session", body))
    assert first.get("conflux_checks") and orch.verifier.calls == 0
    assert [c[0] for c in client.calls] == ["decider", "decider"]
    # A new process resumes the same completion candidate and each member's scope.
    resumed_client = FakeClient(raw=[final("Verified completion")])
    resumed = harness(tmp_path, resumed_client, cfg)
    body = _results(body, first)
    second = asyncio.run(resumed.run_tool_turn("session", body))
    assert not resumed_client.calls and resumed.verifier.calls == 0
    call = second["choices"][0]["message"]["tool_calls"][0]
    assert json.loads(call["function"]["arguments"]) == {"command": "cat /tmp/start"}
    assert all(a["proposal"]["call_id"].startswith("conflux_check_") for a in resumed.action_store.list())
    result = asyncio.run(resumed.run_tool_turn("session", _results(body, second, "initial data")))
    assert result["choices"][0]["message"]["content"] == "Verified completion"
    assert {o["status"] for o in resumed.decision_store.obligations("session")} == {"passed"}
    assert [c[0] for c in resumed_client.calls] == ["executor"]
    assert resumed.verifier.calls == 1
    assert not resumed.decision_store.waiting("session")


@pytest.mark.parametrize("observation", [
    '{"state":"running","stdout":"regression observed"}',
    '{"exit_code":1,"stdout":"verified data"}',
])
def test_failed_done_checks_reconsult_decider_and_revoke_completion(tmp_path, observation):
    cfg = config(max_decisions_per_request=1)
    client = FakeClient({m: [decision(True), decision()] for m in cfg.decider.members},
                        raw=[_response("stat /tmp/item")])
    orch = harness(tmp_path, client, cfg)
    first = asyncio.run(orch.run_tool_turn("session", _body()))
    assert first.get("conflux_checks") and client.raw
    result = asyncio.run(orch.run_tool_turn("session", _results(_body(), first, observation)))
    assert not result.get("conflux_checks")
    assert result["choices"][0]["message"].get("tool_calls")
    assert {o["status"] for o in orch.decision_store.obligations("session")} == {"failed"}
    assert "obligation_failed" in client.calls[2][2][0]["content"]
    assert "failed" in client.calls[2][2][0]["content"]
    assert [c[0] for c in client.calls] == ["decider"] * 4 + ["executor"]
    assert orch.verifier.calls == 0


@pytest.mark.parametrize("command", ["rm /tmp/item", "cat /tmp/other"])  # proven escapes; unprovable ones go to the senate
def test_done_checks_rejected_by_scope_reconsult_without_releasing(tmp_path, command):
    cfg = config(max_decisions_per_request=1)
    d = decision(True)
    d["check"][0]["arguments"]["command"] = command
    client = FakeClient({m: [d] for m in cfg.decider.members})
    orch = harness(tmp_path, client, cfg)
    result = asyncio.run(orch.run_tool_turn("session", _body()))
    assert result["conflux"]["status"] == "incomplete"
    assert {o["status"] for o in orch.decision_store.obligations("session")} == {"unchecked"}
    assert not orch.action_store.list() and orch.verifier.calls == 0


def test_done_waits_for_released_calls_even_without_claims(tmp_path):
    cfg = config(max_decisions_per_request=1)
    client = FakeClient({m: [decision(), decision(True)] for m in cfg.decider.members},
                        raw=[_response("stat /tmp/item"), final()])
    orch = harness(tmp_path, client, cfg)
    body = _body()
    first = asyncio.run(orch.run_tool_turn("session", body))
    client.calls.clear()
    waiting = asyncio.run(orch.run_tool_turn("session", body))
    assert waiting["conflux"]["status"] == "incomplete" and not client.calls
    assert not orch.decision_store.obligations("session")
    body = _results(body, first, "stat output")
    checked = asyncio.run(orch.run_tool_turn("session", body))
    result = _finish_checks(orch, body, checked)
    assert not result.get("conflux") and orch.verifier.calls == 1


def test_failed_batched_done_check_reconsults_before_remaining_checks(tmp_path):
    cfg = config(max_checks_per_turn=1, max_decisions_per_request=1)
    client = FakeClient({m: [decision(True), decision()] for m in cfg.decider.members},
                        raw=[_response("stat /tmp/item")])
    orch = harness(tmp_path, client, cfg)
    first = asyncio.run(orch.run_tool_turn("session", _body()))
    result = asyncio.run(orch.run_tool_turn("session", _results(_body(), first, "regression")))
    assert not result.get("conflux_checks")
    assert [c[0] for c in client.calls] == ["decider"] * 4 + ["executor"]
    assert {o["status"] for o in orch.decision_store.obligations("session")} == {"failed"}
    assert orch.verifier.calls == 0


@pytest.mark.parametrize("old_status", ["failed", "unchecked"])
def test_done_can_supply_replacement_checks_for_old_claims(tmp_path, old_status):
    cfg = config(max_decisions_per_request=1)
    old = decision(True)
    if old_status == "unchecked":
        old["check"] = []
    client = FakeClient({m: [old, decision(True)] for m in cfg.decider.members}, raw=[final()])
    orch = harness(tmp_path, client, cfg)
    body = _body()
    first = asyncio.run(orch.run_tool_turn("session", body))
    if old_status == "failed":
        body = _results(body, first, "regression")
    else:
        assert first["conflux"]["status"] == "incomplete"
    replacement = asyncio.run(orch.run_tool_turn("session", body))
    assert replacement.get("conflux_checks")
    result = _finish_checks(orch, body, replacement)
    assert result["choices"][0]["message"]["content"] == final()["choices"][0]["message"]["content"]
    assert {o["status"] for o in orch.decision_store.obligations("session")} == {"passed"}
    assert orch.verifier.calls == 1


@pytest.mark.parametrize("change", ["goal", "concern"])
def test_changed_context_revokes_checked_completion_before_final(tmp_path, change):
    cfg = config(max_decisions_per_request=1)
    client = FakeClient({m: [decision(True), decision()] for m in cfg.decider.members},
                        raw=[_response("stat /tmp/item")])
    orch = harness(tmp_path, client, cfg)
    body = _body()
    first = asyncio.run(orch.run_tool_turn("session", body))
    body = _results(body, first)
    if change == "goal":
        body["messages"].append({"role": "user", "content": "Now inspect the changed goal"})
    else:
        orch.decision_store.concern("session", "new_feedback", "observed a regression")
    result = asyncio.run(orch.run_tool_turn("session", body))
    assert result["choices"][0]["message"].get("tool_calls")
    assert not result.get("conflux_checks")
    assert [c[0] for c in client.calls] == ["decider"] * 4 + ["executor"]
    assert orch.verifier.calls == 0


def test_proxy_dispatches_checks_after_actions_then_evidence_allows_done_after_restart(tmp_path):
    d = decision(access="write", claim="item contains verified data")
    d["check"][0]["tool"] = "invented_shell"
    client = FakeClient({"executor": [decision(access="write")], "second": [d]}, raw=[_response("stat /tmp/item")])
    orch = harness(tmp_path, client)
    first = asyncio.run(orch.run_tool_turn("session", _body()))
    creator = orch.decision_store.obligations("session")[0]["decision_id"]
    # A restarted orchestrator dispatches the nonselected member's check without
    # consulting either model, using the original scope (including read in write).
    client = FakeClient({m: [decision(True)] for m in config().decider.members}, raw=[final()])
    orch = harness(tmp_path, client)
    body = _results(_body(), first, "stat output")
    second = asyncio.run(orch.run_tool_turn("session", body))
    assert not client.calls
    call = second["choices"][0]["message"]["tool_calls"][0]
    assert call["id"] != "call-original" and call["id"].startswith("conflux_check_")
    assert call["function"]["name"] == "terminal"
    row = orch.decision_store.connection.execute(
        "SELECT decision_id,is_check,result FROM decision_calls WHERE call_id=?", (call["id"],)).fetchone()
    assert row == (creator, 1, None)
    assert orch.decision_store.obligations("session")[0]["status"] == "pending"
    result = asyncio.run(orch.run_tool_turn("session", _results(body, second)))
    result = _finish_checks(orch, _results(body, second), result)
    assert result["choices"][0]["message"]["content"] == final()["choices"][0]["message"]["content"]
    assert orch.decision_store.obligations("session")[0]["status"] == "passed"
    assert orch.verifier.calls == 1


def test_checks_wait_for_all_action_results_and_are_not_reissued_while_inflight(tmp_path):
    raw = _response("stat /tmp/item")
    raw["choices"][0]["message"]["tool_calls"].append(_tool_call("ls /tmp/item", "sibling"))
    client = FakeClient({"executor": [decision(claim="claim")]}, raw=[raw])
    orch = harness(tmp_path, client)
    first = asyncio.run(orch.run_tool_turn("session", _body()))
    client.calls.clear()
    partial = _body(_body()["messages"] + [first["choices"][0]["message"],
        {"role": "tool", "tool_call_id": "call-original", "content": "stat"}])
    assert asyncio.run(orch.run_tool_turn("session", partial))["conflux"]["status"] == "incomplete"
    assert not client.calls
    partial["messages"].append({"role": "tool", "tool_call_id": "sibling", "content": "listing"})
    checked = asyncio.run(orch.run_tool_turn("session", partial))
    assert checked["choices"][0]["message"]["tool_calls"]
    assert asyncio.run(orch.run_tool_turn("session", partial))["conflux"]["status"] == "incomplete"
    assert not client.calls


def test_pending_checks_are_batched_with_fresh_ids_and_stay_evidence_at_done(tmp_path):
    cfg = config(max_checks_per_turn=2, max_decisions_per_request=1)
    d = decision(claim="claim")
    d["expected_changes"] = [f"claim {i}" for i in range(5)]
    d["check"] = [{**d["check"][0], "claim": c} for c in d["expected_changes"]]
    client = FakeClient({"executor": [d]}, raw=[_response("stat /tmp/item")])
    orch = harness(tmp_path, client, cfg)
    first = asyncio.run(orch.run_tool_turn("session", _body()))
    client.calls.clear()
    body = _results(_body(), first, "stat")
    ids = []
    for count in (2, 2, 1):
        result = asyncio.run(orch.run_tool_turn("session", body))
        calls = result["choices"][0]["message"]["tool_calls"]
        assert len(calls) == count and not client.calls
        ids.extend(c["id"] for c in calls)
        body = _results(body, result, '{"exit_code":1,"stdout":"verified data"}')
    assert len(set(ids)) == 5
    client.decisions = {m: [decision(True)] for m in cfg.decider.members}
    client.raw = [final("must suppress")]
    result = asyncio.run(orch.run_tool_turn("session", body))
    # Earlier steps' claims stay evidence; completion proceeds to the done
    # decision's own checks, which must pass.
    calls = result["choices"][0]["message"].get("tool_calls") or []
    assert calls and all(c["id"].startswith("conflux_check_") for c in calls)
    assert all(o["status"] == "failed" for o in orch.decision_store.obligations("session")[:5])
    assert not any(c[0] == "executor" for c in client.calls)


@pytest.mark.parametrize("command", ["cat /tmp/other", "rm /tmp/item"])
def test_check_scope_stays_with_creating_decision(tmp_path, command):
    d = decision(claim="claim")
    d["check"][0]["arguments"]["command"] = command
    client = FakeClient({"executor": [d, decision()]},
                        raw=[_response("stat /tmp/item")] + [_response("cat /tmp/item")] * 6)
    orch = harness(tmp_path, client)
    first = asyncio.run(orch.run_tool_turn("session", _body()))
    client.calls.clear()
    result = asyncio.run(orch.run_tool_turn("session", _results(_body(), first, "stat")))
    # A check the gate cannot scope leaves its claim unchecked; the decider is consulted again.
    assert "obligation checks blocked" not in str(result)
    assert client.calls
    obligation = orch.decision_store.obligations("session")[0]
    assert obligation["status"] == "unchecked"
    assert "outside the decision scope" in obligation["evidence"][-1]["reason"]


def test_check_calls_cross_the_deterministic_governor_policy_gate(tmp_path):
    body = _body()
    body["tools"][0]["function"]["parameters"]["additionalProperties"] = False
    body["tools"][0]["function"]["parameters"]["properties"]["limit"] = {"type": "integer"}
    d = decision(claim="claim")
    d["check"][0]["arguments"]["limit"] = "not an integer"
    client = FakeClient({"executor": [d]}, raw=[_response("stat /tmp/item")])
    orch = harness(tmp_path, client)
    first = asyncio.run(orch.run_tool_turn("session", body))
    following = _results(body, first, "stat")
    following["tools"] = body["tools"]
    client.calls.clear()
    result = asyncio.run(orch.run_tool_turn("session", following))
    assert not result["choices"][0]["message"].get("tool_calls") and not client.calls
    obligation = orch.decision_store.obligations("session")[0]
    assert obligation["status"] == "failed"
    assert "argument_schema" in obligation["evidence"][-1]["reason"]


@pytest.mark.parametrize("blocked", [False, True])
def test_checks_cross_senate_review_without_replacing_original_scope(tmp_path, blocked):
    from conflux.providers import ChatResult
    class Client(FakeClient):
        async def chat(self, model, messages, **kwargs):
            result = await super().chat(model, messages, **kwargs)
            if blocked and "You decide the next step" not in messages[-1]["content"]:
                return ChatResult("<danger>T</danger><how>check would damage the preserved state</how>", 2, 3, 0)
            return result
    body = _body()
    body["tools"].append({"type": "function", "function": {"name": "write_file", "parameters": {
        "type": "object", "required": ["path", "content"], "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}}}})
    d = decision(access="write", claim="claim")
    d["check"][0].update(tool="write_file", arguments={"path": "/tmp/item", "content": "data"})
    client = Client({"executor": [d], "second": [decision(access="write")]}, raw=[_response("stat /tmp/item")])
    orch = harness(tmp_path, client)
    orch.governor.manifest_policies["write_file"] = {"trusted": True, "side_effect": "write", "allowed_targets": ["/tmp/item"]}
    first = asyncio.run(orch.run_tool_turn("session", body))
    creator = orch.decision_store.obligations("session")[0]["decision_id"]
    following = _results(body, first, "stat")
    following["tools"] = body["tools"]
    client.calls.clear()
    result = asyncio.run(orch.run_tool_turn("session", following))
    assert bool(result["choices"][0]["message"].get("tool_calls")) is not blocked
    assert client.calls and all(c[0] == "senate" for c in client.calls)
    assert orch.action_store.list()[0]["proposal"]["decision_id"] == creator
    if blocked:
        obligation = orch.decision_store.obligations("session")[0]
        assert obligation["status"] == "failed" and obligation["evidence"][-1]["source"] == "governor"
        assert "preserved state" in obligation["evidence"][-1]["reason"]


@pytest.mark.parametrize("missing", ["check", "tool"])
def test_unchecked_obligations_are_visible_to_decider_at_done(tmp_path, missing):
    cfg = config(max_decisions_per_request=1)
    d = decision(claim="claim without an executable check")
    if missing == "check":
        d["check"] = []
    else:
        d["check"][0].update(tool="invented", arguments={"path": "/tmp/item"})
    client = FakeClient({"executor": [d]}, raw=[_response("stat /tmp/item")])
    orch = harness(tmp_path, client, cfg)
    first = asyncio.run(orch.run_tool_turn("session", _body()))
    done = decision(True)
    done["next_step"] = ""
    client.decisions = {m: [done] for m in cfg.decider.members}
    client.raw = [final("must suppress")]
    client.calls.clear()
    result = asyncio.run(orch.run_tool_turn("session", _results(_body(), first, "stat")))
    # Earlier steps' claims stay evidence; completion proceeds to the done
    # decision's own checks, which must pass.
    calls = result["choices"][0]["message"].get("tool_calls") or []
    assert calls and all(c["id"].startswith("conflux_check_") for c in calls)
    assert orch.decision_store.obligations("session")[0]["status"] == "unchecked"
    assert "unchecked" in client.calls[0][2][0]["content"]
    assert "claim without an executable check" in client.calls[0][2][0]["content"]


def test_held_check_approval_retains_creating_scope_and_does_not_consult_models(tmp_path):
    d = decision(access="write", claim="claim")
    d["check"][0]["arguments"]["command"] = "touch /tmp/item"
    client = FakeClient({"executor": [d], "second": [decision(access="write")]}, raw=[_response("stat /tmp/item")])
    orch = harness(tmp_path, client)
    first = asyncio.run(orch.run_tool_turn("session", _body()))
    creator = orch.decision_store.obligations("session")[0]["decision_id"]
    orch.governor.manifest_policies["terminal"] = {"requires_human": True}
    body = _results(_body(), first, "stat")
    held = asyncio.run(orch.run_tool_turn("session", body))
    assert not held["choices"][0]["message"].get("tool_calls")
    action = next(a for a in orch.action_store.list() if a["status"] == "human_pending")
    orch.action_store.decide(action["action_id"], "approve")
    client.calls.clear()
    released = asyncio.run(orch.run_tool_turn("session", body))
    assert released["choices"][0]["message"].get("tool_calls") and not client.calls
    row = orch.decision_store.connection.execute(
        "SELECT decision_id,is_check FROM decision_calls WHERE is_check=1").fetchone()
    assert row == (creator, 1)


def test_all_senate_approval_concerns_go_only_to_decider(tmp_path):
    cfg = config()
    cfg.senate.concerns = "top"
    cfg.senate.members = ["critic", "second", "executor"]
    # A structured trusted write makes the critic necessary without permitting
    # an opaque arbitrary command in the decision's scope.
    body = _body()
    body["tools"] = [{"type": "function", "function": {"name": "write_file", "parameters": {
        "type": "object", "required": ["path", "content"], "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}}}}]
    raw = _response("unused")
    raw["choices"][0]["message"]["tool_calls"] = [{"id": "write", "function": {
        "name": "write_file", "arguments": json.dumps({"path": "/tmp/item", "content": "hello"})}}]
    client = FakeClient({"executor": [decision(access="write"), decision(access="write")],
                         "second": [decision(access="write"), decision(access="write")]}, raw=[raw], senate="check the preserved data")
    orch = harness(tmp_path, client, cfg)
    orch.governor.manifest_policies["write_file"] = {
        "trusted": True, "side_effect": "write", "allowed_targets": ["/tmp/item"]}
    result = asyncio.run(orch.run_tool_turn("session", body))
    assert result["choices"][0]["message"].get("tool_calls")
    order = [c[0] for c in client.calls]
    # The senate's approval releases the action; its concerns are not a reason
    # to consult the panel a second time for the same step.
    assert order == ["decider", "decider", "executor", "senate", "senate", "senate"]
    concerns = orch.decision_store.context("session")["concerns"]
    assert {c["data"]["model"] for c in concerns if c["source"] == "senate"} == {"critic", "second", "executor"}
    # Every concern reaches the panel at the next consultation, never the executor.
    from conflux.decider import decision_context
    assert "check the preserved data" in decision_context([], [], **orch.decision_store.context("session"))
    assert "check the preserved data" not in client.calls[2][2]["messages"][-1]["content"]


def test_premature_final_is_suppressed_until_panel_done_and_verification(tmp_path):
    client = FakeClient({"executor": [decision(), decision(True)], "second": [decision(), decision(True)]},
                        raw=[final("Unverified draft"), final()])
    orch = harness(tmp_path, client)
    result = asyncio.run(orch.run_tool_turn("session", _body()))
    result = _finish_checks(orch, _body(), result)
    assert result["choices"][0]["message"]["content"] == "The observation is ready."
    assert orch.verifier.calls == 1


@pytest.mark.parametrize("verifier", [RuntimeError("unavailable"), VerifyReport(0, False, feedback="unsupported claim")])
def test_verifier_failure_never_releases_best_draft(tmp_path, verifier):
    cfg = config(max_decisions_per_request=1)
    client = FakeClient({"executor": [decision(True)], "second": [decision(True)]}, raw=[final("secret draft")])
    orch = harness(tmp_path, client, cfg)
    orch.verifier = FakeVerifier(verifier)
    result = asyncio.run(orch.run_tool_turn("session", _body()))
    result = _finish_checks(orch, _body(), result)
    assert result["conflux"]["status"] == "incomplete"
    assert "secret draft" not in result["choices"][0]["message"]["content"]


def test_budget_and_decider_outage_do_not_generate_executor(tmp_path):
    cfg = config(max_repairs=0)
    client = FakeClient({n: [ProviderError(n, 503, "offline")] for n in cfg.decider.members})
    orch = harness(tmp_path, client, cfg)
    with pytest.raises(DeciderUnavailable):
        asyncio.run(orch.run_tool_turn("session", _body()))
    assert not any(c[0] == "executor" for c in client.calls)
    orch.control.budget_usd = 0.000001
    with pytest.raises(DeciderUnavailable, match="budget"):
        asyncio.run(orch.run_tool_turn("other-session", _body()))


def test_nonselected_members_failed_check_survives_restart_as_evidence(tmp_path):
    client = FakeClient({"second": [decision(claim="second member claim")]}, raw=[_response("cat /tmp/item")])
    orch = harness(tmp_path, client)
    asyncio.run(orch.run_tool_turn("session", _body()))
    next_client = FakeClient({"executor": [decision(True)], "second": [decision(True)]}, raw=[final("must suppress")])
    cfg = config(max_decisions_per_request=1)
    resumed = harness(tmp_path, next_client, cfg)
    messages = _body()["messages"] + [{"role": "tool", "tool_call_id": "call-original", "content": '{"exit_code":0}'}]
    result = asyncio.run(resumed.run_tool_turn("session", _body(messages)))
    # Earlier steps' claims stay evidence; completion proceeds to the done
    # decision's own checks, which must pass.
    calls = result["choices"][0]["message"].get("tool_calls") or []
    assert calls and all(c["id"].startswith("conflux_check_") for c in calls)
    assert resumed.decision_store.obligations("session")[0]["status"] == "failed"


def test_executor_fallback_gets_fresh_family_validation(tmp_path):
    cfg = config(family_rule="different_from_executor", max_repairs=0)
    cfg.models["executor"] = replace(cfg.model("executor"), fallbacks=("critic",))
    client = FakeClient(raw=[ProviderError("executor", 503, "down"), _response("cat /tmp/item")])
    orch = harness(tmp_path, client, cfg)
    result = asyncio.run(orch.run_tool_turn("session", _body()))
    assert result["choices"][0]["message"]["tool_calls"]
    executors = [i for i, c in enumerate(client.calls) if c[0] == "executor"]
    assert len(executors) == 2
    assert client.calls[executors[1] - 2][1] == "executor"


def test_graph_node_overrides_snapshot_and_exclude_decider_prompts(tmp_path):
    client = FakeClient(raw=[_response("cat /tmp/item")])
    orch = harness(tmp_path, client)
    store = ConversationGraphStore(orch.flow_runtime.connection, orch.flow_runtime.registry, orch.cfg)
    endeavor = store.create_endeavor("Decision")
    store.create_conversation(endeavor["id"], "Decision", session="session")
    pair = store.create_message_pair("session", "Inspect")
    instance = pair["workflow"]["instance_id"]
    store.update_workflow_node(instance, "decider", {"config": {"members": ["second"], "max_tokens": 25000, "prompt": "never executor input"}})
    plan = store.workflow_plan(instance)
    assert plan["decider"]["members"] == ["second"]
    assert "never executor input" not in plan["executor_prompts"]
    body = _body()
    body["metadata"] = {"workflow_instance_id": instance}
    asyncio.run(orch.run_tool_turn("session", body))
    assert client.calls[0][1] == "second"
    assert client.calls[0][3]["max_tokens"] == 25000
    run = orch.flow_runtime.recent_runs()[0]
    assert orch.flow_runtime.inspect(run["run_id"])["state"]["decider_plan"]["decider"]["members"] == ["second"]
    assert orch.cfg.decider.members == ["executor", "second"]


@pytest.mark.parametrize("bad", [{"frequency": "on_failure"}, {"done_requires": "none"}, {"members": ["missing"]}])
def test_graph_and_synthesis_validate_decider_settings(tmp_path, bad):
    orch = harness(tmp_path, FakeClient())
    graph = orch.flow_runtime.registry.flows["supervised_tool_turn"].as_dict()
    graph["nodes"] = [dict(n) for n in graph["nodes"]]
    next(n for n in graph["nodes"] if n["agent"] == "decider")["config"] = bad
    graph["nodes"] = list(graph["nodes"])
    graph["edges"] = list(graph["edges"])
    with pytest.raises(ValueError):
        ConversationGraphStore.validate_workflow_graph(graph, cfg=orch.cfg)
    with pytest.raises(ValueError):
        validate_synthesized(graph, orch.flow_runtime.registry, cfg=orch.cfg)


def test_concurrent_feedback_invalidates_in_flight_decision(tmp_path):
    class RacingClient(FakeClient):
        async def chat(self, model, messages, **kwargs):
            result = await super().chat(model, messages, **kwargs)
            orch.decision_store.concern("session", "concurrent", model.name)
            return result
    client = RacingClient()
    orch = harness(tmp_path, client)
    with pytest.raises(DeciderUnavailable, match="context changed"):
        asyncio.run(orch.run_tool_turn("session", _body()))
    assert not any(c[0] == "executor" for c in client.calls)


def test_anonymous_identity_rejected_without_calls(tmp_path):
    client = FakeClient()
    orch = harness(tmp_path, client)
    with pytest.raises(DeciderUnavailable, match="stable"):
        asyncio.run(orch.run_tool_turn("oneshot_anonymous", _body()))
    assert client.calls == []


def write_body_and_response():
    body = _body()
    body["tools"] = [{"type": "function", "function": {"name": "write_file", "parameters": {
        "type": "object", "required": ["path", "content"], "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}}}}]
    raw = _response("unused")
    raw["choices"][0]["message"]["tool_calls"] = [{"id": "exact-write-id", "type": "function", "function": {
        "name": "write_file", "arguments": json.dumps({"path": "/tmp/item", "content": "hello"})}}]
    return body, raw


def test_exact_operator_resume_reconsults_saved_plan_without_executor_regeneration(tmp_path):
    body, raw = write_body_and_response()
    cfg = config()
    client = FakeClient({m: [decision(access="write")] for m in cfg.decider.members}, raw=[raw])
    orch = harness(tmp_path, client, cfg)
    orch.governor.manifest_policies["write_file"] = {
        "trusted": True, "side_effect": "write", "allowed_targets": ["/tmp/item"], "requires_human": True}
    held = asyncio.run(orch.run_tool_turn("session", body))
    assert not held["choices"][0]["message"].get("tool_calls")
    item = orch.action_store.list()[0]
    orch.action_store.decide(item["action_id"], "approve")
    # Runtime defaults changed after the hold; the run's saved node settings win.
    cfg.decider.members = ["critic"]
    resumed_client = FakeClient({"executor": [decision(access="write")], "second": [decision(access="write")]})
    resumed = harness(tmp_path, resumed_client, cfg)
    resumed.governor.manifest_policies = orch.governor.manifest_policies
    result = asyncio.run(resumed.run_tool_turn("session", body))
    assert result == raw
    # Nothing ran while held, so the decision that produced it still stands.
    assert [c[0] for c in resumed_client.calls] == []
    assert resumed.action_store.get(item["action_id"])["status"] == "released"


def test_operator_approval_releases_under_the_decision_that_produced_it(tmp_path):
    body, raw = write_body_and_response()
    cfg = config()
    client = FakeClient({m: [decision(access="write")] for m in cfg.decider.members}, raw=[raw])
    orch = harness(tmp_path, client, cfg)
    orch.governor.manifest_policies["write_file"] = {
        "trusted": True, "side_effect": "write", "requires_human": True}
    asyncio.run(orch.run_tool_turn("session", body))
    item = orch.action_store.list()[0]
    orch.action_store.decide(item["action_id"], "approve")
    resumed_client = FakeClient()
    resumed = harness(tmp_path, resumed_client, cfg)
    resumed.governor.manifest_policies = orch.governor.manifest_policies
    result = asyncio.run(resumed.run_tool_turn("session", body))
    assert result == raw
    assert resumed.action_store.get(item["action_id"])["status"] == "released"
    assert not any(c[0] in {"executor", "decider"} for c in resumed_client.calls)


def test_rewrite_scope_is_rechecked_before_release(tmp_path):
    body, raw = write_body_and_response()
    cfg = config(max_decisions_per_request=1)
    client = FakeClient({m: [decision(access="write")] for m in cfg.decider.members}, raw=[raw])
    orch = harness(tmp_path, client, cfg)
    orch.governor.manifest_policies["write_file"] = {"trusted": True, "side_effect": "write"}
    from conflux.governance import ActionVerdict
    async def critique(*args, **kwargs):
        return ActionVerdict("rewrite", "rewrite", arguments={"path": "/tmp/escape", "content": "bad"})
    orch.governor._critique = critique
    result = asyncio.run(orch.run_tool_turn("session", body))
    assert result["conflux"]["status"] == "incomplete"
    assert not any(a["status"] == "released" for a in orch.action_store.list())


def test_batch_scope_violation_releases_no_sibling(tmp_path):
    cfg = config(max_decisions_per_request=1)
    raw = _response("cat /tmp/item")
    raw["choices"][0]["message"]["tool_calls"].append(_tool_call("cat /etc/passwd", "escape"))
    client = FakeClient(raw=[raw])
    orch = harness(tmp_path, client, cfg)
    result = asyncio.run(orch.run_tool_turn("session", _body()))
    assert result["conflux"]["status"] == "incomplete"
    assert not orch.action_store.list()


def test_done_vote_never_releases_executor_tools_even_matching_its_check(tmp_path):
    cfg = config(max_decisions_per_request=1)
    client = FakeClient({m: [decision(True)] for m in cfg.decider.members}, raw=[_response("cat /tmp/item")])
    orch = harness(tmp_path, client, cfg)
    result = asyncio.run(orch.run_tool_turn("session", _body()))
    result = _finish_checks(orch, _body(), result)
    assert result["conflux"]["status"] == "incomplete"
    assert all(a["proposal"]["call_id"].startswith("conflux_check_") for a in orch.action_store.list())
    assert orch.verifier.calls == 0


def test_per_conversation_lock_serializes_requests(tmp_path):
    client = FakeClient(raw=[_response("cat /tmp/item"), _response("cat /tmp/item")])
    orch = harness(tmp_path, client)
    async def run():
        return await asyncio.gather(orch.run_tool_turn("session", _body()), orch.run_tool_turn("session", _body()))
    results = asyncio.run(run())
    assert len(results) == 2
    assert [c[0] for c in client.calls] == ["decider", "decider", "executor"]
    assert sum(r.get("conflux", {}).get("status") == "incomplete" for r in results) == 1


def test_proxy_identity_outage_and_omitted_final_tools(tmp_path):
    from conflux import proxy
    from tests.test_stateless_endpoint import _Request
    cfg = config(max_repairs=0, max_decisions_per_request=1)
    client = FakeClient({"executor": [decision(), decision(True)], "second": [decision(), decision(True)]},
                        raw=[_response("cat /tmp/item"), final()])
    orch = harness(tmp_path, client, cfg)
    saved = dict(proxy.state)
    proxy.state.clear()
    proxy.state.update(cfg=cfg, control=orch.control, orch=orch, trace=orch.trace)
    from conflux.library import Library
    proxy.state["library"] = Library(str(tmp_path / "library.db"))
    try:
        rejected = asyncio.run(proxy.chat_completions(_Request(_body())))
        assert rejected.status_code == 400
        assert client.calls == []
        first = _body()
        first["conversation_id"] = "session"
        assert asyncio.run(proxy.chat_completions(_Request(first))).status_code == 200
        end = {"model": "super", "conversation_id": "session", "messages": first["messages"] + [
            {"role": "tool", "tool_call_id": "call-original", "content": "verified data"}]}
        result = asyncio.run(proxy.chat_completions(_Request(end)))
        assert result.status_code == 200
        assert json.loads(result.body)["conflux"]["status"] == "incomplete"
        assert orch.verifier.calls == 0
        client.decisions = {m: [ProviderError(m, 503, "down")] for m in cfg.decider.members}
        end["conversation_id"] = "outage"
        end["tools"] = first["tools"]
        assert asyncio.run(proxy.chat_completions(_Request(end))).status_code == 503
    finally:
        proxy.state.clear()
        proxy.state.update(saved)


def test_safe_probe_resume_reconsults_before_exact_stored_release(tmp_path):
    from conflux.governance import ActionVerdict, ProbeSpec
    body, raw = write_body_and_response()
    body["tools"].extend(_body()["tools"])
    d = decision(access="write")
    d["touches"].append({"resource": "/tmp/evidence", "access": "read"})
    cfg = config()
    client = FakeClient({m: [d] for m in cfg.decider.members}, raw=[raw])
    orch = harness(tmp_path, client, cfg)
    orch.governor.manifest_policies["write_file"] = {"trusted": True, "side_effect": "write"}
    async def probe_verdict(*args, **kwargs):
        return ActionVerdict("probe", "need evidence", probe=ProbeSpec("terminal", {"command": "cat /tmp/evidence"}, "observe"))
    orch.governor._critique = probe_verdict
    probe = asyncio.run(orch.run_tool_turn("session", body))
    probe_call = probe["choices"][0]["message"]["tool_calls"][0]
    old_decision_id = orch.action_store.list()[0]["proposal"]["decision_id"]
    assert probe_call["id"].startswith("conflux_probe_")
    resumed_client = FakeClient({m: [decision(access="write")] for m in cfg.decider.members})
    resumed = harness(tmp_path, resumed_client, cfg)
    resumed.governor.manifest_policies = orch.governor.manifest_policies
    async def approve(*args, **kwargs):
        return ActionVerdict("approve", "observed", objection="one concern")
    resumed.governor._critique = approve
    body["messages"] += [probe["choices"][0]["message"], {"role": "tool", "tool_call_id": probe_call["id"], "content": "evidence"}]
    result = asyncio.run(resumed.run_tool_turn("session", body))
    assert result == raw
    assert [c[0] for c in resumed_client.calls] == ["decider", "decider"]
    assert resumed.action_store.list()[0]["proposal"]["decision_id"] != old_decision_id


def test_feedback_arriving_during_final_verification_revokes_done(tmp_path):
    cfg = config(max_decisions_per_request=1)
    client = FakeClient({m: [decision(True)] for m in cfg.decider.members}, raw=[final("suppressed")])
    orch = harness(tmp_path, client, cfg)
    class RacingVerifier:
        async def verify(self, **kwargs):
            orch.decision_store.concern("session", "late_senate", "new evidence")
            return VerifyReport(1, True, verifier="fake")
    orch.verifier = RacingVerifier()
    result = asyncio.run(orch.run_tool_turn("session", _body()))
    result = _finish_checks(orch, _body(), result)
    assert result["conflux"]["status"] == "incomplete"
    assert "suppressed" not in result["choices"][0]["message"]["content"]


def test_scope_violation_repairs_the_same_decision_before_reconsulting(tmp_path):
    client = FakeClient(raw=[_response("cat /tmp/item /etc/passwd"), _response("cat /tmp/item")])
    orch = harness(tmp_path, client)
    result = asyncio.run(orch.run_tool_turn("session", _body()))
    assert result["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == json.dumps({"command": "cat /tmp/item"})
    deciders = [c for c in client.calls if c[0] == "decider"]
    assert len(deciders) == len(orch.cfg.decider.members)
    retry = [c for c in client.calls if c[0] == "executor"][1][2]["messages"][-1]
    assert retry["role"] == "system" and "outside the decision scope" in retry["content"]


def test_unprovable_scope_is_judged_by_the_senate_with_the_decided_scope(tmp_path):
    client = FakeClient(raw=[_response("echo $(uname -a) && cat /tmp/item")])
    orch = harness(tmp_path, client)
    asyncio.run(orch.run_tool_turn("session", _body()))
    senate = [c for c in client.calls if c[0] == "senate"]
    assert senate and all("decision scope unproven (shell expansion" in c[2][-1]["content"]
                          and "/tmp/item" in c[2][-1]["content"] for c in senate)


def test_empty_executor_reply_retries_the_same_decision(tmp_path):
    empty = _response("cat /tmp/item")
    empty["choices"][0]["message"] = {"role": "assistant", "content": None}
    client = FakeClient(raw=[empty, _response("cat /tmp/item")])
    orch = harness(tmp_path, client)
    result = asyncio.run(orch.run_tool_turn("session", _body()))
    assert result["choices"][0]["message"]["tool_calls"]
    assert len([c for c in client.calls if c[0] == "decider"]) == len(orch.cfg.decider.members)



def test_unprovable_check_is_released_after_senate_review(tmp_path):
    d = decision(claim="claim")
    d["check"][0]["arguments"]["command"] = 'v=$(cat /tmp/item) && echo "$v"'
    client = FakeClient({"executor": [d, decision()]}, raw=[_response("stat /tmp/item")])
    orch = harness(tmp_path, client)
    first = asyncio.run(orch.run_tool_turn("session", _body()))
    client.calls.clear()
    result = asyncio.run(orch.run_tool_turn("session", _results(_body(), first, "stat")))
    calls = result["choices"][0]["message"].get("tool_calls") or []
    assert calls and "$(cat /tmp/item)" in calls[0]["function"]["arguments"]
    assert [c for c in client.calls if c[0] == "senate"]
    assert orch.decision_store.obligations("session")[0]["status"] == "pending"



def test_done_is_blocked_by_its_own_failed_claim_and_by_regressions(tmp_path):
    cfg = config(max_decisions_per_request=1)
    client = FakeClient({m: [decision(True)] for m in cfg.decider.members})
    orch = harness(tmp_path, client, cfg)
    result = asyncio.run(orch.run_tool_turn("session", _body()))
    check = result["choices"][0]["message"]["tool_calls"][0]["id"]
    failed = _body()["messages"] + [result["choices"][0]["message"],
                                    {"role": "tool", "tool_call_id": check, "content": "unexpected"}]
    client.decisions = {m: [decision(True)] for m in cfg.decider.members}
    client.raw = [final("must suppress")]
    assert asyncio.run(orch.run_tool_turn("session", _body(failed)))["conflux"]["status"] == "incomplete"
    panel = orch.decision_store.panel("session", orch.decision_store.obligations("session")[0]["decision_id"])
    assert orch.decision_store.unresolved("session", panel.id)
    orch.decision_store.connection.execute(
        "INSERT INTO decision_obligations (id,session,decision_id,member,claim,check_json,status,evidence) "
        "VALUES ('r','session','older','observation','psci0 again','null','unchecked','[]')")
    assert orch.decision_store.unresolved("session", "some-later-done-decision")


def test_same_family_executor_fallback_reuses_the_decision(tmp_path):
    cfg = config()
    cfg.models["executor-backup"] = replace(cfg.model("executor"), name="executor-backup", id="executor-backup")
    cfg.models["executor"] = replace(cfg.model("executor"), fallbacks=("executor-backup",))
    client = FakeClient(raw=[ProviderError("executor", 402, "no credits"), _response("cat /tmp/item")])
    orch = harness(tmp_path, client, cfg)
    result = asyncio.run(orch.run_tool_turn("session", _body()))
    assert result["choices"][0]["message"]["tool_calls"]
    assert len([c for c in client.calls if c[0] == "decider"]) == len(cfg.decider.members)
