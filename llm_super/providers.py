"""Async OpenAI-compatible chat client over the provider registry."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import reqlog
from .config import Config, Model, Provider
from .keys import resolve, try_refresh

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


async def chat_chain(client: "Client", cfg: Config, model_name: str,
                     messages: list[dict[str, Any]], **kw) -> tuple[ChatResult, Model]:
    """Call a model, failing over through its models.yaml fallback chain."""
    last: Exception | None = None
    for model in cfg.executor_chain(model_name):
        try:
            return await client.chat(model, messages, **kw), model
        except ProviderError as e:
            last = e
    raise last if last else ProviderError(model_name, 0, "empty chain")


@dataclass
class _Breaker:
    fails: int = 0
    open_until: float = 0.0
    limit_hits: int = 0        # consecutive rate/usage-limit trips


def _embedded_error_code(data: Any) -> int | None:
    """Some aggregators (Nous) wrap upstream errors in an HTTP 200 body:
    {"error": {"message": "Provider returned error", "code": 429}}."""
    err = data.get("error") if isinstance(data, dict) else None
    if not isinstance(err, dict):
        return None
    code = err.get("code")
    if isinstance(code, int):
        return code
    if isinstance(code, str):
        if code.isdigit():
            return int(code)
        if "rate_limit" in code:
            return 429
    if "rate limit" in str(err.get("message", "")).lower():
        return 429
    return None


class Client:
    """Provider client with retries and circuit breakers.

    Without the breaker, a flaky provider gets independently re-probed by
    every stage (executor, contract, planner, each verifier criterion) and
    their retry loops multiply into minutes of stall. After BREAK_AFTER
    consecutive failures a provider is skipped instantly for BREAK_FOR
    seconds; fallback chains route around it.

    Rate/usage limits get their own treatment, scoped by what they actually
    mean (verified empirically 2026-07-17):
    - an HTTP 429 from the gateway is provider-level exhaustion — on
      OpenCode Go the limits are rolling DOLLAR windows ($12/5h, $30/wk,
      $60/mo; opencode.ai/docs/go#usage-limits), so the condition persists
      for hours and the cooldown escalates (doubling up to LIMIT_BREAK_MAX)
      instead of re-probing every BREAK_FOR seconds;
    - a 429 embedded in an HTTP 200 body (Nous relaying a slammed upstream)
      is MODEL-level: only that model is skipped, never the other ~280
      models on the aggregator."""

    BREAK_AFTER = 2
    BREAK_FOR = 120.0
    LIMIT_BREAK_MAX = 1800.0   # cap the escalating limit cooldown at 30 min

    def __init__(self, cfg: Config, timeout: float | httpx.Timeout | None = None):
        self.cfg = cfg
        self._http = httpx.AsyncClient(
            timeout=timeout if timeout is not None
            else httpx.Timeout(connect=10.0, read=240.0, write=30.0, pool=10.0)
        )
        self._breakers: dict[str, _Breaker] = {}
        self._model_breakers: dict[str, _Breaker] = {}
        self._last_key_refresh: dict[str, float] = {}

    def _trip_limit(self, scope: str, provider: Provider, model: Model,
                    status: int, data: Any) -> ProviderError:
        b = (self._breakers.setdefault(provider.name, _Breaker())
             if scope == "provider"
             else self._model_breakers.setdefault(model.name, _Breaker()))
        b.limit_hits += 1
        cooldown = min(self.LIMIT_BREAK_MAX,
                       self.BREAK_FOR * 2 ** (b.limit_hits - 1))
        b.open_until = time.monotonic() + cooldown
        target = provider.name if scope == "provider" else model.name
        return ProviderError(
            model.name, status or 429,
            f"rate/usage limit ({scope} {target}, cooldown {cooldown:.0f}s): "
            + json.dumps(data)[:200])

    def _check_limit(self, provider: Provider, model: Model,
                     status: int, data: Any) -> None:
        """Raise (and open the right breaker) if this response is a limit."""
        if status == 429:
            raise self._trip_limit("provider", provider, model, status, data)
        if status == 200 and _embedded_error_code(data) == 429:
            raise self._trip_limit("model", provider, model, status, data)

    def _entry_checks(self, provider: Provider, model: Model) -> _Breaker:
        breaker = self._breakers.setdefault(provider.name, _Breaker())
        if time.monotonic() < breaker.open_until:
            raise ProviderError(
                model.name, 0,
                f"circuit open for provider {provider.name} "
                f"({breaker.fails} recent failures); using fallbacks")
        mb = self._model_breakers.get(model.name)
        if mb and time.monotonic() < mb.open_until:
            raise ProviderError(
                model.name, 0,
                f"limit circuit open for model {model.name}; using fallbacks")
        return breaker

    def _note_success(self, provider: Provider, model: Model,
                      breaker: _Breaker) -> None:
        breaker.fails = 0
        breaker.limit_hits = 0
        self._model_breakers.pop(model.name, None)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def raw_chat(self, model: Model, body: dict[str, Any]) -> dict[str, Any]:
        """Forward a full OpenAI-format request body (tools and all) to the
        provider, preserving the response shape. Used for agentic tool-call
        turns, which supervised chat() cannot represent. Same breaker/retry
        policy as chat()."""
        provider = self.cfg.provider_for(model)
        breaker = self._entry_checks(provider, model)
        out = dict(body)
        out["model"] = model.id
        out.pop("stream", None)
        last_exc: Exception | None = None
        for attempt in range(2):
            if attempt:
                await asyncio.sleep(1.5)
            try:
                resp = await self._http.post(
                    f"{provider.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {resolve(provider.key_source)}",
                        "Content-Type": "application/json",
                    },
                    json=out,
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
            self._check_limit(provider, model, resp.status_code, data)
            if resp.status_code >= 500:
                last_exc = ProviderError(model.name, resp.status_code, json.dumps(data))
                continue
            if resp.status_code != 200 or "choices" not in data:
                raise ProviderError(model.name, resp.status_code, json.dumps(data))
            self._note_success(provider, model, breaker)
            reqlog.record("upstream", model.name, {"request": out, "response": data})
            return data
        breaker.fails += 1
        if breaker.fails >= self.BREAK_AFTER:
            breaker.open_until = time.monotonic() + self.BREAK_FOR
        raise last_exc if last_exc else ProviderError(model.name, 0, "exhausted retries")

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

        breaker = self._entry_checks(provider, model)

        last_exc: Exception | None = None
        data = None
        for attempt in range(2):  # transient 5xx/timeouts are routine on aggregators
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
            self._check_limit(provider, model, resp.status_code, data)
            if resp.status_code >= 500:
                last_exc = ProviderError(model.name, resp.status_code, json.dumps(data))
                continue
            if resp.status_code in (401, 403):
                # Expired credential (the Nous agent key rotates ~daily).
                # Self-heal: trigger the provider's refresh path once per
                # cooldown, then retry the request with the new key.
                now = time.monotonic()
                if now - self._last_key_refresh.get(provider.name, 0) > 300:
                    self._last_key_refresh[provider.name] = now
                    refreshed = await asyncio.to_thread(try_refresh, provider.key_source)
                    if refreshed:
                        continue
                raise ProviderError(model.name, resp.status_code, json.dumps(data))
            if resp.status_code != 200 or "choices" not in data:
                # other 4xx: our request is wrong for this provider — don't
                # retry, and don't punish the provider's breaker for it
                raise ProviderError(model.name, resp.status_code, json.dumps(data))
            break
        else:
            breaker.fails += 1
            if breaker.fails >= self.BREAK_AFTER:
                breaker.open_until = time.monotonic() + self.BREAK_FOR
            raise last_exc if last_exc else ProviderError(model.name, 0, "exhausted retries")
        self._note_success(provider, model, breaker)

        reqlog.record("upstream", model.name, {"request": body, "response": data})
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
