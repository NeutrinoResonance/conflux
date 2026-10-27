"""Provider discovery and capped capability probes (rebuild work item B).

Discovery ($0): model catalogues and balance/quota endpoints for Surplus, NanoGPT,
Kimi Code and the GLM Coding Plan (GET/read-only; no generation on subscription routes).

Paid probes (Surplus only): tool-call round trip, logprobs request and streaming on
DeepSeek V4 flash/pro, and Jev-1.14 `choice`/`score` decisions. Every paid request is
admitted beforehand against a conservative charge bound: it must fit both the per-run
experiment cap and what is left of the campaign budget in docs/rebuild/LEDGER.md. The
provider's billed cost replaces the bound afterwards. Jev decisions carry no billed cost,
so theirs is derived from catalogue price x reported usage and labeled `derived`. Any
other response without a cost (or one above its bound) stops all further paid calls.

Keys are read from ~/.config/devbox/secrets/ at runtime. Request headers are never
recorded, and every written line is scrubbed of key strings.

Usage:
  python scripts/provider_probe.py --out ~/evidence/provider-probes/2026-10-27
  python scripts/provider_probe.py --out DIR --cap 0.10 --only decision_score,deepseek-v4-pro:logprobs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import httpx

SECRETS = Path.home() / ".config/devbox/secrets"
LEDGER = Path(__file__).resolve().parents[1] / "docs/rebuild/LEDGER.md"

SURPLUS = "https://www.surplusintelligence.ai/api/inference/v1"
DECISIONS = "https://api.surplusintelligence.ai/v1/decisions"

EXPERIMENT_CAP = 1.00
CAMPAIGN_BUDGET = 50.00
PRICE_FLOOR = 30e-6      # $/token: the ceiling is never below $30 / 1M tokens
PRICE_UNKNOWN = 60e-6    # $/token when the catalogue lists no price
JEV_MIN_INPUT = 300      # Jev bills at least ~300 input tokens per request
SAMPLES = 3


# ---------------------------------------------------------------- accounting


def parse_ledger_total(text: str) -> float:
    m = re.search(r"\*\*Metered total: \$([0-9]+(?:\.[0-9]+)?)\*\*", text)
    if not m:
        raise ValueError("LEDGER.md has no '**Metered total: $X**' line")
    return float(m.group(1))


def price_ceiling(pricing: dict | None) -> float:
    """Conservative $/token for any token of this model: 2x the listed max, floored."""
    prices = []
    for field in ("prompt", "completion"):
        try:
            prices.append(float((pricing or {})[field]))
        except (KeyError, TypeError, ValueError):
            pass
    if not prices:
        return PRICE_UNKNOWN
    return max(2 * max(prices), PRICE_FLOOR)


def charge_bound(body_bytes: int, max_tokens: int, ceiling: float, min_input: int = 0) -> float:
    # The UTF-8 byte length of the request body is an upper bound on its token count.
    return (max(body_bytes, min_input) + max_tokens) * ceiling


def billed_cost(body: object) -> float | None:
    """USD the provider says it billed, from `buyer_cost_micro`; None when absent."""
    if not isinstance(body, dict):
        return None
    for holder in (body.get("usage"), body):
        if isinstance(holder, dict):
            v = holder.get("buyer_cost_micro")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return v / 1e6
    return None


def derived_cost(body: object, pricing: dict | None, min_input: int = 0) -> float | None:
    """USD from catalogue price x reported usage; None when usage or price is missing."""
    usage = body.get("usage") if isinstance(body, dict) else None
    if not isinstance(usage, dict):
        return None
    try:
        tokens_in = int(usage["input_tokens"])
        tokens_out = int(usage.get("output_tokens") or 0)
        prompt = float((pricing or {})["prompt"])
        completion = float((pricing or {}).get("completion") or 0)
    except (KeyError, TypeError, ValueError):
        return None
    return max(tokens_in, min_input) * prompt + tokens_out * completion


class Budget:
    """Pre-request admission plus settlement against actual billed cost."""

    def __init__(self, ledger_total: float, cap: float = EXPERIMENT_CAP,
                 campaign: float = CAMPAIGN_BUDGET):
        self.ledger_total = ledger_total
        self.cap = cap
        self.campaign = campaign
        self.actual = 0.0
        self.derived = 0.0
        self.estimated = 0.0
        self.reserved = 0.0
        self.stop_reason: str | None = None

    @property
    def spent(self) -> float:
        return self.actual + self.derived + self.estimated

    def admit(self, bound: float) -> tuple[bool, str | None]:
        if self.stop_reason:
            return False, self.stop_reason
        campaign_left = self.campaign - self.ledger_total - self.spent - self.reserved
        experiment_left = self.cap - self.spent - self.reserved
        if bound > campaign_left:
            self.stop_reason = "campaign_budget"
        elif bound > experiment_left:
            self.stop_reason = "experiment_cap"
        else:
            self.reserved += bound
            return True, None
        return False, self.stop_reason

    def release(self, bound: float) -> None:
        self.reserved -= bound

    def settle(self, bound: float, cost: float | None, kind: str = "actual") -> str:
        """Replace a reservation with the billed (or derived) cost; returns the cost kind."""
        self.reserved -= bound
        if cost is None:
            self.estimated += bound
            self.stop_reason = self.stop_reason or "unknown_accounting"
            return "estimate"
        if kind == "derived":
            self.derived += cost
        else:
            self.actual += cost
        if cost > bound:
            self.stop_reason = self.stop_reason or "cost_exceeded_bound"
        return kind

    def paused(self) -> bool:
        return (self.stop_reason == "campaign_budget"
                or self.ledger_total + self.spent >= self.campaign)

    def report(self) -> dict:
        return {
            "ledger_total_before": round(self.ledger_total, 6),
            "actual_usd": round(self.actual, 6),
            "derived_usd": round(self.derived, 6),
            "estimated_usd": round(self.estimated, 6),
            "spent_usd": round(self.spent, 6),
            "stop_reason": self.stop_reason,
            "experiment_overrun_usd": round(max(0.0, self.spent - self.cap), 6),
            "campaign_overrun_usd": round(
                max(0.0, self.ledger_total + self.spent - self.campaign), 6),
            "mission_status": "PAUSED" if self.paused() else "ACTIVE",
        }


# ---------------------------------------------------------------- classifiers


def classify_tool_call(body: object) -> tuple[str, dict | None]:
    """First leg: 'tool_call' with the assistant message, else 'no_tool_call'."""
    try:
        msg = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return "malformed", None
    calls = msg.get("tool_calls") or []
    if calls and calls[0].get("function", {}).get("name"):
        return "tool_call", msg
    return "no_tool_call", None


def classify_final_text(body: object) -> str:
    try:
        content = body["choices"][0]["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError):
        return "malformed"
    return "text" if isinstance(content, str) and content.strip() else "empty"


def classify_logprobs(status: int, body: object) -> str:
    """'present' | 'absent' (accepted, none returned) | 'rejected' (4xx) | 'error'."""
    if 400 <= status < 500:
        return "rejected"
    if status != 200 or not isinstance(body, dict):
        return "error"
    try:
        lp = body["choices"][0].get("logprobs") or {}
    except (KeyError, IndexError, TypeError, AttributeError):
        return "error"
    content = lp.get("content") if isinstance(lp, dict) else None
    return "present" if content and content[0].get("top_logprobs") else "absent"


def parse_sse(text: str) -> tuple[list[dict], bool]:
    """Chunks of an OpenAI-style event stream and whether it ended with [DONE]."""
    chunks, done = [], False
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            done = True
            continue
        try:
            chunks.append(json.loads(data))
        except json.JSONDecodeError:
            pass
    return chunks, done


def classify_stream(chunks: list[dict], done: bool) -> dict:
    deltas = 0
    usage = None
    for c in chunks:
        for ch in c.get("choices") or []:
            d = ch.get("delta") or {}
            if d.get("content") or d.get("reasoning_content") or d.get("reasoning"):
                deltas += 1
        if c.get("usage"):
            usage = c["usage"]
    return {"chunks": len(chunks), "content_deltas": deltas, "done": done,
            "usage": usage, "outcome": "streamed" if deltas > 1 and done else "not_streamed"}


def classify_decision(status: int, body: object, kind: str) -> str:
    if status != 200 or not isinstance(body, dict):
        return "error"
    answers = body.get("answers", body) if isinstance(body.get("answers"), dict) else body
    found = _find_probabilities(answers)
    if not found:
        return "no_probabilities"
    total = sum(v for v in found.values() if isinstance(v, (int, float)))
    return f"{kind}_probabilities" if abs(total - 1.0) <= 0.05 else "probabilities_unnormalized"


def _find_probabilities(obj: object) -> dict | None:
    if isinstance(obj, dict):
        p = obj.get("probabilities")
        if isinstance(p, dict) and p:
            return p
        for v in obj.values():
            found = _find_probabilities(v)
            if found:
                return found
    return None


# ---------------------------------------------------------------- recording


_PRIVATE = re.compile(r"(email|secret|api_?key|id$|user|account|name|phone|address)", re.I)


def sanitize_fields(obj: object, depth: int = 0, prefix: str = "") -> dict:
    """Flatten numeric/bool/short-string leaves, dropping private-looking keys."""
    out: dict = {}
    if depth > 4:
        return out
    items = obj.items() if isinstance(obj, dict) else (
        enumerate(obj) if isinstance(obj, list) else [])
    for k, v in items:
        if isinstance(k, str) and _PRIVATE.search(k):
            continue
        path = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, (dict, list)):
            out.update(sanitize_fields(v, depth + 1, path))
        elif isinstance(v, (int, float, bool)) or v is None:
            out[path] = v
        elif isinstance(v, str) and len(v) <= 40:
            out[path] = v
    return out


class Recorder:
    def __init__(self, path: Path, secrets: list[str]):
        self.path = path
        self.secrets = [s for s in secrets if s]
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = path.open("a")

    def scrub(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "<redacted>")
        return text

    def write(self, **rec) -> None:
        rec.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        self.fh.write(self.scrub(json.dumps(rec, default=str)) + "\n")
        self.fh.flush()


# ---------------------------------------------------------------- live runner


def load_key(name: str) -> str:
    return (SECRETS / name).read_text().strip()


def _json(resp: httpx.Response) -> object:
    try:
        return resp.json()
    except ValueError:
        return {"_text": resp.text[:500]}


def _err(body: object) -> object:
    if isinstance(body, dict):
        e = body.get("error", body)
        return sanitize_fields(e) if isinstance(e, dict) else str(e)[:200]
    return str(body)[:200]


def discover(http: httpx.Client, keys: dict, rec: Recorder) -> dict:
    families = re.compile(r"(deepseek|jev|kimi|k3|glm|moonshot|z-ai)", re.I)
    catalogues = {
        "surplus": (f"{SURPLUS}/models", {"Authorization": f"Bearer {keys['surplus']}"}),
        "nanogpt": ("https://nano-gpt.com/api/v1/models",
                    {"Authorization": f"Bearer {keys['nanogpt']}"}),
        "kimi_code": ("https://api.kimi.com/coding/v1/models",
                      {"Authorization": f"Bearer {keys['kimi']}"}),
        "glm_coding": ("https://api.z.ai/api/coding/paas/v4/models",
                       {"Authorization": f"Bearer {keys['glm']}"}),
    }
    quota = {
        "surplus": [("GET", f"{SURPLUS}/balance"), ("GET", f"{SURPLUS}/credits"),
                    ("GET", "https://api.surplusintelligence.ai/v1/balance"),
                    ("GET", "https://api.surplusintelligence.ai/v1/account")],
        "nanogpt": [("POST", "https://nano-gpt.com/api/check-balance"),
                    ("GET", "https://nano-gpt.com/api/subscription/v1/usage")],
        "kimi_code": [("GET", "https://api.kimi.com/coding/v1/usages")],
        "glm_coding": [("GET", "https://api.z.ai/api/monitor/usage/quota/limit")],
    }
    out: dict = {"catalogues": {}, "quota": {}, "surplus_pricing": {}}
    for route, (url, headers) in catalogues.items():
        try:
            r = http.get(url, headers=headers)
            body = _json(r)
            data = body.get("data", []) if isinstance(body, dict) else body
            ids = [m.get("id") for m in data if isinstance(m, dict)] if isinstance(data, list) else []
            entry = {"status": r.status_code, "count": len(ids),
                     "family_ids": sorted(i for i in ids if i and families.search(i)),
                     "has_pricing": any(isinstance(m, dict) and m.get("pricing")
                                        for m in (data if isinstance(data, list) else []))}
            if route == "surplus":
                out["surplus_pricing"] = {m["id"]: m.get("pricing") for m in data
                                          if isinstance(m, dict) and m.get("id") in
                                          ("deepseek-v4-pro", "deepseek-v4-flash", "jev-1.14")}
                out["surplus_catalogue_entries"] = {
                    m["id"]: {"supported_parameters": m.get("supported_parameters"),
                              "modality": (m.get("architecture") or {}).get("modality")}
                    for m in data if isinstance(m, dict) and m.get("id") in out["surplus_pricing"]}
        except httpx.HTTPError as e:
            entry = {"status": None, "error": type(e).__name__}
        out["catalogues"][route] = entry
        rec.write(phase="discovery", kind="catalogue", route=route, **entry)
    for route, probes in quota.items():
        headers = catalogues[route][1]
        out["quota"][route] = []
        for method, url in probes:
            try:
                r = http.request(method, url, headers=headers)
                entry = {"method": method, "url": url, "status": r.status_code,
                         "fields": sanitize_fields(_json(r)) if r.status_code == 200 else {},
                         "error": None if r.status_code == 200 else _err(_json(r))}
            except httpx.HTTPError as e:
                entry = {"method": method, "url": url, "status": None, "error": type(e).__name__}
            out["quota"][route].append(entry)
            rec.write(phase="discovery", kind="quota", route=route, **entry)
    return out


class PaidProber:
    def __init__(self, http: httpx.Client, key: str, budget: Budget, rec: Recorder,
                 pricing: dict, only: list[str] | None = None):
        self.http = http
        self.headers = {"Authorization": f"Bearer {key}"}
        self.budget = budget
        self.rec = rec
        self.pricing = pricing
        self.only = only
        self.results: dict = {}

    def _post(self, url: str, payload: dict, bound: float, label: dict,
              stream: bool = False, derive_min_input: int | None = None) -> tuple[int | None, object]:
        """One admitted-already paid request; settles the reservation."""
        t0 = time.monotonic()
        try:
            if stream:
                with self.http.stream("POST", url, json=payload, headers=self.headers) as r:
                    text = r.read().decode("utf-8", "replace")
                status = r.status_code
                if status == 200:
                    s = classify_stream(*parse_sse(text))
                    body: object = {"_stream": s, "usage": s["usage"]}
                else:
                    body = _json(r)
            else:
                r = self.http.post(url, json=payload, headers=self.headers)
                status, body = r.status_code, _json(r)
            cost, kind = billed_cost(body), "actual"
            if cost is None and derive_min_input is not None and status == 200:
                cost = derived_cost(body, self.pricing.get(label["model"]), derive_min_input)
                kind = "derived"
        except httpx.HTTPError as e:
            status, body, cost, kind = None, {"_transport_error": type(e).__name__}, None, "actual"
        kind = self.budget.settle(bound, cost, kind)
        usage = body.get("usage") if isinstance(body, dict) else None
        self.rec.write(phase="paid", event="response", **label, status=status,
                       latency_s=round(time.monotonic() - t0, 2), bound_usd=bound,
                       cost_usd=cost if cost is not None else bound, cost_kind=kind,
                       usage=usage, body=body)
        return status, body

    def _admit(self, bound: float, label: dict) -> bool:
        ok, reason = self.budget.admit(bound)
        self.rec.write(phase="paid", event="admission", **label, bound_usd=bound,
                       admitted=ok, refused_by=reason, spent_usd=self.budget.spent,
                       reserved_usd=self.budget.reserved)
        return ok

    def _record(self, model: str, cap: str, outcome: str, extra: dict | None = None) -> None:
        self.results.setdefault(model, {}).setdefault(cap, []).append(
            {"outcome": outcome, **(extra or {})})

    def _skip(self, model: str, cap: str) -> bool:
        """Two identical failures on a capability -> stop sampling it."""
        prior = self.results.get(model, {}).get(cap, [])
        fails = [p for p in prior if p["outcome"] not in
                 ("round_trip", "streamed", "present", "absent", "choice_probabilities",
                  "score_probabilities")]
        return len(fails) >= 2 and fails[-1] == fails[-2]

    def chat_body(self, model: str, max_tokens: int, **extra) -> dict:
        return {"model": model, "max_tokens": max_tokens, "temperature": 0, **extra}

    def tool_round_trip(self, model: str, max_tokens: int, i: int) -> None:
        cap = "tool_round_trip"
        label = {"model": model, "capability": cap, "sample": i}
        ceiling = price_ceiling(self.pricing.get(model))
        tools = [{"type": "function", "function": {
            "name": "get_weather", "description": "Current temperature for a city.",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                           "required": ["city"]}}}]
        messages = [{"role": "user", "content":
                     "What is the temperature in Paris right now? Use the tool."}]
        p1 = self.chat_body(model, max_tokens, messages=messages, tools=tools)
        b1 = charge_bound(len(json.dumps(p1).encode()), max_tokens, ceiling)
        # Second leg input <= first leg input + its output + the tool result (~200 tokens).
        b2_up = charge_bound(len(json.dumps(p1).encode()) + max_tokens + 200, max_tokens, ceiling)
        if not self._admit(b1 + b2_up, label):
            return
        status, body = self._post(f"{SURPLUS}/chat/completions", p1, b1, {**label, "leg": 1})
        self.budget.release(b2_up)  # leg 2 is re-admitted below with its exact bound
        if status != 200:
            self._record(model, cap, f"http_{status}", {"error": _err(body)})
            return
        outcome, msg = classify_tool_call(body)
        if outcome != "tool_call":
            self._record(model, cap, outcome)
            return
        call = msg["tool_calls"][0]
        echo = {"role": "assistant", "content": msg.get("content") or "", "tool_calls": msg["tool_calls"]}
        if msg.get("reasoning_content"):
            echo["reasoning_content"] = msg["reasoning_content"]
        p2 = self.chat_body(model, max_tokens, tools=tools, messages=messages + [echo, {
            "role": "tool", "tool_call_id": call.get("id"), "content": '{"temp_c": 18}'}])
        b2 = charge_bound(len(json.dumps(p2).encode()), max_tokens, ceiling)
        if not self._admit(b2, {**label, "leg": 2}):
            self._record(model, cap, "leg2_not_admitted")
            return
        status, body = self._post(f"{SURPLUS}/chat/completions", p2, b2, {**label, "leg": 2})
        if status != 200:
            self._record(model, cap, f"leg2_http_{status}", {"error": _err(body)})
            return
        final = classify_final_text(body)
        self._record(model, cap, "round_trip" if final == "text" else f"leg2_{final}",
                     {"tool": call["function"]["name"]})

    def logprobs(self, model: str, max_tokens: int, i: int) -> None:
        cap = "logprobs"
        label = {"model": model, "capability": cap, "sample": i}
        p = self.chat_body(model, max_tokens, logprobs=True, top_logprobs=5,
                           messages=[{"role": "user", "content": "Reply with only the letter B."}])
        b = charge_bound(len(json.dumps(p).encode()), max_tokens, price_ceiling(self.pricing.get(model)))
        if not self._admit(b, label):
            return
        status, body = self._post(f"{SURPLUS}/chat/completions", p, b, label)
        self._record(model, cap, classify_logprobs(status or 0, body),
                     {"status": status, "error": _err(body) if status != 200 else None})

    def stream(self, model: str, max_tokens: int, i: int) -> None:
        cap = "stream_usage"
        label = {"model": model, "capability": cap, "sample": i}
        p = self.chat_body(model, max_tokens, stream=True, stream_options={"include_usage": True},
                           messages=[{"role": "user", "content": "Count from 1 to 20, comma separated."}])
        b = charge_bound(len(json.dumps(p).encode()), max_tokens, price_ceiling(self.pricing.get(model)))
        if not self._admit(b, label):
            return
        status, body = self._post(f"{SURPLUS}/chat/completions", p, b, label, stream=True)
        if status != 200:
            self._record(model, cap, f"http_{status}", {"error": _err(body)})
            return
        s = body["_stream"]
        self._record(model, cap, s["outcome"], {
            "chunks": s["chunks"], "usage_in_stream": bool(s["usage"]),
            "billed_cost_in_stream": billed_cost({"usage": s["usage"]}) is not None})

    def decision(self, kind: str, i: int) -> None:
        model = "jev-1.14"
        cap = f"decision_{kind}"
        label = {"model": model, "capability": cap, "sample": i}
        state = ("Task: add input validation to parse_port(). Proposed patch rejects values "
                 "outside 1-65535 and non-digits; unit tests for 0, 65536, 'abc' and 8080 pass.")
        q = ({"type": "choice", "question": "Should the patch be accepted?",
              "criteria": {"accept": "the patch meets the task", "retry": "the patch must be redone"}}
             if kind == "choice" else
             {"type": "score", "question": "How strongly does the evidence support the patch?",
              "criteria": ["none", "weak", "strong"]})
        p = {"model": model, "state": state, "questions": {"q1": q}}
        b = charge_bound(len(json.dumps(p).encode()), 0, price_ceiling(self.pricing.get(model)),
                         min_input=JEV_MIN_INPUT)
        if not self._admit(b, label):
            return
        status, body = self._post(DECISIONS, p, b, label, derive_min_input=JEV_MIN_INPUT)
        self._record(model, cap, classify_decision(status or 0, body, kind),
                     {"status": status, "error": _err(body) if status != 200 else None,
                      "billed": billed_cost(body) is not None})

    def plan(self) -> list[tuple[str, str, object, int]]:
        """(model, capability, probe, max_tokens), filtered by `only` selectors.

        A selector is `cap` (every model) or `model:cap`. Probes that may return no
        cost (and so stop paid work) go late, losing only the probes after them.
        """
        plan = [
            ("deepseek-v4-flash", "tool_round_trip", self.tool_round_trip, 512),
            ("deepseek-v4-flash", "logprobs", self.logprobs, 256),
            ("deepseek-v4-pro", "tool_round_trip", self.tool_round_trip, 1024),
            ("jev-1.14", "decision_choice", lambda m, t, i: self.decision("choice", i), 0),
            ("jev-1.14", "decision_score", lambda m, t, i: self.decision("score", i), 0),
            ("deepseek-v4-pro", "logprobs", self.logprobs, 512),
            ("deepseek-v4-flash", "stream_usage", self.stream, 512),
            ("deepseek-v4-pro", "stream_usage", self.stream, 1024),
        ]
        if self.only is None:
            return plan
        return [p for p in plan if p[1] in self.only or f"{p[0]}:{p[1]}" in self.only]

    def run(self) -> None:
        for model, cap, fn, max_tokens in self.plan():
            for i in range(SAMPLES):
                if self.budget.stop_reason:
                    return
                if self._skip(model, cap):
                    break
                fn(model, max_tokens, i)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--no-paid", action="store_true")
    ap.add_argument("--cap", type=float, default=EXPERIMENT_CAP, help="experiment cap in USD")
    ap.add_argument("--only", help="comma-separated selectors: `cap` or `model:cap`")
    args = ap.parse_args()

    keys = {"surplus": load_key("surplus.key"), "nanogpt": load_key("nanogpt.key"),
            "kimi": load_key("kimi-code.key"), "glm": load_key("zai-coding.key")}
    raw = args.out / "probes.jsonl"
    rec = Recorder(raw, list(keys.values()))
    summary: dict = {}
    # Surplus answers gzip requests with a body httpx cannot decode; ask for plain bytes.
    with httpx.Client(timeout=120, headers={"Accept-Encoding": "identity"}) as http:
        summary["discovery"] = discover(http, keys, rec)
        try:
            ledger_total = parse_ledger_total(LEDGER.read_text())
        except (OSError, ValueError) as e:
            summary["paid"] = {"skipped": f"ledger unreadable: {e}"}
            ledger_total = None
        if ledger_total is not None and not args.no_paid:
            budget = Budget(ledger_total, cap=args.cap)
            only = [s.strip() for s in args.only.split(",") if s.strip()] if args.only else None
            prober = PaidProber(http, keys["surplus"], budget, rec,
                                summary["discovery"]["surplus_pricing"], only)
            prober.run()
            summary["paid"] = {"results": prober.results, "budget": budget.report()}
    rec.fh.close()
    summary["raw_sha256"] = hashlib.sha256(raw.read_bytes()).hexdigest()
    (args.out / "summary.json").write_text(rec.scrub(json.dumps(summary, indent=2, default=str)))
    print(rec.scrub(json.dumps(summary.get("paid", {}).get("budget", summary.get("paid")), indent=2)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
