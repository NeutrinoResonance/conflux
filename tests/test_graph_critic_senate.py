"""The graph critic controls the real action senate; all providers are fakes."""

import asyncio
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from conflux.config import DeciderSettings, Config, Execution, Model, SenateSettings, Supervision
from conflux.control import ControlState
from conflux.conversation_graph import ConversationGraphStore
from conflux.flow_synthesis import _PROMPT, validate_synthesized
from conflux.flows import FlowRegistry, SQLiteFlowRuntime
from conflux.governance import ActionGovernor, ActionStore, ToolManifest, assess_action, build_proposal
from conflux.orchestrator import Orchestrator
from conflux.providers import ChatResult, ProviderError
from conflux.trace import Trace


def config():
    def model(name, family):
        # In particular, GLM has neither a verifier role nor logprobs.
        return Model(name, "fake", name, family, (), False, 5, 0, 0)

    return Config(
        decider=DeciderSettings(enabled=False),
        providers={},
        models={name: model(name, family) for name, family in (
            ("executor", "exec"), ("cautious", "other"), ("glm", "glm"), ("ally", "exec"),
        )},
        default_executor="executor", utility="glm", verifier_pool=[],
        supervision=Supervision(confirm_new_sessions=False), execution=Execution(backend="off"),
        senate=SenateSettings(members=["cautious", "glm", "ally"]), learned_routing=False,
    )


def registry():
    return FlowRegistry.load(Path(__file__).parents[1] / "agent_flows.yaml")


class FakeClient:
    def __init__(self, replies=None):
        self.replies = replies or {
            "cautious": ("T", "could corrupt the build"),
            "glm": ("B", "matches the PSCI node and displaces the psci driver"),
            "ally": ("A", "writes optee.c without a backup"),
        }
        self.calls = []

    async def chat(self, model, messages, **kwargs):
        self.calls.append((model.name, messages, kwargs))
        await asyncio.sleep(0)  # every member yields independently
        reply = self.replies[model.name]
        if isinstance(reply, Exception):
            raise reply
        letter, how = reply
        return ChatResult(f"<danger>{letter}</danger><how>{how}</how>", 10, 5, 0.001)

    async def raw_chat(self, model, body):
        return {
            "model": model.name, "choices": [{"index": 0, "finish_reason": "tool_calls",
                "message": {"role": "assistant", "content": "Build it", "tool_calls": [call()]}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }


def call():
    return {"id": "call-build", "type": "function", "function": {
        "name": "terminal", "arguments": '{"command":"make -j2"}',
    }}


def body(instance_id=None):
    return {
        "messages": [{"role": "user", "content": "Build safely"}],
        "metadata": {"workflow_instance_id": instance_id} if instance_id else {},
        "tools": [{"type": "function", "function": {"name": "terminal", "parameters": {
            "type": "object", "properties": {"command": {"type": "string"}},
            "required": ["command"],
        }}}],
    }


@pytest.fixture
def harness(tmp_path):
    cfg = config()
    trace = Trace(str(tmp_path / "trace.db"))
    runtime = SQLiteFlowRuntime(trace.connection, registry())
    client = FakeClient()
    governor = ActionGovernor(cfg, client, trace, ActionStore(trace.connection), runtime)
    store = ConversationGraphStore(trace.connection, runtime.registry, cfg)
    endeavor = store.create_endeavor("Test senate")
    store.create_conversation(endeavor["id"], "test", session="session")
    pair = store.create_message_pair("session", "Build safely")
    yield cfg, client, governor, store, pair["workflow"]["instance_id"]
    trace.connection.close()


def critique(harness, settings=None, requires_human=False):
    cfg, _, governor, _, _ = harness
    manifest = ToolManifest(name="terminal")
    proposal = build_proposal(call(), {"content": "Build"}, manifest)
    assessment = replace(assess_action(proposal, manifest), requires_human=requires_human)
    return asyncio.run(governor._critique(
        proposal, assessment, manifest, cfg.model("executor"), settings=settings,
        messages=body()["messages"], session="session", task="task",
    ))


def test_edit_settings_resolve_into_plan_without_mutating_defaults(harness):
    cfg, _, _, store, instance = harness
    store.update_workflow_node(instance, "action_critic", {"config": {
        "members": ["glm", "ally"], "decision": "quorum", "approve_below": 0.3,
        "quorum": 2, "concerns": "top",
    }})
    plan = store.workflow_plan(instance)
    assert plan["critic"] == {
        "members": ["glm", "ally"], "decision": "quorum", "approve_below": 0.3,
        "quorum": 2, "concerns": "top",
    }
    assert plan["critic_node_id"] == "action_critic"
    assert plan["critic_nodes"]["action_critic"] == plan["critic"]
    assert cfg.senate.members == ["cautious", "glm", "ally"]
    store.update_workflow_node(instance, "action_critic", {"config": {"members": "auto"}})
    assert store.workflow_plan(instance)["critic"] == asdict(cfg.senate)


def test_unconfigured_critic_inherits_every_senate_default(harness):
    cfg, _, _, store, instance = harness
    cfg.senate = SenateSettings(["glm"], "quorum", 0.8, 2, "top")
    store.update_workflow_node(instance, "action_critic", {"config": {}})
    assert store.workflow_plan(instance)["critic"] == asdict(cfg.senate)


def test_legacy_store_constructor_uses_running_config(harness):
    cfg, _, governor, _, instance = harness
    cfg.senate = SenateSettings(["glm"], "mean", 0.8, 2, "top")
    store = ConversationGraphStore(governor.runtime.connection, governor.runtime.registry)
    store.update_workflow_node(instance, "action_critic", {"config": {}})
    assert store.workflow_plan(instance)["critic"] == asdict(cfg.senate)


@pytest.mark.parametrize("bad,match", [
    ({"members": "glm"}, "members"),
    ({"members": ["unknown"]}, "unknown model"),
    ({"members": ["glm", "glm"]}, "duplicate"),
    ({"members": [False]}, "members"),
    ({"decision": "majority"}, "decision"),
    ({"concerns": "loudest"}, "concerns"),
    ({"approve_below": -0.1}, "approve_below"),
    ({"approve_below": float("nan")}, "approve_below"),
    ({"approve_below": "0.5"}, "approve_below"),
    ({"approve_below": True}, "approve_below"),
    ({"quorum": 0}, "quorum"),
    ({"quorum": 1.5}, "quorum"),
    ({"quorum": True}, "quorum"),
])
def test_edit_and_synthesis_reject_bad_critic_settings(harness, bad, match):
    cfg, _, _, store, instance = harness
    original = store.workflow(instance)
    with pytest.raises(ValueError, match=f"critic node 'action_critic'.*{match}"):
        store.update_workflow_node(instance, "action_critic", {"config": bad})
    assert store.workflow(instance) == original
    graph = original["graph"]
    next(n for n in graph["nodes"] if n["id"] == "action_critic")["config"] = bad
    with pytest.raises(ValueError, match=match):
        validate_synthesized(graph, registry(), cfg=cfg)


def test_synthesized_critic_settings_are_preserved_and_prompt_explains_them(harness):
    cfg, _, _, store, instance = harness
    graph = store.workflow(instance)["graph"]
    next(n for n in graph["nodes"] if n["id"] == "action_critic")["config"] = {
        "members": ["glm"], "decision": "mean", "concerns": "all",
    }
    synthesized = validate_synthesized(graph, registry(), cfg=cfg)
    store.apply_synthesized_workflow(instance, synthesized)
    assert store.workflow_plan(instance)["critic"]["members"] == ["glm"]
    assert store.workflow_plan(instance)["critic"]["decision"] == "mean"
    rendered = _PROMPT.format(node_types="critic", agents="critic", max_nodes=14,
                              model_names="glm", task="Build")
    for key in ("members", "decision", "approve_below", "quorum", "concerns"):
        assert key in rendered


def test_non_logprob_non_top_concern_reaches_verdict_and_every_member_is_traced(harness):
    _, client, governor, _, _ = harness
    verdict = critique(harness)
    assert verdict.verdict == "block"
    assert "displaces the psci driver" in verdict.reason
    assert "displaces the psci driver" in verdict.objection
    assert "without a backup" in verdict.objection
    assert {c[0] for c in client.calls} == {"cautious", "glm", "ally"}
    assert verdict.tokens_in == 30 and verdict.tokens_out == 15
    assert verdict.cost_usd == pytest.approx(0.003)
    events = {e["model"]: e for e in governor.trace.recent() if e["kind"] == "critic_review"}
    assert set(events) == {"cautious", "glm", "ally"}
    assert events["cautious"]["data"]["danger"] == 1.0
    assert events["glm"]["data"]["danger"] == pytest.approx(1 / 19)
    assert events["glm"]["data"]["continuous"] is False
    assert events["glm"]["data"]["family"] == "glm"
    assert events["glm"]["data"]["how"] == "matches the PSCI node and displaces the psci driver"
    assert events["glm"]["data"]["voted"] is True
    assert events["ally"]["data"]["voted"] is False


def test_executor_family_never_votes_but_its_concern_is_kept(harness):
    _, client, _, _, _ = harness
    client.replies = {"glm": ("A", "bounded risk"), "ally": ("T", "overwrites source")}
    verdict = critique(harness, {"members": ["glm", "ally"]})
    assert verdict.verdict == "approve"
    assert "ally: overwrites source" in verdict.reason
    assert "ally: overwrites source" in verdict.objection


@pytest.mark.parametrize("method,quorum,expected", [
    ("max", 1, "block"), ("median", 1, "block"), ("mean", 1, "block"),
    ("quorum", 1, "block"), ("quorum", 2, "approve"),
])
def test_decision_method_controls_outcome(harness, method, quorum, expected):
    verdict = critique(harness, {"decision": method, "quorum": quorum})
    assert verdict.verdict == expected


@pytest.mark.parametrize("method,expected", [("max", "block"), ("median", "approve"), ("mean", "approve")])
def test_mean_and_median_can_differ_from_max(harness, method, expected):
    cfg, client, _, _, _ = harness
    cfg.models["low"] = replace(cfg.model("glm"), name="low", family="low")
    client.replies["low"] = ("A", "none")
    verdict = critique(harness, {"members": ["cautious", "glm", "low"], "decision": method})
    assert verdict.verdict == expected


def test_concerns_top_keeps_only_most_cautious_members_text(harness):
    verdict = critique(harness, {"concerns": "top"})
    assert "could corrupt the build" in verdict.objection
    assert "psci" not in verdict.reason and "backup" not in verdict.reason


@pytest.mark.parametrize("requires_human,expected", [(False, "block"), (True, "human")])
def test_outage_is_unavailability_not_an_objection(harness, requires_human, expected):
    cfg, client, governor, _, _ = harness
    client.replies = {name: ProviderError(name, 503, "outage") for name in cfg.senate.members}
    verdict = critique(harness, requires_human=requires_human)
    assert verdict.verdict == expected
    assert "unavailable" in verdict.reason
    assert "objection" not in verdict.reason and "danger decision" not in verdict.reason
    assert verdict.objection == ""
    events = [e for e in governor.trace.recent() if e["kind"] == "critic_error"]
    assert len(events) == 3
    assert all(e["data"]["danger"] is None and not e["data"]["voted"] for e in events)


def test_only_executor_family_answering_is_still_unavailable(harness):
    _, client, _, _, _ = harness
    client.replies = {"glm": ProviderError("glm", 503, "down"),
                      "ally": ("A", "can replace the kernel driver")}
    verdict = critique(harness, {"members": ["glm", "ally"]})
    assert verdict.verdict == "block" and "unavailable" in verdict.reason
    assert verdict.objection == ""
    assert "can replace the kernel driver" in verdict.reason


def test_selected_graph_plan_controls_proxy_pipeline_and_is_snapshotted(harness):
    cfg, client, governor, store, instance = harness
    store.update_workflow_node(instance, "action_critic", {"config": {
        "members": ["cautious", "glm"], "decision": "quorum", "quorum": 2,
    }})
    orch = Orchestrator(cfg, client, governor.trace, ControlState(), governor=governor,
                        flow_runtime=governor.runtime)
    response = asyncio.run(orch.run_tool_turn("session", body(instance), stateless=True))
    assert response["choices"][0]["finish_reason"] == "tool_calls"
    item = governor.store.list()[0]
    state = governor.runtime.inspect(item["run_id"])["state"]
    assert state["critic_plan"]["critic"] == store.workflow_plan(instance)["critic"]
    assert {c[0] for c in client.calls} == {"cautious", "glm"}
    # Editing shared defaults while a run waits for probe evidence cannot
    # silently change the settings used for that held action.
    store.update_workflow_node(instance, "action_critic", {"config": {"decision": "max"}})
    assert governor._critic_plan("session", item["run_id"], body(instance)) == state["critic_plan"]


def test_global_critic_edits_apply_to_clients_without_an_instance(harness):
    cfg, client, governor, store, instance = harness
    store.update_workflow_node(instance, "action_critic", {"config": {
        "members": ["glm"], "decision": "mean",
    }}, apply_globally=True)
    orch = Orchestrator(cfg, client, governor.trace, ControlState(), governor=governor,
                        flow_runtime=governor.runtime)
    response = asyncio.run(orch.run_tool_turn("session", body(), stateless=True))
    assert response["choices"][0]["finish_reason"] == "tool_calls"
    assert [c[0] for c in client.calls] == ["glm"]


def test_synthesized_renamed_critic_controls_the_pipeline(harness):
    cfg, client, governor, store, instance = harness
    graph = store.workflow(instance)["graph"]
    critic = next(n for n in graph["nodes"] if n["id"] == "action_critic")
    critic["id"] = "custom_review"
    critic["config"] = {"members": ["glm"], "decision": "mean"}
    for edge in graph["edges"]:
        for key in ("source", "target"):
            if edge[key] == "action_critic":
                edge[key] = critic["id"]
    store.apply_synthesized_workflow(instance, validate_synthesized(graph, registry(), cfg=cfg))
    orch = Orchestrator(cfg, client, governor.trace, ControlState(), governor=governor,
                        flow_runtime=governor.runtime)
    response = asyncio.run(orch.run_tool_turn("session", body(instance), stateless=True))
    assert response["choices"][0]["finish_reason"] == "tool_calls"
    assert [c[0] for c in client.calls] == ["glm"]
    review = next(e for e in governor.trace.recent() if e["kind"] == "critic_review")
    assert review["data"]["node_id"] == "custom_review"


def test_request_cannot_select_another_conversations_workflow(harness):
    _, _, governor, _, instance = harness
    run_id = governor.start_run("another-session", "task", "Build safely", 1.0)
    with pytest.raises(ValueError, match="another conversation"):
        governor._critic_plan("another-session", run_id, body(instance))


def test_projection_uses_the_reviewed_critic_node():
    from conflux.proxy import _workspace_stage_for_event

    workflow = {"graph": {"nodes": [
        {"id": "first", "type": "critic"}, {"id": "chosen", "type": "critic"},
    ]}}
    assert _workspace_stage_for_event(workflow, "critic_review", {"node_id": "chosen"}) == "chosen"
