"""Async OpenAI-compatible chat client over the provider registry."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Config, Model
from .keys import resolve

# Some gateways emit unescaped control chars inside reasoning text.
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass
class ChatResult:
    text: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    logprob_content: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class ProviderError(RuntimeError):
    def __init__(self, model: str, status: int, body: str):
        self.model, self.status, self.body = model, status, body
        super().__init__(f"{model}: HTTP {status}: {body[:300]}")


class Client:
    def __init__(self, cfg: Config, timeout: float = 300.0):
        self.cfg = cfg
        self._http = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def chat(
        self,
        model: Model,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        logprobs: bool = False,
    ) -> ChatResult:
        provider = self.cfg.provider_for(model)
        body: dict[str, Any] = {
            "model": model.id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if logprobs and model.logprobs:
            body["logprobs"] = True
            body["top_logprobs"] = model.top_logprobs_max

        last_exc: Exception | None = None
        for attempt in range(3):  # transient 5xx/timeouts are routine on aggregators
            if attempt:
                await asyncio.sleep(1.5 * attempt)
            try:
                resp = await self._http.post(
                    f"{provider.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {resolve(provider.key_source)}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
            except httpx.HTTPError as e:
                last_exc = ProviderError(model.name, 0, f"transport error: {e}")
                continue
            text = _CTRL.sub(" ", resp.text)
            try:
                data = json.loads(text, strict=False)
            except json.JSONDecodeError as e:
                last_exc = ProviderError(model.name, resp.status_code, f"unparseable body: {e}")
                continue
            if resp.status_code >= 500:
                last_exc = ProviderError(model.name, resp.status_code, json.dumps(data))
                continue
            if resp.status_code != 200 or "choices" not in data:
                raise ProviderError(model.name, resp.status_code, json.dumps(data))
            break
        else:
            raise last_exc if last_exc else ProviderError(model.name, 0, "exhausted retries")

        choice = data["choices"][0]
        content = (choice.get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens", 0))
        tokens_out = int(usage.get("completion_tokens", 0))
        lp = (choice.get("logprobs") or {}).get("content") or []
        return ChatResult(
            text=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=model.cost(tokens_in, tokens_out),
            logprob_content=lp,
            raw=data,
        )
