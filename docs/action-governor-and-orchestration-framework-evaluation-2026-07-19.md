# Action governance and orchestration framework evaluation (2026-07-19)

Status: **design recommendation; no framework migration has been performed**.

This note records the findings from reviewing llm-super's current agentic path,
the proposed in-context action verifier and preflight mechanism, and the current
state of LangGraph/LangChain, Microsoft Agent Framework, AutoGen, CrewAI, and
AutoGPT. It also gives a staged implementation plan that preserves the parts of
llm-super that were decisive in the NetBSD work.

## 1. Executive conclusion

The immediate missing component is an **online action governor**, not another
final-answer reviewer. Today, a supervised tool-carrying turn verifies final
text, but a model-proposed tool call is returned to the client without an
action-level critique or preflight. That means the final verifier can reject a
false claim after the work, while being unable to stop a dangerous, irrelevant,
or poorly instrumented command before it runs.

The recommended direction is:

1. add the action governor to the existing proxy first;
2. express orchestration as an explicit, checkpointable graph behind a small
   internal runtime interface;
3. run a replay-based comparison of LangGraph and Microsoft Agent Framework;
4. if the spike succeeds, use **LangGraph as the leading runtime candidate**
   while retaining llm-super's policy, evidence, verifier, trace, and UI as the
   product's control plane;
5. use LangChain only where its model/tool/MCP adapters save work;
6. do not begin a new implementation on AutoGen, and do not make CrewAI or
   AutoGPT the core correctness boundary.

This is a hybrid recommendation, not a wholesale rewrite. A framework can
provide graph execution, checkpointing, interrupts, subgraphs, and developer
visualization. It cannot decide llm-super's safety policy, establish that a
shell command is well founded, or turn an MCP server's self-description into a
trusted guarantee.

## 2. What llm-super does now

The current agentic route is explicit in
[`proxy.py`](../llm_super/proxy.py) and
[`orchestrator.py`](../llm_super/orchestrator.py):

- `model=super` plus tools enters `Orchestrator.run_tool_turn`.
- The executor gets at most an initial call and one verified repair.
- If the executor returns final text, heuristic monitors run and an
  evidence-aware, cross-family verifier reviews it.
- If the executor returns `tool_calls`, llm-super records a `tool_step` and
  returns the response to the client immediately.
- The client, not llm-super, performs the tool call and supplies the result in
  its next request.
- A pause racing with an upstream generation can suppress a newly proposed
  call, but otherwise the call is released.
- Selecting an explicit registry model is intentionally unsupervised
  passthrough, including for tool-carrying requests.

The current verifier in [`verifier.py`](../llm_super/verifier.py) is valuable
and should remain. Its review prompt explicitly says observed execution
evidence outranks the model's claims. This is **outcome verification**. It is
not **action authorization**.

The gap is located at the current mid-loop return:

```python
if msg.get("tool_calls"):
    # trace the step
    return data  # client executes it
```

That behavior maintained OpenAI-compatible client loops, but it also explains
why outside monitoring was needed during the NetBSD work. The supervisor could
repair an inadequate final answer; it could not itself object before `dd`, a
broad `pkill`, a hanging QEMU invocation, or a write to the wrong disk target.

## 3. The proposed action governor

### 3.1 Control flow

Every proposed action should cross one gate, but not every action should incur
another LLM call:

```text
conversation + goal + state + evidence
                  |
                  v
           executor proposes action
                  |
                  v
        deterministic policy/risk gate
             /          |           \
       low/read       uncertain     high-risk
          |               |             |
          |         independent critic  |
          |               |             |
          |       safe preflight probe  |
          |               |             |
          +-------- approve/rewrite/block
                          |
                          v
                       execute
                          |
                          v
                 postcondition smoke test
                    /             \
                 pass       recover/replan/stop
                          |
                          v
              existing final-answer verifier
```

The deterministic gate should make the cheap, obvious decisions. The LLM
critic is reserved for actions where intent, context, and causal reasoning
matter.

### 3.2 Another agent or the same agent?

For medium- and high-risk actions, use a **separate critic identity and,
preferably, a different model family**. A model reviewing its own proposal has
correlated blind spots and is likely to rationalize the plan it just made.

The executor should submit a structured rationale, and the critic should make
the strongest concrete case against it. The executor may revise or rebut once.
This should not become an unconstrained debate:

- low risk: deterministic approval, optionally a cheap probe generator;
- medium risk: independent critic, bounded probe, one revision;
- high or irreversible risk: independent critic plus deterministic policy;
  unresolved ambiguity requires human approval;
- no action is approved merely because two models agree.

The critic's context package should contain the original user constraints,
current goal and plan, exact proposed call and targets, intended postcondition,
known target state, relevant prior tool evidence, rollback plan, and remaining
budgets. Tool output must be clearly marked as untrusted data rather than
instructions.

### 3.3 What “smoke test before every command” should mean

There is no useful model-generated rehearsal for every `ls`, `stat`, or bounded
read. Instead, **every command gets a deterministic preflight**, while only
uncertain commands get recursive model work.

| Risk | Examples | Minimum treatment |
|---|---|---|
| Low | bounded reads, exact `stat`, `file`, `sha256`, `git diff` | schema/target validation, timeout, output bound, automatic release |
| Medium | compilation, tests, package install, background process, service restart | independent critique, resource/lock checks, bounded probe, explicit postcondition |
| High | raw disk writes, deletes, instance mutation, broad process kill, credential or network-boundary change | snapshot/backup proof, exact target resolution, independent critique, rollback, usually human approval |
| Unknown | unparsed shell, untrusted MCP server, missing manifest | pessimistically elevate; never assume read-only |

A proposal should carry at least:

```text
ActionProposal
  tool name and exact arguments
  intended effect
  exact targets
  expected observable postcondition
  invariants that must remain true
  timeout and output bound
  idempotency/retry expectations
  rollback or recovery action
```

The preflight should answer narrow factual questions. For example:

- Which exact PIDs match, and are they owned by this run?
- Does the named disk/partition resolve to the authorized resource?
- Is it mounted, locked, or in active use?
- Do the input artifact's size, type, and hash match the plan?
- Is there a restorable backup whose size/hash has been verified?
- Does a single-object compile or read-only parser check fail before the full
  build is attempted?
- Can the operation be run with a hard timeout and a progress heartbeat?

After execution, acceptance must be based on the proposed postcondition, not a
zero shell status alone. Pipelines need failure propagation; background jobs
need a durable job identifier and liveness/exit evidence; writes need a readback
or checksum; QEMU needs serial progress and a bounded exit condition.

### 3.4 Bounded recursion, not recursive autonomy

The sequence “critic asks for probe, probe changes the evidence, critic reviews
again” is recursive in spirit. It should be represented as a bounded graph
cycle with hard limits:

- maximum probe count and revision count;
- maximum nested-flow depth and fan-out;
- wall-clock, token, and dollar budgets;
- deduplication of identical proposed calls;
- safe-probe-only capabilities for the probe planner;
- no destructive action in a preflight subflow;
- fail closed for high-risk actions when the budget or evidence runs out.

An agent may **propose** a new `FlowSpec`; it should not install and execute
arbitrary new control flow. A deterministic compiler must validate allowed node
types, capabilities, cycles, exit conditions, schemas, and budgets before a
child flow can run.

## 4. How this fits the OpenAI tool protocol

llm-super currently does not own execution of agent-client tools. This creates
two viable integration modes.

### Compatibility mode: intercept and substitute a probe

1. The upstream model proposes the original tool call.
2. llm-super stores it as a durable `pending_action`.
3. The action governor approves, blocks, rewrites, or substitutes a safe probe
   call using a tool the client already exposed.
4. The client runs that probe and returns its result normally.
5. llm-super recognizes the probe call ID, re-evaluates the pending action, and
   releases the original call without another executor generation if approved.

This preserves existing OpenAI-compatible clients. It requires durable,
concurrency-safe pending-action state keyed by conversation/run/action identity;
otherwise a proxy restart or two simultaneous client turns can lose or cross
the original action.

Compatibility mode can only generate probes expressible through a tool the
client already provided. If the only exposed tool is an unrestricted shell,
the governor must constrain the exact command it substitutes and treat shell
parsing failures pessimistically.

### Owned-execution mode: run tools inside the graph

For first-party workflows, llm-super should eventually own tool execution. The
graph can then checkpoint before and after the tool, enforce capabilities,
apply timeouts, capture complete evidence, and recover without relying on a
client transcript. The OpenAI proxy remains as a compatibility boundary for
third-party clients.

Owned execution is the cleaner long-term model, but it is a larger change and
must not block the immediate compatibility-mode governor.

## 5. Tool and MCP policy

Framework support makes MCP tools easier to discover and invoke; it does not
make them safe. Each trusted tool needs a local capability manifest with:

- side-effect class and allowed resource scopes;
- argument validator and exact target extractor;
- timeout, output, concurrency, and retry policy;
- idempotency and open-world status;
- preflight and postcondition handlers;
- rollback/snapshot support where applicable;
- provenance and trust level of the server supplying it.

The current MCP schema has `readOnlyHint`, `destructiveHint`,
`idempotentHint`, and `openWorldHint`, but the specification explicitly calls
them hints and says not to trust them from an untrusted server. llm-super can
use trusted annotations as input to the UI and risk classifier, never as its
enforcement boundary. See the official
[MCP schema reference](https://modelcontextprotocol.io/specification/2025-11-25/schema).

For shell-like tools, a single `command: string` schema is too weak for robust
policy. Prefer typed operations such as `read_file`, `list_processes`,
`run_build`, `stop_run_process`, `write_authorized_partition`, or at least an
execution wrapper with an explicit authorized host, working directory,
read/write scopes, timeout, and expected outputs. Unparseable shell syntax
should elevate risk rather than be guessed safe.

## 6. Framework findings

The comparison below concerns suitability as llm-super's **runtime**, not which
project has the largest agent catalog.

| Option | Useful capabilities | Main concern for llm-super | Judgment |
|---|---|---|---|
| Current custom orchestrator | Exact OpenAI compatibility, model-family routing, evidence-first verification, existing trace/UI/control semantics, minimal dependencies | Control flow is embedded in methods; tool steps are not governed; custom durability and dynamic subflows would be expensive | Keep the product semantics, but stop growing orchestration as one-off branches |
| LangGraph | Low-level state graph, durable execution, persistence, streaming, interrupts/HITL, reusable subgraphs; LangSmith Studio can visualize and debug graphs | Adds a runtime and potentially a platform dependency; Studio is developer tooling, not a replacement for llm-super's user-facing Live/History; safety policy remains custom | **Leading spike candidate** for the Python runtime |
| LangChain | High-level agents and broad model/tool integrations; official MCP adapters support multiple servers | Higher-level agent loops can obscure the exact action boundary and state semantics llm-super needs | Use adapters selectively; do not make the prebuilt agent abstraction the core policy layer |
| Microsoft Agent Framework | Current successor to AutoGen and Semantic Kernel; agents, middleware, MCP clients, typed graph workflows, events, checkpointing, HITL; Python and .NET | Newer integration surface; superstep synchronization and provider/session semantics need testing against long-running asynchronous tools and the current proxy | **Strong second spike candidate**, especially if Azure/.NET becomes important |
| AutoGen | Multi-agent patterns and experimental `GraphFlow` with sequential, parallel, conditional, and looping execution | Official project is in maintenance mode and directs new users to Microsoft Agent Framework; GraphFlow is marked experimental | Do not start a new migration on AutoGen |
| CrewAI | Opinionated crews plus event-driven Flows with state, persistence, routing, guardrails, and HITL | Role/task metaphor is less natural for a policy-enforced tool gateway; safety, evidence, and OpenAI protocol behavior would still be custom | Viable for application workflows, not the preferred supervisor core |
| AutoGPT Platform | Visual low-code block builder, workflow lifecycle, continuous agents, monitoring UI, self-hosting | A much larger product/platform surface than a library runtime; Docker/infrastructure overhead; platform folder has a non-MIT Polyform Shield license | Useful product/UI reference, poor fit as llm-super's embedded correctness runtime |

### 6.1 Why LangGraph leads

LangGraph describes itself as a low-level runtime for long-running, stateful
agents and explicitly focuses on durable execution, streaming,
human-in-the-loop, and persistence. It does not require LangChain for the graph
itself. Its subgraphs can be nodes in parent graphs, which matches bounded
critic/probe flows. These are the exact primitives llm-super would otherwise
have to build next. See the official
[LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)
and [subgraph guide](https://docs.langchain.com/oss/python/langgraph/use-subgraphs).

[LangSmith Studio](https://docs.langchain.com/langsmith/studio) can visualize,
interact with, and debug graphs that implement its Agent Server API. That is
useful during development. It does not remove the need for llm-super's current
UI because users need the product-specific risk verdicts, summaries, evidence,
cost, recovery state, and conversation history—not only a declared graph.

LangChain's official
[MCP adapters](https://docs.langchain.com/oss/python/langchain/mcp) are a
reasonable integration component. The governor should wrap the adapter's tool
boundary instead of assuming adapter use is authorization.

### 6.2 What Microsoft's framework is now

The current Microsoft choice is **Microsoft Agent Framework**, the successor to
both AutoGen and Semantic Kernel—not a new AutoGen implementation. Microsoft
documents agents, middleware that can intercept actions, MCP clients, and
graph-based workflows with typed routing, checkpointing, and human-in-the-loop
support in the official
[overview](https://learn.microsoft.com/en-us/agent-framework/overview/).

Its workflows are directed graphs of executors and edges with event streaming
and validation. Execution uses synchronized supersteps, which gives consistent
state and checkpoint boundaries but can make an unrelated long-running branch
hold up other branches. That behavior must be tested against QEMU/build/polling
flows. See
[workflow execution](https://learn.microsoft.com/en-us/agent-framework/workflows/workflows)
and [checkpointing](https://learn.microsoft.com/en-us/agent-framework/workflows/checkpoints).

The former [AutoGen repository](https://github.com/microsoft/autogen) now says
it is in maintenance mode and tells new users to use Microsoft Agent Framework.
That makes AutoGen an unsuitable foundation for a new llm-super migration even
though its GraphFlow concepts are relevant.

### 6.3 CrewAI and AutoGPT

CrewAI's official documentation presents
[Flows](https://docs.crewai.com/en/concepts/flows) as structured,
event-driven workflows with state, persistence, routing, and long-running
resume, alongside role-oriented crews. Those are legitimate orchestration
features. The mismatch is architectural: llm-super's differentiator is a
protocol-level evidence and action-policy boundary, not primarily role-based
task delegation.

The official [AutoGPT repository](https://github.com/Significant-Gravitas/AutoGPT)
describes a self-hosted platform with a low-code block builder, continuous
agents, deployment controls, and monitoring. That is closer to adopting a
second product than embedding a runtime. Its visual block model is worth
studying, but its server/frontend footprint and licensing split make it a poor
foundation for this repository.

## 7. Proposed runtime and event contracts

Framework choice should be hidden behind a deliberately small interface:

```text
FlowRuntime
  compile(flow_spec) -> validated graph/version
  start(input, budgets, capabilities) -> run_id
  stream(run_id) -> normalized events
  interrupt(run_id, reason)
  resume(run_id, input_or_approval)
  checkpoint(run_id) -> durable checkpoint id
  inspect(run_id) -> typed state
  replay(run_id_or_fixture)
```

The normalized event vocabulary should belong to llm-super, not a framework:

```text
action_proposed
risk_assessed
critic_started / critic_verdict
probe_requested / probe_result
action_rewritten / action_blocked / action_released
action_started / action_result
postcheck_result
rollback_started / rollback_result
child_flow_proposed / child_flow_rejected / child_flow_started
checkpoint_saved
human_approval_requested
```

Each event should include parent/child graph identity, conversation/task/action
identity, node label, short summary, long summary, model identity, target,
capability scope, risk, verdict, evidence references, cost/latency, and status.
This lets the existing summary records and Live/History views render both the
declared graph and the graph that actually ran.

The user-facing UI should show the action proposal, critic's objection,
preflight evidence, final disposition, execution result, and postcheck as
distinct graphical nodes. Framework developer UIs can supplement this view,
not replace it.

## 8. How this would have changed the NetBSD run

The prior NetBSD exercise supplies a ready-made adversarial replay suite. An
action governor should have caught or instrumented these cases before release:

- QEMU invocations with no hard timeout or progress heartbeat;
- broad `pkill -f qemu` instead of run-owned exact PIDs;
- a stale or mismatched artifact hash;
- a serial-console regex that expected `>` but the guest printed `> `;
- use of `bootm` on a raw AArch64 image;
- `dd` to `/dev/nbd0p2` without proven target identity, restorable backup,
  size check, and readback;
- shell pipelines that masked an earlier failing command;
- a background HTTP server that kept an SSH session open;
- acceptance based on narration rather than the actual guest UID, driver
  output, boot log, and process state.

Most of these do not need another expensive model. Exact PID resolution,
timeouts, `file`, hashes, mount/lock checks, pipeline status, and readback are
deterministic. The critic is most useful for asking whether the command could
actually cause the claimed next state and whether the proposed evidence would
distinguish success from a plausible false positive.

The existing final verifier was still essential: it rejected the executor's
premature success claim and caused the work to resume. The new governor fills
the other side of the timeline—before effects occur.

## 9. Staged implementation plan

### Phase 0 — action governor in the current orchestrator

Implement this before any framework migration:

1. define `ActionProposal`, `RiskAssessment`, `ProbeSpec`, `ActionVerdict`,
   `PostconditionSpec`, and `ToolManifest` schemas;
2. add a deterministic classifier and target/capability validator;
3. add a cross-family action critic for medium/high risk;
4. intercept the `tool_calls` branch in `run_tool_turn`;
5. durably store pending actions and probe state;
6. emit the normalized action events;
7. add a fail-closed high-risk path and explicit human approval state;
8. preserve explicit-model passthrough as explicitly labeled unsafe behavior,
   or add a separate configuration knob to govern passthrough tools too.

### Phase 1 — replay and policy tests

Create fixtures from the NetBSD trace and require stable decisions for the
known failure cases. Add property tests for:

- exact target extraction and authorization;
- quoting, pipelines, redirects, subshells, and parse failure;
- timeouts and maximum output;
- idempotent retry and duplicate suppression;
- concurrent conversations and pending actions;
- proxy restart between probe and action;
- malicious instructions embedded in tool output;
- critic timeout, malformed verdict, and budget exhaustion;
- postcondition failure and rollback escalation.

### Phase 2 — runtime abstraction and two spikes

Move one representative flow behind `FlowRuntime`, then implement small
LangGraph and Microsoft Agent Framework adapters. Do not port the entire
orchestrator during the spike.

Evaluate both with the same fixtures and measurements:

- exact OpenAI tool-call and streaming compatibility;
- checkpoint/resume across process restart;
- cancellation of QEMU/build/polling work;
- nested critic/probe subflows with depth/fan-out limits;
- event completeness and mapping into the current UI;
- concurrent runs, locking, and state isolation;
- self-hosting requirements and operational complexity;
- provider independence, MCP wrapping, and testability;
- latency and cost added per action;
- deterministic replay and schema migration behavior.

### Phase 3 — adopt only after parity

If LangGraph wins the replay, use it for state transitions, checkpoints,
interrupts, and bounded subgraphs while keeping the following as llm-super
code:

- risk and capability policy;
- executor/critic/verifier family selection;
- evidence contracts and postconditions;
- summaries, trace schema, and normalized events;
- OpenAI-compatible proxy behavior;
- Live/History product UI;
- cost, failure-mode, and human-control semantics.

If neither spike reproduces the current semantics cleanly, keep the runtime
custom but implement it from the same explicit state/event contracts. The
interface and replay suite are useful regardless of which runtime wins.

## 10. Decision summary

- **Should actions be reviewed in conversation context?** Yes, before release,
  with exact goal/state/evidence and tool output treated as untrusted.
- **Same agent or another?** Another, cross-family critic for meaningful risk;
  deterministic policy for obvious cases; human approval for unresolved
  irreversible actions.
- **Smoke test before virtually every command?** Every command gets a cheap
  deterministic preflight; only uncertain commands recurse into critic/probe
  work; every executed command gets a postcondition check.
- **Should agents spawn their own flows?** They may propose bounded declarative
  subflows. A deterministic compiler—not the proposing model—authorizes them.
- **Replace the current orchestrator wholesale?** No. Add the missing governor
  now and isolate runtime mechanics behind an interface.
- **Best framework to test first?** LangGraph. Test Microsoft Agent Framework
  in parallel as the serious alternative. Use LangChain adapters selectively.
- **AutoGen, CrewAI, or AutoGPT?** AutoGen is now a maintenance path; CrewAI is
  better suited to opinionated application workflows; AutoGPT is a larger
  visual automation product. None is the recommended correctness core here.

## Official sources consulted

- [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)
- [LangGraph subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
- [LangSmith Studio](https://docs.langchain.com/langsmith/studio)
- [LangChain MCP adapters](https://docs.langchain.com/oss/python/langchain/mcp)
- [Microsoft Agent Framework overview](https://learn.microsoft.com/en-us/agent-framework/overview/)
- [Microsoft Agent Framework workflow execution](https://learn.microsoft.com/en-us/agent-framework/workflows/workflows)
- [Microsoft Agent Framework checkpoints](https://learn.microsoft.com/en-us/agent-framework/workflows/checkpoints)
- [AutoGen repository and maintenance notice](https://github.com/microsoft/autogen)
- [CrewAI Flows](https://docs.crewai.com/en/concepts/flows)
- [AutoGPT repository/platform overview](https://github.com/Significant-Gravitas/AutoGPT)
- [MCP tool annotations schema](https://modelcontextprotocol.io/specification/2025-11-25/schema)
