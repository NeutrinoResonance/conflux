"""C slice 78: a task with no checks and no lead must not end `accepted`. `run_checks([])` returned "pass", so the
executor's bare `finish` (or the step cap) on a `checks: []` task was a vacuous acceptance."""

from conflux import core
from conflux.core import Budget, Task, Trace, run_task

from tests.test_core_lead import TASK, executor


def _run(tmp_path, script, steps):
    task = Task(id="t", goal=TASK, checks=[], max_steps=steps, max_usd=1.0)
    chat, _, _ = executor(script, delay=0.0)
    return run_task(task, chat, core.local_shell(tmp_path / "w"), Trace(tmp_path / "trace.jsonl"), Budget(10.0),
                    "deepseek-v4-pro")


def test_empty_check_list_has_no_verdict():
    assert core.run_checks([], lambda cmd, t: {}) == (None, [])


def test_finish_without_checks_or_lead_is_unverified(tmp_path):
    res = _run(tmp_path, lambda i: "finish", 5)
    assert (res["status"], res["reason"]) == ("unverified", "check_no_verdict")


def test_step_cap_without_checks_or_lead_is_unverified(tmp_path):
    res = _run(tmp_path, lambda i: "shell", 3)
    assert (res["status"], res["reason"]) == ("unverified", "check_no_verdict")
