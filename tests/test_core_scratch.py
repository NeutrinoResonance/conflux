"""Offline tests of the lead's verify session in conflux/core.py (C slice 56; mechanism measured in C slice 55,
`~/evidence/exec-deliver-demo-2026-10-31/RESULTS.md`): after a running review the lead runs commands in a scratch,
delivers a selection, the harness replays it on a fresh scratch (one feedback turn on failure), and the executor
receives the replayed commands verbatim."""

import base64
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

import pytest

from conflux import core
from conflux.core import Budget, Check, Lead, LocalScratch, Task, Trace, run_task

TASK = "On the project, your goal is to build the thing."


def tc(i, name, **args):
    return {"id": f"t{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def body(calls=(), content="", micro=2):
    msg = {"content": content, "reasoning_content": "lead-reasoning"}
    if calls:
        msg["tool_calls"] = list(calls)
    usage = {"prompt_tokens": 5, "completion_tokens": 3, **({"buyer_cost_micro": micro} if micro is not None else {})}
    return 200, {"id": "v", "choices": [{"message": msg, "finish_reason": "tool_calls" if calls else "stop"}],
                 "usage": usage}, 0.0


class ScriptedLead:
    """Review calls (no tools) answer with a fixed reply; verify calls (tools given) follow `script`, a list of
    functions convo -> reply (the last one repeats)."""

    def __init__(self, script, review="REVIEW-REPLY next steps"):
        self.script, self.review = script, review
        self.verify_convos, self.verify_tools = [], []
        self.lock = threading.Lock()

    def __call__(self, convo, timeout=None, tools=None):
        if tools is None:
            if threading.current_thread() is threading.main_thread():  # a finish review (fresh lead)
                return body(content="GOAL: g1\nfinish review\nDONE")
            return body(content=f"GOAL: g1\n{self.review}")
        with self.lock:
            self.verify_convos.append(json.loads(json.dumps(convo)))
            self.verify_tools.append([t["function"]["name"] for t in tools])
            i = len(self.verify_convos) - 1
        return self.script[min(i, len(self.script) - 1)](convo)


def run(*cmds_then_deliver):
    """Script steps: each item is a list of (name, args) tool calls."""
    steps = []
    for n, item in enumerate(cmds_then_deliver):
        steps.append(lambda convo, item=item, n=n: body([tc(f"{n}-{j}", name, **args)
                                                         for j, (name, args) in enumerate(item)]))
    return steps


def lead_for(tmp_path, call, may_spend=None, budget=None):
    trace = Trace(tmp_path / "lead.jsonl")
    lead = Lead(call, "kimi-k3", budget or Budget(10.0), trace, TASK, set(), may_spend=may_spend)
    lead.convo = [{"role": "system", "content": core.LEAD_SYSTEM}, {"role": "user", "content": "data"},
                  {"role": "assistant", "content": "R1"}]
    return lead, trace


def scratch_for(tmp_path):
    w = tmp_path / "work"
    w.mkdir()
    (w / "base.txt").write_text("base\n")
    return LocalScratch(w, tmp_path / "scr")


def rows(trace, event):
    return [e for e in trace.events if e["event"] == event]


def test_delivered_commands_follow_selection_order(tmp_path):
    lead, trace = lead_for(tmp_path, ScriptedLead(run(
        [("run_shell", {"command": "echo AAA > a.txt"})],
        [("run_shell", {"command": "echo BBB > b.txt"})],
        [("deliver", {"commands": [2, 1], "note": "the note"})])))
    out = lead.verify(3, scratch_for(tmp_path))
    assert out["ids"] == [2, 1] and out["replay_ok"] and out["note"] == "the note"
    assert [c["command"] for c in out["commands"]] == ["echo BBB > b.txt", "echo AAA > a.txt"]
    text = core.deliver_text("REVIEW", out)
    assert text.startswith(core.PREFIX + "REVIEW") and core.DELIVER_HEAD in text and "the note" in text
    assert text.index("echo BBB") < text.index("echo AAA")
    assert "1. (timeout_s 60)\n```bash\necho BBB > b.txt\n```" in text
    assert [r["n"] for r in rows(trace, "scratch_exec")] == [1, 2]
    assert rows(trace, "lead_deliver")[0]["why"] == "delivered"


def test_scratch_starts_from_workdir_and_leaves_it_unchanged(tmp_path):
    sc = scratch_for(tmp_path)
    lead, trace = lead_for(tmp_path, ScriptedLead(run(
        [("run_shell", {"command": "cat base.txt && echo new > new.txt"})],
        [("deliver", {"commands": [1]})])))
    assert lead.verify(1, sc)["replay_ok"]
    assert "base" in rows(trace, "scratch_exec")[0]["stdout"]
    assert not (tmp_path / "work" / "new.txt").exists()
    assert list((tmp_path / "scr").iterdir()) == []  # every scratch removed


def test_replay_is_on_a_fresh_copy_and_feedback_comes_once(tmp_path):
    lead_call = ScriptedLead(run(
        [("run_shell", {"command": "echo x > only.txt"})],
        [("run_shell", {"command": "test -f only.txt"})],
        [("deliver", {"commands": [2]})],          # fails on a fresh copy: only.txt was made by #1
        [("deliver", {"commands": [1, 2]})]))
    lead, trace = lead_for(tmp_path, lead_call)
    out = lead.verify(1, scratch_for(tmp_path))
    assert out["ids"] == [1, 2] and out["replay_ok"]
    assert [r["ok"] for r in rows(trace, "scratch_replay")] == [False, True]
    fb = [m for m in lead_call.verify_convos[-1] if m["role"] == "tool" and m["content"].startswith("The harness re-ran")]
    assert len(fb) == 1 and "[replay 1 of 1: your command #2]\nexit=1" in fb[0]["content"]


def test_second_failing_replay_is_delivered_without_more_feedback(tmp_path):
    lead_call = ScriptedLead(run([("run_shell", {"command": "false"})], [("deliver", {"commands": [1]})]))
    lead, trace = lead_for(tmp_path, lead_call)
    out = lead.verify(1, scratch_for(tmp_path))
    assert out["ids"] == [1] and out["replay_ok"] is False
    assert len(rows(trace, "scratch_replay")) == 2
    d = rows(trace, "lead_deliver")[0]
    assert d["feedback"] and d["why"] == "delivered"


def test_invalid_selection_is_a_tool_error(tmp_path):
    lead_call = ScriptedLead(run([("run_shell", {"command": "true"})], [("deliver", {"commands": [5]})],
                                 [("deliver", {"commands": [True]})], [("deliver", {"commands": [1]})]))
    lead, trace = lead_for(tmp_path, lead_call)
    assert lead.verify(1, scratch_for(tmp_path))["ids"] == [1]
    tool_msgs = [m["content"] for m in lead_call.verify_convos[-1] if m["role"] == "tool"]
    assert "invalid command numbers [5]; run so far: 1..1" in tool_msgs
    assert "invalid arguments: commands must be a list of command numbers" in tool_msgs


def test_command_cap_forces_deliver_and_feedback_raises_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "VERIFY_MAX_CMDS", 2)
    monkeypatch.setattr(core, "VERIFY_EXTRA", 1)
    lead_call = ScriptedLead(run(
        [("run_shell", {"command": "true"}), ("run_shell", {"command": "true"}), ("run_shell", {"command": "true"})],
        [("deliver", {"commands": [2]}), ("run_shell", {"command": "false"})],
        [("run_shell", {"command": "false"})],
        [("deliver", {"commands": [3]})],           # fails: feedback, cap 3 + 1
        [("run_shell", {"command": "true"}), ("run_shell", {"command": "true"})],
        [("deliver", {"commands": [4]})]))
    lead, trace = lead_for(tmp_path, lead_call)
    out = lead.verify(1, scratch_for(tmp_path))
    assert lead_call.verify_tools[0] == ["run_shell", "deliver"]
    first = [m["content"] for m in lead_call.verify_convos[1] if m["role"] == "tool"]
    assert first[2] == "command limit reached; command not run"
    assert lead_call.verify_convos[1][-1] == {"role": "user", "content": core.VERIFY_FORCE}
    assert lead_call.verify_tools[1] == ["deliver"]
    # The forced deliver of [2] replays ok: delivered at once.
    assert out["ids"] == [2] and out["replay_ok"]
    assert len(rows(trace, "scratch_exec")) == 2


def test_feedback_raises_the_command_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "VERIFY_MAX_CMDS", 1)
    monkeypatch.setattr(core, "VERIFY_EXTRA", 1)
    lead_call = ScriptedLead(run(
        [("run_shell", {"command": "false"})],
        [("deliver", {"commands": [1]})],           # fails: feedback, cap 1 + 1
        [("run_shell", {"command": "true"}), ("run_shell", {"command": "true"})],
        [("deliver", {"commands": [2]})]))
    lead, trace = lead_for(tmp_path, lead_call)
    out = lead.verify(1, scratch_for(tmp_path))
    assert lead_call.verify_tools[2] == ["run_shell", "deliver"]  # feedback lifts the forced state
    tool_msgs = [m["content"] for m in lead_call.verify_convos[3] if m["role"] == "tool"]
    assert tool_msgs[-1] == "command limit reached; command not run"
    assert out["ids"] == [2] and len(rows(trace, "scratch_exec")) == 2


def test_max_calls_and_wall_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "VERIFY_MAX_CALLS", 3)
    lead_call = ScriptedLead(run([("run_shell", {"command": "true"})]))
    lead, trace = lead_for(tmp_path, lead_call)
    assert lead.verify(1, scratch_for(tmp_path)) is None
    assert rows(trace, "lead_deliver")[0]["why"] == "max_calls" and len(lead_call.verify_convos) == 3

    lead_call = ScriptedLead(run([("run_shell", {"command": "true"})], [("deliver", {"commands": [1]})]))
    (tmp_path / "b").mkdir()
    lead, _ = lead_for(tmp_path / "b", lead_call)
    assert lead.verify(1, scratch_for(tmp_path / "b"), wall_s=0)["ids"] == [1]
    assert lead_call.verify_tools[1] == ["deliver"]


def test_no_deliver_after_nudge_and_empty_selection_give_no_delivery(tmp_path):
    lead_call = ScriptedLead([lambda c: body(content="I think it is fine")])
    lead, trace = lead_for(tmp_path, lead_call)
    assert lead.verify(1, scratch_for(tmp_path)) is None
    assert lead_call.verify_convos[1][-1] == {"role": "user", "content": core.VERIFY_NUDGE}
    assert rows(trace, "lead_deliver")[0]["why"] == "no_deliver"
    assert core.deliver_text("R", None) == core.PREFIX + "R"

    (tmp_path / "e").mkdir()
    lead, trace = lead_for(tmp_path / "e", ScriptedLead(run([("deliver", {"commands": []})])))
    assert lead.verify(1, scratch_for(tmp_path / "e")) is None
    assert rows(trace, "lead_deliver")[0]["why"] == "empty_selection"


def test_reasoning_passed_back_and_ask_text(tmp_path):
    lead_call = ScriptedLead(run([("run_shell", {"command": "true"})], [("deliver", {"commands": [1]})]))
    lead, _ = lead_for(tmp_path, lead_call)
    lead.verify(1, scratch_for(tmp_path))
    c = lead_call.verify_convos[1]
    assert c[:3] == lead.convo
    assert c[3]["content"] == core.VERIFY_ASK.format(describe=LocalScratch.describe)
    assert c[4]["role"] == "assistant" and c[4]["reasoning_content"] == "lead-reasoning"


def test_accounting_billed_pending_and_cap(tmp_path):
    lead_call = ScriptedLead([lambda c: body([tc(1, "run_shell", command="true")], micro=None),
                              lambda c: body([tc(2, "deliver", commands=[1])], micro=7)])
    budget = Budget(10.0)
    charged = []
    lead, trace = lead_for(tmp_path, lead_call, budget=budget)
    lead.on_cost = charged.append
    lead.verify(1, scratch_for(tmp_path))
    calls = rows(trace, "lead_call")
    assert [c["cost_kind"] for c in calls] == ["pending", "billed"] and [c["turn"] for c in calls] == ["verify1",
                                                                                                        "verify2"]
    assert calls[0]["tools"] == ["run_shell", "deliver"]
    assert charged == [0.0, 7e-6] and len(budget.pending) == 1 and lead.calls == 2

    lead_call = ScriptedLead(run([("run_shell", {"command": "true"})]))
    (tmp_path / "c").mkdir()
    lead, trace = lead_for(tmp_path / "c", lead_call, may_spend=lambda: False)
    assert lead.verify(1, scratch_for(tmp_path / "c")) is None
    assert lead_call.verify_convos == [] and rows(trace, "lead_deliver")[0]["why"] == "budget"


def executor(n_shell, delay=0.05):
    gaps, last, seen = [], [None], []

    def chat(messages, tools, timeout=None):
        now = time.monotonic()
        if last[0] is not None:
            gaps.append(now - last[0])
        seen.append(json.loads(json.dumps(messages)))
        i = len(seen)
        time.sleep(delay)
        name, args = ("finish", {"summary": "s"}) if i > n_shell else ("run_shell", {"command": f"echo {i}"})
        msg = {"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}", "type": "function",
                                                                  "function": {"name": name,
                                                                               "arguments": json.dumps(args)}}]}
        last[0] = time.monotonic()
        return 200, {"id": "x", "choices": [{"message": msg, "finish_reason": "tool_calls"}],
                     "usage": {"prompt_tokens": 1, "completion_tokens": 1, "buyer_cost_micro": 1}}, 0.0
    return chat, seen, gaps


def go(tmp_path, lead_call, n_shell, delay=0.05, checks=(Check("true"),)):
    task = Task(id="t", goal=TASK, checks=list(checks), max_steps=200, max_usd=100.0)
    trace = Trace(tmp_path / "trace.jsonl")
    chat, seen, gaps = executor(n_shell, delay)
    sc = LocalScratch(tmp_path / "w", tmp_path / "scr")
    res = run_task(task, chat, core.local_shell(tmp_path / "w"), trace, Budget(10.0), "deepseek-v4-pro",
                   lead_call=lead_call, cadence_s=1000.0, scratch=sc)
    lead_rows = [json.loads(x) for x in (tmp_path / "lead.jsonl").read_text().splitlines()]
    return res, seen, gaps, lead_rows


def test_executor_receives_replayed_commands_and_is_never_blocked(tmp_path):
    lead_call = ScriptedLead(run([("run_shell", {"command": "sleep 1.5; echo FIX-1 > fix.txt"})],
                                 [("deliver", {"commands": [1], "note": "apply this"})]))
    res, seen, gaps, lead_rows = go(tmp_path, lead_call, n_shell=60)
    assert res["status"] == "accepted"
    injected = [m["content"] for m in seen[-1] if m["role"] == "user" and m["content"].startswith(core.PREFIX)]
    # C slice 59: the reply arrives when its review returns; the delivery follows as its own message
    assert len(injected) == 2 and "REVIEW-REPLY" in injected[0] and "echo FIX-1" not in injected[0]
    assert "REVIEW-REPLY" not in injected[1] and "echo FIX-1 > fix.txt" in injected[1] and "apply this" in injected[1]
    inj = [r for r in lead_rows if r["event"] == "lead_inject"]
    assert [(r["kind"], r["delivered"]) for r in inj] == [("review", None), ("delivery", [1])]
    assert max(gaps) < 1.0  # the executor kept working during the 3 s of scratch commands (session + replay)
    assert res["lead_cost_usd"] > 0
    assert not any((tmp_path / "scr").iterdir())


def test_close_kills_a_running_scratch_command(tmp_path):
    lead_call = ScriptedLead(run([("run_shell", {"command": "sleep 120", "timeout_s": 600})],
                                 [("deliver", {"commands": [1]})]))
    t0 = time.monotonic()
    res, seen, gaps, lead_rows = go(tmp_path, lead_call, n_shell=10, delay=0.1)
    assert time.monotonic() - t0 < 30
    assert res["status"] == "accepted"
    d = [r for r in lead_rows if r["event"] == "lead_deliver"][0]
    assert d["why"] == "stopped" and d["ids"] is None
    assert [r["kind"] for r in lead_rows if r["event"] == "lead_inject"] == ["review"]  # no delivery
    assert [(r.get("kind"), r.get("delivered")) for r in lead_rows if r["event"] == "lead_dropped"] == [("session", None)]
    assert not any((tmp_path / "scr").iterdir())


def test_lab_scratch_commands(tmp_path):
    sent = []

    def shell(command, timeout):
        sent.append((command, timeout))
        return {"exit": 0, "stdout": "PID=42\n", "stderr": "", "timed_out": False}

    sc = core.LabScratch(shell, "~/optee-work")
    sc.new("v1-s")
    sc.run("v1-s", "make | tail", 900)
    sc.rm("v1-s")
    sc.kill_all()
    assert all(c.startswith("exec bash -c ") for c, _ in sent)
    run_cmd, timeout = sent[1]
    assert timeout == 900
    b64, workdir = run_cmd.split()[-2:]
    assert workdir == "'~/optee-work'" and base64.b64decode(b64).decode() == core._wrap("make | tail")
    assert [c.split()[-2:] for c, _ in sent[2:]] == [["rm", "v1-s"], ["killall", "-"]]
    assert subprocess.run(["bash", "-n", "-c", core.SCRATCH_SH]).returncode == 0
    p = subprocess.run(["bash", "-c", core.SCRATCH_SH, "_", "new", "../x"], capture_output=True, text=True)
    assert p.returncode == 2 and "bad scratch id" in p.stderr


SHIMS = {
    # Only "sudo" may write the scratch root, as on the lab where root creates it (C slice 56 smoke try 1: the holder
    # log was opened by the calling user in root's dir, so every `new` failed with NEW_FAIL / Permission denied).
    "sudo": """while [ $# -gt 0 ]; do case $1 in -n|-E) shift;; -u) shift 2;; *) break;; esac; done
chmod u+w "$CONFLUX_SCRATCH_ROOT" 2>/dev/null; "$@"; rc=$?; chmod a-w "$CONFLUX_SCRATCH_ROOT" 2>/dev/null; exit $rc""",
    "unshare": """while [ $# -gt 0 ]; do case $1 in -m) shift;; --propagation) shift 2;; *) break;; esac; done; exec "$@" """,
    "nsenter": """while [ $# -gt 0 ]; do case $1 in -t) shift 2;; -m) shift;; --) shift; break;; *) break;; esac; done
exec "$@" """,
    "mount": "exit 0",
    "mkfs.ext4": "exit 0",
}


def test_scratch_script_writes_under_root_owned_dir_only_via_sudo(tmp_path, monkeypatch):
    shims = tmp_path / "bin"
    shims.mkdir()
    for name, body_ in SHIMS.items():
        (shims / name).write_text("#!/bin/bash\n" + body_ + "\n")
        (shims / name).chmod(0o755)
    root = tmp_path / "scr"
    monkeypatch.setenv("PATH", f"{shims}:/usr/bin:/bin")
    monkeypatch.setenv("CONFLUX_SCRATCH_ROOT", str(root))
    work = tmp_path / "w"
    sc = core.LabScratch(core.local_shell(tmp_path / "jobs"), str(work))
    try:
        sc.new("t1")
        assert (root / "t1" / "pid").read_text().strip().isdigit()
        assert not (root / "t1.holder.log").exists()
        r = sc.run("t1", "pwd; echo hi | cat", 30)
        assert r["exit"] == 0 and r["stdout"].split() == [str(work), "hi"] and r["pipestatus"] == [0, 0]
    finally:
        pid = (root / "t1" / "pid").read_text().strip() if (root / "t1" / "pid").exists() else None
        if pid:  # the shimmed holder runs in this namespace: the script's kill fails closed, so stop it here
            subprocess.run(["kill", pid])
        subprocess.run(["chmod", "-R", "u+w", str(root)])
    sc.rm("t1")
    assert not (root / "t1").exists()


def _real_sudo() -> bool:
    try:
        return shutil.which("unshare") is not None and subprocess.run(["sudo", "-n", "true"],
                                                                      capture_output=True).returncode == 0
    except OSError:
        return False


@pytest.mark.skipif(not _real_sudo(), reason="needs passwordless sudo and unshare (real mount namespaces)")
def test_lab_scratch_contents_unreachable_from_root_namespace(tmp_path, monkeypatch):
    """C slice 64 regression (slices 60-61: the executor read and copied a live scratch's upper dir from the root
    namespace). The scratch root must not be under /tmp or /home: the holder mounts over both before it publishes
    its pid."""
    root = Path(tempfile.mkdtemp(prefix="conflux-scratch-test-", dir="/var/tmp"))
    monkeypatch.setenv("CONFLUX_SCRATCH_ROOT", str(root))
    m = f"m-{uuid.uuid4().hex}"
    sc = core.LabScratch(core.local_shell(tmp_path / "jobs"), f"~/{m}-w")
    try:
        sc.new("iso")
        r = sc.run("iso", f"echo t > /tmp/{m}; echo h > ~/{m}", 60)
        assert r["exit"] == 0, r
        r = sc.run("iso", f"cat /tmp/{m} ~/{m}", 60)
        assert r["exit"] == 0 and r["stdout"].split() == ["t", "h"], r  # (a) the scratch keeps its writes
        assert not (Path("/tmp") / m).exists() and not (Path.home() / m).exists()  # (b)
        assert not (Path.home() / f"{m}-w").exists()
        found = subprocess.run(["sudo", "-n", "find", str(root), "-name", f"{m}*"], capture_output=True, text=True)
        assert found.stdout.strip() == "", f"scratch contents visible from the root namespace: {found.stdout}"  # (c)
        sc.rm("iso")
        assert not (root / "iso").exists()
        for _ in range(20):  # (d) the loop device is released once the namespace is gone
            loops = subprocess.run(["sudo", "-n", "losetup", "-a"], capture_output=True, text=True).stdout
            if str(root) not in loops:
                break
            time.sleep(0.5)
        assert str(root) not in loops, loops
    finally:
        try:
            sc.rm("iso")
        finally:
            subprocess.run(["sudo", "-n", "rm", "-rf", str(root)])


def test_kill_never_targets_the_root_namespace(tmp_path, monkeypatch):
    shims = tmp_path / "bin"
    shims.mkdir()
    (shims / "sudo").write_text("#!/bin/bash\n" + SHIMS["sudo"] + "\n")
    (shims / "sudo").chmod(0o755)
    root = tmp_path / "scr"
    (root / "g").mkdir(parents=True)
    victim = subprocess.Popen(["sleep", "60"])
    try:
        (root / "g" / "pid").write_text(f"{victim.pid}\n")  # a pid in this (the root-side) namespace
        monkeypatch.setenv("PATH", f"{shims}:/usr/bin:/bin")
        monkeypatch.setenv("CONFLUX_SCRATCH_ROOT", str(root))
        sc = core.LabScratch(core.local_shell(tmp_path / "jobs"), str(tmp_path))
        sc._op("kill", "g")
        sc.kill_all()
        assert victim.poll() is None
    finally:
        victim.kill()
        subprocess.run(["chmod", "-R", "u+w", str(root)])


def test_verify_calls_are_reconciled_with_the_run(tmp_path):
    (tmp_path / "t").mkdir()
    lead_call = ScriptedLead(run([("run_shell", {"command": "true"})], [("deliver", {"commands": [1]})]))
    lead, _ = lead_for(tmp_path / "t", lead_call)
    lead.verify(1, scratch_for(tmp_path / "t"))
    calls = core._billed_calls(tmp_path)
    assert [c["lead"] for c in calls] == ["lead:running:verify1", "lead:running:verify2"]
    assert all(c["usage"] and c["cost_kind"] == "billed" for c in calls)


def test_finish_review_cancels_a_running_verify_session(tmp_path):
    # Task without checks: finish goes to a fresh lead's finish review, which supersedes the running review. Its verify
    # session (here inside a long scratch command) is cancelled, not waited for.
    lead_call = ScriptedLead(run([("run_shell", {"command": "sleep 120", "timeout_s": 600})],
                                 [("deliver", {"commands": [1]})]))
    t0 = time.monotonic()
    res, seen, gaps, lead_rows = go(tmp_path, lead_call, n_shell=10, delay=0.1, checks=())
    assert time.monotonic() - t0 < 30
    assert res["reason"] == "finish_review_done"
    d = [r for r in lead_rows if r["event"] == "lead_deliver"]
    assert len(d) == 1 and d[0]["why"] == "stopped"
    assert [(r.get("kind"), r.get("delivered")) for r in lead_rows if r["event"] == "lead_superseded"] \
        == [("session", None)]
    assert [r["kind"] for r in lead_rows if r["event"] == "lead_inject"] == ["review"]  # no delivery
    assert [c["cost_kind"] for c in (r for r in lead_rows if r["event"] == "lead_call" and r["turn"] == "verify1")] \
        == ["billed"]  # the in-flight verify call was accounted
    assert not any((tmp_path / "scr").iterdir())


def test_local_scratch_kills_background_jobs_of_finished_commands(tmp_path):
    for how in ("rm", "kill_all"):
        (tmp_path / how).mkdir()
        sc = scratch_for(tmp_path / how)
        sc.new("s")
        r = sc.run("s", "nohup sleep 3600 >/dev/null 2>&1 & echo $!", 30)
        pid = int(r["stdout"].strip())
        assert r["exit"] == 0 and Path(f"/proc/{pid}").exists()  # the launching shell has exited; the job runs on
        getattr(sc, how)(*(["s"] if how == "rm" else []))
        for _ in range(50):
            try:  # the job may be reaped between any two reads of /proc
                if "Z" in Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1][:3]:
                    break
            except FileNotFoundError:
                break
            time.sleep(0.1)
        else:
            raise AssertionError(f"{how}: background job {pid} still running")
        sc.rm("s")


def test_local_scratch_never_kills_a_reused_group_id(tmp_path):
    sc = scratch_for(tmp_path)
    sc.new("s")
    other = subprocess.Popen(["sleep", "60"], start_new_session=True)
    try:
        sc.groups["s"] = {other.pid}  # as if the scratch's group id had been reused by an unrelated process
        sc.rm("s")
        assert other.poll() is None
    finally:
        other.kill()


def test_lab_scratch_teardown_runs_after_the_task_deadline(tmp_path, monkeypatch):
    shims = tmp_path / "bin"
    shims.mkdir()
    for name, body_ in SHIMS.items():
        (shims / name).write_text("#!/bin/bash\n" + body_ + "\n")
        (shims / name).chmod(0o755)
    root = tmp_path / "scr"
    monkeypatch.setenv("PATH", f"{shims}:/usr/bin:/bin")
    monkeypatch.setenv("CONFLUX_SCRATCH_ROOT", str(root))
    jobs = str(tmp_path / "w")
    expired = core.lab_shell(core.local_remote, jobs, deadline=time.monotonic() - 1, poll_s=0.1)
    live = core.lab_shell(core.local_remote, jobs, deadline=time.monotonic() + 120, poll_s=0.1)
    (root / "x" / "up").mkdir(parents=True)
    (root / "y" / "up").mkdir(parents=True)
    with pytest.raises(core.ScratchError):  # a teardown that could not run is an error, never silent
        core.LabScratch(expired, jobs).rm("x")
    assert (root / "x").exists()
    sc = core.LabScratch(expired, jobs, teardown=live)
    sc.rm("x")
    assert not (root / "x").exists() and (root / "y").exists()
    sc.kill_all()
    sc.purge()
    assert not root.exists()


# ---------------------------------------------------------------- C slice 59: sessions beside the review cadence

class GatedLead:
    """Reviews answer at once (their final turn with `review k`); verify calls run one scratch command, then deliver it. The verify
    session of review k blocks on `gates[k]` (set to release it) before its first call."""

    def __init__(self):
        self.reviews, self.gates, self.verify_seen = 0, {}, []
        self.lock = threading.Lock()
        self.open_all = False

    def release(self):
        """Release every session, including those of later reviews (so `close` does not wait on a gate)."""
        with self.lock:
            self.open_all = True
            for g in self.gates.values():
                g.set()

    def __call__(self, convo, timeout=None, tools=None):
        if tools is None:
            if not convo[-1]["content"].endswith((core.INIT_ASK, core.FINAL_ASK)):
                return body(content="goal answer")
            with self.lock:
                self.reviews += 1
                k = self.reviews
                self.gates[k] = threading.Event()
                if self.open_all:
                    self.gates[k].set()
            return body(content=f"GOAL: g1\nreview {k}")
        last_review = next(m["content"] for m in reversed(convo) if m["role"] == "assistant"
                           and m["content"].startswith("GOAL"))
        k = int(last_review.split()[-1])
        has_cmd = any(m["role"] == "tool" for m in convo)
        if not has_cmd:
            self.verify_seen.append(k)
            assert self.gates[k].wait(20)
            return body([tc(f"{k}a", "run_shell", command=f"echo FIX-{k} > fix{k}.txt")])
        return body([tc(f"{k}b", "deliver", commands=[1], note=f"note {k}")])


def steer(tmp_path, lead_call):
    lead = Lead(lead_call, "kimi-k3", Budget(10.0), Trace(tmp_path / "lead.jsonl"), TASK, set())
    return core.Steering(lead, cadence_s=0.0, scratch=scratch_for(tmp_path)), lead


def turn_until(st, msgs, step, cond, timeout=20):
    t0 = time.monotonic()
    while not cond():
        assert time.monotonic() - t0 < timeout
        step += 1
        st.turn(msgs, step)
        time.sleep(0.02)
    return step


def injected(msgs):
    return [m["content"] for m in msgs if m["role"] == "user" and m["content"].startswith(core.PREFIX)]


def test_open_session_does_not_stop_reviews_and_never_two_sessions(tmp_path):
    lead_call = GatedLead()
    st, lead = steer(tmp_path, lead_call)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": TASK}]
    step = turn_until(st, msgs, 0, lambda: lead_call.verify_seen == [1])  # session 1 open, held at its gate
    # reviews 2 and 3 return and are injected while session 1 is open; neither opens a session
    step = turn_until(st, msgs, step, lambda: sum("review 3" in c for c in injected(msgs)) == 1)
    assert st.session_open and lead_call.verify_seen == [1]
    assert [c.split("\n")[-1] for c in injected(msgs)] == ["review 1", "review 2", "review 3"]
    skipped = [e["review"] for e in lead.trace.events if e["event"] == "lead_session_skipped"]
    assert 2 in skipped and 3 in skipped
    lead_call.gates[1].set()  # session 1 delivers; its delivery arrives as its own message
    step = turn_until(st, msgs, step, lambda: any("FIX-1" in c for c in injected(msgs)))
    d1 = [c for c in injected(msgs) if "FIX-1" in c][0]
    assert "note 1" in d1 and "review 1" not in d1
    # a later review opens the next session (only one at a time ever)
    step = turn_until(st, msgs, step, lambda: len(lead_call.verify_seen) == 2)
    k = lead_call.verify_seen[1]
    assert k > 3
    lead_call.gates[k].set()
    step = turn_until(st, msgs, step, lambda: any(f"FIX-{k}" in c for c in injected(msgs)))
    lead_call.release()
    st.close(step)
    ends = [e["why"] for e in lead.trace.events if e["event"] == "lead_deliver"]
    assert ends in (["delivered", "delivered"], ["delivered", "delivered", "stopped"])  # a 3rd may open before close
    inj = [e for e in lead.trace.events if e["event"] == "lead_inject" and e["kind"] == "delivery"]
    assert [e["review"] for e in inj] == [1, k]


def test_session_continues_its_own_reviews_conversation(tmp_path):
    # The session thread gets its review's conversation; a later review replaces `lead.convo` while it runs.
    lead_call = ScriptedLead(run([("deliver", {"commands": []})]))
    lead, _ = lead_for(tmp_path, lead_call)
    own = [{"role": "system", "content": core.LEAD_SYSTEM}, {"role": "user", "content": "data"},
           {"role": "assistant", "content": "REVIEW-1"}]
    lead.verify(1, scratch_for(tmp_path), convo=own)
    assert lead_call.verify_convos[0][:3] == own and "R1" not in json.dumps(lead_call.verify_convos[0])


def test_finish_and_close_drop_an_open_session_and_a_review(tmp_path):
    for how in ("finish", "close"):
        d = tmp_path / how
        d.mkdir()
        lead_call = GatedLead()
        st, lead = steer(d, lead_call)
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": TASK}]
        turn_until(st, msgs, 0, lambda: lead_call.verify_seen == [1])
        t0 = time.monotonic()
        threading.Timer(0.5, lead_call.gates[1].set).start()  # the session's call returns; it must not deliver
        (st.settle_for_finish if how == "finish" else st.close)(99)
        assert time.monotonic() - t0 < 15 and not st._alive()
        assert not st.session_open and not st.inflight and st.result is None and st.reply is None
        rows_ = [e for e in lead.trace.events if e["event"] == "lead_deliver"]
        assert [e["why"] for e in rows_] == ["stopped"]
        assert not any(e["event"] == "lead_inject" and e.get("kind") == "delivery" for e in lead.trace.events)
        if how == "finish":
            assert not lead.cancel_verify
            n = lead_call.reviews
            st.turn(msgs, 100)  # after the finish review the running lead goes on
            turn_until(st, msgs, 100, lambda: lead_call.reviews > n)
            lead_call.release()
            st.close(200)


def test_deliver_text_without_reply():
    out = {"ids": [1], "note": None, "commands": [{"command": "true", "timeout_s": 60}], "replay_ok": True}
    text = core.deliver_text(None, out)
    assert text.startswith(core.PREFIX + core.DELIVER_HEAD) and "```bash\ntrue\n```" in text


def test_verify_ask_does_not_claim_the_reply_is_held():
    # C slice 59: the reply reaches the agent before the session; the ask must not say otherwise (PR #68 critic;
    # wording measured in ~/evidence/verify-prompt-demo-2026-10-31/RESULTS.md)
    assert "Before your reply reaches" not in core.VERIFY_ASK and "has been sent to the agent" in core.VERIFY_ASK
