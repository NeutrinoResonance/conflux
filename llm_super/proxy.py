"""OpenAI-compatible ingress (SPEC §2): any OSS client connects unmodified.

Model name "super" (or "super/<anything>") routes through the supervised
orchestrator; a registry model name (e.g. "deepseek-v4-pro") passes through
unsupervised. Streaming requests are answered as SSE with the final verified
text (optimistic token-by-token streaming is a later milestone).
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .config import load
from .control import ControlState, handle
from .orchestrator import Orchestrator, _last_user_text
from .providers import Client, ProviderError
from .trace import Trace

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load(state.get("config_path", "models.yaml"))
    client = Client(cfg)
    trace = Trace(state.get("trace_path", "traces.db"))
    control = ControlState()
    state.update(
        cfg=cfg,
        client=client,
        trace=trace,
        control=control,
        orch=Orchestrator(cfg, client, trace, control),
    )
    yield
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
    reply = handle(_last_user_text(messages), control, list(cfg.models))
    if reply is not None:
        state["trace"].record(_session_id(messages), "-", "control", command=_last_user_text(messages))
        return _sse(reply, model_name) if stream else JSONResponse(_completion_body(reply, model_name))

    session = _session_id(messages)

    # Pass-through mode for registry model names.
    if model_name in cfg.models:
        try:
            res = await state["client"].chat(cfg.model(model_name), messages,
                                             max_tokens=body.get("max_tokens", 4096),
                                             temperature=body.get("temperature", 0.2))
        except ProviderError as e:
            return JSONResponse({"error": {"message": str(e)}}, status_code=502)
        state["trace"].record(session, "-", "passthrough", model=model_name,
                              tokens_in=res.tokens_in, tokens_out=res.tokens_out,
                              cost_usd=res.cost_usd)
        return _sse(res.text, model_name) if stream else JSONResponse(_completion_body(res.text, model_name))

    # Supervised mode.
    report = await state["orch"].run_turn(session, messages)
    text = report.text
    if cfg.supervision.trailer:
        text += report.trailer()
    if report.escalated and not report.text:
        text = f"[llm-super] {report.escalated}"
    return _sse(text, model_name) if stream else JSONResponse(_completion_body(text, model_name))


@app.get("/v1/models")
async def models():
    cfg = state["cfg"]
    now = int(time.time())
    data = [{"id": "super", "object": "model", "created": now, "owned_by": "llm-super"}]
    data += [{"id": name, "object": "model", "created": now, "owned_by": m.provider}
             for name, m in cfg.models.items()]
    return {"object": "list", "data": data}


@app.get("/admin/status")
async def admin_status():
    c: ControlState = state["control"]
    return {
        "paused": c.paused,
        "forced_executor": c.forced_executor,
        "budget_usd": c.budget_usd,
        "recent_commands": c.history[-10:],
    }


@app.get("/admin/events")
async def admin_events(n: int = 50):
    return state["trace"].recent(n)


@app.post("/admin/pause")
async def admin_pause():
    state["control"].paused = True
    return {"paused": True}


@app.post("/admin/resume")
async def admin_resume():
    state["control"].paused = False
    return {"paused": False}
