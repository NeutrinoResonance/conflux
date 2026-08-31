from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from conflux.config import Config, Execution, Model, Provider, Supervision
from conflux.control import ControlState
from conflux.keys import KeyResolutionError
from conflux.orchestrator import Orchestrator
from conflux.providers import Client, ProviderError, chat_chain


def _model(name: str, provider: str, model_id: str,
           fallbacks: tuple[str, ...] = ()) -> Model:
    return Model(
        name=name,
        provider=provider,
        id=model_id,
        family=name,
        roles=("executor",),
        logprobs=False,
        top_logprobs_max=5,
        price_in_per_m=0,
        price_out_per_m=0,
        fallbacks=fallbacks,
    )


def _config() -> Config:
    primary = _model("primary", "primary-provider", "primary-id", ("fallback",))
    fallback = _model("fallback", "fallback-provider", "fallback-id")
    return Config(
        providers={
            "primary-provider": Provider(
                "primary-provider", "https://primary.test/v1", "hermes:nous"),
            "fallback-provider": Provider(
                "fallback-provider", "https://fallback.test/v1", "env:FALLBACK"),
        },
        models={"primary": primary, "fallback": fallback},
        default_executor="primary",
        utility="fallback",
        verifier_pool=[],
        supervision=Supervision(),
        execution=Execution(),
        learned_routing=False,
    )


class _Trace:
    def __init__(self) -> None:
        self.events: list[tuple] = []
        self.exchanges: list[tuple] = []

    def record(self, *args, **kwargs) -> None:
        self.events.append((args, kwargs))

    def record_exchange(self, *args, **kwargs) -> None:
        self.exchanges.append((args, kwargs))

    def last_client_request(self, session: str):
        return None


class ProviderCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def _client(self, handler) -> Client:
        client = Client(_config())
        await client._http.aclose()
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)
        return client

    async def test_raw_chat_refreshes_after_transient_then_auth_failure(self) -> None:
        sent: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            if len(sent) == 1:
                return httpx.Response(503, json={"error": "transient"})
            if len(sent) == 2:
                return httpx.Response(401, json={"error": "expired"})
            return httpx.Response(200, json={
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "shell", "arguments": "{}"},
                        }],
                    },
                    "finish_reason": "tool_calls",
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            })

        client = await self._client(handler)
        original = {
            "model": "super",
            "messages": [{"role": "user", "content": "inspect"}],
            "tools": [{"type": "function", "function": {"name": "shell"}}],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        with patch("conflux.providers.resolve", return_value="token"), \
                patch("conflux.providers.try_refresh", return_value=True) as refresh, \
                patch("conflux.providers.asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await client.raw_chat(client.cfg.model("primary"), original)

        self.assertEqual(len(sent), 3)
        refresh.assert_called_once_with("hermes:nous")
        sleep.assert_awaited_once_with(1.5)
        self.assertEqual(result["choices"][0]["finish_reason"], "tool_calls")
        for request_body in sent:
            self.assertEqual(request_body["model"], "primary-id")
            self.assertNotIn("stream", request_body)
            self.assertNotIn("stream_options", request_body)
        # Adapting the provider request must not mutate the caller's body; the
        # proxy still needs these fields when it reconstructs the client SSE.
        self.assertTrue(original["stream"])
        self.assertEqual(original["stream_options"], {"include_usage": True})

    async def test_key_resolution_error_is_provider_error_and_agent_falls_back(self) -> None:
        seen_hosts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_hosts.append(request.url.host or "")
            return httpx.Response(200, json={
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call-fallback",
                            "type": "function",
                            "function": {"name": "shell", "arguments": "{}"},
                        }],
                    },
                    "finish_reason": "tool_calls",
                }],
                "usage": {},
            })

        client = await self._client(handler)

        def resolve_key(source: str) -> str:
            if source == "hermes:nous":
                raise KeyResolutionError("primary credential missing")
            return "fallback-token"

        orchestrator = Orchestrator(client.cfg, client, _Trace(), ControlState())
        body = {
            "model": "super",
            "messages": [{"role": "user", "content": "use a tool"}],
            "tools": [{"type": "function", "function": {"name": "shell"}}],
        }
        with patch("conflux.providers.resolve", side_effect=resolve_key):
            result = await orchestrator.run_tool_turn("session", body)

        self.assertEqual(seen_hosts, ["fallback.test"])
        self.assertEqual(
            result["choices"][0]["message"]["tool_calls"][0]["id"],
            "call-fallback",
        )
        errors = [kwargs for _, kwargs in orchestrator.trace.events
                  if kwargs.get("model") == "primary"]
        self.assertTrue(any("credential resolution failed" in e.get("error", "")
                            for e in errors))

    async def test_text_chat_chain_also_routes_around_key_resolution_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {},
            })

        client = await self._client(handler)

        def resolve_key(source: str) -> str:
            if source == "hermes:nous":
                raise KeyResolutionError("primary credential missing")
            return "fallback-token"

        with patch("conflux.providers.resolve", side_effect=resolve_key):
            result, model = await chat_chain(
                client, client.cfg, "primary",
                [{"role": "user", "content": "hello"}],
            )

        self.assertEqual(result.text, "ok")
        self.assertEqual(model.name, "fallback")

    async def test_unrefreshable_raw_auth_error_remains_provider_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "blocked"})

        client = await self._client(handler)
        with patch("conflux.providers.resolve", return_value="token"), \
                patch("conflux.providers.try_refresh", return_value=False):
            with self.assertRaises(ProviderError) as raised:
                await client.raw_chat(client.cfg.model("primary"), {
                    "messages": [{"role": "user", "content": "hello"}],
                    "tools": [],
                })
        self.assertEqual(raised.exception.status, 403)


if __name__ == "__main__":
    unittest.main()
