"""Exchange-recording context: lets the provider client attribute every
upstream request/response to the (trace, session, task) that caused it,
without threading those through every call signature. contextvars flow
through awaits and asyncio.gather, so parallel units inherit correctly.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_ctx: ContextVar[tuple[Any, str, str] | None] = ContextVar("conflux_reqlog", default=None)


def set_context(trace: Any, session: str, task: str) -> None:
    _ctx.set((trace, session, task))


def record(kind: str, model: str | None, payload: Any) -> None:
    ctx = _ctx.get()
    if ctx is None:
        return
    trace, session, task = ctx
    try:
        trace.record_exchange(session, task, kind, model, payload)
    except Exception:
        pass  # recording must never break a live turn
