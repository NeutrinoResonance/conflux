import importlib.util
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from conflux.trace import Trace

_spec = importlib.util.spec_from_file_location(
    "step_lab", Path(__file__).resolve().parents[1] / "scripts" / "step_lab.py")
step_lab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(step_lab)


def _call(command):
    return {"type": "function", "function": {"name": "run", "arguments": json.dumps({"command": command})}}


def test_steps_pair_requests_with_responses_including_oversized(tmp_path):
    db = tmp_path / "t.db"
    trace = Trace(db)
    goal = {"role": "user", "content": "do the task"}
    big = {"role": "tool", "content": "x" * 500_000}
    trace.record_exchange("s", "t", "client_request", None, {"messages": [goal], "tools": []})
    trace.record_exchange("s", "t", "client_response", None,
                          {"choices": [{"message": {"role": "assistant", "tool_calls": [_call("ls /")]}}]})
    trace.record_exchange("s", "t", "upstream", None, {"ignored": True})
    trace.record_exchange("s", "t", "client_request", None, {"messages": [goal, big], "tools": []})
    trace.record_exchange("s", "t", "client_response", None,
                          {"choices": [{"message": {"role": "assistant", "content": "done"}}]})

    conn = step_lab.open_db(str(db))
    steps = step_lab.load_steps(conn, "s")
    assert [s["step"] for s in steps] == [1, 2]
    first, second = (step_lab.step_parts(conn, s) for s in steps)
    assert first["goal"] == "do the task"
    assert step_lab.calls(first["proposal"]) == [("run", "ls /")]
    assert second["complete"] and len(second["messages"][1]["content"]) == 500_000
    assert step_lab.parse_steps("1,3-5,99", 4) == [1, 3, 4]


def test_star_session_pairs_across_stateless_sessions(tmp_path):
    import importlib
    import sqlite3
    from conflux.trace import Trace

    step_lab = importlib.import_module("scripts.step_lab")
    trace = Trace(tmp_path / "t.db")
    for i in range(2):
        trace.record_exchange(f"oneshot_{i}", "t", "client_request", None,
                              {"messages": [{"role": "user", "content": "goal"}]})
        trace.record_exchange(f"oneshot_{i}", "t", "client_response", None,
                              {"choices": [{"message": {"role": "assistant", "content": str(i)}}]})
    conn = sqlite3.connect(tmp_path / "t.db")
    assert [s["step"] for s in step_lab.load_steps(conn, "*")] == [1, 2]
    assert len(step_lab.load_steps(conn, "oneshot_1")) == 1


def test_decision_points_hide_executor_reasoning_and_the_future(tmp_path, monkeypatch):
    transcript = [
        {"role": "user", "content": "build the thing"},
        {"role": "assistant", "content": "", "reasoning_content": "private plan",
         "tool_calls": [_call("ls /src")]},
        {"role": "tool", "content": "a.c b.c"},
        {"role": "assistant", "content": "", "tool_calls": [_call("rm -rf /src")]},
        {"role": "tool", "content": "gone"},
    ]
    (tmp_path / "t.json").write_text(json.dumps(transcript))
    points = tmp_path / "points.json"
    points.write_text(json.dumps({"transcript": str(tmp_path / "t.json"), "points": [
        {"id": "p", "index": 3, "kind": "problem", "outcome": "deleted the sources"}]}))
    monkeypatch.setattr(step_lab, "ROOT", Path("/"))

    messages, spec = step_lab.transcript_points(str(points))
    assert all(not k.startswith("reasoning") for m in messages for k in m)
    parts = step_lab._point_parts(messages, spec["points"][0], 10_000)
    assert parts["goal"] == "build the thing"
    assert "ls /src" in parts["context"] and "rm -rf" not in parts["context"]
    assert parts["original"] == "run: rm -rf /src"
    prompt = step_lab.DECIDER_PROMPT.format(goal=parts["goal"], context=parts["context"])
    assert "deleted the sources" not in prompt and "rm -rf" not in prompt


def test_stage_decide_uses_production_context_and_recorded_tool_contracts(tmp_path):
    from conflux.decider import decision_context
    from conflux.providers import ChatResult
    from tests.test_decider import config, decision
    tools = [{"type": "function", "function": {"name": "recorded_tool", "description": "The recorded tool",
              "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}}]
    messages = [{"role": "user", "content": "goal"},
                {"role": "assistant", "content": "observed", "reasoning_content": "private"},
                {"role": "assistant", "content": "future"}]
    transcript = tmp_path / "transcript.json"
    transcript.write_text(json.dumps({"messages": messages, "tools": tools}))
    points = tmp_path / "points.json"
    points.write_text(json.dumps({"transcript": str(transcript), "points": [
        {"id": "p", "kind": "control", "index": 2, "outcome": "hindsight"}]}))
    class Client:
        async def chat(self, model, sent, **kwargs):
            self.prompt = sent[0]["content"]
            return ChatResult(json.dumps(decision(True)), 1, 1, 0)
    client = Client()
    out = tmp_path / "decisions.jsonl"
    args = SimpleNamespace(points=str(points), out=str(out), concurrency=1, context_chars=10000,
                           max_tokens=100, temperature=0, models="executor", n=1)
    asyncio.run(step_lab.stage_decide(args, config(), client))
    assert client.prompt == step_lab.DECIDER_PROMPT.format(goal="goal", context=decision_context(messages[:2], tools))
    assert "future" not in client.prompt and "hindsight" not in client.prompt and "private" not in client.prompt
    assert json.loads(out.read_text())["tools"] == tools


@pytest.mark.parametrize("mode", ["vm", "container"])
def test_legacy_transcript_uses_entire_runner_mode_tool_set(tmp_path, mode):
    from scripts.direct_vm_tool_loop import (TOOL_DEFINITIONS, CONTAINER_TOOL_DEFINITION,
                                            CONTAINER_WRITE_TOOL_DEFINITION)
    expected = TOOL_DEFINITIONS if mode == "vm" else [CONTAINER_TOOL_DEFINITION, CONTAINER_WRITE_TOOL_DEFINITION]
    transcript = tmp_path / "transcript.json"
    transcript.write_text(json.dumps({"messages": [{"role": "assistant", "tool_calls": [
        {"function": {"name": expected[0]["function"]["name"], "arguments": "{}"}}]}]}))
    assert step_lab.transcript_tools({"transcript": str(transcript)}) == expected


def test_tools_can_come_from_recorded_request_and_ambiguous_history_requires_it(tmp_path):
    transcript = tmp_path / "transcript.json"
    transcript.write_text(json.dumps([{"role": "assistant", "tool_calls": [_call("cat /tmp/item")]}]))
    with pytest.raises(ValueError, match="ambiguous"):
        step_lab.transcript_tools({"transcript": str(transcript)})
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"tools": [{"function": {"name": "unused_tool", "parameters": {}}}]}))
    assert step_lab.transcript_tools({"transcript": str(transcript), "request": str(request)}) == json.loads(request.read_text())["tools"]


def test_decision_report_alone_prints_normalized_validity_and_top_reasons(tmp_path, capsys):
    from tests.test_action_governor import _body
    from tests.test_decider import decision
    raw = decision(claim="original claim")
    raw["check"][0]["claim"] = "paraphrase"
    rows = [{"model": "a", "decision": "```json\n" + json.dumps(raw) + "\n```", "error": ""},
            {"model": "a", "decision": "", "error": ""},
            {"model": "b", "decision": json.dumps(decision(True)), "tools": _body()["tools"], "error": ""}]
    out = tmp_path / "decisions.jsonl"
    out.write_text("\n".join(json.dumps(r) for r in rows))
    step_lab.stage_report(SimpleNamespace(decisions=str(out), decisions_judged=None, senate=None, judged=None))
    report = capsys.readouterr().out
    assert "validity" in report and "1/2 = 50.0%" in report and "1/1 = 100.0%" in report
    assert "1: no JSON object" in report


def test_done_validity_report_rejects_missing_checks_and_mutating_scope(tmp_path, capsys):
    from tests.test_action_governor import _body
    from tests.test_decider import decision
    absent = decision(True)
    absent["check"] = []
    empty = decision(True)
    empty.update(expected_changes=[], check=[])
    unbound = decision(True)
    unbound["check"][0].update(tool="missing", arguments={"path": "/tmp/item"})
    rows = [{"model": "done", "decision": json.dumps(d), "tools": _body()["tools"]}
            for d in [absent, empty, unbound, decision(True, access="write"), decision(True)]]
    out = tmp_path / "decisions.jsonl"
    out.write_text("\n".join(json.dumps(row) for row in rows))
    step_lab.stage_report(SimpleNamespace(decisions=str(out), decisions_judged=None, senate=None, judged=None))
    report = capsys.readouterr().out
    assert "1/5 = 20.0%" in report
    assert "done has unchecked claims" in report
    assert "done requires at least one expected change with a check" in report
    assert "done touches must be read-only" in report


def test_replay_observations_reports_a_line_lost_since_two_runs(tmp_path, capsys):
    import argparse
    from scripts.step_lab import stage_replay_observations
    boot = ["firmware", "psci0 at simplebus0", "root device:"]
    messages = []
    for index, lines in enumerate([boot, boot, [boot[0], boot[2]]]):
        call = {"id": f"c{index}", "function": {"name": "run", "arguments": json.dumps(
            {"command": f"timeout {index + 1}s qemu-system-aarch64 -m 2G"})}}
        messages += [{"role": "assistant", "tool_calls": [call]},
                     {"role": "tool", "tool_call_id": f"c{index}", "content": json.dumps({"stdout": "\n".join(lines)})}]
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"messages": messages}))
    stage_replay_observations(argparse.Namespace(transcript=str(path)))
    out = capsys.readouterr().out
    assert "- psci0 at simplebus0" in out and "unresolved regressions at end: 1" in out
