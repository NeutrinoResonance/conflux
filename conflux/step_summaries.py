"""Cheap, persisted summaries for one logical conversation step.

The raw ``exchanges`` rows remain the source of truth.  This module adds a
small display index keyed by the trace identity ``(session, task)``.  Runtime
summaries are deliberately deterministic: recording a step must never add a
model call, latency, provider dependency, or spend.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import sqlite3
import time
from collections.abc import Mapping, Sequence
from typing import Any


PROMPT_VERSION = "step-summary-v1"
GENERATOR = "deterministic"

_SPACE_RE = re.compile(r"\s+")
_LEADING_REQUEST_RE = re.compile(
    r"^(?:please\s+|could you\s+|can you\s+|would you\s+|i(?:'d| would) like you to\s+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StepSummary:
    """The three presentation levels shared by live and history views."""

    short_summary: str
    node_label: str
    long_summary: str

    def as_dict(self) -> dict[str, str]:
        return {
            "short_summary": self.short_summary,
            "node_label": self.node_label,
            "long_summary": self.long_summary,
        }


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Apply the additive summary-index migration to an open trace DB."""
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS step_summaries (
          session TEXT NOT NULL,
          task TEXT NOT NULL,
          short_summary TEXT NOT NULL,
          node_label TEXT NOT NULL,
          long_summary TEXT NOT NULL,
          generator TEXT NOT NULL,
          prompt_version TEXT NOT NULL,
          created_ts REAL NOT NULL,
          updated_ts REAL NOT NULL,
          PRIMARY KEY (session, task)
        );
        CREATE INDEX IF NOT EXISTS idx_step_summaries_updated
          ON step_summaries (updated_ts DESC);
        """
    )


def upsert_step_summary(
    conn: sqlite3.Connection,
    session: str,
    task: str,
    summary: StepSummary | Mapping[str, Any],
    *,
    generator: str = GENERATOR,
    prompt_version: str = PROMPT_VERSION,
    timestamp: float | None = None,
) -> None:
    """Insert or replace the current display summary for a logical step.

    The caller owns the surrounding transaction.  Keeping this helper free of
    commits lets :class:`Trace` persist the exchange and its summary atomically,
    while backfill can commit validated batches.
    """
    values = summary.as_dict() if isinstance(summary, StepSummary) else summary
    now = float(time.time() if timestamp is None else timestamp)
    conn.execute(
        """INSERT INTO step_summaries (
               session,task,short_summary,node_label,long_summary,
               generator,prompt_version,created_ts,updated_ts
             ) VALUES (?,?,?,?,?,?,?,?,?)
             ON CONFLICT(session,task) DO UPDATE SET
               short_summary=excluded.short_summary,
               node_label=excluded.node_label,
               long_summary=excluded.long_summary,
               generator=excluded.generator,
               prompt_version=excluded.prompt_version,
               updated_ts=excluded.updated_ts""",
        (
            str(session), str(task),
            str(values.get("short_summary") or "Step recorded."),
            str(values.get("node_label") or "Conversation step"),
            str(values.get("long_summary") or "This conversation step was recorded."),
            str(generator), str(prompt_version), now, now,
        ),
    )


def derive_step_summary(
    request: Mapping[str, Any] | None,
    response: Mapping[str, Any] | None = None,
) -> StepSummary:
    """Derive all three display levels without exposing private model state."""
    request = request or {}
    response = response or {}
    messages = request.get("messages")
    messages = messages if isinstance(messages, list) else []
    prompt = _last_user_text(messages) or _latest_input_text(messages)
    prompt = _clip(prompt or "a conversation step", 220)

    calls = _tool_calls(response)
    answer = _response_text(response)
    if calls:
        call_names = [call[0] for call in calls]
        unique_names = list(dict.fromkeys(call_names))
        rendered_names = ", ".join(_humanize(name) for name in unique_names[:3])
        extra = len(unique_names) - 3
        if extra > 0:
            rendered_names += f" and {extra} more"
        effect = (
            f"{len(calls)} tool call{'s' if len(calls) != 1 else ''}: "
            f"{rendered_names}"
        )
        node_label = _clip(
            rendered_names if len(calls) == 1 else f"Run {len(calls)} tool actions",
            72,
        )
        detail = _tool_detail(calls)
        long_summary = (
            f'The prompt was “{prompt}”. The assistant responded by requesting '
            f"{effect}. {detail}"
        )
    elif answer:
        answer_excerpt = _clip(answer, 260)
        effect = f'a text response beginning “{answer_excerpt}”'
        node_label = _prompt_label(prompt)
        long_summary = (
            f'The prompt was “{prompt}”. The assistant returned a text answer. '
            f'Its opening was “{answer_excerpt}”.'
        )
    else:
        effect = "a response that is still pending"
        node_label = _prompt_label(prompt)
        long_summary = (
            f'The prompt was “{prompt}”. No assistant text or tool action has '
            "been recorded for this step yet."
        )

    short_summary = _clip(f'Prompted with “{prompt}”; elicited {effect}.', 320)
    return StepSummary(
        short_summary=short_summary,
        node_label=node_label,
        long_summary=_clip(long_summary, 1400),
    )


def _message_text(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return _clean(content)
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
        pieces: list[str] = []
        for part in content:
            if not isinstance(part, Mapping):
                continue
            text = part.get("text")
            if isinstance(text, str):
                pieces.append(text)
        return _clean(" ".join(pieces))
    return ""


def _last_user_text(messages: Sequence[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, Mapping) and message.get("role") == "user":
            text = _message_text(message)
            if text:
                return text
    return ""


def _latest_input_text(messages: Sequence[Any]) -> str:
    for message in reversed(messages):
        if not isinstance(message, Mapping):
            continue
        text = _message_text(message)
        if text:
            return text
    return ""


def _response_text(response: Mapping[str, Any]) -> str:
    direct = response.get("text")
    if isinstance(direct, str):
        return _clean(direct)
    error = response.get("error")
    if isinstance(error, Mapping) and isinstance(error.get("message"), str):
        return _clean(f"Provider error: {error['message']}")
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        return ""
    message = choices[0].get("message")
    return _message_text(message) if isinstance(message, Mapping) else ""


def _tool_calls(response: Mapping[str, Any]) -> list[tuple[str, tuple[str, ...]]]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        return []
    message = choices[0].get("message")
    if not isinstance(message, Mapping) or not isinstance(message.get("tool_calls"), list):
        return []
    result: list[tuple[str, tuple[str, ...]]] = []
    for call in message["tool_calls"]:
        if not isinstance(call, Mapping):
            continue
        function = call.get("function")
        if not isinstance(function, Mapping):
            continue
        name = str(function.get("name") or "tool")
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except (json.JSONDecodeError, TypeError):
                parsed = {}
        else:
            parsed = arguments
        keys = tuple(sorted(str(key) for key in parsed)) if isinstance(parsed, Mapping) else ()
        result.append((name, keys))
    return result


def _tool_detail(calls: Sequence[tuple[str, tuple[str, ...]]]) -> str:
    descriptions = []
    for name, keys in calls[:4]:
        key_text = f" with {', '.join(keys)}" if keys else ""
        descriptions.append(f"{_humanize(name)}{key_text}")
    detail = "; ".join(descriptions)
    if len(calls) > 4:
        detail += f"; plus {len(calls) - 4} additional calls"
    return f"The recorded actions were {detail}." if detail else ""


def _prompt_label(prompt: str) -> str:
    text = _LEADING_REQUEST_RE.sub("", _clean(prompt)).strip(" .:;-\n")
    first = re.split(r"(?:\n|[.!?](?:\s|$))", text, maxsplit=1)[0]
    first = re.sub(r"^(?:your goal is to|the goal is to)\s+", "", first, flags=re.I)
    label = _clip(first or "Conversation step", 72)
    return label[:1].upper() + label[1:]


def _humanize(name: str) -> str:
    text = _clean(name.replace("_", " ").replace("-", " ")) or "Tool"
    return text[:1].upper() + text[1:]


def _clean(value: Any) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip()


def _clip(value: str, limit: int) -> str:
    text = _clean(value)
    if len(text) <= limit:
        return text
    clipped = text[: max(1, limit - 1)].rstrip()
    boundary = clipped.rfind(" ")
    if boundary >= max(20, limit // 2):
        clipped = clipped[:boundary]
    return clipped.rstrip(" ,;:") + "…"
