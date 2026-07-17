"""Runtime credential resolution.

Keys are resolved at request time, never cached at startup: the Nous agent
key in ~/.hermes/auth.json rotates roughly daily, and OpenCode may re-mint
its keys too.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

HERMES_AUTH = Path.home() / ".hermes" / "auth.json"
OPENCODE_AUTH = Path.home() / ".local" / "share" / "opencode" / "auth.json"


class KeyResolutionError(RuntimeError):
    pass


def _hermes_key(provider: str) -> str:
    try:
        data = json.loads(HERMES_AUTH.read_text())
        key = data["providers"][provider]["agent_key"]
    except (OSError, KeyError, json.JSONDecodeError) as e:
        raise KeyResolutionError(
            f"cannot read agent_key for {provider!r} from {HERMES_AUTH}: {e}. "
            f"Run `hermes login --provider {provider}` to refresh."
        ) from e
    if not key:
        raise KeyResolutionError(f"empty agent_key for {provider!r} in {HERMES_AUTH}")
    return key


def _opencode_key(provider: str) -> str:
    try:
        data = json.loads(OPENCODE_AUTH.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise KeyResolutionError(f"cannot read {OPENCODE_AUTH}: {e}") from e
    entry = data.get(provider)
    if isinstance(entry, dict) and entry.get("key"):
        return entry["key"]
    raise KeyResolutionError(f"no API key for {provider!r} in {OPENCODE_AUTH}")


def resolve(key_source: str) -> str:
    """Resolve a models.yaml key_source spec to a bearer token."""
    scheme, _, arg = key_source.partition(":")
    if scheme == "env":
        val = os.environ.get(arg, "")
        if not val:
            raise KeyResolutionError(f"environment variable {arg} is not set")
        return val
    if scheme == "hermes":
        return _hermes_key(arg)
    if scheme == "opencode":
        return _opencode_key(arg)
    raise KeyResolutionError(f"unknown key_source scheme: {key_source!r}")
