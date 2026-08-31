"""Load balancing view: per-provider window usage vs declared limits.

Provider limits live in models.yaml (`providers.<name>.limits`) because they
are provider facts, not code: OpenCode Go drains rolling DOLLAR windows
($12/5h, $30/week, $60/month) at each model's real API price — our Go
registry entries are $0 marginal (subscription), so the recorded ledger cost
cannot measure window drain and tokens are re-priced here at the paid twin's
NOMINAL rates ("<name>-go" → "<name>"). NanoGPT's limit is input tokens per
week, burned at per-model multipliers. The "≈ N requests left" figures mirror
how the Go docs express limits (estimated messages per window), derived from
the window's average burn per request.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from .config import Config

WINDOWS: dict[str, float] = {  # label -> seconds
    "5h": 5 * 3600,
    "week": 7 * 86400,
    "month": 30 * 86400,
}
# which limit key governs each window, per unit
_LIMIT_KEYS = {
    "usd": {"5h": "usd_5h", "week": "usd_week", "month": "usd_month"},
    "input_tokens": {"week": "input_tokens_week"},
}


def nominal_prices(cfg: Config, model_name: str) -> tuple[float, float]:
    """Per-M prices a request really drains from the provider's allowance:
    the listed price, or the paid twin's for $0 subscription entries."""
    m = cfg.models.get(model_name)
    if m is None:
        return 0.0, 0.0
    if m.price_in_per_m or m.price_out_per_m:
        return m.price_in_per_m, m.price_out_per_m
    twin = cfg.models.get(model_name[:-3]) if model_name.endswith("-go") else None
    if twin is not None:
        return twin.price_in_per_m, twin.price_out_per_m
    return 0.0, 0.0


def provider_usage(path: str | Path, cfg: Config) -> dict[str, Any]:
    horizon = max(WINDOWS.values())
    now = time.time()
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute(
            "SELECT ts, model, tokens_in, tokens_out FROM events "
            "WHERE ts >= ? AND model IS NOT NULL", (now - horizon,)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()

    out: dict[str, Any] = {}
    for pname, provider in cfg.providers.items():
        windows: dict[str, Any] = {}
        for wname, wsecs in WINDOWS.items():
            cutoff = now - wsecs
            reqs = tin = tout = 0
            usd = 0.0
            for ts, model, ti, to in rows:
                m = cfg.models.get(model)
                if m is None or m.provider != pname or ts < cutoff:
                    continue
                pin, pout = nominal_prices(cfg, model)
                reqs += 1
                tin += ti or 0
                tout += to or 0
                usd += ((ti or 0) * pin + (to or 0) * pout) / 1e6
            w: dict[str, Any] = {
                "requests": reqs,
                "tokens_in": tin,
                "tokens_out": tout,
                "nominal_usd": round(usd, 4),
            }
            # limit + estimated-requests-remaining, in the limit's own unit
            limits = provider.limits or {}
            usd_key = _LIMIT_KEYS["usd"].get(wname)
            tok_key = _LIMIT_KEYS["input_tokens"].get(wname)
            if usd_key and usd_key in limits:
                cap = float(limits[usd_key])
                w["limit_usd"] = cap
                w["used_pct"] = round(100 * usd / cap, 1) if cap else None
                if reqs and usd > 0:
                    w["est_requests_left"] = int(max(0.0, cap - usd) / (usd / reqs))
            if tok_key and tok_key in limits:
                cap = float(limits[tok_key])
                w["limit_tokens_in"] = cap
                w["used_pct"] = round(100 * tin / cap, 1) if cap else None
                if reqs and tin > 0:
                    w["est_requests_left"] = int(max(0.0, cap - tin) / (tin / reqs))
            windows[wname] = w
        out[pname] = {"windows": windows, "limits": dict(provider.limits or {})}
    return out
