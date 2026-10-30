"""Offline tests of the lead in conflux/core.py (C slice 49): the running lead steers without blocking the executor;
on a task with no checks a fresh lead's finish review is the stop rule (slice 48)."""

import json
import threading
import time

import pytest

from conflux import core
from conflux.core import Budget, Check, Task, Trace, run_task

TASK = "On the project, your goal is to:\n a) build the thing\n b) prove it works"
MARK = "RUNNING-LEAD-NOTE-7f3"


def executor(script, delay=0.05):
    """Executor fake: script(i) -> "shell" | "finish" for call i (1-based); records each request's messages."""
    seen, gaps, last = [], [], [None]

    def chat(messages, tools, timeout=None):
        now = time.monotonic()
        if last[0] is not None:
            gaps.append(now - last[0])
        seen.append(json.loads(json.dumps(messages)))
        i = len(seen)
        time.sleep(delay)
        kind = script(i)
        if kind == "finish":
            calls = [{"id": f"f{i}", "type": "function",
                      "function": {"name": "finish", "arguments": json.dumps({"summary": f"done {i}"})}}]
        else:
            calls = [{"id": f"c{i}", "type": "function",
                      "function": {"name": "run_shell", "arguments": json.dumps({"command": f"echo {i}"})}}]
        msg = {"role": "assistant", "content": "", "reasoning_content": f"r{i}", "tool_calls": calls}
        last[0] = time.monotonic()
        return 200, {"id": "x", "choices": [{"message": msg, "finish_reason": "tool_calls"}],
                     "usage": {"prompt_tokens": 1, "completion_tokens": 1, "buyer_cost_micro": 1}}, 0.0
    return chat, seen, gaps


def reply(text, micro=2):
    usage = {"prompt_tokens": 5, "completion_tokens": 3, **({"buyer_cost_micro": micro} if micro is not None else {})}
    return 200, {"id": "l", "choices": [{"message": {"content": text}, "finish_reason": "stop"}], "usage": usage}, 0.0


class FakeLead:
    """Lead fake. Calls on the main thread are the finish review's (the running lead's run in its review thread)."""

    def __init__(self, finish_done=lambda n: False, running_done=False, delay=0.0):
        self.convos, self.roles = [], []
        self.finish_done, self.running_done, self.delay = finish_done, running_done, delay
        self.live = self.peak = self.finish_reviews = 0
        self.lock = threading.Lock()

    def __call__(self, convo, timeout=None):
        role = "finish" if threading.current_thread() is threading.main_thread() else "running"
        with self.lock:
            self.convos.append(json.loads(json.dumps(convo)))
            self.roles.append(role)
            self.live += 1
            self.peak = max(self.peak, self.live)
        time.sleep(self.delay)
        with self.lock:
            self.live -= 1
        last = convo[-1]["content"]
        if role == "running":
            if last.endswith(core.INIT_ASK) or last.startswith(core.FINAL_ASK):
                return reply(f"GOAL: running-goal-a\nGOAL: running-goal-b\n{MARK} next steps"
                             + ("\nDONE" if self.running_done else ""))
            return reply(f"{MARK} answer")
        if core.FINISH_ASK in last and (last.startswith(core.FINAL_ASK) or core.INIT_ASK in last):
            self.finish_reviews += 1
            return reply("GOAL: fresh-goal\nreviewer: not proven yet"
                         + ("\nDONE" if self.finish_done(self.finish_reviews) else ""))
        if last.endswith(core.INIT_ASK) or last.startswith(core.FINAL_ASK):
            return reply("GOAL: fresh-goal\nfresh init")
        return reply("fresh answer")


def go(tmp_path, script, lead, steps=12, cadence=0.0, checks=(), delay=0.05, allowance=10.0):
    task = Task(id="t", goal=TASK, checks=list(checks), max_steps=steps, max_usd=100.0)
    trace = Trace(tmp_path / "trace.jsonl")
    chat, seen, gaps = executor(script, delay)
    res = run_task(task, chat, core.local_shell(tmp_path / "w"), trace, Budget(allowance), "deepseek-v4-pro",
                   lead_call=lead, cadence_s=cadence)
    rows = [json.loads(line) for line in (tmp_path / "lead.jsonl").read_text().splitlines()] \
        if (tmp_path / "lead.jsonl").exists() else []
    return res, trace, seen, gaps, rows


def test_no_checks_goal_text_is_task_text():
    assert core._goal_text(Task(id="t", goal=TASK, checks=[])) == TASK
    assert "Acceptance checks" in core._goal_text(Task(id="t", goal=TASK, checks=[Check("true")]))


def test_running_lead_layout_and_injection(tmp_path):
    lead = FakeLead()
    res, trace, seen, gaps, rows = go(tmp_path, lambda i: "shell", lead, steps=6, cadence=1e9)
    # One running review (cadence never elapses): init turn on the bare task, data first, request last.
    first = lead.convos[0]
    assert lead.roles[0] == "running" and len(first) == 2 and first[0]["content"] == core.LEAD_SYSTEM
    assert first[1]["content"].startswith("Analyze this:\n\nThe user's task (verbatim):\n" + TASK)
    assert first[1]["content"].endswith(core.INIT_ASK)
    # The executor's first request is the task text alone; the reply arrives at the next turn, after the tool result.
    assert seen[0][1]["content"] == TASK and len(seen[0]) == 2
    inj = [e for e in rows if e["event"] == "lead_inject"]
    assert inj and inj[0]["reviewed_step"] < inj[0]["step"]
    req = seen[inj[0]["step"] - 1]
    assert req[-1]["content"].startswith(core.PREFIX + "GOAL: running-goal-a") and req[-2]["role"] == "tool"
    assert [e["goals"] for e in rows if e["event"] == "lead_goals"][0] == ["running-goal-a", "running-goal-b"]
    # step cap, no checks: the fresh review rejected -> no verdict
    assert res["status"] == "unverified" and res["reason"] == "step_cap"


def test_goal_turns_on_later_reviews(tmp_path):
    lead = FakeLead()
    go(tmp_path, lambda i: "shell", lead, steps=10, cadence=0.0)
    run = [c for c, r in zip(lead.convos, lead.roles) if r == "running"]
    goal1 = next(c for c in run if len(c) == 2 and c[1]["content"].endswith(
        core.FIRST_GOAL.format(n=2, g="running-goal-a")))
    i = run.index(goal1)
    assert run[i + 1][-1]["content"] == core.NEXT_GOAL.format(i=2, n=2, g="running-goal-b") and len(run[i + 1]) == 4
    assert run[i + 2][-1]["content"] == core.FINAL_ASK and len(run[i + 2]) == 6
    # The second review's data carries the first review's notes; the running lead's own messages are not activity.
    data = goal1[1]["content"]
    assert f"Your final answer last time:\nGOAL: running-goal-a" in data
    assert "harness message to the agent" not in data


def test_never_blocks_and_one_in_flight(tmp_path):
    lead = FakeLead(delay=0.15)
    res, trace, seen, gaps, rows = go(tmp_path, lambda i: "shell", lead, steps=30, cadence=0.1, delay=0.02)
    starts = [e for e in rows if e["event"] == "lead_start"]
    assert len(starts) >= 3 and lead.peak == 1
    assert max(gaps) < 0.1  # the executor never waited for a running review (step cap review comes after)


def test_finish_review_loop(tmp_path):
    lead = FakeLead(finish_done=lambda n: n >= 2)
    res, trace, seen, gaps, rows = go(tmp_path, lambda i: "finish" if i in (5, 8) else "shell", lead, steps=20)
    assert res["status"] == "unverified" and res["reason"] == "finish_review_done" and res["steps"] == 8
    assert res["retries"] == 1
    fr = [e for e in trace.events if e["event"] == "finish_review"]
    assert [e["verdict"] for e in fr] == ["fail", "pass"]
    # The rejection reached the executor at the next step.
    assert seen[5][-1]["content"] == core.PREFIX + "GOAL: fresh-goal\nreviewer: not proven yet"
    finish = [c for c, r in zip(lead.convos, lead.roles) if r == "finish"]
    # Fresh protocol: init review through step k-10 (k=5 -> step 1), then the finish review with the summary.
    assert finish[0][1]["content"].endswith(core.INIT_ASK) and "The agent has called finish" not in finish[0][1]["content"]
    assert "### step 2" not in finish[0][1]["content"]
    assert "The agent has called finish with this summary:\ndone 5" in finish[1][1]["content"]
    assert finish[-1][-1]["content"] == core.FINAL_ASK + "\n\n" + core.FINISH_ASK
    # The first finish rejection is visible to the running lead as a harness message.
    later = [c[1]["content"] for c, r in zip(lead.convos, lead.roles) if r == "running" and len(c) == 2]
    assert any("harness message to the agent:\n" + core.PREFIX + "GOAL: fresh-goal" in d for d in later)
    assert res["lead_cost_usd"] == pytest.approx(len(lead.convos) * 2e-6)


def test_finish_review_gets_none_of_the_running_leads_state(tmp_path):
    """Regression (slice 48): the stop rule's review must not see the running lead's notes, goal list or injected
    replies; reusing the running Lead (or its messages) puts MARK and its goals into the finish review."""
    lead = FakeLead()
    res, trace, seen, gaps, rows = go(tmp_path, lambda i: "finish" if i == 9 else "shell", lead, steps=9, cadence=0.0)
    assert any(r == "running" for r in lead.roles) and any(MARK in json.dumps(c) for c in lead.convos)
    assert any(m["content"].startswith(core.PREFIX + "GOAL: running-goal") for m in seen[-1] if m["role"] == "user")
    finish = [c for c, r in zip(lead.convos, lead.roles) if r == "finish"]
    assert len(finish) >= 2
    for c in finish:
        text = json.dumps(c)
        assert MARK not in text and "running-goal" not in text
    assert "(none: the run is starting)" in finish[0][1]["content"]


def test_running_lead_done_never_stops(tmp_path):
    lead = FakeLead(running_done=True)
    res, *_ = go(tmp_path, lambda i: "shell", lead, steps=8, cadence=0.0)
    assert res["status"] == "unverified" and res["reason"] == "step_cap" and res["steps"] == 8


def test_step_cap_review(tmp_path):
    lead = FakeLead(finish_done=lambda n: True)
    res, trace, seen, gaps, rows = go(tmp_path, lambda i: "shell", lead, steps=4, cadence=1e9)
    assert res["reason"] == "finish_review_done_at_step_cap" and res["status"] == "unverified"
    finish = [c for c, r in zip(lead.convos, lead.roles) if r == "finish"]
    assert core.CAP_SUMMARY in finish[-1][1]["content"]


def test_finish_review_no_reply(tmp_path):
    def call(convo, timeout=None):
        if threading.current_thread() is threading.main_thread():
            return 503, {"error": "no_healthy_sellers"}, 0.0
        return reply("GOAL: g")
    res, trace, *_ = go(tmp_path, lambda i: "finish" if i == 2 else "shell", call, steps=5, cadence=1e9)
    assert res["status"] == "unverified" and res["reason"] == "finish_review_no_reply"


def test_tasks_with_checks_keep_acceptance(tmp_path):
    lead = FakeLead()
    res, trace, seen, *_ = go(tmp_path, lambda i: "finish" if i == 2 else "shell", lead, steps=5, cadence=1e9,
                              checks=[Check("true")])
    assert res["status"] == "accepted" and res["reason"] == "checks_passed"
    assert "finish" not in lead.roles
    assert "Acceptance checks" in seen[0][1]["content"]


def test_lead_cost_pending_is_deferred(tmp_path):
    def call(convo, timeout=None):
        return reply("GOAL: g\nnext", micro=None)
    trace = Trace()
    budget = Budget(1.0)
    lead = core.Lead(call, "kimi-k3", budget, trace, TASK, set())
    assert lead.ask([{"role": "system", "content": "s"}], 1) == "GOAL: g\nnext"
    row = [e for e in trace.events if e["event"] == "lead_call"][0]
    assert row["cost_kind"] == "pending" and row["cost_usd"] == 0 and len(budget.pending) == 1


def test_budget_lock_is_reentrant():
    """A deferred settlement callback that touches the budget inside resolve() must not deadlock (slice 47)."""
    budget = Budget(1.0, billing=lambda day: [])
    budget.defer({"model": "m", "ts": time.time() - 10_000, "usage": None},
                 lambda usd, kind, rid: budget.settle(0.0, usd))
    t = threading.Thread(target=lambda: budget.admit(0.0) and budget.resolve(force=True))
    t.start()
    t.join(5)
    assert not t.is_alive() and not budget.pending


def test_task_cap_counts_lead_spend(tmp_path):
    """PR #58 review: executor + lead spend together are capped by task.max_usd, before calls by either role."""
    lead = FakeLead()
    task = Task(id="t", goal=TASK, checks=[], max_steps=30, max_usd=8e-6)
    chat, seen, _ = executor(lambda i: "shell")
    res = run_task(task, chat, core.local_shell(tmp_path / "w"), Trace(tmp_path / "trace.jsonl"), Budget(10.0),
                   "deepseek-v4-pro", lead_call=lead, cadence_s=0.0)
    assert res["reason"] == "task_budget"
    # 1 micro per executor call, 2 per lead call: the cap binds on the sum; one call in flight may overshoot it
    assert res["cost_usd"] + res["lead_cost_usd"] < 8e-6 + 3e-6
    assert res["cost_usd"] < 8e-6


def test_zero_task_cap_makes_no_lead_call(tmp_path):
    lead = FakeLead()
    task = Task(id="t", goal=TASK, checks=[], max_steps=5, max_usd=0.0)
    chat, seen, _ = executor(lambda i: "shell")
    res = run_task(task, chat, core.local_shell(tmp_path / "w"), Trace(tmp_path / "trace.jsonl"), Budget(10.0),
                   "deepseek-v4-pro", lead_call=lead, cadence_s=0.0)
    assert res["reason"] == "task_budget" and lead.convos == [] and seen == []


def test_lead_closed_and_accounted_on_check_acceptance(tmp_path):
    """PR #58 review: an in-flight review is waited for and accounted before task_end; nothing starts after it."""
    lead = FakeLead(delay=0.3)
    res, trace, seen, gaps, rows = go(tmp_path, lambda i: "finish" if i == 1 else "shell", lead, steps=5,
                                      cadence=0.0, checks=[Check("true")], delay=0.0)
    assert res["status"] == "accepted"
    assert not any(t.name != "MainThread" and t.is_alive() for t in threading.enumerate() if t.daemon)
    calls = [e for e in rows if e["event"] == "lead_call"]
    assert len(calls) == 1 and res["lead_cost_usd"] == pytest.approx(2e-6)
    end = next(e for e in trace.events if e["event"] == "task_end")
    assert all(e["ts"] <= end["ts"] for e in rows if e["event"] == "lead_call")
    time.sleep(0.4)
    assert len(lead.convos) == 1


def test_lead_closed_when_the_executor_raises(tmp_path):
    lead = FakeLead(delay=0.2)
    chat, _, _ = executor(lambda i: "shell", delay=0.0)

    def boom(messages, tools, timeout=None):
        if len(messages) > 4:
            raise RuntimeError("executor fault")
        return chat(messages, tools, timeout)
    task = Task(id="t", goal=TASK, checks=[], max_steps=10, max_usd=1.0)
    with pytest.raises(RuntimeError):
        run_task(task, boom, core.local_shell(tmp_path / "w"), Trace(tmp_path / "trace.jsonl"), Budget(10.0),
                 "deepseek-v4-pro", lead_call=lead, cadence_s=0.0)
    assert not any(t.is_alive() for t in threading.enumerate() if t.daemon and t.name != "MainThread")
    n = len(lead.convos)
    time.sleep(0.3)
    assert len(lead.convos) == n == 1


class HookLock:
    """A lock that runs `hook` once, right after the main thread's first release (deterministic interleaving)."""

    def __init__(self):
        self.inner, self.hook = threading.Lock(), None

    def __enter__(self):
        self.inner.acquire()

    def __exit__(self, *exc):
        self.inner.release()
        if self.hook and threading.current_thread() is threading.main_thread():
            hook, self.hook = self.hook, None
            hook()


def test_review_finishing_mid_turn_is_not_overwritten():
    """PR #58 review: a review that completes during Steering.turn (after its reply was looked for) must not let a
    successor start; its reply is injected at the next turn."""
    gate, n = threading.Event(), [0]

    def call(convo, timeout=None):
        n[0] += 1
        if n[0] == 1:
            gate.wait(5)
        return reply(f"GOAL: g\nreview {n[0]}")
    lead = core.Lead(call, "kimi-k3", Budget(1.0), Trace(), TASK, set())
    st = core.Steering(lead, cadence_s=0.0)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": TASK}]
    st.turn(msgs, 1)  # review 1 starts and blocks
    first = st.thread
    st.lock = HookLock()

    def finish_review_1():
        gate.set()
        first.join(5)
    st.lock.hook = finish_review_1  # review 1 completes between the turn's critical section and the rest
    st.turn(msgs, 2)
    assert st.n == 1 and st.thread is first  # no successor while review 1's reply is untaken
    st.turn(msgs, 3)
    assert msgs[-1]["content"] == core.PREFIX + "GOAL: g\nreview 1" and st.n == 2
    st.close(3)


def test_reconcile_includes_lead_calls(tmp_path, monkeypatch):
    """PR #58 review: `reconcile` bills lead calls (lead.jsonl) alongside executor calls, attributed to the task."""
    d = tmp_path / "run12"
    d.mkdir()
    usage = {"prompt_tokens": 10, "completion_tokens": 2}
    (d / "trace.jsonl").write_text(json.dumps({"event": "model_call", "ts": 1000.0, "task": "run12", "step": 1,
                                               "model": "deepseek-v4-pro", "usage": usage, "cost_usd": 0}) + "\n")
    (d / "lead.jsonl").write_text(json.dumps({"event": "lead_call", "ts": 1001.0, "role": "running", "step": 1,
                                              "turn": "init", "model": "kimi-k3", "usage": usage, "cost_usd": 0,
                                              "id": "gen-l"}) + "\n")
    rows = [{"request_id": "a", "created_at": "1970-01-01T00:16:40Z", "model": "deepseek-v4-pro", "input_tokens": "10",
             "output_tokens": "2", "buyer_cost_usd": "0.0001"},
            {"request_id": "b", "created_at": "1970-01-01T00:16:41Z", "model": "kimi-k3", "input_tokens": "10",
             "output_tokens": "2", "buyer_cost_usd": "0.00002"}]
    monkeypatch.setattr(core, "load_key", lambda name: "k")
    monkeypatch.setattr(core, "fetch_export", lambda key, day: rows)
    assert core.main(["reconcile", "--out", str(tmp_path), "--day", "1970-01-01"]) == 0
    rep = json.loads((tmp_path / "reconciled.json").read_text())
    assert rep["billed_usd"] == pytest.approx(0.00012) and rep["lead_billed_usd"] == pytest.approx(0.00002)
    lead_row = next(m for m in rep["matched"] if m.get("lead"))
    assert lead_row["task"] == "run12" and lead_row["lead"] == "lead:running:init"
