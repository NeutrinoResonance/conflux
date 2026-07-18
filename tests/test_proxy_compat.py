from __future__ import annotations

import json
import unittest

from llm_super import proxy
from llm_super.config import Config, Execution, Model, Provider, Supervision
from llm_super.control import ControlState
from llm_super.orchestrator import TurnReport


def _config() -> Config:
    model = Model(
        name="direct", provider="test", id="provider-model-id",
        family="test", roles=("executor",), logprobs=False,
        top_logprobs_max=5, price_in_per_m=1.0, price_out_per_m=2.0,
    )
    return Config(
        providers={"test": Provider(
            "test", "https://provider.test/v1", "env:TEST_KEY")},
        models={"direct": model}, default_executor="direct", utility="direct",
        verifier_pool=[], supervision=Supervision(confirm_new_sessions=True),
        execution=Execution(backend="off"), learned_routing=False,
    )


def _raw_response() -> dict:
    return {
        "id": "chatcmpl-upstream",
        "object": "chat.completion",
        "created": 123,
        "model": "provider-model-id",
        "provider": "test-provider",
        "service_tier": "default",
        "system_fingerprint": "fp-123",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "checking",
                "reasoning": "I should inspect the remote host.",
                "reasoning_details": [{
                    "type": "reasoning.text",
                    "text": "I should inspect the remote host.",
                    "signature": "signed-state",
                }],
                "refusal": None,
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "shell", "arguments": "{}"},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        },
    }


async def _sse_events(response) -> list[dict | str]:
    events: list[dict | str] = []
    async for raw in response.body_iterator:
        text = raw.decode() if isinstance(raw, bytes) else raw
        for block in text.split("\n\n"):
            if not block.startswith("data: "):
                continue
            payload = block[6:]
            events.append(payload if payload == "[DONE]" else json.loads(payload))
    return events


class RawSSECompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_reasoning_extensions_and_requested_usage(self) -> None:
        events = await _sse_events(
            proxy._sse_raw(_raw_response(), "direct", include_usage=True)
        )

        chunks = [event for event in events if isinstance(event, dict)]
        deltas = [chunk["choices"][0]["delta"]
                  for chunk in chunks if chunk["choices"]]
        extension_delta = next(
            delta for delta in deltas if "reasoning_details" in delta
        )
        self.assertEqual(extension_delta["reasoning"],
                         "I should inspect the remote host.")
        self.assertEqual(extension_delta["reasoning_details"][0]["signature"],
                         "signed-state")

        tool_delta = next(delta for delta in deltas if "tool_calls" in delta)
        self.assertEqual(tool_delta["tool_calls"][0]["index"], 0)
        self.assertEqual(tool_delta["tool_calls"][0]["id"], "call-1")

        usage_chunks = [chunk for chunk in chunks if not chunk["choices"]]
        self.assertEqual(len(usage_chunks), 1)
        self.assertEqual(usage_chunks[0]["usage"]["total_tokens"], 18)
        self.assertEqual(usage_chunks[0]["provider"], "test-provider")
        self.assertEqual(usage_chunks[0]["system_fingerprint"], "fp-123")
        self.assertEqual(events[-1], "[DONE]")

    async def test_usage_chunk_is_omitted_unless_client_requested_it(self) -> None:
        events = await _sse_events(proxy._sse_raw(_raw_response(), "direct"))
        chunks = [event for event in events if isinstance(event, dict)]
        self.assertFalse(any(not chunk["choices"] for chunk in chunks))


class _Request:
    def __init__(self, body: dict):
        self.body = body

    async def json(self) -> dict:
        return self.body


class _Library:
    def __init__(self) -> None:
        self.touched: list[str] = []

    def resolve_alias(self, session: str) -> str:
        return session

    def touch_session(self, session: str, title: str) -> None:
        self.touched.append(session)

    def has_session(self, session: str) -> bool:
        return False


class _Trace:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def record(self, *args, **kwargs) -> None:
        self.events.append((args, kwargs))


class _History:
    def recent_turns(self, *args, **kwargs) -> list:
        return []


class _SupervisedOrchestrator:
    def __init__(self, *, tokens_in: int, tokens_out: int) -> None:
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.calls = 0

    async def run_turn(self, session: str, messages: list[dict]) -> TurnReport:
        self.calls += 1
        return TurnReport(
            text="supervised answer", task_id="task-1", executor="direct",
            attempts=1, verify=None, tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
        )


class SupervisedUsageRenderingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.old_state = dict(proxy.state)
        proxy.state.clear()
        self.messages = [{"role": "user", "content": "meter this turn"}]
        session = proxy._session_id(self.messages)
        self.orch = _SupervisedOrchestrator(tokens_in=31, tokens_out=9)
        proxy.state.update(
            cfg=_config(), control=ControlState(), library=_Library(),
            trace=_Trace(), history=_History(), checkpoints=object(),
            armed_sessions={session}, orch=self.orch,
        )

    def tearDown(self) -> None:
        proxy.state.clear()
        proxy.state.update(self.old_state)

    def _body(self, *, stream: bool, include_usage: bool = False) -> dict:
        body = {"model": "super", "stream": stream, "messages": self.messages}
        if include_usage:
            body["stream_options"] = {"include_usage": True}
        return body

    async def test_nonstream_response_reports_supervision_usage(self) -> None:
        response = await proxy.chat_completions(
            _Request(self._body(stream=False))
        )
        payload = json.loads(response.body)

        self.assertEqual(self.orch.calls, 1)
        self.assertEqual(payload["usage"], {
            "prompt_tokens": 31,
            "completion_tokens": 9,
            "total_tokens": 40,
        })

    async def test_stream_response_emits_requested_supervision_usage(self) -> None:
        response = await proxy.chat_completions(
            _Request(self._body(stream=True, include_usage=True))
        )
        events = await _sse_events(response)
        chunks = [event for event in events if isinstance(event, dict)]
        usage_chunks = [chunk for chunk in chunks if not chunk["choices"]]

        self.assertEqual(len(usage_chunks), 1)
        self.assertEqual(usage_chunks[0]["usage"], {
            "prompt_tokens": 31,
            "completion_tokens": 9,
            "total_tokens": 40,
        })
        self.assertEqual(events[-1], "[DONE]")

    async def test_stream_usage_is_omitted_when_not_requested(self) -> None:
        response = await proxy.chat_completions(
            _Request(self._body(stream=True))
        )
        events = await _sse_events(response)
        chunks = [event for event in events if isinstance(event, dict)]

        self.assertFalse(any(not chunk["choices"] for chunk in chunks))


class _Client:
    def __init__(self) -> None:
        self.raw_calls: list[tuple[Model, dict]] = []
        self.chat_calls = 0

    async def raw_chat(self, model: Model, body: dict) -> dict:
        self.raw_calls.append((model, body))
        return _raw_response()

    async def chat(self, *args, **kwargs):
        self.chat_calls += 1
        raise AssertionError("tool-carrying registry requests must not use chat()")


class RegistryToolRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.old_state = dict(proxy.state)
        proxy.state.clear()
        self.client = _Client()
        self.library = _Library()
        self.control = ControlState(paused=True)
        proxy.state.update(
            cfg=_config(), control=self.control, client=self.client,
            library=self.library, trace=_Trace(), history=object(),
            checkpoints=object(), armed_sessions=set(), orch=object(),
        )

    def tearDown(self) -> None:
        proxy.state.clear()
        proxy.state.update(self.old_state)

    @staticmethod
    def _body(*, stream: bool) -> dict:
        return {
            "model": "direct",
            "stream": stream,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "user", "content": "inspect remotely"}],
            "tools": [{
                "type": "function",
                "function": {"name": "shell", "parameters": {"type": "object"}},
            }],
        }

    async def test_nonstream_registry_tool_request_uses_raw_passthrough(self) -> None:
        # Explicit registry passthrough remains usable while virtual supervision
        # is paused; this is an intentional operator escape hatch.
        response = await proxy.chat_completions(_Request(self._body(stream=False)))
        payload = json.loads(response.body)

        self.assertEqual(self.client.chat_calls, 0)
        self.assertEqual(len(self.client.raw_calls), 1)
        self.assertEqual(self.client.raw_calls[0][0].name, "direct")
        self.assertEqual(payload["model"], "direct")
        self.assertEqual(payload["choices"][0]["finish_reason"], "tool_calls")

    async def test_stream_registry_tool_request_preserves_raw_fields(self) -> None:
        response = await proxy.chat_completions(_Request(self._body(stream=True)))
        events = await _sse_events(response)
        chunks = [event for event in events if isinstance(event, dict)]
        deltas = [chunk["choices"][0]["delta"]
                  for chunk in chunks if chunk["choices"]]

        self.assertEqual(len(self.client.raw_calls), 1)
        self.assertTrue(any("reasoning_details" in delta for delta in deltas))
        self.assertTrue(any(not chunk["choices"] and "usage" in chunk
                            for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
