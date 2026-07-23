"""OpenAI-compatible ingress (SPEC §2): any OSS client connects unmodified.

Model name "super" (or "super/<anything>") routes through the supervised
orchestrator; a registry model name (e.g. "deepseek-v4-pro") passes through
unsupervised. Streaming requests are answered as SSE with the final verified
text (optimistic token-by-token streaming is a later milestone).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from . import graph_ui, history_ui, ui, workspace_ui

from . import balance as balance_mod
from . import export as export_mod
from . import report as report_mod
from . import retention
from .checkpoint import Checkpoints
from .config import load
from .conversation_graph import ConversationGraphStore
from .control import PAUSED_NOTICE, ControlState, gate_warning, handle
from .durable_jobs import DurableJobStore
from .execution_backends import ExecutionBoundaryError
from .history import History
from .history_view import HistoryView
from .library import DEFAULT_SETTINGS, Library
from .orchestrator import Orchestrator, _last_user_text
from .providers import Client, ProviderError  # noqa: F401 (ProviderError used below)
from .trace import Trace
from .workspace import WorkspaceService

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load(state.get("config_path", "models.yaml"))
    client = Client(cfg)
    trace_path = state.get("trace_path", "traces.db")
    trace = Trace(trace_path)
    job_store = DurableJobStore(trace.connection)
    control = ControlState()
    history = History(trace_path)
    library = Library(trace_path)
    checkpoints = Checkpoints(trace_path)
    orch = Orchestrator(cfg, client, trace, control,
                        checkpoints=checkpoints, history=history)
    workspace_store = ConversationGraphStore(
        trace.connection, orch.flow_runtime.registry
    )
    workspace_service = WorkspaceService(
        workspace_store, orch, library, trace
    )
    state.update(
        cfg=cfg,
        client=client,
        trace=trace,
        control=control,
        history=history,
        library=library,
        trace_path=trace_path,
        checkpoints=checkpoints,
        armed_sessions=set(),
        orch=orch,
        flow_runtime=orch.flow_runtime,
        action_store=orch.action_store,
        job_store=job_store,
        workspace_store=workspace_store,
        workspace_service=workspace_service,
    )

    async def retention_loop():
        while True:
            try:
                report = await asyncio.to_thread(
                    retention.prune, trace_path, library.retention_settings())
                if any(report["deleted"].values()):
                    trace.record("-", "-", "retention_prune", **report["deleted"],
                                 reclaimed_bytes=report["reclaimed_bytes"])
            except Exception:
                pass  # retention must never take the proxy down
            await asyncio.sleep(3600)

    task = asyncio.create_task(retention_loop())
    yield
    task.cancel()
    await client.aclose()


app = FastAPI(title="llm-super", lifespan=lifespan)


def _session_id(messages: list[dict]) -> str:
    """Conversation-prefix hash: same first user message → same session."""
    for m in messages:
        if m.get("role") == "user":
            return hashlib.sha256(json.dumps(m, sort_keys=True).encode()).hexdigest()[:12]
    return "anon"


def _usage(prompt_tokens: int = 0, completion_tokens: int = 0) -> dict[str, int]:
    prompt = int(prompt_tokens or 0)
    completion = int(completion_tokens or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def _completion_body(
    text: str,
    model: str,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": _usage(prompt_tokens, completion_tokens),
    }


def _record_proxy_exchange(
    session: str,
    task: str,
    kind: str,
    model: str | None,
    payload: dict,
) -> None:
    """Record a direct proxy exchange when the configured trace supports it.

    The small capability check keeps compatibility with embedders and tests
    that provide an event-only trace sink.
    """
    recorder = getattr(state.get("trace"), "record_exchange", None)
    if callable(recorder):
        recorder(session, task, kind, model, payload)


def _sse_raw(data: dict, model: str, *, include_usage: bool = False):
    """Convert a complete (non-streamed) completion — possibly containing
    tool_calls and provider-specific reasoning state — into an OpenAI-format
    SSE stream without discarding fields the client needs on its next turn."""
    cid = data.get("id") or f"chatcmpl-{uuid.uuid4().hex[:24]}"
    choice = data["choices"][0]
    msg = choice.get("message") or {}
    finish = choice.get("finish_reason") or "stop"
    created = data.get("created") or int(time.time())
    top_extensions = {
        key: value for key, value in data.items()
        if key not in {"id", "object", "created", "model", "choices", "usage"}
        and value is not None
    }
    message_extensions = {
        key: value for key, value in msg.items()
        if key not in {"role", "content", "tool_calls"} and value is not None
    }

    def chunk(delta: dict, fin: str | None = None) -> str:
        return "data: " + json.dumps({
            "id": cid, "object": "chat.completion.chunk",
            "created": created, "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": fin}],
            **top_extensions,
        }) + "\n\n"

    async def gen():
        yield chunk({"role": msg.get("role", "assistant")})
        if message_extensions:
            yield chunk(message_extensions)
        content = msg.get("content")
        if isinstance(content, str) and content:
            for i in range(0, len(content), 512):
                yield chunk({"content": content[i: i + 512]})
        elif content is not None and not isinstance(content, str):
            yield chunk({"content": content})
        if msg.get("tool_calls"):
            deltas = [{**tc, "index": i} for i, tc in enumerate(msg["tool_calls"])]
            yield chunk({"tool_calls": deltas})
        yield chunk({}, finish)
        if include_usage and data.get("usage") is not None:
            yield "data: " + json.dumps({
                "id": cid, "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [], "usage": data["usage"],
                **top_extensions,
            }) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


def _sse(text: str, model: str):
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    def chunk(delta: dict, finish: str | None = None) -> str:
        return "data: " + json.dumps(
            {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
        ) + "\n\n"

    async def gen():
        yield chunk({"role": "assistant"})
        for i in range(0, len(text), 512):
            yield chunk({"content": text[i : i + 512]})
        yield chunk({}, "stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    model_name = body.get("model", "super")
    stream = bool(body.get("stream", False))
    cfg, control = state["cfg"], state["control"]

    # A client thread may be !attach-ed onto another conversation: resolve
    # the content-derived id through the alias table before anything
    # session-scoped runs.
    raw_session = _session_id(messages)
    session = state["library"].resolve_alias(raw_session)

    # In-band control commands short-circuit everything.
    reply = handle(_last_user_text(messages), control, list(cfg.models),
                   checkpoints=state["checkpoints"],
                   session=session,
                   history=state["history"],
                   library=state["library"], raw_session=raw_session,
                   execution_backend_lock=cfg.execution.locked_backend)
    if reply is not None:
        state["trace"].record(session, "-", "control", command=_last_user_text(messages))
        return _sse(reply, model_name) if stream else JSONResponse(_completion_body(reply, model_name))

    # Pause is a no-spend ingress gate for every virtual-super request,
    # including agentic tool turns.  Explicit registry-model passthrough is
    # intentionally unaffected.  In-flight calls also check the flag at the
    # orchestrator boundary before releasing a newly generated tool call.
    if control.paused and model_name not in cfg.models:
        state["trace"].record(
            session, "-", "pause_block",
            agentic=bool(body.get("tools") or body.get("tool_choice")),
            preview=_last_user_text(messages)[:150],
        )
        return _sse(PAUSED_NOTICE, model_name) if stream else JSONResponse(
            _completion_body(PAUSED_NOTICE, model_name)
        )

    # New-conversation gate (SPEC §7): in "dumb command mode" an unknown
    # conversation's first non-command message returns a warning WITHOUT
    # calling any model; continuing (or resending) confirms. Commands above
    # always work ungated; explicit passthrough model names are exempt.
    gate_on = (control.gate_enabled if control.gate_enabled is not None
               else cfg.supervision.confirm_new_sessions)
    if (gate_on and model_name not in cfg.models
            and session not in state["armed_sessions"]
            and not state["library"].has_session(session)
            and not state["history"].recent_turns(session, 1)):
        state["armed_sessions"].add(session)
        state["trace"].record(session, "-", "gate",
                              preview=_last_user_text(messages)[:150])
        warn = gate_warning(session, control, cfg)
        return _sse(warn, model_name) if stream else JSONResponse(
            _completion_body(warn, model_name))

    state["library"].touch_session(session, _last_user_text(messages))

    # Pass-through mode for registry model names. Default max_tokens matches
    # the supervised executor path (8192): reasoning models can burn 4096
    # entirely on thought and return an EMPTY answer at the ceiling.
    if model_name in cfg.models:
        task_id = uuid.uuid4().hex[:8]
        _record_proxy_exchange(
            session, task_id, "client_request", None, body
        )
        try:
            # Explicit registry models are unsupervised passthrough, including
            # tool-carrying agent requests.  Sending those through chat()
            # would silently discard the tool definitions and tool_calls.
            if body.get("tools") or body.get("tool_choice"):
                data = await state["client"].raw_chat(cfg.model(model_name), body)
                usage = data.get("usage") or {}
                selected = cfg.model(model_name)
                state["trace"].record(
                    session, task_id, "passthrough", model=model_name,
                    tokens_in=usage.get("prompt_tokens", 0),
                    tokens_out=usage.get("completion_tokens", 0),
                    cost_usd=selected.cost(
                        usage.get("prompt_tokens", 0),
                        usage.get("completion_tokens", 0),
                    ),
                    agentic=True, governed=False,
                    safety_boundary="unsafe explicit-model passthrough",
                )
                data["model"] = model_name
                _record_proxy_exchange(
                    session, task_id, "client_response", model_name, data
                )
                if not stream:
                    return JSONResponse(data)
                include_usage = bool(
                    (body.get("stream_options") or {}).get("include_usage")
                )
                return _sse_raw(
                    data, model_name, include_usage=include_usage
                )
            res = await state["client"].chat(cfg.model(model_name), messages,
                                             max_tokens=body.get("max_tokens", 8192),
                                             temperature=body.get("temperature", 0.2))
        except ProviderError as e:
            state["trace"].record(
                session, task_id, "provider_error", model=model_name,
                error=str(e)[:300],
            )
            _record_proxy_exchange(
                session,
                task_id,
                "client_response",
                model_name,
                {"error": {"message": str(e)}},
            )
            return JSONResponse({"error": {"message": str(e)}}, status_code=502)
        data = _completion_body(res.text, model_name)
        state["trace"].record(session, task_id, "passthrough", model=model_name,
                              tokens_in=res.tokens_in, tokens_out=res.tokens_out,
                              cost_usd=res.cost_usd)
        _record_proxy_exchange(
            session, task_id, "client_response", model_name, data
        )
        return _sse(res.text, model_name) if stream else JSONResponse(data)

    # Agentic tool-carrying turns (Hermes, OpenCode, …): mid-loop tool_calls
    # pass through untouched; final text answers get monitored + verified
    # with one repair attempt (Orchestrator.run_tool_turn).
    if body.get("tools") or body.get("tool_choice"):
        try:
            data = await asyncio.wait_for(
                state["orch"].run_tool_turn(session, body),
                cfg.supervision.turn_timeout_s)
        except ProviderError as e:
            return JSONResponse({"error": {"message": str(e)}}, status_code=502)
        except asyncio.TimeoutError:
            return JSONResponse({"error": {"message": "turn timeout"}}, status_code=504)
        data["model"] = model_name
        if not stream:
            return JSONResponse(data)
        include_usage = bool(
            (body.get("stream_options") or {}).get("include_usage")
        )
        return _sse_raw(data, model_name, include_usage=include_usage)

    # Supervised mode (bounded by a hard wall-clock timeout).
    timeout = cfg.supervision.turn_timeout_s

    def render(report) -> str:
        text = report.text
        if cfg.supervision.trailer:
            text += report.trailer()
        if report.escalated and not report.text:
            text = f"[llm-super] {report.escalated}"
        return text

    if not stream:
        try:
            report = await asyncio.wait_for(
                state["orch"].run_turn(session, messages), timeout)
        except asyncio.TimeoutError:
            state["trace"].record(session, "-", "turn_timeout", timeout_s=timeout)
            return JSONResponse(_completion_body(
                f"[llm-super] turn exceeded the {timeout:.0f}s wall-clock limit "
                "and was stopped; partial work is in the trace (!status, /admin/events)",
                model_name))
        return JSONResponse(_completion_body(
            render(report), model_name,
            prompt_tokens=report.tokens_in,
            completion_tokens=report.tokens_out,
        ))

    # Streaming: long supervised turns need keepalives or clients drop the
    # connection. SSE comment lines are ignored by OpenAI-compatible clients.
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    def chunk(delta: dict, finish: str | None = None) -> str:
        return "data: " + json.dumps({
            "id": cid, "object": "chat.completion.chunk",
            "created": int(time.time()), "model": model_name,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }) + "\n\n"

    include_usage = bool(
        (body.get("stream_options") or {}).get("include_usage")
    )

    async def gen():
        task = asyncio.create_task(state["orch"].run_turn(session, messages))
        start = time.monotonic()
        report = None
        yield chunk({"role": "assistant"})
        while True:
            done, _ = await asyncio.wait({task}, timeout=15.0)
            if done:
                break
            if time.monotonic() - start > timeout:
                task.cancel()
                yield chunk({"content": f"[llm-super] turn exceeded the "
                             f"{timeout:.0f}s wall-clock limit and was stopped"})
                yield chunk({}, "stop")
                yield "data: [DONE]\n\n"
                return
            yield ": keepalive\n\n"
        try:
            report = task.result()
            text = render(report)
        except Exception as e:
            text = f"[llm-super] turn failed: {e}"
        for i in range(0, len(text), 512):
            yield chunk({"content": text[i: i + 512]})
        yield chunk({}, "stop")
        if include_usage and report is not None:
            yield "data: " + json.dumps({
                "id": cid, "object": "chat.completion.chunk",
                "created": int(time.time()), "model": model_name,
                "choices": [],
                "usage": _usage(report.tokens_in, report.tokens_out),
            }) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/v1/models")
async def models():
    cfg = state["cfg"]
    now = int(time.time())
    data = [{"id": "super", "object": "model", "created": now, "owned_by": "llm-super"}]
    data += [{"id": name, "object": "model", "created": now, "owned_by": m.provider}
             for name, m in cfg.models.items()]
    return {"object": "list", "data": data}


@app.get("/", include_in_schema=False)
async def dashboard():
    return HTMLResponse(ui.PAGE)


@app.get("/history", include_in_schema=False)
async def history_dashboard():
    """Low-noise, endeavor-oriented history UI."""
    return HTMLResponse(history_ui.PAGE)


@app.get("/graphs", include_in_schema=False)
async def graph_dashboard():
    """Declared agent architecture with live governed-run overlays."""
    return HTMLResponse(graph_ui.PAGE)


@app.get("/workspace", include_in_schema=False)
async def workspace_dashboard():
    """Unified editable conversation and per-message workflow workspace."""
    return HTMLResponse(workspace_ui.PAGE)


@app.get("/admin/graphs")
async def admin_graphs():
    runtime = state["flow_runtime"]
    declared = runtime.registry.describe()
    declared["compiled"] = {
        flow_id: runtime.compile(flow_id)
        for flow_id in runtime.registry.flows
    }
    return declared


@app.get("/admin/graphs/runs")
async def admin_graph_runs(flow_id: str | None = None, limit: int = 50):
    if flow_id and flow_id not in state["flow_runtime"].registry.flows:
        raise HTTPException(status_code=404, detail="flow not found")
    return {"items": _graph_run_context(
        state["flow_runtime"].recent_runs(flow_id, limit)
    )}


@app.get("/admin/graphs/runs/{run_id}")
async def admin_graph_run(run_id: str):
    try:
        return _graph_run_context([state["flow_runtime"].inspect(run_id)])[0]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="graph run not found") from exc


async def _workspace_contexts() -> list[dict]:
    try:
        return await _history_query("list_contexts", limit=100)
    except HTTPException as exc:
        if exc.status_code == 503:
            return []
        raise


_UNASSIGNED_ENDEAVOR_ID = "end_unassigned_history"


def _workspace_history_titles() -> dict[str, str]:
    return {
        str(item.get("session")): str(item.get("title") or "")
        for item in state["library"].sessions()
    }


def _workspace_import_session(
    endeavor_id: str, endeavor_title: str, session: str, titles: dict[str, str]
) -> None:
    store: ConversationGraphStore = state["workspace_store"]
    exchanges = state["trace"].exchanges(session=session, n=1000)
    store.import_trace_conversation(
        endeavor_id, endeavor_title, session,
        titles.get(session) or f"Conversation {session}", exchanges,
    )


def _workspace_rehome_legacy_singletons(contexts: list[dict]) -> None:
    """Move old session-shaped containers under one honest parent.

    Earlier workspace builds projected every ungrouped history conversation
    as an endeavor.  The message data remains untouched; only its derived
    workspace parent is corrected.  Empty legacy containers are retained in
    SQLite for auditability and omitted from the product navigation.
    """
    store: ConversationGraphStore = state["workspace_store"]
    synthetic_ids = {
        str(item.get("id") or "") for item in contexts
        if not item.get("explicit_grouping")
    }
    legacy = [
        item for item in store.endeavors(limit=500)
        if item["id"] in synthetic_ids and item.get("conversation_count")
    ]
    if not legacy:
        return
    store.create_endeavor(
        "Unassigned conversations", endeavor_id=_UNASSIGNED_ENDEAVOR_ID,
        status="historical",
    )
    for item in legacy:
        for conversation in store.endeavor(item["id"])["conversations"]:
            store.move_conversation(
                conversation["session"], _UNASSIGNED_ENDEAVOR_ID
            )


def _workspace_navigation(contexts: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return explicit endeavor trees and separately unassigned conversations."""
    store: ConversationGraphStore = state["workspace_store"]
    titles = _workspace_history_titles()
    synthetic_ids = {
        str(item.get("id") or "") for item in contexts
        if not item.get("explicit_grouping")
    }
    actual = []
    managed_sessions: set[str] = set()
    for item in store.endeavors(limit=500):
        detail = store.endeavor(item["id"])
        conversations = detail.get("conversations", [])
        managed_sessions.update(str(value["session"]) for value in conversations)
        if item["id"] in synthetic_ids:
            continue
        actual.append({**item, "source": "workspace", "conversations": conversations})

    merged = {item["id"]: item for item in actual}
    unassigned: list[dict] = []
    for context in contexts:
        sessions = [
            str(value) for value in context.get("conversation_ids", [])
            if str(value) not in managed_sessions
        ]
        if not sessions:
            continue
        if context.get("explicit_grouping"):
            merged[str(context["id"])] = {
                **dict(context),
                "source": "history",
                "conversations": [
                    {
                        "session": session,
                        "endeavor_id": str(context["id"]),
                        "title": titles.get(session) or f"Conversation {session}",
                        "status": "historical", "node_count": 0,
                        "updated_at": context.get("last_ts"),
                    }
                    for session in sessions
                ],
            }
        else:
            unassigned.extend({
                "session": session,
                "title": titles.get(session) or str(context.get("title") or f"Conversation {session}"),
                "status": "historical", "updated_at": context.get("last_ts"),
                "source_context_id": str(context.get("id") or ""),
            } for session in sessions)

    endeavors = sorted(
        merged.values(),
        key=lambda item: float(item.get("updated_at") or item.get("last_ts") or 0),
        reverse=True,
    )
    unassigned.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
    return endeavors, unassigned


async def _workspace_ensure_endeavor(
    endeavor_id: str, contexts: list[dict] | None = None
) -> dict:
    """Import one selected history container into the editable projection."""
    store: ConversationGraphStore = state["workspace_store"]
    contexts = contexts if contexts is not None else await _workspace_contexts()
    context = next((item for item in contexts if item["id"] == endeavor_id), None)
    try:
        existing = store.endeavor(endeavor_id)
    except KeyError:
        existing = None
    if context is None:
        if existing is None:
            raise HTTPException(status_code=404, detail="endeavor not found")
        return existing
    titles = _workspace_history_titles()
    target_id = endeavor_id
    target_title = str(context["title"])
    for session in context.get("conversation_ids", []):
        try:
            managed = store.conversation(str(session))
        except KeyError:
            continue
        target_id = managed["endeavor_id"]
        target_title = store.endeavor(target_id)["title"]
        break
    if not context.get("explicit_grouping"):
        target_id = _UNASSIGNED_ENDEAVOR_ID
        target_title = "Unassigned conversations"
    for session in context.get("conversation_ids", []):
        try:
            store.conversation(str(session))
        except KeyError:
            _workspace_import_session(
                target_id, target_title, str(session), titles
            )
    return store.endeavor(target_id)


async def _workspace_import_unassigned(
    session: str, contexts: list[dict]
) -> dict:
    context = next(
        (item for item in contexts
         if not item.get("explicit_grouping")
         and session in [str(value) for value in item.get("conversation_ids", [])]),
        None,
    )
    if context is None:
        raise HTTPException(status_code=404, detail="archived conversation not found")
    _workspace_import_session(
        _UNASSIGNED_ENDEAVOR_ID, "Unassigned conversations", session,
        _workspace_history_titles(),
    )
    return state["workspace_store"].endeavor(_UNASSIGNED_ENDEAVOR_ID)


def _workspace_graph(session: str) -> dict:
    """Project a conversation together with only its pending decisions."""
    store: ConversationGraphStore = state["workspace_store"]
    graph = store.graph(session)
    for workflow in graph.get("workflows", []):
        workflow["execution_summary"] = _workspace_workflow_execution(
            workflow["instance_id"], include_payloads=False
        )
    action_store = state.get("action_store")
    if action_store is None:
        graph["pending_actions"] = []
        return graph
    nodes_by_task = {
        str((node.get("config") or {}).get("task_id") or ""): node["node_id"]
        for node in graph["nodes"]
        if (node.get("config") or {}).get("task_id")
    }
    pending = []
    for action in action_store.list(status="human_pending", limit=100):
        if str(action.get("session") or "") != session:
            continue
        projected = _public_action(action)
        projected["workspace_node_id"] = nodes_by_task.get(
            str(action.get("task") or "")
        )
        pending.append(projected)
    graph["pending_actions"] = pending
    return graph


def _workspace_stage_for_event(workflow: dict, kind: str,
                               data: dict | None = None) -> str | None:
    """Project legacy trace vocabulary onto the declared workflow graph."""
    nodes = workflow.get("graph", {}).get("nodes", [])
    data = data or {}

    def first(*types: str, ids: tuple[str, ...] = ()) -> str | None:
        return next((node["id"] for node in nodes
                     if node.get("id") in ids or node.get("type") in types), None)

    if kind.startswith("ensemble_") or data.get("ensemble"):
        return first("ensemble", "agent")
    if kind.startswith("soundness_"):
        return first("checker", ids=("soundness_checker",))
    if kind in {"action_critic", "critic_review", "critic_error"}:
        return first("critic", ids=("action_critic",))
    if kind in {"execute", "executor_fallback", "synthesis", "unit_done",
                "wave_start", "repair_requested"}:
        return first("agent")
    if kind in {"verify", "verify_error", "ensemble_fusion_rejected"}:
        return first("verifier", "checker")
    if kind in {"tool_step", "tool_result"}:
        return first("tool")
    if kind in {"policy", "risk_assessment", "contract", "contract_failed",
                "contract_skipped", "plan", "difficulty_route", "fm_event"}:
        return first("ingress", "policy")
    if kind in {"turn_start", "resume", "operator_guidance_added"}:
        return first("ingress")
    if kind == "turn_end":
        return first("terminal", ids=("completed", "job_complete"))
    return None


def _workspace_runtime_run(workflow: dict, session: str,
                           task: str) -> dict | None:
    runtime = state.get("flow_runtime")
    recent = getattr(runtime, "recent_runs", None)
    inspect = getattr(runtime, "inspect", None)
    if not callable(recent) or not callable(inspect) or not task:
        return None
    try:
        candidates = recent(workflow.get("flow_id"), 200)
        match = next((item for item in candidates
                      if str(item.get("session") or "") == session
                      and str(item.get("task") or "") == task), None)
        return inspect(match["run_id"]) if match else None
    except (KeyError, TypeError, ValueError):
        return None


def _workspace_workflow_execution(instance_id: str, *,
                                  include_payloads: bool) -> dict:
    """Join a message workflow definition to its actual run and LLM exchanges."""
    store: ConversationGraphStore = state["workspace_store"]
    workflow = store.workflow(instance_id)
    owner = store.node(workflow["owner_node_id"])
    session = str(owner.get("session") or "")
    task = str((owner.get("config") or {}).get("task_id")
               or owner.get("run_id") or "")
    trace = state.get("trace")
    trace_events = (
        trace.task_events(session, task, n=1000)
        if trace is not None and task and hasattr(trace, "task_events") else []
    )
    projected = []
    for event in trace_events:
        stage_id = _workspace_stage_for_event(
            workflow, str(event.get("kind") or ""), event.get("data") or {}
        )
        projected.append({**event, "node_id": stage_id})

    run = _workspace_runtime_run(workflow, session, task)
    runtime_events = list((run or {}).get("events") or [])
    route_events = runtime_events or [event for event in projected if event["node_id"]]
    observed_sequence = [str(event.get("node_id") or "") for event in route_events
                         if event.get("node_id")]
    observed_transitions = [
        {"source": before, "target": after}
        for before, after in zip(observed_sequence, observed_sequence[1:])
        if before != after
    ]

    exchange_count = 0
    upstream_count = 0
    if trace is not None and task:
        try:
            exchange_count, upstream_count = trace.connection.execute(
                """SELECT COUNT(*),COALESCE(SUM(kind='upstream'),0)
                     FROM exchanges WHERE session=? AND task=?""",
                (session, task),
            ).fetchone()
        except (AttributeError, TypeError):
            pass
    exchanges = (
        trace.exchanges(task=task, session=session, n=500)
        if include_payloads and trace is not None and task else []
    )
    upstream = [item for item in exchanges if item.get("kind") == "upstream"]
    model_events = [event for event in projected
                    if event.get("model") or event.get("tokens_in")
                    or event.get("tokens_out")]
    used_event_ids: set[int] = set()
    model_steps = []
    for index, exchange in enumerate(upstream):
        model = str(exchange.get("model") or "")
        eligible = [event for event in model_events
                    if int(event.get("id") or 0) not in used_event_ids
                    and float(event.get("ts") or 0) >= float(exchange.get("ts") or 0)
                    and (not model or not event.get("model")
                         or str(event.get("model")) == model)]
        matched = min(eligible, key=lambda event: float(event.get("ts") or 0),
                      default=None)
        if matched:
            used_event_ids.add(int(matched.get("id") or 0))
        payload = exchange.get("payload") if isinstance(exchange.get("payload"), dict) else {}
        stage_id = (matched or {}).get("node_id") or _workspace_stage_for_event(
            workflow, str((matched or {}).get("kind") or "execute"),
            (matched or {}).get("data") or {},
        )
        model_steps.append({
            "id": str(exchange.get("id") or index + 1),
            "ts": exchange.get("ts"),
            "node_id": stage_id,
            "kind": (matched or {}).get("kind") or "model_exchange",
            "model": model or (matched or {}).get("model") or "routed model",
            "tokens_in": int((matched or {}).get("tokens_in") or 0),
            "tokens_out": int((matched or {}).get("tokens_out") or 0),
            "cost_usd": float((matched or {}).get("cost_usd") or 0),
            "configuration": (matched or {}).get("data") or {},
            "input": payload.get("request", payload),
            "output": payload.get("response", {}),
        })

    result = {
        "instance_id": instance_id,
        "task_id": task,
        "run_id": (run or {}).get("run_id"),
        "status": (run or {}).get("status") or workflow.get("status") or "idle",
        "current_node": (run or {}).get("current_node") or workflow.get("active_node"),
        "observed_sequence": observed_sequence,
        "observed_nodes": list(dict.fromkeys(observed_sequence)),
        "observed_transitions": observed_transitions,
        "runtime_event_count": len(runtime_events),
        "trace_event_count": len(trace_events),
        "model_step_count": int(upstream_count or len(upstream)),
        "exchange_count": int(exchange_count),
    }
    if include_payloads:
        result.update({
            "run": run,
            "runtime_events": runtime_events,
            "trace_events": projected,
            "model_steps": model_steps,
            "client_exchanges": [item for item in exchanges
                                 if item.get("kind") != "upstream"],
        })
    return result


@app.get("/admin/workspace/bootstrap")
async def admin_workspace_bootstrap(
    endeavor_id: str | None = None, conversation_id: str | None = None,
    history_conversation_id: str | None = None,
):
    store: ConversationGraphStore = state["workspace_store"]
    contexts = await _workspace_contexts()
    _workspace_rehome_legacy_singletons(contexts)
    endeavors, unassigned = _workspace_navigation(contexts)
    if history_conversation_id:
        endeavor = await _workspace_import_unassigned(
            history_conversation_id, contexts
        )
        selected_id = endeavor["id"]
        conversation_id = history_conversation_id
    elif conversation_id:
        try:
            selected_id = store.conversation(conversation_id)["endeavor_id"]
            endeavor = store.endeavor(selected_id)
        except KeyError:
            context = next(
                (item for item in contexts
                 if conversation_id in [str(value) for value in item.get("conversation_ids", [])]),
                None,
            )
            if context is None:
                raise HTTPException(status_code=404, detail="conversation not found")
            endeavor = await _workspace_ensure_endeavor(str(context["id"]), contexts)
            selected_id = endeavor["id"]
    elif endeavor_id:
        endeavor = await _workspace_ensure_endeavor(endeavor_id, contexts)
        selected_id = endeavor["id"]
    elif endeavors:
        endeavor = await _workspace_ensure_endeavor(endeavors[0]["id"], contexts)
        selected_id = endeavor["id"]
    elif unassigned:
        conversation_id = unassigned[0]["session"]
        endeavor = await _workspace_import_unassigned(conversation_id, contexts)
        selected_id = endeavor["id"]
    else:
        created = store.create_endeavor("My first endeavor")
        store.create_conversation(created["id"], "New conversation")
        selected_id = created["id"]
        endeavor = store.endeavor(selected_id)
    conversations = endeavor.get("conversations") or []
    if not conversations:
        created = store.create_conversation(selected_id, "New conversation")
        conversations = [created]
        endeavor = store.endeavor(selected_id)
    selected_conversation = conversation_id or conversations[0]["session"]
    try:
        graph = _workspace_graph(selected_conversation)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="conversation is not in the selected endeavor"
        ) from exc
    endeavors, unassigned = _workspace_navigation(contexts)
    cfg = state["cfg"]
    execution = cfg.execution
    execution_lock = {
        "backend": execution.locked_backend,
        "agent_selectable": False,
        "local_workload_spawn": False,
    }
    if hasattr(execution, "gcloud_zone"):
        execution_lock.update({
            "target": {
                "project": execution.gcloud_project or "active gcloud project",
                "account": execution.gcloud_account or "active gcloud account",
                "zone": execution.gcloud_zone,
                "machine_type": execution.gcloud_machine_type,
            },
            "provisioning": "Spot",
            "lifecycle": "ephemeral · delete after execution",
            "configuration_source": str(getattr(cfg, "path", "models.yaml")),
        })
    registry_description = state["flow_runtime"].registry.describe()
    return {
        "endeavors": endeavors,
        "unassigned_conversations": unassigned,
        "graph": graph,
        "models": [
            {"id": name, "family": model.family, "roles": list(model.roles)}
            for name, model in cfg.models.items()
        ],
        "flows": registry_description["flows"],
        "agents": registry_description["agents"],
        "execution_lock": execution_lock,
    }


@app.get("/admin/workspace/conversations/{session}")
async def admin_workspace_conversation(session: str):
    try:
        return _workspace_graph(session)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/admin/workspace/workflows/{instance_id}/execution")
async def admin_workspace_workflow_execution(instance_id: str):
    """Full, on-demand run evidence for one assistant-message workflow."""
    try:
        return _workspace_workflow_execution(instance_id, include_payloads=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="workflow instance not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/admin/workspace/endeavors")
async def admin_workspace_create_endeavor(request: Request):
    body = await request.json()
    try:
        store: ConversationGraphStore = state["workspace_store"]
        endeavor = store.create_endeavor(str(body.get("title") or ""))
        if body.get("create_conversation"):
            endeavor["conversation"] = store.create_conversation(
                endeavor["id"], str(body.get("conversation_title") or "")
            )
        return endeavor
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/admin/workspace/endeavors/{endeavor_id}")
async def admin_workspace_rename_endeavor(endeavor_id: str, request: Request):
    body = await request.json()
    try:
        return state["workspace_store"].rename_endeavor(
            endeavor_id, str(body.get("title") or "")
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="endeavor not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/admin/workspace/endeavors/{endeavor_id}/conversations")
async def admin_workspace_create_conversation(endeavor_id: str, request: Request):
    body = await request.json()
    try:
        return state["workspace_store"].create_conversation(
            endeavor_id, str(body.get("title") or "")
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="endeavor not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/admin/workspace/conversations/{session}")
async def admin_workspace_rename_conversation(session: str, request: Request):
    body = await request.json()
    try:
        conversation = state["workspace_store"].rename_conversation(
            session, str(body.get("title") or "")
        )
        library = state.get("library")
        if library is not None:
            library.set_session_title(session, conversation["title"])
        return conversation
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/admin/workspace/conversations/{session}/messages", status_code=202)
async def admin_workspace_send_message(session: str, request: Request):
    body = await request.json()
    try:
        return state["workspace_service"].send(
            session, str(body.get("content") or ""),
            parent_id=body.get("parent_id"),
            flow_id=str(body.get("flow_id") or "supervised_tool_turn"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="conversation or workflow not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/admin/workspace/conversations/{session}/nodes")
async def admin_workspace_add_conversation_node(session: str, request: Request):
    body = await request.json()
    try:
        return state["workspace_store"].add_node(
            session, kind=str(body.get("kind") or "context"),
            label=str(body.get("label") or "Context"),
            input_text=str(body.get("input_text") or ""),
            parent_id=body.get("parent_id"), target_id=body.get("target_id"),
            config=body.get("config") or {},
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="conversation or node not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/admin/workspace/nodes/{node_id}")
async def admin_workspace_edit_node(node_id: str, request: Request):
    body = await request.json()
    auto = bool(body.pop("auto_recalculate", True))
    try:
        return state["workspace_service"].edit_node(
            node_id, body, auto_recalculate=auto
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="node not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/admin/workspace/nodes/{node_id}/revisions")
async def admin_workspace_node_revisions(node_id: str):
    try:
        return {"items": state["workspace_store"].revisions(node_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/admin/workspace/nodes/{node_id}/pause")
async def admin_workspace_pause_node(node_id: str):
    try:
        return state["workspace_service"].pause(node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="node not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/admin/workspace/nodes/{node_id}/resume", status_code=202)
async def admin_workspace_resume_node(node_id: str):
    try:
        return state["workspace_service"].resume(node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="node not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/admin/workspace/nodes/{node_id}/recalculate", status_code=202)
async def admin_workspace_recalculate_node(node_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        return state["workspace_service"].recalculate(
            node_id, include_root=bool(body.get("include_root", False))
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="node not found") from exc


@app.post("/admin/workspace/workflows/{instance_id}/nodes")
async def admin_workspace_add_workflow_node(instance_id: str, request: Request):
    body = await request.json()
    try:
        return state["workspace_store"].add_workflow_node(
            instance_id, node_type=str(body.get("type") or "context"),
            label=str(body.get("label") or "Workflow node"),
            after_node_id=str(body.get("after_node_id") or ""),
            config=body.get("config") or {},
            apply_globally=bool(body.get("apply_globally", False)),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="workflow or node not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/admin/workspace/workflows/{instance_id}/nodes/{node_id}")
async def admin_workspace_edit_workflow_node(
    instance_id: str, node_id: str, request: Request
):
    body = await request.json()
    apply_globally = bool(body.pop("apply_globally", False))
    try:
        return state["workspace_store"].update_workflow_node(
            instance_id, node_id, body, apply_globally=apply_globally
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="workflow or node not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/admin/workspace/workflows/{instance_id}/nodes/{node_id}")
async def admin_workspace_delete_workflow_node(
    instance_id: str, node_id: str, request: Request
):
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        return state["workspace_store"].delete_workflow_node(
            instance_id, node_id,
            apply_globally=bool(body.get("apply_globally", False)),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="workflow or node not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/admin/workspace/stores")
async def admin_workspace_stores():
    return {"items": state["workspace_store"].stores()}


@app.post("/admin/workspace/stores")
async def admin_workspace_create_store(request: Request):
    body = await request.json()
    try:
        return state["workspace_store"].create_store(
            str(body.get("name") or ""),
            description=str(body.get("description") or ""),
            adapter=str(body.get("adapter") or "sqlite-vector"),
            connection_ref=str(body.get("connection_ref") or "local"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/admin/workspace/stores/{store_id}/records")
async def admin_workspace_store_record(store_id: str, request: Request):
    body = await request.json()
    try:
        return state["workspace_store"].save_record(
            store_id, str(body.get("text") or ""),
            source_node_id=body.get("source_node_id"),
            metadata=body.get("metadata") or {},
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="store not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/admin/workspace/stores/{store_id}/query")
async def admin_workspace_query_store(store_id: str, request: Request):
    body = await request.json()
    try:
        return {"items": state["workspace_store"].query_store(
            store_id, str(body.get("query") or ""),
            top_k=int(body.get("top_k", 5)),
            query_prompt=str(body.get("query_prompt") or ""),
        )}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="store not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _graph_run_context(items: list[dict]) -> list[dict]:
    """Add human-facing provenance without exposing raw conversation payloads."""
    titles: dict[str, str] = {}
    library = state.get("library")
    if library is not None:
        try:
            titles = {
                str(row.get("session")): str(row.get("title") or "")
                for row in library.sessions()
            }
        except (AttributeError, TypeError):
            titles = {}
    for item in items:
        run_input = item.get("input") if isinstance(item.get("input"), dict) else {}
        task_label = str(
            run_input.get("goal") or run_input.get("label")
            or item.get("task") or item.get("run_id") or "Task run"
        )
        session = str(item.get("session") or "-")
        conversation_title = titles.get(session, "")
        item["task_label"] = task_label
        item["conversation_title"] = conversation_title or f"Conversation {session}"
    return items


@app.get("/admin/jobs")
async def admin_jobs(status: str | None = None, limit: int = 100):
    """Low-noise durable workload projection for the graph studio."""
    return {
        "items": state["job_store"].list(state=status, limit=limit),
        "execution_lock": {
            "backend": state["cfg"].execution.locked_backend,
            "agent_selectable": False,
            "local_workload_spawn": False,
        },
    }


@app.get("/admin/jobs/{job_id}")
async def admin_job(job_id: str):
    try:
        item = state["job_store"].get(job_id)
        item["events"] = state["job_store"].events(job_id, limit=300)
        return item
    except ExecutionBoundaryError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@app.get("/admin/jobs/{job_id}/events")
async def admin_job_events(job_id: str, after: int = 0, limit: int = 200):
    try:
        return {"items": state["job_store"].events(
            job_id, after=after, limit=limit
        )}
    except ExecutionBoundaryError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


def _public_action(item: dict) -> dict:
    """Graph-studio projection: exact call/policy, never the full model response."""
    projected = {
        key: value for key, value in item.items()
        if key not in {"response", "manifest"}
    } | {
        "manifest": {
            key: value for key, value in (item.get("manifest") or {}).items()
            if key != "parameters"
        }
    }
    projected["soundness_checks"] = state["action_store"].soundness_checks(
        action_id=str(item.get("action_id", "")), limit=10,
    )
    return projected


def _resolve_action_decision(action_id: str, decision: str, note: str) -> dict:
    action = state["action_store"].decide(action_id, decision, note)
    runtime = state["flow_runtime"]
    if decision == "approve":
        runtime.resume(action["run_id"], {
            "human_decision": "approve", "action_id": action_id,
        })
    else:
        runtime.transition(
            action["run_id"], "blocked", "human_action_denied",
            status="blocked", summary=note or "Operator denied the action",
            verdict="deny",
        )
    state["trace"].record(
        action["session"], action["task"], "human_approval_resolved",
        graph_id="supervised_tool_turn", graph_run_id=action["run_id"],
        node_id="human_approval", action_id=action_id,
        verdict=decision, note=note[:500],
    )
    return state["action_store"].get(action_id) or action


@app.get("/admin/actions")
async def admin_actions(status: str | None = None, limit: int = 100):
    return {"items": [
        _public_action(item)
        for item in state["action_store"].list(status=status, limit=limit)
    ]}


@app.post("/admin/actions/{action_id}/decision")
async def admin_action_decision(action_id: str, request: Request):
    body = await request.json()
    decision = str(body.get("decision", ""))
    note = str(body.get("note", ""))
    try:
        action = _resolve_action_decision(action_id, decision, note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="action not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _public_action(action)


@app.post("/admin/workspace/actions/{action_id}/decision", status_code=202)
async def admin_workspace_action_decision(action_id: str, request: Request):
    """Resolve an inline approval and automatically continue its message."""
    body = await request.json()
    decision = str(body.get("decision", ""))
    note = str(body.get("note", ""))
    before = state["action_store"].get(action_id)
    if before is None:
        raise HTTPException(status_code=404, detail="action not found")
    workspace_node = next(
        (
            node for node in state["workspace_store"].nodes(before["session"])
            if node.get("role") == "assistant"
            and str((node.get("config") or {}).get("task_id") or "")
            == str(before.get("task") or "")
        ),
        None,
    )
    try:
        action = _resolve_action_decision(action_id, decision, note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="action not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    continuation = None
    if workspace_node is not None:
        continuation = state["workspace_service"].resume(
            workspace_node["node_id"]
        )
    return {
        "action": _public_action(action),
        "workspace_node_id": workspace_node["node_id"] if workspace_node else None,
        "continuation": continuation,
    }


async def _history_query(method: str, *args, **kwargs):
    """Run one scoped projection against a short-lived read-only connection.

    The rest of the proxy owns several long-lived SQLite handles. History is
    intentionally isolated from them: no migration, no shared connection
    across worker threads, and no cumulative raw payloads unless the caller
    selects ``raw_exchange`` explicitly.
    """
    trace_path = state.get("trace_path", "traces.db")

    def query():
        with HistoryView(trace_path) as view:
            return getattr(view, method)(*args, **kwargs)

    try:
        return await asyncio.to_thread(query)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="history item not found") from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="history database unavailable") from exc


@app.get("/admin/history/endeavors")
async def admin_history_endeavors(
    project: str | None = None,
    status: str | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
):
    return await _history_query(
        "list_endeavors", project_id=project, status=status, query=q,
        cursor=cursor, limit=limit,
    )


@app.get("/admin/history/sessions/{session}/context")
async def admin_history_session_context(session: str):
    """Map one conversation to its containing endeavor without a global scan."""
    return await _history_query("session_context", session)


@app.get("/admin/history/endeavors/{endeavor_id}")
async def admin_history_endeavor(endeavor_id: str):
    return await _history_query("get_endeavor", endeavor_id)


@app.get("/admin/history/endeavors/{endeavor_id}/runs")
async def admin_history_runs(
    endeavor_id: str, cursor: str | None = None, limit: int = 50,
):
    return await _history_query(
        "list_runs", endeavor_id, cursor=cursor, limit=limit,
    )


@app.get("/admin/history/endeavors/{endeavor_id}/timeline")
async def admin_history_timeline(
    endeavor_id: str,
    routine: str = "collapse",
    cursor: str | None = None,
    limit: int = 50,
):
    if routine not in {"collapse", "all"}:
        raise HTTPException(
            status_code=400, detail="routine must be 'collapse' or 'all'"
        )
    return await _history_query(
        "timeline", endeavor_id, cursor=cursor, limit=limit,
        collapse_polling=routine == "collapse",
    )


@app.get("/admin/history/exchanges/{exchange_id}/raw")
async def admin_history_raw_exchange(exchange_id: int, response: Response):
    """Explicit, one-row raw drill-down; summary endpoints never call this."""
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return await _history_query("raw_exchange", exchange_id)


@app.get("/admin/status")
async def admin_status():
    c: ControlState = state["control"]
    recent = state["trace"].recent(200)
    return {
        "paused": c.paused,
        "forced_executor": c.forced_executor,
        "budget_usd": c.budget_usd,
        "checklist": ("off" if not c.contract_enabled
                      else "skip" if c.contract_skip_once else "on"),
        "sandbox": c.sandbox_backend or "auto",
        "execution_lock": state["cfg"].execution.locked_backend,
        "plan": c.plan_mode,
        "ensemble": c.ensemble_n,
        "strategy": c.strategy,
        "cutoff": c.cutoff,
        "gate": (c.gate_enabled if c.gate_enabled is not None
                 else state["cfg"].supervision.confirm_new_sessions),
        "breakpoints": list(c.breakpoints),
        "models": list(state["cfg"].models),
        "recent_spend": round(sum(e.get("cost_usd") or 0 for e in recent), 4),
        "recent_commands": c.history[-10:],
    }


@app.post("/admin/control")
async def admin_control(request: Request):
    """Steering from the dashboard — same semantics as the in-band !commands."""
    body = await request.json()
    c: ControlState = state["control"]
    field, value = body.get("field"), body.get("value")
    if field == "paused":
        c.paused = bool(value)
    elif field == "executor":
        c.forced_executor = value if value in state["cfg"].models else None
    elif field == "budget":
        try:
            c.budget_usd = float(value) if value not in ("", None) else None
        except ValueError:
            return JSONResponse({"error": f"bad budget {value!r}"}, status_code=400)
    elif field == "checklist":
        c.contract_enabled = value != "off"
        c.contract_skip_once = value == "skip"
    elif field == "sandbox":
        lock = state["cfg"].execution.locked_backend
        if lock and value not in ("auto", "off", lock):
            return JSONResponse(
                {"error": f"execution backend is operator-locked to {lock}"},
                status_code=409,
            )
        c.sandbox_backend = None if value == "auto" else value
    elif field == "plan":
        if value in ("auto", "on", "off"):
            c.plan_mode = value
    elif field == "ensemble":
        try:
            n = int(value or 0)
        except (TypeError, ValueError):
            return JSONResponse({"error": f"bad ensemble {value!r}"}, status_code=400)
        if n != 0 and not 2 <= n <= 4:
            return JSONResponse({"error": "ensemble must be 0 (off) or 2-4"},
                                status_code=400)
        c.ensemble_n = n
        if n and c.strategy not in ("best", "union", "fuse"):
            c.strategy = "fuse"
        if not n and c.strategy in ("best", "union", "fuse"):
            c.strategy = "single"
    elif field == "strategy":
        if value not in ("single", "exploit", "best", "union", "fuse"):
            return JSONResponse({"error": f"bad strategy {value!r}"}, status_code=400)
        c.strategy = value
        if value in ("single", "exploit"):
            c.ensemble_n = 0
        elif c.ensemble_n < 2:
            c.ensemble_n = 3
    elif field == "cutoff":
        if value in ("", None, "off"):
            c.cutoff = None
        else:
            try:
                v = float(value)
            except (TypeError, ValueError):
                return JSONResponse({"error": f"bad cutoff {value!r}"}, status_code=400)
            if not 0 < v <= 1:
                return JSONResponse({"error": "cutoff must be in (0, 1]"},
                                    status_code=400)
            c.cutoff = v
    elif field == "break_add":
        rule = str(value or "").strip()
        valid = (rule == "escalation"
                 or (rule.startswith("fm:") and len(rule) > 3)
                 or rule.startswith("budget:"))
        if rule.startswith("budget:"):
            try:
                float(rule[7:])
            except ValueError:
                valid = False
        if not valid:
            return JSONResponse({"error": f"bad breakpoint rule {rule!r}"},
                                status_code=400)
        if rule not in c.breakpoints:
            c.breakpoints.append(rule)
    elif field == "break_clear":
        if value:
            if value in c.breakpoints:
                c.breakpoints.remove(value)
        else:
            c.breakpoints.clear()
    else:
        return JSONResponse({"error": f"unknown field {field!r}"}, status_code=400)
    state["trace"].record("-", "-", "control", command=f"ui:{field}={value}")
    return await admin_status()


@app.get("/admin/routing")
async def admin_routing():
    cfg = state["cfg"]
    return {
        "settings": {
            "default_executor": cfg.default_executor,
            "utility": cfg.utility,
            "referee": cfg.referee,
            "trivial_executor": cfg.trivial_executor,
            "learned_routing": cfg.learned_routing,
            "min_routing_samples": cfg.min_routing_samples,
            "verifier_pool": list(cfg.verifier_pool),
        },
        "models": {name: {"roles": list(m.roles), "family": m.family,
                          "logprobs": m.logprobs, "provider": m.provider,
                          "fallbacks": list(m.fallbacks)}
                   for name, m in cfg.models.items()},
    }


@app.post("/admin/routing")
async def admin_routing_set(request: Request):
    """Runtime routing overrides from the dashboard. In-memory only:
    models.yaml stays the on-disk source of truth (a restart reloads it)."""
    b = await request.json()
    cfg = state["cfg"]
    for key, value in (b.get("patch") or {}).items():
        if key in ("default_executor", "utility", "referee", "trivial_executor"):
            # referee/trivial_executor may be unset (referee then falls back
            # to the default executor; trivial turns keep normal routing)
            if value == "" and key in ("referee", "trivial_executor"):
                setattr(cfg, key, "")
            elif value not in cfg.models:
                return JSONResponse({"error": f"unknown model {value!r}"},
                                    status_code=400)
            else:
                setattr(cfg, key, value)
        elif key == "learned_routing":
            cfg.learned_routing = bool(value)
        elif key == "min_routing_samples":
            try:
                cfg.min_routing_samples = max(1, int(value))
            except (TypeError, ValueError):
                return JSONResponse({"error": f"bad min_samples {value!r}"},
                                    status_code=400)
        elif key == "verifier_pool":
            names = [str(v) for v in value] if isinstance(value, list) else []
            bad = [n for n in names if n not in cfg.models]
            if bad or not names:
                return JSONResponse(
                    {"error": f"unknown models in pool: {', '.join(bad) or '(empty)'}"},
                    status_code=400)
            cfg.verifier_pool = names
        elif key == "fallbacks":
            # value: {model_name: [ordered fallback names]} — the model's
            # provider-rotation order (model itself always runs first)
            if not isinstance(value, dict):
                return JSONResponse({"error": "fallbacks must be a mapping"},
                                    status_code=400)
            try:
                for mname, chain in value.items():
                    if mname not in cfg.models:
                        raise ValueError(f"unknown model {mname!r}")
                    if not isinstance(chain, list):
                        raise ValueError(f"chain for {mname!r} must be a list")
                    cfg.set_fallbacks(mname, [str(x) for x in chain])
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
        else:
            return JSONResponse({"error": f"unknown field {key!r}"},
                                status_code=400)
        state["trace"].record("-", "-", "control", command=f"ui:routing.{key}={value}")
    return await admin_routing()


@app.get("/admin/events")
async def admin_events(n: int = 50):
    return state["trace"].recent(n)


@app.get("/admin/stats")
async def admin_stats():
    """Per-model outcome stats (feeds learned routing)."""
    return state["history"].stats()


@app.get("/admin/edits")
async def admin_edits(session: str):
    """Edit/rewind history for a conversation (branch divergences)."""
    return state["history"].edits(session)


@app.get("/admin/balance")
async def admin_balance():
    """Load balancing: per-provider window usage vs declared limits, plus
    live circuit-breaker state."""
    usage = await asyncio.to_thread(
        balance_mod.provider_usage, state["trace_path"], state["cfg"])
    return {"providers": usage, "breakers": state["client"].breaker_status()}


@app.get("/admin/report")
async def admin_report(days: float = 30.0):
    """Efficiency report (SPEC §8): spend by role, repair vs first-pass,
    plus learned repair-success priors."""
    rep = await asyncio.to_thread(report_mod.efficiency, state["trace_path"], days)
    rep["repair_stats"] = state["history"].repair_stats()
    return rep


@app.get("/admin/messages")
async def admin_messages(task: str | None = None, session: str | None = None,
                         n: int = 100):
    """Full message payloads — every client and upstream exchange."""
    return state["trace"].exchanges(task=task, session=session, n=n)


# ---- conversation library: projects, sessions, settings, export ----

@app.get("/admin/library")
async def admin_library():
    lib: Library = state["library"]
    return {
        "projects": lib.projects(),
        "sessions": lib.sessions(),
        "default_settings": lib.global_default(),
        "settings_schema": {k: type(v).__name__ for k, v in DEFAULT_SETTINGS.items()},
    }


@app.get("/admin/project/{pid}/settings")
async def admin_project_settings(pid: str):
    """Resolved settings with per-field source (inherited vs overridden)."""
    return state["library"].resolved_settings(pid)


@app.post("/admin/library")
async def admin_library_action(request: Request):
    lib: Library = state["library"]
    b = await request.json()
    action = b.get("action")
    try:
        if action == "create_project":
            return {"id": lib.create_project(b["name"])}
        if action == "rename_project":
            lib.rename_project(b["id"], b["name"]); return {"ok": True}
        if action == "delete_project":
            lib.delete_project(b["id"]); return {"ok": True}
        if action == "assign_session":
            lib.set_session_project(b["session"], b["project_id"]); return {"ok": True}
        if action == "rename_session":
            lib.set_session_title(b["session"], b["title"]); return {"ok": True}
        if action == "delete_session":
            lib.delete_session(b["session"]); return {"ok": True}
        if action == "set_default":
            lib.set_global_default(b["patch"]); return {"ok": True}
        if action == "set_project_override":
            lib.set_project_override(b["id"], b["key"], b["value"]); return {"ok": True}
        if action == "clear_project_override":
            lib.clear_project_override(b["id"], b["key"]); return {"ok": True}
    except (KeyError, ValueError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"error": f"unknown action {action!r}"}, status_code=400)


@app.get("/admin/retention")
async def admin_retention():
    return {
        "settings": state["library"].retention_settings(),
        "stats": retention.stats(state["trace_path"]),
    }


@app.post("/admin/retention")
async def admin_retention_set(request: Request):
    b = await request.json()
    state["library"].set_retention(b.get("patch", {}))
    return await admin_retention()


@app.post("/admin/prune")
async def admin_prune():
    report = await asyncio.to_thread(
        retention.prune, state["trace_path"], state["library"].retention_settings())
    state["trace"].record("-", "-", "retention_prune", **report["deleted"],
                          reclaimed_bytes=report["reclaimed_bytes"])
    return report


@app.post("/admin/export")
async def admin_export(request: Request):
    b = await request.json()
    try:
        result = await asyncio.to_thread(
            export_mod.export, state["trace"], state["library"],
            session=b.get("session"), project_id=b.get("project_id"),
            passphrase=b.get("passphrase"))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return result


@app.post("/admin/pause")
async def admin_pause():
    state["control"].paused = True
    return {"paused": True}


@app.post("/admin/resume")
async def admin_resume():
    state["control"].paused = False
    return {"paused": False}
