"""Decision contract, configuration and evidence tests; no external services."""
import asyncio
import json
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from conflux.config import DeciderSettings, load
from conflux.decider import (DECIDER_PROMPT, Decider, DeciderUnavailable, Decision,
                             DecisionStore, PanelDecision, ScopeViolation,
                             clean_messages, enforce_scope)
from conflux.governance import ToolManifest
from conflux.orchestrator import Budget
from conflux.providers import ChatResult, ProviderError
from tests.test_action_governor import _config


def decision(done=False, resource="/tmp/item", access="read", claim=None):
    if done and claim is None:
        claim = "the goal is achieved and required initial state is preserved"
    return {"done": done, "next_step": "Return the result" if done else "Inspect the item",
            "why": "Use the observed evidence", "touches": [
                {"resource": resource, "access": access}],
            "expected_changes": [claim] if claim else [],
            "check": [{"claim": claim, "tool": "terminal", "arguments": {"command": "cat /tmp/item"},
                       "predicate": {"type": "contains", "value": "verified data"}}] if claim else []}


def config(**overrides):
    cfg = _config()
    cfg.models["second"] = replace(cfg.model("critic"), name="second", id="second", family="second", logprobs=False)
    cfg.decider = DeciderSettings(members=["executor", "second"], **overrides)
    return cfg


class FakeClient:
    def __init__(self, decisions=None, raw=None, senate="approval concern"):
        self.decisions = decisions or {}
        self.raw = list(raw or [])
        self.senate = senate
        self.calls = []

    async def chat(self, model, messages, **kwargs):
        prompt = messages[-1]["content"]
        self.calls.append(("decider" if "You decide the next step" in prompt else "senate", model.name, messages, kwargs))
        await asyncio.sleep(0)
        if "You decide the next step" not in prompt:
            return ChatResult(f"<danger>A</danger><how>{self.senate}</how>", 2, 3, 0.00001)
        replies = self.decisions.get(model.name, [])
        reply = replies.pop(0) if replies else decision()
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(reply if isinstance(reply, str) else json.dumps(reply), 2, 3, 0.00001)

    async def raw_chat(self, model, body):
        self.calls.append(("executor", model.name, body))
        reply = self.raw.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def panel_decide(cfg, client, store=None, budget=None):
    from tests.test_action_governor import _body
    store = store or DecisionStore(sqlite3.connect(":memory:"))
    return asyncio.run(Decider(cfg, client, store).decide("session", "run", cfg.model("executor"),
        cfg.decider_settings(), "Goal", [{"role": "user", "content": "Goal", "reasoning_content": "secret"}],
        budget or Budget(1), lambda *a, **kw: None, tools=_body()["tools"]))


def test_measured_defaults_and_shared_lab_prompt():
    cfg = load(Path(__file__).parents[1] / "models.yaml")
    assert cfg.decider == DeciderSettings()
    from scripts.step_lab import DECIDER_PROMPT as measured
    assert measured is DECIDER_PROMPT
    assert clean_messages({"reasoning": "secret", "nested": [{"reasoning_content": "private", "content": "public"}]}) == {"nested": [{"content": "public"}]}


@pytest.mark.parametrize("changes", [
    {"enabled": "yes"}, {"members": []}, {"members": ["x", "x"]},
    {"members": "x"}, {"done_requires": "some"}, {"next_step_from": "random"},
    {"family_rule": "hard"}, {"frequency": "sometimes"}, {"max_tokens": 0},
    {"max_tokens": True}, {"timeout_s": float("nan")}, {"timeout_s": 0},
    {"max_repairs": -1}, {"max_decisions_per_request": 0}, {"failure_mode": "open"},
    {"max_checks_per_turn": 0}, {"max_checks_per_turn": True},
])
def test_invalid_settings(changes):
    with pytest.raises(ValueError):
        DeciderSettings(**changes)


def test_config_overrides_are_isolated_and_validate_models():
    cfg = config()
    settings = cfg.decider_settings({"members": ["second"], "max_tokens": 32000})
    settings.members.append("critic")
    assert cfg.decider.members == ["executor", "second"]
    with pytest.raises(ValueError, match="unknown model"):
        cfg.decider_settings({"members": ["missing"]})
    with pytest.raises(ValueError, match="unknown decider"):
        cfg.decider_settings({"model": "second"})


@pytest.mark.parametrize("changes", [
    {"done": "true"}, {"next_step": ""}, {"why": []}, {"extra": 1},
    {"touches": ["/tmp/item"]},
    {"touches": [{"resource": "/tmp/../item", "access": "read"}]},
    {"expected_changes": [17]}, {"check": "exit zero"},
])
def test_strict_decision_schema(changes):
    raw = decision()
    raw.update(changes)
    with pytest.raises(ValueError):
        Decision.parse(json.dumps(raw))


# Predicates glm-5.2 actually wrote in the decider lab (decisions-v4.jsonl).
@pytest.mark.parametrize("predicate, reason", [
    ({"type": "json_equals", "path": ["exit_code"], "value": 0}, "semantic"),
    ({"type": "contains", "value": "\n"}, "nonempty observation"),
    ({"type": "contains", "value": ""}, "nonempty observation"),
    ({"type": "json_equals", "path": ["stdout"]}, "contains or json_equals"),
    ({"type": "regex", "value": "NetBSD.*booting"}, "contains or json_equals"),
    ({"type": "contains", "value": "x", "path": "stdout"}, "keys/indices"),
])
def test_weak_predicate_leaves_its_claim_unchecked_without_discarding_the_decision(predicate, reason):
    raw = decision(claim="the output is correct")
    raw["check"].append({"claim": "the item is intact", "tool": "terminal",
                         "arguments": {"command": "cat /tmp/item"},
                         "predicate": {"type": "contains", "value": "intact"}})
    raw["check"][0]["predicate"] = predicate
    raw["expected_changes"].append("the item is intact")
    from tests.test_action_governor import _body
    parsed = Decision.parse(json.dumps(raw), _body()["tools"])
    assert parsed.next_step == "Inspect the item"
    assert parsed.unchecked_claims() == ["the output is correct"]
    assert reason in parsed.check[0]["unchecked_reason"]
    assert "unchecked_reason" not in parsed.check[1]


def test_weak_predicate_cannot_support_done():
    raw = decision(True)
    raw["check"][0]["predicate"] = {"type": "json_equals", "path": ["exit_code"], "value": 0}
    assert Decision.parse(json.dumps(raw)).unchecked_claims() == raw["expected_changes"]


@pytest.mark.parametrize("access", ["write", "execute"])
def test_done_touches_reject_mutation_access(access):
    with pytest.raises(ValueError, match="done touches must be read-only"):
        Decision.parse(json.dumps(decision(True, access=access)))


def test_done_requires_an_observable_claim():
    raw = decision(True)
    raw.update(expected_changes=[], check=[])
    with pytest.raises(ValueError, match="at least one expected change with a check"):
        Decision.parse(json.dumps(raw))


def test_done_missing_check_is_a_durable_unchecked_obligation():
    raw = decision(True)
    raw["check"] = []
    store = DecisionStore(sqlite3.connect(":memory:"))
    panel = panel_decide(config(), FakeClient({m: [raw] for m in config().decider.members}), store)
    assert panel.decision.unchecked_claims() == raw["expected_changes"]
    assert {o["status"] for o in store.obligations("session")} == {"unchecked"}
    assert store.unresolved("session")


@pytest.mark.parametrize("command,is_check,allowed", [
    ("cat /tmp/item", True, True),
    ("cat /tmp/item", False, False),
    ("stat /tmp/item", True, False),
    ("cat /tmp/other", True, False),
    ("rm /tmp/item", True, False),
    ("sh /tmp/item", True, "senate"),
    ("find /tmp/item -delete", True, False),
    ("ls", True, False),
])
def test_done_authorizes_only_exact_system_checks_with_read_effects(command, is_check, allowed):
    from tests.test_action_governor import _body, _tool_call
    raw = decision(True)
    if command.startswith(("rm ", "sh ", "find ")) or command == "ls":
        raw["check"][0]["arguments"]["command"] = command
    parsed = Decision.parse(json.dumps(raw), _body()["tools"])
    if allowed == "senate":
        assert enforce_scope(parsed, _tool_call(command), ToolManifest(name="terminal"), is_check=is_check)
    elif allowed:
        assert enforce_scope(parsed, _tool_call(command), ToolManifest(name="terminal"), is_check=is_check) == []
    else:
        with pytest.raises(ScopeViolation):
            enforce_scope(parsed, _tool_call(command), ToolManifest(name="terminal"), is_check=is_check)


@pytest.mark.parametrize("command", ["cat /tmp/item;2>/tmp/item", "true;>/tmp/item; cat /tmp/item"])
def test_done_check_cannot_hide_a_write_behind_a_separator(command):
    from tests.test_action_governor import _body, _tool_call
    raw = decision(True)
    raw["check"][0]["arguments"]["command"] = command
    parsed = Decision.parse(json.dumps(raw), _body()["tools"])
    with pytest.raises(ScopeViolation, match="read-only effects"):
        enforce_scope(parsed, _tool_call(command), ToolManifest(name="terminal"), is_check=True)


@pytest.mark.parametrize("wrap", ["```json\n{}\n```", "Here is the decision:\n{}\nSome explanation."])
def test_decision_extracts_first_object_and_allows_empty_done_step(wrap):
    raw = decision(True)
    raw["next_step"] = ""
    assert Decision.parse(wrap.format(json.dumps(raw))).done
    raw = decision(claim="braces {inside} the claim")
    assert Decision.parse(wrap.format(json.dumps(raw))).expected_changes == raw["expected_changes"]


@pytest.mark.parametrize("text", ["", "not JSON", '{"done":true,', '{"done":false,"done":true}',
                                      '{"why":NaN}', '{bad}\n' + json.dumps(decision())])
def test_decision_does_not_repair_malformed_json_itself(text):
    with pytest.raises(ValueError):
        Decision.parse(text)


def test_paraphrased_check_is_an_additional_claim_and_missing_checks_are_durable():
    raw = decision(claim="original claim")
    raw["check"][0]["claim"] = "a paraphrased claim"
    parsed = Decision.parse(json.dumps(raw))
    assert parsed.expected_changes == ["original claim", "a paraphrased claim"]
    store = DecisionStore(sqlite3.connect(":memory:"))
    panel_decide(config(), FakeClient({"executor": [raw]}), store)
    obligations = store.context("session")["obligations"]
    assert [(o["claim"], o["status"]) for o in obligations] == [
        ("original claim", "unchecked"), ("a paraphrased claim", "planned")]
    assert obligations[0]["check"] is None
    assert obligations[0]["evidence"] == [{"reason": "claim has no check"}]
    assert store.unresolved("session")


@pytest.mark.parametrize("names,arguments,rebound", [
    (["terminal"], {"command": "cat /tmp/item"}, True),
    (["terminal", "other"], {"command": "cat /tmp/item"}, False),
    ([], {"command": "cat /tmp/item"}, False),
    (["terminal"], {"path": "/tmp/item"}, False),
])
def test_unknown_check_tools_only_rebind_to_one_command_string_tool(names, arguments, rebound):
    from tests.test_action_governor import _body
    tools = [{**_body()["tools"][0], "function": {**_body()["tools"][0]["function"], "name": n}} for n in names]
    raw = decision(claim="claim")
    raw["check"][0].update(tool="invented", arguments=arguments)
    parsed = Decision.parse(json.dumps(raw), tools)
    check = parsed.check[0]
    assert (check["tool"] == "terminal") is rebound
    assert ("unchecked_reason" not in check) is rebound
    store = DecisionStore(sqlite3.connect(":memory:"))
    panel = PanelDecision("p", parsed, [{"model": "m", "decision": asdict(parsed)}], "m", 0)
    store.save("s", "r", panel, "context", config().decider)
    obligation = store.obligations("s")[0]
    assert obligation["status"] == ("planned" if rebound else "unchecked")
    if not rebound:
        assert "not exposed" in obligation["evidence"][0]["reason"]


def test_nontyped_resource_is_accepted_but_never_matches_even_an_opaque_tool():
    raw = decision(resource="apt-packages")
    parsed = Decision.parse(json.dumps(raw))
    call = {"function": {"name": "read", "arguments": '{"resource":"apt-packages"}'}}
    with pytest.raises(ScopeViolation, match="outside"):
        enforce_scope(parsed, call, ToolManifest(name="read", trusted=True, side_effect="read"))


def test_unchecked_claim_can_receive_a_later_released_check():
    from tests.test_action_governor import _response
    raw = decision(claim="claim")
    raw["check"] = []
    store = DecisionStore(sqlite3.connect(":memory:"))
    panel_decide(config(), FakeClient({"executor": [raw]}), store)
    later = panel_decide(config(), FakeClient({"executor": [decision(claim="claim")]}), store)
    assert any(o["status"] == "unchecked" for o in store.obligations("session"))
    store.release("session", later, _response("cat /tmp/item"), ["action"])
    assert [o["status"] for o in store.obligations("session")] == ["pending"]
    store.ingest("session", [{"role": "tool", "tool_call_id": "call-original", "content": "verified data"}])
    assert not store.unresolved("session")


@pytest.mark.parametrize("policy,votes,done", [
    ("all", [True, True], True), ("all", [True, False], False),
    ("any", [False, True], True), ("majority", [True, False], False),
])
def test_panel_done_rules(policy, votes, done):
    from tests.test_action_governor import _body
    cfg = config(done_requires=policy)
    panel = panel_decide(cfg, FakeClient({m: [decision(v)] for m, v in zip(cfg.decider.members, votes)}))
    assert panel.decision.done is done
    assert Decision.parse(json.dumps(asdict(panel.decision)), _body()["tools"]) == panel.decision
    assert len(panel.members) == 2


def test_each_in_turn_and_nonselected_obligations_and_scope_concerns():
    cfg = config(next_step_from="each_in_turn")
    store = DecisionStore(sqlite3.connect(":memory:"))
    def client():
        return FakeClient({"executor": [decision(claim="first claim")],
                           "second": [decision(resource="/tmp/other", claim="second claim")]})
    assert panel_decide(cfg, client(), store).selected == "executor"
    assert {o["claim"] for o in store.obligations("session")} == {"first claim", "second claim"}
    assert store.context("session")["concerns"][0]["source"] == "decider_scope_disagreement"
    assert panel_decide(cfg, client(), store).selected == "second"


def test_default_panel_carries_out_every_members_step_read_only_first():
    cfg = config()
    assert cfg.decider.next_step_from == "all"
    store = DecisionStore(sqlite3.connect(":memory:"))
    writer = decision(resource="/tmp/driver.c", access="write", claim="driver written")
    writer["next_step"] = "Write the driver"
    reader = decision(resource="/tmp/dtb", claim="device tree dumped")
    reader["next_step"] = "Dump the device tree"
    panel = panel_decide(cfg, FakeClient({"executor": [writer], "second": [reader]}), store)
    step = panel.decision.next_step
    assert step.index("Dump the device tree") < step.index("Write the driver")
    assert {(t["resource"], t["access"]) for t in panel.decision.touches} == {
        ("/tmp/dtb", "read"), ("/tmp/driver.c", "write")}
    assert set(panel.decision.expected_changes) == {"driver written", "device tree dumped"}
    assert len(panel.decision.check) == 2 and panel.selected == "executor,second"
    assert not store.context("session")["concerns"]


def test_default_panel_completion_contract_comes_only_from_done_voters():
    cfg = config(done_requires="any")
    other = decision(claim="more work")
    panel = panel_decide(cfg, FakeClient({"executor": [decision(True)], "second": [other]}))
    assert panel.decision.done and "more work" not in panel.decision.expected_changes


def test_same_family_is_allowed_and_no_logprobs_requested():
    client = FakeClient()
    panel_decide(config(), client)
    assert client.calls[0][1] == "executor"
    assert all("logprobs" not in c[3] for c in client.calls)
    assert all(c[3]["max_tokens"] == 24000 for c in client.calls)
    assert all("secret" not in c[2][0]["content"] for c in client.calls)


def test_family_rule_applies_to_fallbacks_and_budget_charges_repairs():
    cfg = config(family_rule="different_from_executor", max_repairs=0)
    cfg.models["executor"] = replace(cfg.model("executor"), fallbacks=("critic",))
    client = FakeClient()
    panel = panel_decide(cfg, client)
    assert panel.members[0]["model"] == "critic"
    assert all(c[1] != "executor" for c in client.calls)
    cfg.decider.family_rule = "any"
    cfg.decider.max_repairs = 1
    client = FakeClient({"executor": ["{}", decision()]})
    budget = Budget(1)
    panel_decide(cfg, client, budget=budget)
    assert len(client.calls) == 3
    assert budget.tokens_out == 9


def test_malformed_json_still_uses_the_existing_repair_retry():
    client = FakeClient({"executor": ['{"done":', decision()]})
    panel_decide(config(), client)
    assert len(client.calls) == 3
    seat = [c for c in client.calls if c[1] == "executor"]
    assert "previous reply was invalid" in seat[1][2][0]["content"]


def test_unavailable_panel_fails_closed_and_missing_seat_cannot_vote_done():
    cfg = config(max_repairs=0)
    unavailable = ProviderError("fake", 503, "unavailable")
    with pytest.raises(DeciderUnavailable):
        panel_decide(cfg, FakeClient({"executor": [unavailable], "second": [unavailable]}))
    panel = panel_decide(cfg, FakeClient({"executor": [decision(True)], "second": [unavailable]}))
    assert not panel.decision.done
    assert panel.selected == "executor"
    assert panel.decision.next_step == decision(True)["next_step"]


def test_durable_obligation_requires_exact_released_check_and_idempotent_evidence(tmp_path):
    path = tmp_path / "decisions.db"
    conn = sqlite3.connect(path)
    store = DecisionStore(conn)
    panel = panel_decide(config(), FakeClient({"executor": [decision(claim="claim")]}), store)
    from tests.test_action_governor import _response
    store.release("session", panel, _response("cat /tmp/item"), ["action"])
    assert store.unresolved("session")
    conn.close()
    store = DecisionStore(sqlite3.connect(path))
    wrong = {"role": "tool", "tool_call_id": "unknown", "content": "verified data"}
    assert not store.ingest("session", [wrong])
    result = {**wrong, "tool_call_id": "call-original", "content": '{"exit_code":0,"stdout":"verified data"}'}
    assert store.ingest("session", [result])[0]["passed"]
    assert not store.unresolved("session")
    assert store.ingest("session", [result]) == []
    with pytest.raises(DeciderUnavailable, match="conflicting replay"):
        store.ingest("session", [{**result, "content": "changed"}])


def test_existing_call_ledger_migrates_without_losing_action_results():
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE decision_calls (
        session TEXT,call_id TEXT,decision_id TEXT,action_id TEXT,tool TEXT,
        arguments TEXT,result TEXT,PRIMARY KEY(session,call_id))""")
    conn.execute("INSERT INTO decision_calls VALUES ('s','c','d','a','terminal','{}','observed')")
    DecisionStore(conn)
    assert conn.execute("SELECT result,is_check,obligation_ids FROM decision_calls").fetchone() == ("observed", 0, "[]")


def _expect_scope(d, command, allowed):
    """allowed: True (proven inside), False (proven escape), "senate" (unprovable:
    the senate judges it, for executor actions and checks alike)."""
    from tests.test_action_governor import _tool_call
    call, manifest = _tool_call(command), ToolManifest(name="terminal")
    if allowed is True:
        assert enforce_scope(d, call, manifest) == []
    elif allowed == "senate":
        assert enforce_scope(d, call, manifest)
        assert enforce_scope(d, call, manifest, is_check=True)
    else:
        with pytest.raises(ScopeViolation):
            enforce_scope(d, call, manifest)


@pytest.mark.parametrize("command,allowed", [
    ("cat /tmp/item", True), ("cat /tmp/other", False),
    ("cat /tmp/item /etc/passwd", False), ("cat /tmp/item; cat /etc/passwd", False),
    ("python3 -c 'print(1)'", "senate"), ("sh /tmp/item", "senate"),
    ("cat relative", "senate"), ("cat /tmp/../etc/passwd", False),
    ("echo $(uname -a); cat /etc/passwd", False),
    ("rm /tmp/item", False), ("cat $(pwd)/item", False),
])
def test_scope_rejects_escapes(command, allowed):
    _expect_scope(Decision.parse(json.dumps(decision())), command, allowed)


@pytest.mark.parametrize("command,touches,allowed", [
    ("cd /w/build && make -j4 2>&1 | tail -n 50", [("/w/", "execute")], True),
    ("cd /w/build && make -j4", [("/w/", "read")], "senate"),
    ("cd /w && make && cp out/a.bin /home/u/obj/a.bin", [("/w/", "execute")], False),
    ("cd /w && make && cp out/a.bin /w/dist/a.bin", [("/w/", "write")], True),
    ("make -C /w/build >/dev/null 2>&1", [("/w/", "execute")], True),
    ("make -j4", [("/w/", "execute")], "senate"),
    ("qemu-system-aarch64 -bios /w/bin/qemu_fw.bios -kernel /home/u/obj/netbsd", [("/w/", "execute")], False),
    ("cd /w && ./build.sh", [("/w/", "execute")], True),
    ("cd /w && rm junk", [("/w/", "read")], False),
    ("cd /w && rm junk", [("/w/", "write")], True),
    ("make -C $HOME/w", [("/w/", "execute")], "senate"),
    ("f=/w/out; make -C /w/build && cp $f /home/u/obj/a", [("/w/", "write")], False),
    ("cd /w\nmake\nrm -rf /home/u/obj", [("/w/", "write")], False),
    ("grep -rn psci0 /w/logs", [("/w/logs/", "read")], True),
    ("cat /w/a > /w/b", [("/w/a", "read")], False),
    ("df -h / /w", [("/", "read")], "senate"),     # unknown program inside granted read
    ("cd /w && cat state.txt", [("/w/state.txt", "read")], True),   # cd only traverses
    ('cd /w && [ "a" = "b" ] && [ -s /w/state.txt ]', [("/w/state.txt", "read")], True),
    ("cd /w && git clone https://x/netbsd netbsd", [("/w/netbsd/", "write")], "senate"),
    ("cd /home/u && git clone https://x/netbsd netbsd", [("/w/netbsd/", "write")], False),
    ("cd /etc && cat /w/state.txt", [("/w/state.txt", "read")], False),
    ("rm -rf /home/u/x", [("/", "read"), ("/w/", "write")], False),
])
def test_scope_covers_every_named_path_for_any_program(command, touches, allowed):
    raw = decision()
    raw["touches"] = [{"resource": r, "access": a} for r, a in touches]
    _expect_scope(Decision.parse(json.dumps(raw)), command, allowed)


def _observe_runs(store, outputs, tool="terminal", via_job=False):
    """Record each output as one run of the same program, in order."""
    from conflux.decider import canonical
    for index, stdout in enumerate(outputs):
        command = f"timeout {60 + index}s qemu-system-aarch64 -machine virt -kernel /tmp/k{index}"
        calls = [(f"start-{index}", tool, {"command": command},
                  json.dumps({"job_id": f"job_{index:08d}"} if via_job else {"stdout": stdout, "exit_code": 0}))]
        if via_job:
            calls.append((f"watch-{index}", "watch_job", {"job_id": f"job_{index:08d}"},
                          json.dumps({"stdout": stdout, "exit_code": 124})))
        for call_id, name, arguments, content in calls:
            store.connection.execute(
                "INSERT INTO decision_calls (session,call_id,decision_id,action_id,tool,arguments) VALUES (?,?,?,?,?,?)",
                ("session", call_id, "d", call_id, name, canonical(arguments)))
            store.ingest("session", [{"role": "tool", "tool_call_id": call_id, "content": content}])


BOOT = ["Booting firmware", "[ 1.000] psci0 at simplebus0: PSCI 1.1", "[ 1.200] cpu0 at mainbus0", "root device:"]


@pytest.mark.parametrize("via_job", [False, True])
def test_line_both_previous_runs_printed_becomes_an_unresolved_obligation(via_job):
    store = DecisionStore(sqlite3.connect(":memory:"))
    final = [BOOT[0], "[ 2.000] optee0 at simplebus0", BOOT[2].replace("1.200", "1.300"), BOOT[3]]
    _observe_runs(store, ["\r\n".join(BOOT), "\n".join(BOOT), "\n".join(final)], via_job=via_job)
    regressions = [o for o in store.obligations("session") if o["member"] == "observation"]
    assert [o["status"] for o in regressions] == ["unchecked"]
    assert regressions[0]["claim"].endswith("psci0 at simplebus0: PSCI 1.1")
    assert store.unresolved("session")
    concern = [c for c in store.context("session")["concerns"] if c["source"] == "observation_regression"]
    assert concern[0]["data"]["missing_since_previous_run"] == [BOOT[1]]


@pytest.mark.parametrize("runs", [
    [BOOT, BOOT, BOOT[:1]],                       # truncated output never progressed past the line
    [BOOT[:1] + BOOT[2:], BOOT, BOOT[:1] + BOOT[2:]],   # only one previous run printed it
    [BOOT, BOOT, BOOT],
])
def test_no_regression_without_a_repeated_line_the_output_progressed_past(runs):
    store = DecisionStore(sqlite3.connect(":memory:"))
    _observe_runs(store, ["\n".join(r) for r in runs])
    assert not [o for o in store.obligations("session") if o["member"] == "observation"]


def test_regression_resolves_when_a_later_run_prints_the_line_again():
    store = DecisionStore(sqlite3.connect(":memory:"))
    _observe_runs(store, ["\n".join(BOOT), "\n".join(BOOT), "\n".join(BOOT[:1] + BOOT[2:]), "\n".join(BOOT)])
    assert [o["status"] for o in store.obligations("session") if o["member"] == "observation"] == ["passed"]


@pytest.mark.parametrize("a,b,same", [
    ("timeout 60s qemu-system-aarch64 -bios /x/bl1.bin -m 2G", "timeout 90s qemu-system-aarch64 -bios /y/fw.bios -m 2G", True),
    ("make -f qemu_v8.mk optee-os", "make -f qemu_v8.mk toolchains", False),
    ("cat /tmp/a", "cat /tmp/b", False),
])
def test_observation_signature_ignores_inputs_but_not_requests(a, b, same):
    from conflux.decider import observation_signature
    assert (observation_signature(a) == observation_signature(b)) is same


@pytest.mark.parametrize("tool, side_effect, arguments, allowed", [
    ("inspect_locked_job", "read", {"job_id": "job_a540"}, True),
    ("inspect_locked_job", "read", {"job_id": "job_9999"}, False),
    ("signal_locked_job", "write", {"job_id": "job_a540", "signal": "TERM"}, False),
    ("watch_locked_job", "read", {"job_id": "job_a540", "stdout_cursor": 0}, True),
])
def test_trusted_tools_are_scoped_by_their_handles(tool, side_effect, arguments, allowed):
    raw = decision()
    raw["touches"] = [{"resource": "locked_job:job_a540", "access": "read"}]
    d = Decision.parse(json.dumps(raw))
    call = {"function": {"name": tool, "arguments": json.dumps(arguments)}}
    manifest = ToolManifest(name=tool, trusted=True, side_effect=side_effect)
    if allowed:
        assert enforce_scope(d, call, manifest) == []
    else:
        with pytest.raises(ScopeViolation):
            enforce_scope(d, call, manifest)


def test_failure_output_lost_on_success_is_not_a_regression():
    from conflux.decider import canonical
    store = DecisionStore(sqlite3.connect(":memory:"))
    runs = [("Traceback (most recent call last):\nImportError: x", 1)] * 2 + [("imports ok", 0)]
    for index, (stdout, code) in enumerate(runs):
        store.connection.execute(
            "INSERT INTO decision_calls (session,call_id,decision_id,action_id,tool,arguments) VALUES (?,?,?,?,?,?)",
            ("session", f"c{index}", "d", f"c{index}", "terminal", canonical({"command": "python3 -c 'import x'"})))
        store.ingest("session", [{"role": "tool", "tool_call_id": f"c{index}",
                                  "content": json.dumps({"stdout": stdout, "exit_code": code})}])
    assert not [o for o in store.obligations("session") if o["member"] == "observation"]
