"""Offline tests of the slice-1 execution loop in conflux/core.py (scripted provider responses)."""

import json
from pathlib import Path

import pytest

from conflux import core
from conflux.core import Budget, Check, Task, Trace, reconcile, run_task

FIXTURES = Path(__file__).parent / "fixtures/core_loop"


def call(name, args, cid="c1"):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def resp(*calls, content="", micro=14, rid="gen-1", prompt=300, completion=40):
    usage = {"prompt_tokens": prompt, "completion_tokens": completion}
    if micro is not None:
        usage["buyer_cost_micro"] = micro
    msg = {"role": "assistant", "content": content, **({"tool_calls": list(calls)} if calls else {})}
    return 200, {"id": rid, "choices": [{"message": msg}], "usage": usage}, 0.1


class Scripted:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen = []

    def __call__(self, messages, tools):
        self.seen.append(json.loads(json.dumps(messages)))
        return self.responses.pop(0)


TOUCH = Task(id="touch", goal="create ok.txt containing yes",
             checks=[Check("cat ok.txt", expect_stdout="yes")], max_steps=4)


def run(task, chat, tmp_path, allowance=1.0):
    trace = Trace(tmp_path / "trace.jsonl")
    return run_task(task, chat, tmp_path / "work", trace, Budget(allowance)), trace


def test_accepted_after_tool_and_finish(tmp_path):
    chat = Scripted(resp(call("run_shell", {"command": "echo yes > ok.txt"})),
                    resp(call("finish", {"summary": "done"}), micro=6))
    res, trace = run(TOUCH, chat, tmp_path)
    assert res["status"] == "accepted" and res["steps"] == 2 and res["retries"] == 0
    assert res["cost_usd"] == pytest.approx(20e-6)
    # The shell result went back to the model as a tool message.
    tool_msg = chat.seen[1][-1]
    assert tool_msg["role"] == "tool" and tool_msg["content"].startswith("exit=0")
    events = [e["event"] for e in map(json.loads, (tmp_path / "trace.jsonl").read_text().splitlines())]
    assert events == ["task_start", "model_call", "policy", "exec", "model_call", "policy",
                      "acceptance", "task_end"]


def test_failed_acceptance_feeds_evidence_back_then_accepts(tmp_path):
    chat = Scripted(resp(call("run_shell", {"command": "echo no > ok.txt"})),
                    resp(call("finish", {})),
                    resp(call("run_shell", {"command": "echo yes > ok.txt"})),
                    resp(call("finish", {})))
    res, _ = run(TOUCH, chat, tmp_path)
    assert res["status"] == "accepted" and res["retries"] == 1
    feedback = chat.seen[2][-1]
    assert feedback["role"] == "user" and "Acceptance checks failed" in feedback["content"]
    assert "'no\\n'" in feedback["content"]


def test_step_cap_with_failing_checks_is_failed(tmp_path):
    chat = Scripted(*[resp(call("run_shell", {"command": "true"}))] * 4)
    res, trace = run(TOUCH, chat, tmp_path)
    assert res["status"] == "failed" and res["reason"] == "step_cap" and res["steps"] == 4
    assert trace.events[-2]["event"] == "acceptance" and trace.events[-2]["verdict"] == "fail"


def test_checks_passing_at_step_cap_are_accepted(tmp_path):
    chat = Scripted(*[resp(call("run_shell", {"command": "echo yes > ok.txt"}))] * 4)
    res, _ = run(TOUCH, chat, tmp_path)
    assert res["status"] == "accepted" and res["reason"] == "checks_passed_at_step_cap"


def test_provider_error_is_unverified_not_failed(tmp_path):
    chat = Scripted((503, {"error": {"message": "no_healthy_sellers"}}, 0.2))
    res, trace = run(TOUCH, chat, tmp_path)
    assert res["status"] == "unverified" and res["reason"] == "provider_503"
    mc = [e for e in trace.events if e["event"] == "model_call"][0]
    assert mc["cost_kind"] == "bound" and mc["error"] == {"message": "no_healthy_sellers"}


def test_check_timeout_is_unverified(tmp_path):
    task = Task(id="slow", goal="g", checks=[Check("sleep 5", timeout=0.2)])
    res, _ = run(task, Scripted(resp(call("finish", {}))), tmp_path)
    assert res["status"] == "unverified" and res["reason"] == "check_no_verdict"


def test_a_real_check_failure_beats_a_timeout(tmp_path):
    task = Task(id="mixed", goal="g", checks=[Check("sleep 5", timeout=0.2), Check("false")], max_steps=1)
    res, _ = run(task, Scripted(resp(call("finish", {}))), tmp_path)
    assert res["status"] == "failed"


def test_missing_cost_settles_at_bound_and_continues(tmp_path):
    chat = Scripted(resp(call("run_shell", {"command": "echo yes > ok.txt"}), micro=None),
                    resp(call("finish", {})))
    res, trace = run(TOUCH, chat, tmp_path)
    assert res["status"] == "accepted"
    first = [e for e in trace.events if e["event"] == "model_call"][0]
    assert first["cost_kind"] == "bound" and first["cost_usd"] == first["bound_usd"] > 0


def test_run_budget_refusal_is_unverified_and_makes_no_call(tmp_path):
    chat = Scripted()
    res, _ = run(TOUCH, chat, tmp_path, allowance=1e-6)
    assert res["status"] == "unverified" and res["reason"] == "run_budget" and chat.seen == []


def test_task_budget_refusal(tmp_path):
    task = Task(id="t", goal="g", checks=[Check("true")], max_usd=1e-6)
    res, _ = run(task, Scripted(), tmp_path)
    assert res["reason"] == "task_budget"


def test_budget_releases_reservation_on_settle():
    b = Budget(0.01)
    assert b.admit(0.008)
    b.settle(0.008, 0.000014)
    assert b.admit(0.008)
    assert not b.admit(0.008)


def test_policy_denials_go_back_to_the_model(tmp_path):
    bad_json = {"id": "c2", "type": "function", "function": {"name": "run_shell", "arguments": "{oops"}}
    chat = Scripted(resp(call("rm_rf", {}), bad_json, call("run_shell", {"command": "  "}, "c3")),
                    resp(call("run_shell", {"command": "echo yes > ok.txt"})),
                    resp(call("finish", {})))
    res, trace = run(TOUCH, chat, tmp_path)
    assert res["status"] == "accepted"
    reasons = [e["reason"] for e in trace.events if e["event"] == "policy"][:3]
    assert reasons == ["unknown_tool", "bad_arguments", "empty_command"]
    assert [m["content"] for m in chat.seen[1][-3:]] == [
        "denied: unknown_tool", "denied: bad_arguments", "denied: empty_command"]


def test_setup_failure_is_unverified(tmp_path):
    task = Task(id="t", goal="g", checks=[Check("true")], setup="exit 3")
    res, _ = run(task, Scripted(), tmp_path)
    assert res == {**res, "status": "unverified", "reason": "setup_failed"}


def test_tuning_task_checks_reject_the_untouched_setup(tmp_path):
    tasks = {t.id: t for t in map(Task.from_dict, json.loads((FIXTURES / "tasks.json").read_text()))}
    assert set(tasks) == {"fizzbuzz", "fix-mean", "csv-total"}
    for t in tasks.values():
        w = tmp_path / t.id
        w.mkdir()
        assert core.execute(t.setup or "true", w)["exit"] == 0
        assert core.run_checks(t.checks, w)[0] == "fail"


def test_reconcile_matches_on_model_tokens_and_nearest_time():
    calls = [
        {"task": "a", "step": 1, "id": "gen-1", "model": "deepseek-v4-flash", "ts": 1793077562.0,
         "usage": {"prompt_tokens": 291, "completion_tokens": 45}, "cost_usd": 14e-6},
        {"task": "a", "step": 2, "id": "gen-2", "model": "deepseek-v4-flash", "ts": 1793077600.0,
         "usage": {"prompt_tokens": 400, "completion_tokens": 10}, "cost_usd": 20e-6},
    ]
    rows = [
        {"request_id": "far", "created_at": "2026-10-27T05:30:00.000Z", "model": "deepseek-v4-flash",
         "input_tokens": "291", "output_tokens": "45", "buyer_cost_usd": "0.000099", "settlement_status": "accrued"},
        {"request_id": "near", "created_at": "2026-10-27T05:06:03.500Z", "model": "deepseek-v4-flash",
         "input_tokens": "291", "output_tokens": "45", "buyer_cost_usd": "0.000014", "settlement_status": "accrued"},
        {"request_id": "other", "created_at": "2026-10-27T05:06:03.500Z", "model": "deepseek-v4-pro",
         "input_tokens": "400", "output_tokens": "10", "buyer_cost_usd": "0.000003", "settlement_status": "accrued"},
    ]
    rep = reconcile(calls, rows)
    assert [(m["request_id"], m["match"]) for m in rep["matched"]] == [("near", "tokens")]
    assert rep["unmatched"] == [{"task": "a", "step": 2, "id": "gen-2"}]
    assert rep["billed_usd"] == pytest.approx(14e-6) and rep["in_flight_usd"] == pytest.approx(34e-6)


def test_reconcile_matches_a_call_without_usage_by_time_after_token_matches():
    # A body that failed to decode has no usage but was still billed.
    calls = [
        {"task": "b", "step": 1, "id": None, "model": "deepseek-v4-flash", "ts": 1793077563.0,
         "usage": None, "cost_usd": 0.0067},
        {"task": "a", "step": 1, "id": "gen-1", "model": "deepseek-v4-flash", "ts": 1793077562.0,
         "usage": {"prompt_tokens": 291, "completion_tokens": 45}, "cost_usd": 14e-6},
    ]
    rows = [
        {"request_id": "tok", "created_at": "2026-10-27T05:06:03.000Z", "model": "deepseek-v4-flash",
         "input_tokens": "291", "output_tokens": "45", "buyer_cost_usd": "0.000014"},
        {"request_id": "late", "created_at": "2026-10-27T05:06:40.000Z", "model": "deepseek-v4-flash",
         "input_tokens": "602", "output_tokens": "135", "buyer_cost_usd": "0.000032"},
    ]
    rep = reconcile(calls, rows)
    assert {m["request_id"]: m["match"] for m in rep["matched"]} == {"tok": "tokens", "late": "time"}
    assert rep["unmatched"] == [] and rep["billed_usd"] == pytest.approx(46e-6)


def test_recorded_live_run_replays_to_the_same_status_and_cost(tmp_path):
    rec = json.loads((FIXTURES / "recorded_fix-mean.json").read_text())
    task = {t["id"]: Task.from_dict(t) for t in json.loads((FIXTURES / "tasks.json").read_text())}[rec["task"]]
    chat = Scripted(*[(r["status"], r["body"], 0.0) for r in rec["responses"]])
    res, trace = run(task, chat, tmp_path)
    assert {k: res[k] for k in rec["expected"]} == rec["expected"]
    assert chat.responses == []
    assert all(e["cost_kind"] == "billed" for e in trace.events if e["event"] == "model_call")
