"""Offline tests of the slice-1 execution loop in conflux/core.py (scripted provider responses)."""

import dataclasses
import itertools
import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
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
        self.timeouts = []

    def __call__(self, messages, tools, timeout=None):
        self.seen.append(json.loads(json.dumps(messages)))
        self.timeouts.append(timeout)
        return self.responses.pop(0)


TOUCH = Task(id="touch", goal="create ok.txt containing yes",
             checks=[Check("cat ok.txt", expect_stdout="yes")], max_steps=4)


def run(task, chat, tmp_path, allowance=1.0):
    trace = Trace(tmp_path / "trace.jsonl")
    return run_task(task, chat, core.local_shell(tmp_path / "work"), trace, Budget(allowance)), trace


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
                      "acceptance", "audit", "task_end"]


def test_reasoning_content_is_passed_back_on_later_turns(tmp_path):
    # DeepSeek requires the assistant's reasoning_content on every later turn of a tool-call loop (MISSION c36f507).
    first = resp(call("run_shell", {"command": "echo yes > ok.txt"}))
    first[1]["choices"][0]["message"]["reasoning_content"] = "write ok.txt, then finish"
    chat = Scripted(first, resp(call("run_shell", {"command": "true"}, cid="c2")),
                    resp(call("finish", {"summary": "done"}, cid="c3")))
    res, _ = run(TOUCH, chat, tmp_path)
    assert res["status"] == "accepted"
    turns = [m for m in chat.seen[2] if m["role"] == "assistant"]
    assert turns[0]["reasoning_content"] == "write ok.txt, then finish"
    assert "reasoning_content" not in turns[1]


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
    assert trace.events[-3]["event"] == "acceptance" and trace.events[-3]["verdict"] == "fail"


def test_checks_passing_at_step_cap_are_accepted(tmp_path):
    chat = Scripted(*[resp(call("run_shell", {"command": "echo yes > ok.txt"}))] * 4)
    res, _ = run(TOUCH, chat, tmp_path)
    assert res["status"] == "accepted" and res["reason"] == "checks_passed_at_step_cap"


def test_provider_error_is_unverified_not_failed(tmp_path):
    chat = Scripted((503, {"error": {"message": "no_healthy_sellers"}}, 0.2))
    res, trace = run(TOUCH, chat, tmp_path)
    assert res["status"] == "unverified" and res["reason"] == "provider_unavailable"
    mc = [e for e in trace.events if e["event"] == "model_call"][0]
    assert mc["cost_kind"] == "no_usage" and mc["cost_usd"] == 0 and mc["error"] == {"message": "no_healthy_sellers"}


def test_check_timeout_is_unverified(tmp_path):
    task = Task(id="slow", goal="g", checks=[Check("sleep 5", timeout=0.2)])
    res, _ = run(task, Scripted(resp(call("finish", {}))), tmp_path)
    assert res["status"] == "unverified" and res["reason"] == "check_no_verdict"


def test_a_real_check_failure_beats_a_timeout(tmp_path):
    task = Task(id="mixed", goal="g", checks=[Check("sleep 5", timeout=0.2), Check("false")], max_steps=1)
    res, _ = run(task, Scripted(resp(call("finish", {}))), tmp_path)
    assert res["status"] == "failed"


def export_row(model, prompt, completion, usd, ts, rid="01EXPORT"):
    created = core.datetime.fromtimestamp(ts, core.timezone.utc).isoformat().replace("+00:00", "Z")
    return {"request_id": rid, "created_at": created, "model": model, "input_tokens": str(prompt),
            "output_tokens": str(completion), "buyer_cost_usd": f"{usd:.6f}", "settlement_status": "accrued"}


def test_missing_cost_is_pending_and_never_settled_at_ceilings(tmp_path):
    # MISSION a58a30e: without a billing source the cost stays pending at 0, never usage x list-price ceilings.
    chat = Scripted(resp(call("run_shell", {"command": "echo yes > ok.txt"}), micro=None),
                    resp(call("finish", {})))
    res, trace = run(TOUCH, chat, tmp_path)
    assert res["status"] == "accepted" and res["pending_calls"] == 1
    first = [e for e in trace.events if e["event"] == "model_call"][0]
    assert first["cost_kind"] == "pending" and first["cost_usd"] == 0
    assert res["cost_usd"] == pytest.approx(14e-6)


def test_pending_cost_settles_from_the_export_row_and_counts_against_the_cap(tmp_path, monkeypatch):
    # A reply without buyer_cost_micro that Surplus did bill: its export row settles it, and admission uses it.
    monkeypatch.setattr(core, "BILLING_POLL_S", 0)
    seen_days = []

    def billing(day):
        seen_days.append(day)
        mc = [e for e in trace.events if e["event"] == "model_call"]
        return [export_row(core.MODEL, 300, 40, 0.02, mc[0]["ts"])] if mc else []

    trace = Trace(tmp_path / "trace.jsonl")
    chat = Scripted(resp(call("run_shell", {"command": "true"}), micro=None),
                    resp(call("run_shell", {"command": "true"}, cid="c2")))
    res = run_task(TOUCH, chat, core.local_shell(tmp_path / "work"), trace, Budget(0.01, billing=billing))
    assert res["status"] == "unverified" and res["reason"] == "run_budget" and len(chat.seen) == 1
    r = [e for e in trace.events if e["event"] == "cost_resolved"]
    assert [(e["step"], e["cost_kind"], e["cost_usd"], e["request_id"]) for e in r] == [(1, "export", 0.02, "01EXPORT")]
    assert res["cost_usd"] == pytest.approx(0.02) and res["pending_calls"] == 0 and seen_days


def test_unbilled_replies_do_not_end_the_run(tmp_path, monkeypatch):
    # Fault (C slice 43 lead-s2): deepseek-v4-pro replies with usage but no buyer_cost_micro were settled at usage x
    # CEILINGS; with the lead's, $1.59 settled against $0.029 billed ended a 240-step run at step 107 (run_budget).
    # They never reached the usage export (balance delta = export total): resolved there, they settle at 0.
    fx = json.loads((FIXTURES / "slice43_unbilled_calls.json").read_text())["calls"]
    assert sum(c[3] for c in fx) > 0.5  # what the old core settled for these 6 replies
    clock = [1_800_000_000.0]
    monkeypatch.setattr(core.time, "time", lambda: clock[0])

    def billing(day):
        return [export_row("deepseek-v4-pro", 1000, 50, 0.0001, clock[0] - 30, rid="01OTHER")]  # an unrelated row

    def ticking(messages, tools, timeout=None):
        clock[0] += core.UNBILLED_AFTER_S  # each reply arrives one unbilled-window after the last
        return chat(messages, tools, timeout)

    chat = Scripted(*[resp(call("run_shell", {"command": "true"}, cid=f"c{s}"), micro=None, prompt=p, completion=o)
                      for s, p, o, _ in fx],
                    resp(call("run_shell", {"command": "echo yes > ok.txt"})), resp(call("finish", {})))
    task = dataclasses.replace(TOUCH, max_steps=10, max_usd=0.50)
    trace = Trace(tmp_path / "trace.jsonl")
    res = run_task(task, ticking, core.local_shell(tmp_path / "work"), trace, Budget(0.50, billing=billing),
                   model="deepseek-v4-pro")
    assert res["status"] == "accepted", res
    kinds = [e["cost_kind"] for e in trace.events if e["event"] == "cost_resolved"]
    assert kinds == ["unbilled"] * 6 and res["cost_usd"] == pytest.approx(28e-6) and res["pending_calls"] == 0


def test_billing_api_down_keeps_costs_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "BILLING_POLL_S", 0)

    def billing(day):
        raise httpx.ConnectError("down")

    chat = Scripted(resp(call("run_shell", {"command": "echo yes > ok.txt"}), micro=None), resp(call("finish", {})))
    trace = Trace(tmp_path / "trace.jsonl")
    res = run_task(TOUCH, chat, core.local_shell(tmp_path / "work"), trace, Budget(1.0, billing=billing))
    assert res["status"] == "accepted" and res["pending_calls"] == 1
    assert not [e for e in trace.events if e["event"] == "cost_resolved"]


def test_missing_cost_without_usage_is_pending_and_matched_by_time(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "BILLING_POLL_S", 0)
    status, body, lat = resp(call("run_shell", {"command": "echo yes > ok.txt"}))
    chat = Scripted((status, {**body, "usage": None}, lat), resp(call("finish", {})))
    trace = Trace(tmp_path / "trace.jsonl")

    def billing(day):
        mc = [e for e in trace.events if e["event"] == "model_call"]
        return [export_row(core.MODEL, 280, 33, 0.000012, mc[0]["ts"] + 1)] if mc else []

    res = run_task(TOUCH, chat, core.local_shell(tmp_path / "work"), trace, Budget(1.0, billing=billing))
    first = [e for e in trace.events if e["event"] == "model_call"][0]
    assert res["status"] == "accepted" and first["cost_kind"] == "pending"
    assert res["cost_usd"] == pytest.approx(0.000012 + 14e-6) and res["pending_calls"] == 0


def test_pro_calls_without_cost_do_not_exhaust_the_task_budget(tmp_path):
    # Fault (C slice 20, lab c3, b1b): deepseek-v4-pro omitted buyer_cost_micro on 7 of 27 calls; each was settled at
    # its request bound ($0.08-0.24), so $0.94 of the $1.00 task cap was charged for $0.0007 billed and the task
    # ended `unverified task_budget` at step 28, mid-repair. Replays the recorded usage and request growth.
    calls = json.loads((FIXTURES / "pro_b1b_missing_cost_calls.json").read_text())["calls"]
    p = core.CEILINGS["deepseek-v4-pro"][0]
    replies = [resp(call("run_shell", {"command": "true"}), micro=micro, prompt=prompt, completion=completion)
               for prompt, completion, micro, _ in calls]
    task = Task(id="pro", goal="g", checks=[Check("test -f ok.txt")], max_steps=40, max_usd=1.0)
    chat = Scripted(*replies, resp(call("run_shell", {"command": "echo yes > ok.txt"})), resp(call("finish", {})))
    grow = itertools.chain((round((nxt[3] - cur[3]) / p) for cur, nxt in zip(calls, calls[1:])), itertools.repeat(0))

    def padded(messages, tools, timeout=None):
        status, body, lat = chat(messages, tools, timeout)
        body["choices"][0]["message"]["content"] = "x" * max(next(grow), 0)  # request bytes grow as recorded
        return status, body, lat

    res = run_task(task, padded, core.local_shell(tmp_path / "work"), Trace(tmp_path / "t.jsonl"), Budget(1.0),
                   model="deepseek-v4-pro")
    assert res["status"] == "accepted", res
    assert res["cost_usd"] < 0.3 and res["pending_calls"] == 7  # 20 billed calls (recorded bound sum: $0.94)


def test_run_budget_refusal_is_unverified_and_makes_no_call(tmp_path):
    chat = Scripted()
    res, _ = run(TOUCH, chat, tmp_path, allowance=0.0)
    assert res["status"] == "unverified" and res["reason"] == "run_budget" and chat.seen == []


def test_task_budget_refusal(tmp_path):
    task = Task(id="t", goal="g", checks=[Check("true")], max_usd=0.0)
    res, _ = run(task, Scripted(), tmp_path)
    assert res["reason"] == "task_budget"


def test_budget_caps_settled_spend_and_reserves_no_bound():
    # Slice 39b lead-b1: input bounds of ~$0.3 per 250 KB pro request ended a $0.50-cap run at step 63 with $0.002
    # billed. Admission now looks only at settled spend (MISSION 90b27cd).
    b = Budget(0.01)
    assert b.admit(5.0) and b.admit(5.0)  # a large bound alone never refuses
    b.settle(5.0, 0.009)
    assert b.admit(5.0)
    b.settle(5.0, 0.002)  # one call may overshoot the cap by its own cost
    assert b.committed == pytest.approx(0.011) and not b.admit(0.0)


def test_a_long_context_is_admitted_under_a_small_cap(tmp_path):
    # The same run shape: a ~300 KB request (pro input bound ~$0.6) under a $0.05 task cap bills $0.000014.
    big = "x" * 300_000
    chat = Scripted(resp(call("run_shell", {"command": "echo yes > ok.txt"})), resp(call("finish", {})))
    task = dataclasses.replace(TOUCH, goal=TOUCH.goal + big, max_usd=0.05)
    res = run_task(task, chat, core.local_shell(tmp_path / "work"), Trace(tmp_path / "t.jsonl"), Budget(0.05),
                   model="deepseek-v4-pro")
    assert res["status"] == "accepted", res


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
        assert core.run_checks(t.checks, core.local_shell(w))[0] == "fail"


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


# ---------------------------------------------------------------- slice 2: lab backend


import os
import shlex
import time


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """lab_shell over the local seam; job dirs land under a temporary $HOME."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    def make(deadline=None, remote=core.local_remote):
        return core.lab_shell(remote, str(tmp_path / "work"), deadline, poll_s=0.1)
    return make


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_lab_shell_returns_exit_and_output(lab, tmp_path):
    r = lab()("echo hi; echo err >&2; pwd", 10)
    assert r["exit"] == 0 and r["stdout"] == f"hi\n{tmp_path / 'work'}\n" and r["stderr"] == "err\n"
    assert lab()("exit 3", 10)["exit"] == 3


def test_lab_shell_runs_awkward_commands_verbatim(lab, tmp_path):
    cmd = "printf '%s|' \"a'b\" '$HOME' \"x\\\\y\"\necho \"`echo tick`\" $((1+2))"
    assert lab()(cmd, 10)["stdout"] == core.execute(cmd, tmp_path)["stdout"] == "a'b|$HOME|x\\y|tick 3\n"


def test_lab_shell_timeout_kills_the_process_group_and_keeps_output(lab, tmp_path):
    r = lab()("echo started; sleep 30 & echo $! > child.pid; wait", 1.5)
    assert r["timed_out"] and r["exit"] is None and not r["deadline"] and r["stdout"] == "started\n"
    assert not _alive(int((tmp_path / "work/child.pid").read_text()))
    assert (tmp_path / "home/.conflux-jobs" / r["job"] / "out").read_text() == "started\n"


def test_lab_shell_transport_failure_is_no_verdict(lab):
    r = lab(remote=lambda script: ["false"])("echo hi", 10)
    assert r["exit"] is None and r["transport_error"] == "launch" and not r["timed_out"]
    task = Task(id="t", goal="g", checks=[Check("true")])
    assert core.run_checks(task.checks, lab(remote=lambda script: ["false"]))[0] is None


def test_lab_shell_deadline_caps_the_command_timeout(lab, tmp_path):
    t0 = time.monotonic()
    r = lab(deadline=t0 + 1.5)("sleep 30 & echo $! > child.pid; wait", 60)
    assert r["timed_out"] and r["deadline"] and time.monotonic() - t0 < 6
    assert not _alive(int((tmp_path / "work/child.pid").read_text()))
    late = lab(deadline=t0)("echo never > ran.txt", 10)
    assert late["exit"] is None and late["deadline"] and not (tmp_path / "work/ran.txt").exists()


def test_run_task_ends_at_the_lab_deadline_without_another_model_call(lab, tmp_path):
    deadline = time.monotonic() + 1.5
    chat = Scripted(resp(call("run_shell", {"command": "sleep 30", "timeout_s": 60})),
                    resp(call("finish", {})))
    res = run_task(TOUCH, chat, lab(deadline=deadline), Trace(), Budget(1.0), deadline=deadline)
    assert res["status"] == "unverified" and res["reason"] == "lab_deadline" and len(chat.responses) == 1


def test_gcloud_remote_puts_the_whole_script_in_one_command_value():
    script = "set -e; d=\"$HOME\"/x; echo 'q' | base64 -d > \"$d/cmd.sh\""
    argv = core.gcloud_remote("c2")(script)
    assert argv[:4] == ["gcloud", "compute", "ssh", "conflux-dev-lab-c2"]
    commands = [a for a in argv if a.startswith("--command")]
    assert commands == [argv[-1]]
    assert shlex.split(argv[-1][len("--command="):]) == ["bash", "-c", script]


@pytest.mark.parametrize("t,deny", [(None, None), (1, None), (10800, None), (0, "bad_timeout"),
                                    (-5, "bad_timeout"), (10801, "bad_timeout"), (2.5, "bad_timeout"),
                                    ("60", "bad_timeout"), (True, "bad_timeout")])
def test_policy_timeout_bounds(t, deny):
    args = {"command": "true", **({} if t is None else {"timeout_s": t})}
    name, got, reason = core.policy(call("run_shell", args))
    assert reason == deny
    if deny is None:
        assert got["timeout_s"] == (60 if t is None else t)


@pytest.fixture
def devbox_lab(tmp_path, monkeypatch):
    """A fake `devbox-lab` on PATH that logs its arguments."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "devbox-lab.log"
    (bindir / "devbox-lab").write_text(f"#!/bin/sh\necho \"$*\" >> {log}\n")
    (bindir / "devbox-lab").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    return lambda: log.read_text().splitlines()


@pytest.fixture(autouse=True)
def fast_poll(monkeypatch):
    monkeypatch.setattr(core, "POLL_S", 0.1)


@pytest.fixture(autouse=True)
def no_sudo_setup(monkeypatch):
    """The local seam has no sudo: lab setup and the egress check succeed trivially unless a test says otherwise."""
    monkeypatch.setattr(core, "LAB_SETUP", "true")
    monkeypatch.setattr(core, "EGRESS_CHECK", "true")


def _run_lab(tmp_path, chat, hours=1.0, tasks=(TOUCH,)):
    """The tunnel is a long sleep that records its pid, so tests can check it is gone afterwards."""
    pidfile = tmp_path / "tunnel.pid"
    return core.run_lab(list(tasks), chat, Budget(1.0), tmp_path / "out", "c2", str(tmp_path / "w"), hours,
                        remote=core.local_remote,
                        tunnel=lambda port: ["bash", "-c", f"echo $$ > {pidfile}; exec sleep 1000"])


def test_run_lab_stops_the_lab_after_normal_completion(lab, tmp_path, devbox_lab):
    chat = Scripted(resp(call("run_shell", {"command": "echo yes > ok.txt"})), resp(call("finish", {})))
    s = _run_lab(tmp_path, chat)
    assert devbox_lab() == ["up c2", "stop c2"]
    assert s["accepted"] == 1 and s["lab"]["smoke"]["exit"] == 0 and s["lab"]["keep_disk"]
    assert json.loads((tmp_path / "out/summary.json").read_text())["lab"]["stop_exit"] == 0


def test_run_lab_stops_the_lab_when_a_task_raises(lab, tmp_path, devbox_lab):
    def boom(messages, tools, timeout=None):
        raise RuntimeError("provider exploded")
    with pytest.raises(RuntimeError):
        _run_lab(tmp_path, boom)
    assert devbox_lab() == ["up c2", "stop c2"]
    assert (tmp_path / "out/summary.json").exists()


def test_run_lab_stops_the_lab_at_the_deadline(lab, tmp_path, devbox_lab):
    s = _run_lab(tmp_path, Scripted(), hours=1e-9)
    assert devbox_lab() == ["up c2", "stop c2"]
    assert s["runs"] == [] and s["lab"]["stopped_reason"] == "smoke_failed"
    assert s["lab"]["smoke"]["deadline"]


def test_run_lab_stops_after_the_first_non_accepted_task(lab, tmp_path, devbox_lab):
    second = Task(id="second", goal="g", checks=[Check("true")])
    chat = Scripted(resp(call("finish", {})), *[resp(call("run_shell", {"command": "true"}))] * 3)
    s = _run_lab(tmp_path, chat, tasks=(TOUCH, second))
    assert [r["task"] for r in s["runs"]] == ["touch"] and s["lab"]["stopped_reason"] == "touch:step_cap"
    assert devbox_lab() == ["up c2", "stop c2"] and not s["lab"]["keep_disk"]


def test_optee_goal_a_checks_execute_and_reject_an_empty_workdir(tmp_path):
    tasks = [Task.from_dict(d) for d in json.loads((FIXTURES / "optee_goal_a.json").read_text())]
    assert [t.id for t in tasks] == ["a1-host-prereqs", "a2-sources", "a3-build", "a4-boot"]
    for t in tasks[1:]:  # a1 depends on the host; a2-a4 cannot pass without a tree
        assert core.run_checks(t.checks, core.local_shell(tmp_path))[0] == "fail"


def test_optee_a3_image_check_accepts_the_empty_pageable_image(tmp_path):
    # Run c4's real tree: CFG_WITH_PAGER=n leaves tee-pageable_v2.bin (bl32_extra2.bin) at 0 bytes.
    image_check = [Task.from_dict(d) for d in json.loads((FIXTURES / "optee_goal_a.json").read_text())][2].checks[0]
    out = tmp_path / "optee/out/bin"
    out.mkdir(parents=True)
    for f in ("bl1.bin", "bl2.bin", "bl31.bin", "bl32.bin", "bl32_extra1.bin", "Image", "rootfs.cpio.gz"):
        (out / f).write_bytes(b"x")
    (out / "bl32_extra2.bin").touch()
    assert core.run_checks([image_check], core.local_shell(tmp_path))[0] == "pass"
    (out / "bl32_extra1.bin").write_bytes(b"")
    assert core.run_checks([image_check], core.local_shell(tmp_path))[0] == "fail"


def test_optee_a4_boot_check_runs_only_a_pristine_upstream_evaluator(tmp_path, monkeypatch):
    # The harness reruns upstream's `make check-only` (no rebuild) itself, and only from a clean optee/build whose
    # HEAD is in upstream history: a model-written Makefile target or a fake QEMU cannot fabricate the boot.
    a4 = {t.id: t for t in map(Task.from_dict, json.loads((FIXTURES / "optee_goal_a.json").read_text()))}["a4-boot"]
    assert "make check-only " in a4.checks[0].cmd and a4.checks[0].timeout > 1500

    def git(*args, cwd):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                       capture_output=True)
    fake = "check-only:\n\techo 'I/TC: Primary CPU switching to normal world boot' > ../out/bin/serial1.log\n" \
           "\techo 'Linux version 6.x' > ../out/bin/serial0.log\n"
    seed, upstream = tmp_path / "seed", tmp_path / "upstream.git"
    seed.mkdir()
    (seed / "Makefile").write_text(fake)  # stands in for upstream's evaluator
    git("init", "-q", "-b", "master", cwd=seed)
    git("add", "Makefile", cwd=seed)
    git("commit", "-q", "-m", "upstream", cwd=seed)
    git("clone", "-q", "--bare", str(seed), str(upstream), cwd=tmp_path)
    work = tmp_path / "w"
    build, out, qemu, bin_ = work / "optee/build", work / "optee/out/bin", work / "optee/qemu/build", tmp_path / "bin"
    for d in (out, qemu, bin_):
        d.mkdir(parents=True)
    git("clone", "-q", str(upstream), str(build), cwd=tmp_path)
    (qemu / "qemu-system-aarch64").write_bytes(b"\x7fELF")
    (bin_ / "expect").write_text("#!/bin/sh\n")  # present, so the check does not apt-get it
    (bin_ / "expect").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}:{os.environ['PATH']}")
    monkeypatch.setenv("OPTEE_BUILD_UPSTREAM", str(upstream))

    def verdict():
        return core.run_checks(a4.checks, core.local_shell(work))[0]
    assert verdict() == "pass"
    (build / "Makefile").write_text(fake + "# edited\n")  # dirty tree
    assert verdict() == "fail"
    git("commit", "-q", "-am", "fabricated target", cwd=build)  # clean, but not upstream history
    assert verdict() == "fail"
    git("reset", "-q", "--hard", "origin/master", cwd=build)
    (qemu / "qemu-system-aarch64").write_text("#!/bin/sh\necho QEMU\n")  # not a built QEMU
    assert verdict() == "fail"
    (qemu / "qemu-system-aarch64").write_bytes(b"\x7fELF")
    (seed / "Makefile").write_text("check-only:\n\ttrue\n")  # upstream boot that writes no logs
    git("commit", "-q", "-am", "no logs", cwd=seed)
    git("push", "-q", str(upstream), "master", cwd=seed)
    git("pull", "-q", cwd=build)
    (out / "serial1.log").write_text("I/TC: Primary CPU switching to normal world boot\n")  # stale
    (out / "serial0.log").write_text("Linux version 6.x\n")
    assert verdict() == "fail"


def _goal_b():
    return {t.id: t for t in map(Task.from_dict, json.loads((FIXTURES / "optee_goal_b.json").read_text()))}


def _git(*args, cwd):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


OPTEE_FDT_STANZA = "device\toptee: smccc\nattach\toptee at fdt\nfile\tdev/fdt/optee.c\t\toptee\n"


def _netbsd_root(tmp_path, monkeypatch):
    """A stand-in NetBSD project: a git source tree with the driver enabled, a built kernel, a tooldir nm.
    Its first commit plays the snapshot baseline (NETBSD_BASE)."""
    nb = tmp_path / "nb"
    conf, kdir, tools = (nb / "netbsd-src/sys/arch/evbarm/conf", nb / "netbsd-obj/sys/arch/evbarm/compile/GENERIC64",
                         nb / "netbsd-obj/tooldir.Linux-x/bin")
    fdt = nb / "netbsd-src/sys/dev/fdt"
    for d in (conf, kdir, tools, fdt):
        d.mkdir(parents=True)
    (conf / "GENERIC64").write_text("simplebus*\tat fdt? pass 0\n")
    (fdt / "files.fdt").write_text("device\tsimplebus\n")
    src = nb / "netbsd-src"
    _git("init", "-q", cwd=src)
    _git("add", ".", cwd=src)
    _git("commit", "-q", "-m", "base", cwd=src)
    monkeypatch.setenv("NETBSD_BASE", _git("rev-parse", "HEAD", cwd=src))
    (conf / "GENERIC64").write_text("simplebus*\tat fdt? pass 0\noptee*\t\tat fdt? pass 0\n")
    (fdt / "files.fdt").write_text("device\tsimplebus\n" + OPTEE_FDT_STANZA)
    (fdt / "optee.c").write_text("CFATTACH_DECL_NEW(optee, 0, optee_match, optee_attach, NULL, NULL);\n")
    for f in (conf / "GENERIC64", fdt / "files.fdt", fdt / "optee.c"):
        os.utime(f, (1_000, 1_000))
    (kdir / "netbsd").write_text("kernel")
    (kdir / "netbsd.img").write_text("image")
    (tools / "aarch64--netbsd-nm").write_text("#!/bin/sh\necho 'ffffc00001234567 D optee_cd'\n")
    (tools / "aarch64--netbsd-nm").chmod(0o755)
    monkeypatch.setenv("NETBSD_ROOT", str(nb))
    return src, kdir


def test_optee_goal_b_checks_execute_and_reject_an_empty_workdir(tmp_path, monkeypatch):
    tasks = _goal_b()
    assert list(tasks) == ["b1a-driver-source", "b1b-kernel-build", "b2-firmware-boot", "b3-driver-proof"]
    monkeypatch.setenv("NETBSD_ROOT", str(tmp_path / "absent"))
    for t in tasks.values():
        assert core.run_checks(t.checks, core.local_shell(tmp_path))[0] == "fail"


def test_optee_goal_b_kernel_and_firmware_must_be_newer_than_the_driver_source(tmp_path, monkeypatch):
    # Changes are measured against the fixed snapshot commit, so unstaged, staged and committed edits all count.
    src, kdir = _netbsd_root(tmp_path, monkeypatch)
    b = _goal_b()
    b1a, b1 = b["b1a-driver-source"].checks, b["b1b-kernel-build"].checks
    fresh = [b["b2-firmware-boot"].checks[0], b["b3-driver-proof"].checks[0]]
    assert b1[0].cmd == b1a[0].cmd  # b1b re-checks b1a's source: removing the driver cannot pass the build
    assert fresh[0].cmd == fresh[1].cmd
    work = tmp_path / "w"
    (work / "netbsd-optee").mkdir(parents=True)
    (work / "netbsd-optee/qemu_fw.bios").write_text("fw")
    driver = src / "sys/dev/fdt/optee.c"

    def verdict(checks):
        return core.run_checks(checks, core.local_shell(work))[0]

    def at(path, t):
        os.utime(path, (t, t))
    at(kdir / "netbsd.img", 2_000)  # sources at 1_000
    at(work / "netbsd-optee/qemu_fw.bios", 2_500)
    assert verdict(b1) == "pass" and verdict(fresh[:1]) == "pass"
    at(driver, 3_000)  # driver edited after the build
    assert verdict(b1) == "fail" and verdict(fresh[:1]) == "fail"
    assert verdict(b1a) == "pass"  # b1a is source only: a stale kernel does not matter
    at(kdir / "netbsd.img", 4_000)  # kernel rebuilt, firmware not
    assert verdict(b1) == "pass" and verdict(fresh[:1]) == "fail"
    at(work / "netbsd-optee/qemu_fw.bios", 5_000)  # firmware rebuilt
    assert verdict(fresh[:1]) == "pass"
    _git("add", "sys", cwd=src)  # staged edit after the build
    at(driver, 6_000)
    assert verdict(b1) == "fail" and verdict(fresh[:1]) == "fail"
    _git("commit", "-q", "-m", "driver", cwd=src)  # committed edit: still a change against the snapshot
    assert verdict(b1) == "fail" and verdict(fresh[:1]) == "fail"
    at(kdir / "netbsd.img", 7_000)
    at(work / "netbsd-optee/qemu_fw.bios", 8_000)
    assert verdict(b1) == "pass" and verdict(fresh[:1]) == "pass"
    (tmp_path / "nb/netbsd-obj/tooldir.Linux-x/bin/aarch64--netbsd-nm").write_text("#!/bin/sh\necho 'x D other_cd'\n")
    assert verdict(b1) == "fail"  # kernel without the optee cfdriver
    (src / "sys/arch/evbarm/conf/GENERIC64").write_text("simplebus*\tat fdt? pass 0\n")
    assert verdict(b1a) == "fail"  # driver not enabled in GENERIC64


def test_optee_goal_b_b1a_needs_a_registered_changed_driver_not_only_a_config_line(tmp_path, monkeypatch):
    src, _ = _netbsd_root(tmp_path, monkeypatch)
    b1a = _goal_b()["b1a-driver-source"].checks
    fdt = src / "sys/dev/fdt"

    def verdict():
        return core.run_checks(b1a, core.local_shell(tmp_path))[0]
    assert verdict() == "pass"
    (fdt / "optee.c").unlink()
    (fdt / "files.fdt").write_text("device\tsimplebus\n")
    assert verdict() == "fail"  # only `optee* at fdt?` in GENERIC64
    (fdt / "files.fdt").write_text("device\tsimplebus\n" + OPTEE_FDT_STANZA)
    assert verdict() == "fail"  # registered, but the source file is missing
    (fdt / "optee.c").write_text("/* no autoconf glue */\n")
    assert verdict() == "fail"  # source without CFATTACH_DECL
    (fdt / "optee.c").write_text("CFATTACH_DECL_NEW(optee, 0, m, a, NULL, NULL);\n")
    assert verdict() == "pass"
    (fdt / "files.fdt").write_text("device\tsimplebus\ndevice\toptee: smccc\nfile\tdev/fdt/optee.c\toptee\n")
    assert verdict() == "fail"  # no `attach optee at fdt`
    (fdt / "files.fdt").write_text("device\tsimplebus\nattach\toptee at fdt\nfile\tdev/fdt/optee.c\toptee\n")
    assert verdict() == "fail"  # no `device optee`
    (fdt / "files.fdt").write_text("device\tsimplebus\n" + OPTEE_FDT_STANZA)
    _git("add", "-A", "sys", cwd=src)
    _git("commit", "-q", "-m", "driver", cwd=src)
    monkeypatch.setenv("NETBSD_BASE", _git("rev-parse", "HEAD", cwd=src))
    assert verdict() == "fail"  # driver already in the snapshot: not written by this sub-goal


def test_optee_goal_b_literal_guard_rejects_hard_coded_uid_words_and_build_hash(tmp_path, monkeypatch):
    src, _ = _netbsd_root(tmp_path, monkeypatch)
    guard = _goal_b()["b3-driver-proof"].checks[1]
    tee = tmp_path / "optee/optee_os"
    tee.mkdir(parents=True)
    _git("init", "-q", cwd=tee)
    _git("commit", "-q", "--allow-empty", "-m", "optee", cwd=tee)
    build_hash = _git("rev-parse", "HEAD", cwd=tee)

    def verdict():
        return core.run_checks([guard], core.local_shell(tmp_path))[0]
    assert verdict() == "pass"
    for literal in ("0x384FB3E0", "0xa5d5c51b", f"0x{build_hash[:9]}"):
        (src / "sys/arch/evbarm/optee.c").write_text(f'printf("optee0: UID {literal}\\n");\n')  # untracked
        assert verdict() == "fail", literal
    (src / "sys/arch/evbarm/optee.c").write_text("/* driver */\n")
    monkeypatch.setenv("NETBSD_ROOT", str(tmp_path / "absent"))  # git error is not "no match"
    assert verdict() == "fail"


def _proof_part(cmd):
    """The log-reading part of a boot check, without the QEMU run."""
    return cmd.split("[ $rc = 0 ] || [ $rc = 124 ]; } && ", 1)[1]


def test_optee_goal_b_proof_needs_every_uid_word_both_revisions_and_the_booted_kernel(tmp_path, monkeypatch):
    _, kdir = _netbsd_root(tmp_path, monkeypatch)
    boot = _goal_b()["b3-driver-proof"].checks[2].cmd
    proof = boot.split("; [ \"$(dpkg", 1)[0] + "; " + _proof_part(boot)  # path variables + log checks
    banner = "NetBSD 10.1_STABLE (GENERIC64) #7: Tue Oct 27 13:01:21 UTC 2026"
    (kdir / "netbsd.img").write_bytes(b"\0\0" + banner.encode() + b"\n\0")
    logs = tmp_path / "netbsd-optee"
    logs.mkdir()
    (logs / "serial1.log").write_text("I/TC: OP-TEE version: 4.11.0-38-g9185a5212 (gcc ...) #1\n"
                                      "I/TC: Primary CPU switching to normal world boot\n")
    good = {"banner": f"[   1.0000000] {banner}\r\n",
            "attach": "[   1.0000000] optee0 at simplebus0\r\n",
            "uid": "[   1.0000000] optee0: UID 0x384fb3e0 0xe7f811e3 0xaf630002 0xa5d5c51b\r\n",
            "api": "[   1.0000000] optee0: API revision 2.0\r\n",
            "os": "[   1.0000000] optee0: OS revision 4.11 build 0x9185a5212b78465a\r\n"}

    def verdict(**override):
        (logs / "serial0.log").write_text("".join({**good, **override}.values()))
        return core.run_checks([Check(proof)], core.local_shell(tmp_path))[0]
    assert verdict() == "pass"
    assert verdict(uid="[   1.0000000] optee0: UID 0x384fb3e0\r\n") == "fail"  # first word only
    assert verdict(uid="[   1.0000000] optee0: UID 0x384fb3e0 0x0 0x0 0x0\r\n") == "fail"
    assert verdict(api="") == "fail"
    assert verdict(os="") == "fail"
    assert verdict(os="[   1.0000000] optee0: OS revision 4.11 build 0x1234\r\n") == "fail"  # not the secure build
    assert verdict(os="[   1.0000000] optee0: OS revision 4.4 build 0x9185a5212b78465a\r\n") == "fail"
    assert verdict(banner=f"[   1.0000000] {banner.replace('#7', '#6')}\r\n") == "fail"  # an older kernel booted


def test_optee_goal_b_boots_only_the_package_verified_qemu(tmp_path, monkeypatch):
    # The harness boots with the dpkg-verified distro QEMU. A workdir script or a native executable that writes the
    # expected logs is rejected before anything runs.
    b = _goal_b()
    boots = [b["b2-firmware-boot"].checks[1], b["b3-driver-proof"].checks[2], b["b3-driver-proof"].checks[3]]
    auth = '[ "$(dpkg -S $Q 2>/dev/null)" = "qemu-system-arm: $Q" ] && [ -z "$(dpkg -V qemu-system-arm 2>&1)" ]'
    assert all(auth in c.cmd for c in boots)
    assert all("qemu/build" not in c.cmd for c in boots)  # never a workdir binary
    (tmp_path / "netbsd-optee").mkdir()
    (tmp_path / "netbsd-optee/qemu_fw.bios").write_text("fw")
    writer = ("echo 'I/TC: Primary CPU switching to normal world boot' > netbsd-optee/serial1.log; "
              "printf 'optee0 at simplebus0\\noptee0: UID 0x384fb3e0 0xe7f811e3 0xaf630002 0xa5d5c51b\\n' "
              "> netbsd-optee/serial0.log")
    fakes = [tmp_path / "qemu-script"]
    fakes[0].write_text(f"#!/bin/sh\n{writer}\n")
    fakes[0].chmod(0o755)
    cc = shutil.which("cc")
    if cc:
        (tmp_path / "fake.c").write_text("#include <stdlib.h>\nint main(void){return system(\"%s\");}\n"
                                         % writer.replace("\\", "\\\\").replace('"', '\\"'))
        subprocess.run([cc, "-o", str(tmp_path / "qemu-native"), str(tmp_path / "fake.c")], check=True)
        assert (tmp_path / "qemu-native").read_bytes()[:4] == b"\x7fELF"
        fakes.append(tmp_path / "qemu-native")
    for fake in fakes:
        monkeypatch.setenv("CHECK_QEMU", str(fake))
        for c in boots:
            r = core.run_checks([c], core.local_shell(tmp_path))
            assert r[0] == "fail" and "not the verified qemu-system-arm" in r[1][0]["stdout"], (fake, c.cmd[:80])
        assert not (tmp_path / "netbsd-optee/serial0.log").exists()  # rejected before it ran


def test_admission_bound_is_the_request_input_at_the_executors_ceiling(tmp_path):
    # MISSION 90b27cd: admission never reserves max_tokens x output price (pro at 128000 tokens: ~$0.97 per call).
    chat = Scripted(resp(call("run_shell", {"command": "echo yes > ok.txt"})), resp(call("finish", {})))
    trace = Trace(tmp_path / "trace.jsonl")
    task = dataclasses.replace(TOUCH, max_usd=0.05)
    res = run_task(task, chat, core.local_shell(tmp_path / "work"), trace, Budget(0.05), model="deepseek-v4-pro")
    assert res["status"] == "accepted", res  # the old output-reserving bound ($0.062+) refused pro under $0.05
    mc = [e for e in trace.events if e["event"] == "model_call"][0]
    req = {"model": "deepseek-v4-pro", "messages": chat.seen[0], "tools": core.TOOLS, "max_tokens": 128000}
    assert mc["bound_usd"] == pytest.approx(len(json.dumps(req).encode()) * core.CEILINGS["deepseek-v4-pro"][0])
    assert mc["bound_usd"] < 0.01


def test_an_executor_without_ceilings_is_refused_before_any_call(tmp_path, monkeypatch):
    chat = Scripted()
    with pytest.raises(KeyError):
        run_task(TOUCH, chat, core.local_shell(tmp_path / "work"), Trace(tmp_path / "t.jsonl"), Budget(1.0),
                 model="some-expensive-model")
    assert chat.seen == []
    monkeypatch.setattr(core, "load_key", lambda name: pytest.fail("key loaded"))
    with pytest.raises(SystemExit):
        core.main(["run", "--tasks", "t.json", "--out", str(tmp_path), "--model", "some-expensive-model"])


def test_d1_git_global_options_keep_a_read_a_read():
    row = {"event": "exec", "source": "model", "step": 1, "exit": 0, "stdout": "error: in file content\n"}
    assert core.audit([{**row, "command": "git -C src -c safe.directory='*' log -1"}]) == []
    assert len(core.audit([{**row, "command": "git -c user.name=x commit -m y"}])) == 1


def test_lab_shell_rides_out_transient_poll_failures(lab):
    calls = []

    def flaky(script):
        calls.append(script)
        return ["false"] if len(calls) in (2, 3) else core.local_remote(script)  # first poll: 2 of 3 attempts
    r = lab(remote=flaky)("sleep 0.5; echo done", 10)
    assert r["exit"] == 0 and r["stdout"] == "done\n"


def test_lab_shell_stops_when_poll_retries_are_exhausted(lab, tmp_path):
    def no_poll(script):
        return ["false"] if 'cat "$d/rc"' in script else core.local_remote(script)
    t0 = time.monotonic()
    r = lab(remote=no_poll)("sleep 30 & echo $! > child.pid; wait", 60)
    assert r["exit"] is None and r["transport_error"] == "poll" and time.monotonic() - t0 < 6
    assert not _alive(int((tmp_path / "work/child.pid").read_text()))
    assert core.run_checks([Check("true")], lab(remote=no_poll))[0] is None


def test_lab_shell_retried_launch_does_not_start_the_job_twice(lab, tmp_path):
    launches = []

    def drops_after_first_launch(script):
        if "base64 -d" in script and not launches:
            launches.append(script)
            return ["bash", "-c", script + "\nexit 255"]  # ran remotely, then the connection dropped
        return core.local_remote(script)
    r = lab(remote=drops_after_first_launch)("echo run >> count.txt; sleep 0.3", 10)
    assert r["exit"] == 0 and launches
    assert (tmp_path / "work/count.txt").read_text() == "run\n"


def test_lab_shell_transport_waits_are_bounded_by_the_command_timeout(lab, monkeypatch):
    monkeypatch.setattr(core, "GRACE", 0.5)
    t0 = time.monotonic()
    r = lab(remote=lambda script: ["sleep", "30"])("echo hi", 1)
    assert r["exit"] is None and time.monotonic() - t0 < 4


def test_unfetched_stdout_gives_no_verdict_for_an_output_check(lab):
    def no_stdout(script):
        return ["false"] if 'tail -c' in script and '/out"' in script else core.local_remote(script)
    r = lab(remote=no_stdout)("echo yes", 10)
    assert r["exit"] == 0 and r["unavailable"] == ["stdout"]
    assert core.run_checks([Check("echo yes", expect_stdout="yes")], lab(remote=no_stdout))[0] is None
    assert core.run_checks([Check("echo yes", expect_stdout="")], lab(remote=no_stdout))[0] is None
    assert core.run_checks([Check("true")], lab(remote=no_stdout))[0] == "pass"


def test_provider_call_is_bounded_by_the_lab_deadline(tmp_path):
    deadline = time.monotonic() + 30
    chat = Scripted(resp(call("finish", {})))
    run_task(Task(id="t", goal="g", checks=[Check("true")]), chat, core.local_shell(tmp_path), Trace(),
             Budget(1.0), deadline=deadline)
    assert 0 < chat.timeouts[0] <= 30

    def slow(messages, tools, timeout=None):
        time.sleep(timeout + 0.1)
        return resp(call("run_shell", {"command": "touch ran"}))
    res = run_task(TOUCH, slow, core.local_shell(tmp_path), Trace(), Budget(1.0),
                   deadline=time.monotonic() + 0.5)
    assert res["reason"] == "lab_deadline" and not (tmp_path / "ran").exists()


# ---------------------------------------------------------------- slice 3: lab egress


import http.server
import socket
import threading
import urllib.request


def _http_server():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = f"{self.path}|{self.headers.get('Connection')}|{self.headers.get('Proxy-Authorization')}"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_egress_proxy_forwards_absolute_form_http_as_one_closed_request():
    srv = _http_server()
    port = core.egress_proxy()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{port}"}))
    req = urllib.request.Request(f"http://127.0.0.1:{srv.server_port}/dists/x?y=1",
                                 headers={"Proxy-Authorization": "Basic x"})
    assert opener.open(req, timeout=10).read().decode() == "/dists/x?y=1|close|None"
    srv.shutdown()


def test_egress_proxy_tunnels_connect():
    echo = socket.create_server(("127.0.0.1", 0))

    def serve():
        c, _ = echo.accept()
        c.sendall(c.recv(100).upper())
        c.close()
    threading.Thread(target=serve, daemon=True).start()
    s = socket.create_connection(("127.0.0.1", core.egress_proxy()), timeout=10)
    s.sendall(f"CONNECT 127.0.0.1:{echo.getsockname()[1]} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    assert s.recv(100).startswith(b"HTTP/1.1 200")
    s.sendall(b"ping")
    assert s.recv(100) == b"PING"
    s.close()


def test_egress_proxy_answers_502_for_an_unreachable_upstream():
    dead = socket.create_server(("127.0.0.1", 0))
    port = dead.getsockname()[1]
    dead.close()
    s = socket.create_connection(("127.0.0.1", core.egress_proxy()), timeout=10)
    s.sendall(f"CONNECT 127.0.0.1:{port} HTTP/1.1\r\n\r\n".encode())
    assert s.recv(100).startswith(b"HTTP/1.1 502")


def test_lab_shell_exports_env_to_every_job(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    sh = core.lab_shell(core.local_remote, str(tmp_path / "w"), poll_s=0.1, env=core.PROXY_ENV)
    r = sh("echo $https_proxy $no_proxy", 10)
    assert r["stdout"] == f"http://127.0.0.1:3128 {core.PROXY_ENV['no_proxy']}\n"


def test_gcloud_tunnel_reverse_forwards_the_lab_proxy_port():
    argv = core.gcloud_tunnel("c3")(4567)
    assert argv[:4] == ["gcloud", "compute", "ssh", "conflux-dev-lab-c3"]
    assert "--ssh-flag=-R3128:127.0.0.1:4567" in argv and "--ssh-flag=-N" in argv
    assert "--ssh-flag=-oExitOnForwardFailure=yes" in argv and not any("--command" in a for a in argv)


def _tunnel_pid(out):
    return int((out / "tunnel.pid").read_text())


def test_run_lab_egress_failure_makes_no_model_call_and_kills_the_tunnel(lab, tmp_path, devbox_lab,
                                                                         monkeypatch):
    monkeypatch.setattr(core, "EGRESS_CHECK", "echo https://github.com 000; exit 1")
    chat = Scripted()
    s = _run_lab(tmp_path, chat)
    assert s["lab"]["stopped_reason"] == "egress_failed" and s["runs"] == [] and chat.seen == []
    assert s["lab"]["egress"]["exit"] == 1 and s["lab"]["tunnel_starts"] == 1
    assert devbox_lab() == ["up c2", "stop c2"]
    assert not _alive(_tunnel_pid(tmp_path))


def test_run_lab_sets_up_egress_before_the_first_task(lab, tmp_path, devbox_lab, monkeypatch):
    monkeypatch.setattr(core, "LAB_SETUP", "echo setup >> order.txt")
    monkeypatch.setattr(core, "EGRESS_CHECK", "echo egress >> order.txt")
    chat = Scripted(resp(call("run_shell", {"command": "echo task >> order.txt; echo yes > ok.txt"})),
                    resp(call("finish", {})))
    s = _run_lab(tmp_path, chat)
    assert s["accepted"] == 1 and s["lab"]["egress"]["exit"] == 0
    assert (tmp_path / "w/order.txt").read_text().split() == ["setup", "egress", "task"]
    assert not _alive(_tunnel_pid(tmp_path))


def test_egress_proxy_keeps_the_response_after_the_client_half_closes():
    up = socket.create_server(("127.0.0.1", 0))

    def serve():
        c, _ = up.accept()
        data = b""
        while chunk := c.recv(100):  # read to the client's EOF, then answer
            data += chunk
        c.sendall(data[::-1])
        c.close()
    threading.Thread(target=serve, daemon=True).start()
    s = socket.create_connection(("127.0.0.1", core.egress_proxy()), timeout=10)
    s.sendall(f"CONNECT 127.0.0.1:{up.getsockname()[1]} HTTP/1.1\r\n\r\n".encode())
    assert s.recv(100).startswith(b"HTTP/1.1 200")
    s.sendall(b"abc")
    s.shutdown(socket.SHUT_WR)
    assert s.recv(100) == b"cba"


# ---------------------------------------------------------------- pipefail + PIPESTATUS (C slice 6)


@pytest.fixture(params=["local", "lab"])
def any_shell(request, lab, tmp_path):
    return core.local_shell(tmp_path / "work") if request.param == "local" else lab()


def test_a_failing_pipeline_stage_is_not_masked(any_shell):
    r = any_shell("false | tail -n 1", 10)
    assert r["exit"] == 1 and r["pipestatus"] == [1, 0]
    assert "PIPESTATUS" not in r["stderr"]


def test_a_reader_that_exits_early_reports_sigpipe(any_shell):
    """The case acceptance checks must avoid: an early-exiting reader kills a long producer."""
    r = any_shell("seq 1000000 | head -n 1", 10)
    assert r["exit"] == 141 and r["pipestatus"] == [141, 0] and r["stdout"] == "1\n"


def test_explicit_exit_and_plain_output_are_unchanged(any_shell):
    r = any_shell("echo out; echo err >&2; false | true; exit 5", 10)
    assert r["exit"] == 5 and r["stdout"] == "out\n" and r["stderr"] == "err\n" and r["pipestatus"] == [1, 0]
    assert any_shell("true", 10)["pipestatus"] == [0]


def test_a_masked_build_failure_reaches_the_model_with_stage_statuses(tmp_path):
    """Run c4 shape: `make … 2>&1 | tail` reported exit 0 while make had failed."""
    build = "sh -c 'echo make: *** Error 2 >&2; exit 2' 2>&1 | tail -n 5"
    chat = Scripted(resp(call("run_shell", {"command": build})), resp(call("finish", {})),
                    resp(call("finish", {})), resp(call("finish", {})))
    res, trace = run(TOUCH, chat, tmp_path)
    ex = next(e for e in trace.events if e["event"] == "exec")
    assert ex["exit"] == 2 and ex["pipestatus"] == [2, 0]
    tool = next(m for m in chat.seen[1] if m["role"] == "tool")["content"]
    assert tool.startswith("exit=2 pipestatus=2 0\n") and "Error 2" in tool
    results = next(e for e in trace.events if e["event"] == "acceptance")["results"]
    assert results[0]["pipestatus"] == [1]


@pytest.mark.parametrize("ifs", ["IFS=", "IFS=:", "IFS=,", "unset IFS"])
def test_pipestatus_does_not_depend_on_the_commands_ifs(any_shell, ifs):
    r = any_shell(f"{ifs}; false | true | (exit 3)", 10)
    assert r["exit"] == 3 and r["pipestatus"] == [1, 0, 3] and "PIPESTATUS" not in r["stderr"]


def test_pipestatus_survives_stderr_written_after_the_exit_trap():
    """C slice 40 lead-c1 step 19: a `cmd &` child wrote stderr after the EXIT trap's marker."""
    late = ("/home/dev/.conflux-jobs/18e2f4f457e53c18/cmd.sh: line 4: cd: /home/darrenhidalgo/optee-demo: "
            "No such file or directory\n")
    assert core._split_pipestatus(f"\n{core._PS_MARK}0 failed=0\n{late}") == (late, [0], 0)


# The child writes only once the job's main shell is gone or a zombie, i.e. after its EXIT trap ran.
LATE_CHILD = ("true; (while [ -e /proc/$$ ] && ! grep -q ') Z' /proc/$$/stat; do sleep 0.01; done; "
              "echo late >&2; touch late.done) &")


@pytest.mark.parametrize("path", ["local", "lab"])
def test_a_background_childs_late_stderr_keeps_the_statuses(path, lab, tmp_path):
    if path == "local":
        r = core.local_shell(tmp_path / "work")(LATE_CHILD, 10)
    else:
        (tmp_path / "work").mkdir()

        def remote(script):
            if 'f="$d/err"' in script:  # collection waits for the late write
                end = time.monotonic() + 10
                while not (tmp_path / "work" / "late.done").exists():
                    assert time.monotonic() < end, "late child never wrote"
                    time.sleep(0.01)
            return core.local_remote(script)
        r = lab(remote=remote)(LATE_CHILD, 10)
    assert r["exit"] == 0 and r["pipestatus"] == [0] and r["failed_cmds"] == 0
    assert "late" in r["stderr"] and "PIPESTATUS" not in r["stderr"]


# ---------------------------------------------------------------- failed simple commands (C slice 7)


def test_a_failure_hidden_by_a_later_command_reaches_the_model(any_shell):
    """Run c3/a1 step 3 shape: a `;` chain hid a Traceback behind exit 0 (D1 residual)."""
    r = any_shell("python3 -c 'import nope'; echo ok", 10)
    assert r["exit"] == 0 and r["failed_cmds"] == 1 and r["stdout"] == "ok\n"
    assert "PIPESTATUS" not in r["stderr"] and "nope" in r["stderr"]
    assert core._tool_result(r, 10).startswith("exit=0 failed_cmds=1\n")


def test_conditions_and_handled_failures_are_not_counted(any_shell):
    r = any_shell("if false; then :; fi; false || true; ! false; true", 10)
    assert r["exit"] == 0 and r["failed_cmds"] == 0
    assert core._tool_result(r, 10).startswith("exit=0\n")


@pytest.mark.parametrize("cmd, exit, stages, failed", [
    ("false | true", 1, [1, 0], 1),
    ("false | true; exit 3", 3, [1, 0], 1),
    ("true | false | true; exit", 1, [0, 1, 0], 1),
    ("false; true | false", 1, [0, 1], 2),
])
def test_the_err_trap_keeps_the_final_pipelines_statuses(any_shell, cmd, exit, stages, failed):
    r = any_shell(cmd, 10)
    assert (r["exit"], r["pipestatus"], r["failed_cmds"]) == (exit, stages, failed)
    assert "failed_cmds" not in core._tool_result(r, 10)


# ---------------------------------------------------------------- D1 self-audit (work item F)

D1_CASES = json.loads((FIXTURES / "audit_d1_cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", D1_CASES, ids=lambda c: f"{c['trace']}:{c['step']}")
def test_d1_flags_exactly_the_masked_failures_of_the_demo_traces(case):
    findings = core.audit([case["row"]])
    assert [f["step"] for f in findings] == ([case["step"]] if case["expect"] == "hit" else [])


def test_d1_ignores_failed_exits_harness_rows_and_reads():
    out = "make: *** [all] Error 2"
    rows = [{"event": "exec", "source": "model", "step": 1, "command": "make", "exit": 2, "stdout": out},
            {"event": "exec", "source": "setup", "step": None, "command": "make", "exit": 0, "stdout": out},
            {"event": "exec", "source": "model", "step": 2, "command": "cat build.log | grep -n 'Error\\|fatal'",
             "exit": 0, "stdout": out},
            {"event": "exec", "source": "model", "step": 3, "command": "make; true", "exit": 0, "stderr": out}]
    assert [(f["check"], f["step"]) for f in core.audit(rows)] == [("D1", 3)]


@pytest.mark.parametrize("cmd, segs", [
    ("grep 'a\\|b' f; make", ["grep 'a\\|b' f", "make"]),
    ('echo "x;y" && ls', ['echo "x;y"', "ls"]),
    ("cd d && git log -3 | head\nls", ["git log -3", "head", "ls"]),
    ("echo a\;b || false", ["echo a\;b", "false"]),
])
def test_segments_split_only_outside_quotes(cmd, segs):
    assert core._scan(cmd)[0] == segs


def test_segments_drop_comments_even_with_apostrophes():
    assert core._scan("# Let's look\ngrep -n 'x' f # it's here")[0] == ["grep -n 'x' f"]


def test_d1_keeps_stderr_diagnostics_of_reads():
    row = {"event": "exec", "source": "model", "step": 1, "command": "cat /definitely-missing; echo done",
           "exit": 0, "stdout": "done\n", "stderr": "cat: /definitely-missing: No such file or directory\n"}
    assert [f["evidence"] for f in core.audit([row])] == ["cat: /definitely-missing: No such file or directory"]
    assert core.audit([{**row, "stdout": "error: in file content\n", "stderr": ""}]) == []


def test_d1_keeps_a_tool_error_that_an_unexecuted_fallback_echo_would_also_print():
    """An `|| echo` literal equal to the tool's error must not hide it: the audit cannot tell whether the echo ran."""
    row = next(c["row"] for c in D1_CASES if c["expect"] == "hit" and "curl -sL" in c["row"]["command"])
    row = {**row, "command": row["command"] + ' || echo "404: Not Found"'}
    assert [f["evidence"] for f in core.audit([row])] == ["404: Not Found"]


@pytest.mark.parametrize("cmd, exempt", [
    ("python3 -c 'import nope'; echo \"exit=$?\"", True),
    ("python3 -c 'import nope'; echo $?", True),
    ("python3 -c 'import nope'; echo '$?'", False),
    ("python3 -c 'import nope'; echo \\$?", False),
    ("python3 -c 'import nope' # then check $?", False),
    ("# echo $?\npython3 -c 'import nope'", False),
])
def test_d1_status_exemption_needs_an_expanded_dollar_question(cmd, exempt):
    row = {"event": "exec", "source": "model", "step": 1, "command": cmd, "exit": 0,
           "stderr": "Traceback (most recent call last):\nModuleNotFoundError: No module named 'nope'\n"}
    assert (core.audit([row]) == []) == exempt


def test_every_task_end_carries_its_audit(tmp_path):
    chat = Scripted(resp(call("run_shell", {"command": "printf 'fatal: no repo\\n' >&2; echo yes > ok.txt"})),
                    resp(call("finish", {})))
    res, trace = run(TOUCH, chat, tmp_path)
    assert res["status"] == "accepted" and res["audit_hits"] == 1
    events = [e["event"] for e in trace.events]
    assert events[-2:] == ["audit", "task_end"]
    assert trace.events[-2]["findings"][0]["evidence"] == "fatal: no repo"
    clean, _ = run(TOUCH, Scripted(resp(call("run_shell", {"command": "echo yes > ok.txt"})),
                                   resp(call("finish", {}))), tmp_path / "b")
    assert clean["audit_hits"] == 0


def test_audit_subcommand_needs_no_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(core, "SECRETS", tmp_path / "no-secrets")
    t = tmp_path / "trace.jsonl"
    t.write_text("\n".join(json.dumps(r) for r in [{"event": "task_start"}, D1_CASES[0]["row"]]) + "\n")
    assert core.main(["audit", str(t)]) == 0
    line = json.loads(capsys.readouterr().out)
    assert line["trace"] == str(t) and [f["step"] for f in line["findings"]] == [D1_CASES[0]["step"]]


def test_truncated_reply_is_named_to_the_model_and_is_not_a_finish(tmp_path):
    # c10/b1 steps 19-37: flash's reasoning filled max_tokens and cut the tool call off (arguments "{").
    cut = {"id": "c1", "type": "function", "function": {"name": "run_shell", "arguments": "{"}}
    cut_call = resp(cut, completion=1000)
    cut_call[1]["choices"][0]["finish_reason"] = "length"
    cut_plain = resp(completion=core.MAX_OUTPUT[core.MODEL])  # at the requested limit, no finish_reason: not a finish
    chat = Scripted(cut_call, cut_plain,
                    resp(call("run_shell", {"command": "echo yes > ok.txt"})), resp(call("finish", {})))
    res, trace = run(TOUCH, chat, tmp_path)
    assert res["status"] == "accepted" and res["retries"] == 0 and res["steps"] == 4
    assert [e["reason"] for e in trace.events if e["event"] == "policy"][0] == "truncated_at_max_tokens"
    assert "output limit" in chat.seen[1][-1]["content"] and chat.seen[1][-1]["role"] == "tool"
    assert "output limit" in chat.seen[2][-1]["content"] and chat.seen[2][-1]["role"] == "user"
    assert [e["step"] for e in trace.events if e["event"] == "acceptance"] == [4]
    assert [e["finish_reason"] for e in trace.events if e["event"] == "model_call"][0] == "length"


class FakeClock:
    """core.time stand-in: sleep() advances monotonic() instantly; time() is real (trace timestamps)."""

    def __init__(self):
        self.now, self.slept = 1000.0, []

    def monotonic(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s

    def time(self):
        return time.time()


def test_every_surplus_request_sets_the_discount_floor_and_waits_out_a_refusal(monkeypatch):
    # MISSION 5ee7a8b: without a floor kimi-k3.1-pro was billed at ~60% off while 96-99% offers existed.
    # 404 minimum_discount_not_met = no seller at the floor now: back off and retry, never a lower floor.
    seen, script = [], [404] * 7 + [200]

    def handler(request):
        seen.append(dict(request.headers))
        st = script.pop(0)
        if st == 404:
            return httpx.Response(404, json={"error": {"code": "minimum_discount_not_met", "message": "no seller"}})
        return httpx.Response(200, json={"id": "g", "choices": [{"message": {"role": "assistant", "content": ""}}],
                                         "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    clock = FakeClock()
    monkeypatch.setattr(core, "time", clock)
    chat = core.surplus_chat("k", "deepseek-v4-pro", httpx.Client(transport=httpx.MockTransport(handler)))
    status, body, _ = chat([{"role": "user", "content": "hi"}], core.TOOLS)
    assert status == 200 and len(seen) == 8 and clock.slept == [30, 60, 120, 300, 600, 600, 600]
    assert all(h["x-min-discount"] == "90" for h in seen)
    # the whole availability window without a seller: the refusal comes back (the caller decides), no lower floor
    script[:] = [404] * 100
    t0 = clock.now
    status, body, _ = chat([{"role": "user", "content": "hi"}], core.TOOLS)
    assert status == 404 and body["error"]["code"] == "minimum_discount_not_met"
    assert core.AVAILABILITY_WINDOW_S - 600 < clock.now - t0 <= core.AVAILABILITY_WINDOW_S
    script[:] = [404, 200]  # too little time left before the caller's deadline: returned, not slept through
    status, _, _ = chat([{"role": "user", "content": "hi"}], core.TOOLS, timeout=20)
    assert status == 404 and script == [200]
    # A slow refusal uses up the deadline too (PR #47 review): a 404 that takes 50 s of a 60 s budget is returned
    # instead of waiting 30 s past the deadline.
    slow = {"s": 50}
    orig = handler

    def slow_handler(request):
        clock.now += slow["s"]
        return orig(request)
    chat = core.surplus_chat("k", "deepseek-v4-pro", httpx.Client(transport=httpx.MockTransport(slow_handler)))
    script[:] = [404, 200]
    clock.slept.clear()
    status, _, _ = chat([{"role": "user", "content": "hi"}], core.TOOLS, timeout=60)
    assert status == 404 and script == [200] and clock.slept == []


def test_a_retry_never_outlasts_the_availability_window(monkeypatch):
    # PR #47 review: near the end of the window a retry could still be sent with the full CHAT_TIMEOUT (900 s). Each
    # retry's request timeout is now bounded by the window's remainder as well as the caller's deadline.
    clock = FakeClock()
    monkeypatch.setattr(core, "time", clock)
    monkeypatch.setattr(core, "AVAILABILITY_WINDOW_S", 100)
    monkeypatch.setattr(core, "AVAILABILITY_BACKOFF_S", (30,))
    timeouts = []

    def handler(request):
        timeouts.append(request.extensions["timeout"]["read"])
        clock.now += 25  # each refusal takes 25 s
        return httpx.Response(404, json={"error": {"code": "minimum_discount_not_met"}})
    chat = core.surplus_chat("k", "deepseek-v4-pro", httpx.Client(transport=httpx.MockTransport(handler)))
    status, body, _ = chat([{"role": "user", "content": "hi"}], core.TOOLS)
    # sent at 0 (900 s), refused at 25, slept 30, retry sent at 55 with <= 45 s left, refused at 80: 80 + 30 > 100
    assert status == 404 and timeouts[0] == core.CHAT_TIMEOUT and len(timeouts) == 2 and timeouts[1] <= 45


def test_a_provider_outage_never_ends_the_task_as_the_executors_doing(tmp_path, monkeypatch):
    # Slice 39 pair 1: HTTP 200 {"error": no_healthy_sellers} with no choices/usage ended both runs `unverified
    # provider_200` (lead at step 40, control at 107) and was settled at its input bound ($0.24, $0.66). Outages
    # (200 error body, 404 below the floor, 429/5xx) are retried with backoff over a long window; one that outlasts it
    # ends the task `unverified provider_unavailable`, never failed/finished; an error reply without usage costs 0.
    outage = {"error": {"type": "service_unavailable", "code": "no_healthy_sellers", "message": "none"}}
    script = [(200, outage)] * 6 + [(503, {"error": {"code": "no_healthy_sellers"}}),
                                     (404, {"error": {"code": "minimum_discount_not_met"}}), (200, None)]

    def handler(request):
        st, body = script.pop(0)
        if body is None:
            msg = {"role": "assistant", "content": "", "tool_calls": [call("finish", {})]}
            body = {"id": "g", "choices": [{"message": msg}], "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                                                                        "buyer_cost_micro": 3}}
        return httpx.Response(st, json=body)
    clock = FakeClock()
    monkeypatch.setattr(core, "time", clock)
    http_ = httpx.Client(transport=httpx.MockTransport(handler))
    task = dataclasses.replace(TOUCH, setup="echo yes > ok.txt")
    res, trace = run(task, core.surplus_chat("k", core.MODEL, http_), tmp_path)
    assert res["status"] == "accepted" and not script and sum(clock.slept) == 2910, res  # ~49 min of outage
    script[:] = [(200, outage)] * 1000
    (tmp_path / "2").mkdir()
    res, trace = run(task, core.surplus_chat("k", core.MODEL, http_), tmp_path / "2")
    mc = [e for e in trace.events if e["event"] == "model_call"]
    assert (res["status"], res["reason"]) == ("unverified", "provider_unavailable"), res
    assert [(e["cost_kind"], e["cost_usd"]) for e in mc] == [("no_usage", 0.0)] and res["cost_usd"] == 0


def test_every_call_requests_the_models_own_maximum_output(tmp_path, monkeypatch):
    # Fault (MISSION 90b27cd): max_tokens 8192 cut off 26/29 slice-34 calls; requests now carry the provider's
    # max_completion_tokens, less only what the context window cannot hold; unknown models omit max_tokens.
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "g", "choices": [{"message": {"role": "assistant", "content": ""}}],
                                         "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    http_ = httpx.Client(transport=httpx.MockTransport(handler))
    small = [{"role": "user", "content": "hi"}]
    for model in ("deepseek-v4-pro", "deepseek-v4.1-flash", "glm-5.3", "kimi-k3.1-pro", "unknown-model"):
        core.surplus_chat("k", model, http_)(small, core.TOOLS)
    assert [r.get("max_tokens") for r in sent] == [128000, 384000, 131072, 943718, None]
    assert "max_tokens" not in sent[-1]
    # Byte-heavy input that still leaves token headroom keeps the full limit (PR #47 review: counting bytes as tokens
    # cut a 900 KB pro request to 99 k): ~300 k tokens + 128 k output fit pro's 1 M context.
    core.surplus_chat("k", "deepseek-v4-pro", http_)([{"role": "user", "content": "x" * 900_000}], core.TOOLS)
    assert sent[-1]["max_tokens"] == 128000
    # Once the provider has counted the conversation, its count replaces the estimate: a 2.9 MB prompt is estimated at
    # ~967 k tokens (cold call clamped), but the provider reports 300 k, so the next turn gets the full 128 k.
    counted = []

    def counting(request):
        counted.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "g", "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                                         "usage": {"prompt_tokens": 300_000, "completion_tokens": 1_000}})
    chat = core.surplus_chat("k", "deepseek-v4-pro", httpx.Client(transport=httpx.MockTransport(counting)))
    convo = [{"role": "user", "content": "x" * 2_900_000}]
    chat(convo, core.TOOLS)
    convo += [{"role": "assistant", "content": "ok"}, {"role": "user", "content": "next"}]
    chat(convo, core.TOOLS)
    assert counted[0]["max_tokens"] < 128000 and counted[1]["max_tokens"] == 128000
    # Only what the context cannot hold is taken off: 2.4 MB (~800 k tokens) leaves kimi-k3.1-pro ~247 k of 943,718.
    core.surplus_chat("k", "kimi-k3.1-pro", http_)([{"role": "user", "content": "x" * 2_400_000}], core.TOOLS)
    assert 1048576 - 2_400_000 // 3 - 2000 < sent[-1]["max_tokens"] < 1048576 - 2_400_000 // 3 - core.CONTEXT_MARGIN


# ---------------------------------------------------------------- slice 17: slow provider replies


def _slow_once_surplus():
    """Local stand-in for Surplus chat: the first request answers after 1 s, later ones at once."""
    served = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            served.append(self.path)
            if len(served) == 1:
                time.sleep(1.0)
            n = len(served)
            msg = {"role": "assistant", "content": "",
                   "tool_calls": [call("run_shell", {"command": "echo yes > ok.txt"}) if n == 2
                                  else call("finish", {})]}
            body = json.dumps({"id": f"gen-{n}", "choices": [{"message": msg}],
                               "usage": {"prompt_tokens": 300, "completion_tokens": 40,
                                         "buyer_cost_micro": 14}}).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:  # the client already gave up on the slow reply
                pass

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, served


def test_slow_provider_reply_does_not_end_the_task(tmp_path, monkeypatch):
    # Fault: a reply slower than CHAT_TIMEOUT came back as status 0 and ended the task `unverified provider_0`
    # (headroom demo: 10/18 flash calls > 180 s). One transport failure is now retried, each attempt settled.
    srv, served = _slow_once_surplus()
    monkeypatch.setattr(core, "SURPLUS", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setattr(core, "CHAT_TIMEOUT", 0.3)
    try:
        res, trace = run(TOUCH, core.surplus_chat("k"), tmp_path)
    finally:
        srv.shutdown()
    assert res["status"] == "accepted", res
    calls = [e for e in trace.events if e["event"] == "model_call"]
    assert [(e["step"], e["attempt"], e["status"]) for e in calls] == [(1, 1, 0), (1, 2, 200), (2, 1, 200)]
    assert calls[0]["cost_kind"] == "pending" and res["cost_usd"] == pytest.approx(28e-6) and res["pending_calls"] == 1
    assert res["steps"] == 2 and len(served) == 3


def test_second_transport_failure_is_unverified(tmp_path):
    chat = Scripted((0, {"error": "ReadTimeout"}, 0.1), (0, {"error": "ReadTimeout"}, 0.1))
    res, trace = run(TOUCH, chat, tmp_path)
    assert res["status"] == "unverified" and res["reason"] == "provider_0" and len(chat.seen) == 2
    assert [e["attempt"] for e in trace.events if e["event"] == "model_call"] == [1, 2]


def test_http_error_is_not_retried(tmp_path):
    # run_task does not retry an HTTP reply itself: surplus_post already waited out the availability window.
    chat = Scripted((503, {"error": {"message": "no_healthy_sellers"}}, 0.2))
    res, _ = run(TOUCH, chat, tmp_path)
    assert res["reason"] == "provider_unavailable" and len(chat.seen) == 1
    chat = Scripted((400, {"error": {"message": "bad request"}}, 0.2))
    res, _ = run(TOUCH, chat, tmp_path / "x")
    assert res["reason"] == "provider_400" and len(chat.seen) == 1


def test_transport_failure_past_the_deadline_is_not_retried(tmp_path):
    calls = []

    def slow(messages, tools, timeout=None):
        calls.append(timeout)
        time.sleep(timeout + 0.1)
        return 0, {"error": "ReadTimeout"}, timeout
    res = run_task(TOUCH, slow, core.local_shell(tmp_path), Trace(), Budget(1.0), deadline=time.monotonic() + 0.3)
    assert res["reason"] == "lab_deadline" and len(calls) == 1


def test_chat_timeout_covers_measured_latency():
    assert core.CHAT_TIMEOUT >= 713  # slowest measured flash reply (headroom demo, 2026-10-27)


@pytest.mark.parametrize("redirect", ["", ">&2"])
def test_long_output_keeps_its_head_where_the_cause_is(any_shell, redirect):
    """C slice 21 step 12 (recorded job output, 4966 B): build.sh's `Permission denied` lines come first, so
    the old last-4096-bytes view returned only the cleandir failure summary and the model never saw the cause."""
    f = FIXTURES / "s21_step12_build_out.txt"
    r = any_shell(f"cat '{f}' {redirect}", 10)
    text = r["stderr" if redirect else "stdout"]
    marker = core._OMIT % (f.stat().st_size - core.TAIL)  # lab stderr also omits its PIPESTATUS bytes
    assert "Permission denied" in text and text.endswith("EXIT: 1\n") and "bytes omitted" in text
    assert len(text) <= core.TAIL + len(marker)


def test_output_that_fits_is_returned_whole(any_shell):
    r = any_shell(f"head -c {core.TAIL} /dev/zero | tr '\\0' x", 10)
    assert r["stdout"] == "x" * core.TAIL


def test_long_non_ascii_output_is_clipped_by_bytes(any_shell):
    """5000 x `é` is 10000 UTF-8 bytes: 5904 omitted, at most TAIL content bytes kept, on both paths."""
    r = any_shell("printf '%.0sé' $(seq 5000)", 10)
    marker = core._OMIT % (10000 - core.TAIL)
    head, sep, tail = r["stdout"].partition(marker)
    assert sep and head == "é" * (core.HEAD // 2) and tail == "é" * ((core.TAIL - core.HEAD) // 2)


# ---------------------------------------------------------------- slice 30: a scheduled supervisor message


def test_inject_is_sent_once_before_its_step(tmp_path):
    task = dataclasses.replace(TOUCH, inject_step=2, inject="Correction: write yes to ok.txt")
    chat = Scripted(resp(call("run_shell", {"command": "true"})),
                    resp(call("run_shell", {"command": "echo yes > ok.txt"})), resp(call("finish", {})))
    res, trace = run(task, chat, tmp_path)
    assert res["status"] == "accepted" and res["steps"] == 3
    assert all(m.get("content") != task.inject for m in chat.seen[0])
    assert chat.seen[1][-1] == {"role": "user", "content": task.inject}
    assert [m.get("content") for m in chat.seen[2]].count(task.inject) == 1
    assert [(e["step"], e["content"]) for e in trace.events if e["event"] == "inject"] == [(2, task.inject)]


def test_inject_after_finish_is_never_sent(tmp_path):
    task = dataclasses.replace(TOUCH, inject_step=3, inject="late")
    chat = Scripted(resp(call("run_shell", {"command": "echo yes > ok.txt"})), resp(call("finish", {})))
    res, trace = run(task, chat, tmp_path)
    assert res["status"] == "accepted" and not [e for e in trace.events if e["event"] == "inject"]
