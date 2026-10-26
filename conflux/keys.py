"""Runtime credential resolution.

Keys are resolved at request time, never cached at startup: the Nous agent
key in ~/.hermes/auth.json rotates roughly daily, and OpenCode may re-mint
its keys too.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERMES_AUTH = Path.home() / ".hermes" / "auth.json"
HERMES_SHARED_NOUS_AUTH = Path.home() / ".hermes" / "shared" / "nous_auth.json"
OPENCODE_AUTH = Path.home() / ".local" / "share" / "opencode" / "auth.json"
# Hermes's own interpreter: background servers often run without ~/.local/bin
# on PATH, so the CLI cannot be assumed findable.
HERMES_PYTHON = Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "python"
# Nous agent keys live one hour; renew this long before expiry so a request
# never goes out with a key that dies in flight.  The renewal is forced:
# Hermes keeps a key it still considers valid, however close to expiry.
REFRESH_MARGIN = timedelta(minutes=5)


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
    entry = data["providers"][provider]
    if provider == "nous" and _expiring(entry.get("agent_key_expires_at")) \
            and _hermes_resolver_refresh(force=True):
        return _hermes_key_unchecked(provider) or key
    return key


def _hermes_key_unchecked(provider: str) -> str | None:
    try:
        return json.loads(HERMES_AUTH.read_text())["providers"][provider]["agent_key"]
    except (OSError, KeyError, json.JSONDecodeError):
        return None


def _expiring(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    try:
        when = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when - datetime.now(timezone.utc) < REFRESH_MARGIN


def _hermes_resolver_refresh(force: bool, timeout: float = 60.0) -> bool:
    """Mint a fresh Nous agent key through Hermes's runtime resolver.

    The resolver refreshes the OAuth token when needed, persists the new key
    to ~/.hermes/auth.json, and coordinates concurrent callers through the
    auth store's file lock; it never prompts.
    """
    if not HERMES_PYTHON.exists():
        return False
    code = ("from hermes_cli.auth import resolve_nous_runtime_credentials as r; "
            f"r(force_refresh={bool(force)})")
    try:
        proc = subprocess.run([str(HERMES_PYTHON), "-c", code],
                              capture_output=True, timeout=timeout, text=True)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _opencode_key(provider: str) -> str:
    try:
        data = json.loads(OPENCODE_AUTH.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise KeyResolutionError(f"cannot read {OPENCODE_AUTH}: {e}") from e
    entry = data.get(provider)
    if isinstance(entry, dict) and entry.get("key"):
        return entry["key"]
    raise KeyResolutionError(f"no API key for {provider!r} in {OPENCODE_AUTH}")


def try_refresh(key_source: str, timeout: float = 60.0) -> bool:
    """Attempt to refresh a rejected credential through Hermes.

    The forced runtime resolver is tried first: it needs no prompt and no
    ``hermes`` on PATH.  The CLI flow below is the fallback.

    ``hermes auth status nous`` validates expiry but does not force rotation
    of a still-unexpired key that the inference service has rejected.  The
    supported forced-refresh path is ``hermes auth add nous --type oauth``:
    accepting its existing-shared-credential prompt rehydrates the session,
    forces an OAuth refresh, and persists the new inference key.  Feeding one
    newline makes that flow usable by the unattended proxy.

    If the shared OAuth state is absent, do not start a device-code login that
    cannot be completed by a background server.  Other key-source schemes do
    not currently have an unattended refresh path.
    """
    scheme, _, arg = key_source.partition(":")
    if scheme != "hermes" or arg != "nous":
        return False
    if _hermes_resolver_refresh(force=True, timeout=timeout):
        return True
    if not HERMES_SHARED_NOUS_AUTH.exists():
        return False
    hermes = shutil.which("hermes") or str(HERMES_PYTHON.parent / "hermes")
    try:
        proc = subprocess.run(
            [hermes, "auth", "add", "nous", "--type", "oauth",
             "--no-browser", "--timeout", str(max(5, int(timeout) - 5))],
            input="\n", capture_output=True, timeout=timeout, text=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    output = proc.stdout + proc.stderr
    return proc.returncode == 0 and (
        "Imported nous OAuth credentials" in output
        or "Saved nous OAuth device-code credentials" in output
    )


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
