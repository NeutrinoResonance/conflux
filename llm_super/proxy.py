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

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from . import ui

from . import balance as balance_mod
from . import export as export_mod
from . import report as report_mod
from . import retention
from .checkpoint import Checkpoints
from .config import load
from .control import ControlState, handle
from .history import History
from .library import DEFAULT_SETTINGS, Library
from .orchestrator import Orchestrator, _last_user_text
from .providers import Client, ProviderError  # noqa: F401 (ProviderError used below)
from .trace import Trace

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load(state.get("config_path", "models.yaml"))
    client = Client(cfg)
    trace_path = state.get("trace_path", "traces.db")
    trace = Trace(trace_path)
    control = ControlState()
    history = History(trace_path)
    library = Library(trace_path)
    checkpoints = Checkpoints(trace_path)
    state.update(
        cfg=cfg,
        client=client,
        trace=trace,
        control=control,
        history=history,
        library=library,
        trace_path=trace_path,
        checkpoints=checkpoints,
        orch=Orchestrator(cfg, client, trace, control,
                          checkpoints=checkpoints,
                          history=history),
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


def _completion_body(text: str, model: str) -> dict:
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
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _sse_raw(data: dict, model: str):
    """Convert a complete (non-streamed) completion — possibly containing
    tool_calls — into a minimal OpenAI-format SSE stream."""
    cid = data.get("id") or f"chatcmpl-{uuid.uuid4().hex[:24]}"
    choice = data["choices"][0]
    msg = choice.get("message") or {}
    finish = choice.get("finish_reason") or "stop"

    def chunk(delta: dict, fin: str | None = None) -> str:
        return "data: " + json.dumps({
            "id": cid, "object": "chat.completion.chunk",
            "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": fin}],
        }) + "\n\n"

    async def gen():
        yield chunk({"role": "assistant"})
        if msg.get("content"):
            for i in range(0, len(msg["content"]), 512):
                yield chunk({"content": msg["content"][i: i + 512]})
        if msg.get("tool_calls"):
            deltas = [{**tc, "index": i} for i, tc in enumerate(msg["tool_calls"])]
            yield chunk({"tool_calls": deltas})
        yield chunk({}, finish)
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

    # In-band control commands short-circuit everything.
    reply = handle(_last_user_text(messages), control, list(cfg.models),
                   checkpoints=state["checkpoints"],
                   session=_session_id(messages),
                   history=state["history"])
    if reply is not None:
        state["trace"].record(_session_id(messages), "-", "control", command=_last_user_text(messages))
        return _sse(reply, model_name) if stream else JSONResponse(_completion_body(reply, model_name))

    session = _session_id(messages)
    state["library"].touch_session(session, _last_user_text(messages))

    # Pass-through mode for registry model names. Default max_tokens matches
    # the supervised executor path (8192): reasoning models can burn 4096
    # entirely on thought and return an EMPTY answer at the ceiling.
    if model_name in cfg.models:
        try:
            res = await state["client"].chat(cfg.model(model_name), messages,
                                             max_tokens=body.get("max_tokens", 8192),
                                             temperature=body.get("temperature", 0.2))
        except ProviderError as e:
            return JSONResponse({"error": {"message": str(e)}}, status_code=502)
        state["trace"].record(session, "-", "passthrough", model=model_name,
                              tokens_in=res.tokens_in, tokens_out=res.tokens_out,
                              cost_usd=res.cost_usd)
        return _sse(res.text, model_name) if stream else JSONResponse(_completion_body(res.text, model_name))

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
        return _sse_raw(data, model_name)

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
        return JSONResponse(_completion_body(render(report), model_name))

    # Streaming: long supervised turns need keepalives or clients drop the
    # connection. SSE comment lines are ignored by OpenAI-compatible clients.
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    def chunk(delta: dict, finish: str | None = None) -> str:
        return "data: " + json.dumps({
            "id": cid, "object": "chat.completion.chunk",
            "created": int(time.time()), "model": model_name,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }) + "\n\n"

    async def gen():
        task = asyncio.create_task(state["orch"].run_turn(session, messages))
        start = time.monotonic()
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
            text = render(task.result())
        except Exception as e:
            text = f"[llm-super] turn failed: {e}"
        for i in range(0, len(text), 512):
            yield chunk({"content": text[i: i + 512]})
        yield chunk({}, "stop")
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
        "plan": c.plan_mode,
        "ensemble": c.ensemble_n,
        "strategy": c.strategy,
        "cutoff": c.cutoff,
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
