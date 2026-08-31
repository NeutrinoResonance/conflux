#!/usr/bin/env python3
"""Create a deterministic workspace hierarchy and held action for browser QA.

This fixture never executes the proposed tool.  It writes only product-state
records so a browser test can inspect the exact approval and containment UX.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from conflux.conversation_graph import ConversationGraphStore
from conflux.flows import FlowRegistry, SQLiteFlowRuntime
from conflux.governance import (
    ActionStore,
    ActionVerdict,
    ToolManifest,
    assess_action,
    build_proposal,
)
from conflux.library import Library
from conflux.trace import Trace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="traces.db")
    args = parser.parse_args()

    db_path = Path(args.db)
    trace = Trace(db_path)
    registry = FlowRegistry.load(Path(__file__).parents[1] / "agent_flows.yaml")
    runtime = SQLiteFlowRuntime(trace.connection, registry)
    store = ConversationGraphStore(trace.connection, registry)

    endeavor = store.create_endeavor("Public release readiness")
    primary = store.create_conversation(endeavor["id"], "Resolve deployment risks")
    store.create_conversation(endeavor["id"], "Polish onboarding copy")
    store.create_message_pair(
        primary["session"], "Check whether deployment is safe",
        completed_output="The read-only checks passed.", task_id="task-browser-safe",
    )
    held = store.create_message_pair(
        primary["session"], "Start the production migration",
        completed_output="Operator approval is required.", task_id="task-browser-held",
    )

    run_id = runtime.start(
        "supervised_tool_turn", {"goal": "start production migration"}, {},
        list(registry.flows["supervised_tool_turn"].capabilities),
        session=primary["session"], task="task-browser-held",
    )
    runtime.transition(
        run_id, "executor", "executor_proposed_action",
        summary="Executor proposed the production migration command",
        model="executor-fixture", data={"tool": "terminal", "proposal_count": 1},
    )
    runtime.transition(
        run_id, "policy_gate", "risk_classified", summary="Risk classified high",
        risk="high", verdict="review", data={"requires_human": True},
    )
    runtime.transition(
        run_id, "action_critic", "critic_requested_approval",
        summary="Independent critic found the migration irreversible",
        model="critic-fixture", risk="high", verdict="human",
        data={"objection": "No verified rollback was supplied."},
    )
    runtime.transition(
        run_id, "human_approval", "operator_input_requested",
        status="interrupted", summary="Waiting for explicit operator approval",
    )

    trace.record_exchange(
        primary["session"], "task-browser-held", "upstream", "executor-fixture",
        {
            "request": {
                "model": "executor-fixture", "temperature": 0.2,
                "messages": [{"role": "user", "content": "Start the production migration"}],
                "tools": [{"name": "terminal"}],
            },
            "response": {
                "tool_calls": [{"name": "terminal", "arguments": {
                    "command": "start-production-migration --target gce://release-worker"
                }}]
            },
        },
    )
    trace.record(
        primary["session"], "task-browser-held", "execute",
        model="executor-fixture", tokens_in=31, tokens_out=14, cost_usd=0.00012,
        attempt=1, temperature=0.2,
    )
    trace.record_exchange(
        primary["session"], "task-browser-held", "upstream", "critic-fixture",
        {
            "request": {
                "model": "critic-fixture", "temperature": 0,
                "messages": [{"role": "system", "content": "Independently challenge this action."}],
                "proposal": "start production migration",
            },
            "response": {
                "decision": "human", "reason": "No verified rollback was supplied."
            },
        },
    )
    trace.record(
        primary["session"], "task-browser-held", "action_critic",
        model="critic-fixture", tokens_in=24, tokens_out=9, cost_usd=0.00009,
        decision="human", risk="high",
    )

    manifest = ToolManifest(
        name="terminal", side_effect="destructive", trusted=True,
        requires_human=True, shell_command=True,
    )
    call = {
        "id": "call-browser-held",
        "function": {
            "name": "terminal",
            "arguments": json.dumps({
                "command": "start-production-migration --target gce://release-worker"
            }),
        },
    }
    proposal = build_proposal(
        call, {"content": "Start the migration only after an operator review."},
        manifest,
    )
    actions = ActionStore(trace.connection)
    actions.put(
        primary["session"], "task-browser-held", run_id, proposal,
        assess_action(proposal, manifest), manifest, "human_pending",
        {"choices": []},
        verdict=ActionVerdict("human", "Production migration needs explicit approval"),
    )
    store.set_node_status(
        held["assistant"]["node_id"], "awaiting_approval",
        output_text="Operator approval is required. Review the exact action below.",
        run_id="task-browser-held",
        config_patch={"pending_action_ids": [proposal.action_id]},
    )
    store.set_workflow_runtime(
        held["workflow"]["instance_id"], status="awaiting_approval",
        active_node="human_approval", node_status="awaiting_approval",
    )

    archive_session = "archived-browser-thread"
    Library(db_path).touch_session(archive_session, "Unassigned archived discussion")
    trace.record_exchange(
        archive_session, "task-archive", "client_request", None,
        {"messages": [{"role": "user", "content": "An earlier discussion"}]},
    )
    trace.record_exchange(
        archive_session, "task-archive", "client_response", None,
        {"text": "An earlier answer"},
    )
    print(json.dumps({
        "endeavor_id": endeavor["id"],
        "conversation_id": primary["session"],
        "assistant_node_id": held["assistant"]["node_id"],
        "action_id": proposal.action_id,
        "run_id": run_id,
        "archive_session": archive_session,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
