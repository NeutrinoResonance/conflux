"""Minimal replacement core: one explicit execution loop (rebuild work item C).

DeepSeek (Surplus chat, plain OpenAI `tools`) proposes shell actions. Deterministic code
admits each call against the budget, checks each proposal against a permissive policy,
executes it, and owns acceptance: the task's checks are shell commands the harness runs
itself. Every model call's cost is the provider's `buyer_cost_micro`; when absent (or no reply came back) the cost is
ambiguous: the call is `"pending"` at 0 until Surplus's own billing data resolves it (`Budget.resolve`: a usage-export
row settles it, `"export"`; still absent UNBILLED_AFTER_S later, it was not billed, `"unbilled"`), never at list-price
ceilings (MISSION a58a30e). An error reply with no choices and no usage is 0 (`"no_usage"`). After a run, `reconcile`
matches the calls against the Surplus buyer usage export, the authoritative billed cost. Every call requests the
model's maximum output (`max_output`); admission bounds the request's input only, never max_tokens x price
(founder decision MISSION 90b27cd: a capped answer is a harness fault).

Commands run through a `Shell`: `local_shell` (a subprocess in a workdir) or `lab_shell`
(a detached job on a `devbox-lab` VM, polled over ssh, all waits capped by one deadline that
starts when the lab comes up). Every command runs under `pipefail`, and its result carries
`pipestatus`, the exit status of each stage of the last pipeline it ran (founder decision: the
executor must not mask pipeline failures), and `failed_cmds`, the number of simple commands outside
conditions that exited non-zero (shown to the model when the command still exited 0). Labs have
no internet egress, so `run_lab` serves an HTTP proxy on the controller (`egress_proxy`),
reverse-tunnels it to the lab's 127.0.0.1:3128 over ssh, and exports `PROXY_ENV` to every lab command; an egress check gates the first model call.

Terminal statuses: `accepted` (all checks pass), `failed` (checks ran and failed when
steps ran out), `unverified` (no verdict: provider error, budget refusal, check timeout,
transport error, lab deadline). With a lead (`--lead`), a task with no checks ends on a fresh lead's finish review:
DONE is `unverified`/`finish_review_done`, a stop rule, not an acceptance (graded outside the run).

Usage:
  python -m conflux.core run --tasks tests/fixtures/core_loop/tasks.json --out DIR --repeats 2
  python -m conflux.core run --tasks tests/fixtures/core_loop/optee_goal_a.json --out DIR \
      --lab c2 --workdir '~/optee-work' --lab-hours 4
  python -m conflux.core run --tasks TASK.json --out DIR --model deepseek-v4-pro --lead kimi-k3 --lab g1 ...
  python -m conflux.core reconcile --out DIR --day 2026-10-27
  python -m conflux.core audit DIR/*/trace.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import functools
import io
import itertools
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

SECRETS = Path.home() / ".config/devbox/secrets"
LEDGER = Path(__file__).resolve().parents[1] / "docs/rebuild/LEDGER.md"
SURPLUS = "https://www.surplusintelligence.ai/api/inference/v1"
EXPORT = "https://api.surplusintelligence.ai/v1/buyer/usage/export"

MODEL = "deepseek-v4.1-flash"
# Output limit and context per model: the provider's `top_provider.max_completion_tokens` / `context_length` (Surplus
# /models, 2026-10-28). Every call requests the model's maximum (MISSION 90b27cd; 8192 cut off 26/29 slice-34 calls).
MAX_OUTPUT = {"deepseek-v4.1-flash": 384000, "deepseek-v4-pro": 128000, "glm-5.3": 131072, "kimi-k3.1-pro": 943718,
              "glm-5.3-flash": 131072, "kimi-k3": 131072}
CONTEXT = {"deepseek-v4.1-flash": 1048576, "deepseek-v4-pro": 1000000, "glm-5.3": 1000000, "kimi-k3.1-pro": 1048576,
           "glm-5.3-flash": 1048576, "kimi-k3": 1000000}
CONTEXT_MARGIN = 1024
# Input tokens come from the provider's own count (`usage.prompt_tokens + completion_tokens` of the last reply covers the
# message prefix it saw); only messages added since are estimated, at BYTES_PER_TOKEN (JSON/code/English run ~3.5-4.5
# bytes/token on these tokenizers, so 3 errs high). A cold first call is estimated whole (PR #47 review).
BYTES_PER_TOKEN = 3
# Admission bounds per executor: ($/byte of request, $/output token). Tokens <= bytes, so a $/byte above the top input
# list rate bounds input; the bound is traced with each call and never settled as its cost (MISSION a58a30e). Admission
# looks at billed spend alone (`Budget`). An executor without an entry is refused (KeyError).
CEILINGS = {
    "deepseek-v4.1-flash": (4e-7, 2.4e-6),  # top list $0.3/M in, $1.2/M out
    "deepseek-v4-pro": (2e-6, 7.6e-6),      # top list $1.73/M in, $3.796/M out (2026-10-27 /v1/prices, C slice 18)
}
CAMPAIGN_BUDGET = 50.00
MIN_DISCOUNT = 90          # X-Min-Discount on every Surplus request (MISSION 5ee7a8b); never lowered
# Ambiguous costs (MISSION a58a30e): a reply without `buyer_cost_micro` is looked up in the usage export (rows appear
# 1-3 min after a call; one fetch ~2 s, so at most one per BILLING_POLL_S). Still absent UNBILLED_AFTER_S after the
# call, it was not billed: slice 43's 20/20 such replies never reached the export and the balance moved by exactly the
# export total (lead-s1 $0.160438, lead-s2 $0.028633).
BILLING_POLL_S = 60
UNBILLED_AFTER_S = 600
# No seller at the floor / outage (`_unavailable`): retry with backoff for up to AVAILABILITY_WINDOW_S of wall clock
# (bounded by the run deadline); Surplus seller availability fluctuates over minutes to hours (slice 39 pair 1).
AVAILABILITY_BACKOFF_S = (30, 60, 120, 300, 600)   # then the last value repeats
AVAILABILITY_WINDOW_S = 4 * 3600
RUN_CAP = 0.20
EXEC_TIMEOUT = 60
CHAT_TIMEOUT = 900         # flash replies took up to 713 s (headroom demo); the lab deadline still bounds each call
MAX_TIMEOUT = 10800
POLL_S = 5
TRANSPORT_TIMEOUT = 120    # one ssh round trip
TRANSPORT_RETRIES = 3
GRACE = 15                 # kill + output collection after a command's end or the deadline
SSH_WAIT_TRIES = 10
LAB_ZONE = "us-central1-a"
LAB_PREFIX = "conflux-dev-lab-"
LAB_PROXY_PORT = 3128
TUNNEL_RESTART_S = 5
TAIL = 4096               # output returned per stream: its first HEAD and last TAIL - HEAD bytes
HEAD = 1024               # build tools print the cause (e.g. `Permission denied`) first, the summary last
MAX_COMMAND = 8192
MATCH_WINDOW_S = 120

SYSTEM = (
    "You work in a shell workspace; commands run with the workspace as the current directory. "
    "Use run_shell to inspect and change files. Each command times out after 60 s unless you pass "
    "timeout_s (up to 10800); give long downloads, syncs and builds a large timeout_s. "
    "When the task is done, call finish. "
    "The harness then runs the acceptance checks itself and tells you if any fail."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "run_shell",
        "description": "Run one bash command in the workspace and return exit code, stdout and stderr "
                       "(each up to 4 KB; longer output keeps its first 1 KB and last 3 KB around a "
                       "'[... N bytes omitted ...]' line). timeout_s defaults to 60; use up to 10800 for long jobs.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"},
                                                        "timeout_s": {"type": "integer"}},
                       "required": ["command"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Declare the task done; the harness runs the acceptance checks.",
        "parameters": {"type": "object", "properties": {"summary": {"type": "string"}},
                       "additionalProperties": False}}},
]

Chat = Callable[..., tuple[int, object, float]]  # (messages, tools, timeout=None)
# (command, timeout_s) -> {exit, stdout, stderr, timed_out, duration_s, ...}; exit None = no verdict.
Shell = Callable[[str, float], dict]


@dataclass
class Check:
    cmd: str
    expect_stdout: str | None = None
    timeout: float = 30


@dataclass
class Task:
    id: str
    goal: str
    checks: list[Check]
    setup: str = ""
    max_steps: int = 8
    max_usd: float = 0.05
    inject_step: int = 0   # before this step's model call, `inject` goes to the model once as a user message
    inject: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(**{**d, "checks": [Check(**c) for c in d["checks"]]})


class Budget:
    """Run-level money cap on billed cost (MISSION 90b27cd, a58a30e): a call is admitted while the spend so far is below
    the allowance; no per-call bound is reserved. Slice 39b: a 250 KB deepseek-v4-pro request's input bound (~$0.3-0.5)
    refused calls that bill ~$0.0001 and ended a run at step 63 with $0.002 spent. One call may overshoot by its cost.

    A call whose cost is ambiguous is `defer`red (counted at 0) and resolved from Surplus's billing data: `billing(day)`
    returns that UTC day's usage-export rows (`fetch_export`). Without `billing` it stays pending. Calls billed in their
    reply are `observe`d too, so their export rows are reserved and never charged again to a pending call.

    Shared by the executor loop and the lead's review thread: every method holds one re-entrant lock (a deferred
    settlement callback runs inside `resolve`; slice 47's demo deadlocked on a non-reentrant one)."""

    def __init__(self, allowance: float, billing: Callable[[str], list[dict]] | None = None):
        self.lock = threading.RLock()
        self.allowance = allowance
        self.committed = 0.0
        self.billing = billing
        self.pending: list[tuple[dict, Callable[[float, str, str | None], None]]] = []
        self.billed: list[dict] = []  # recent calls billed in their reply, until their export row is reserved
        self.used: set[str] = set()  # export request_ids already matched to a call
        self.polled = float("-inf")

    def admit(self, bound: float) -> bool:
        with self.lock:
            self.resolve()
            return self.committed < self.allowance

    def settle(self, bound: float, cost: float) -> None:
        with self.lock:
            self.committed += cost

    def defer(self, call: dict, on_settle: Callable[[float, str, str | None], None]) -> None:
        """`call` has model, usage (or None) and ts; `on_settle(usd, kind, request_id)` runs once when resolved."""
        with self.lock:
            self.pending.append((call, on_settle))

    def observe(self, call: dict) -> None:
        """A call billed in its reply (model, usage, ts): its export row is reserved when pending calls are matched."""
        with self.lock:
            self.billed.append(call)

    def resolve(self, force: bool = False, now: float | None = None) -> None:
        """Settle pending calls from the usage export: a matched row at its `buyer_cost_usd` (`"export"`), an unmatched
        call older than UNBILLED_AFTER_S at 0 (`"unbilled"`). The billing API being down leaves them pending."""
        with self.lock:
            self._resolve(force, now)

    def _resolve(self, force: bool, now: float | None) -> None:
        now = time.time() if now is None else now
        if not self.pending or self.billing is None or (not force and now - self.polled < BILLING_POLL_S):
            return
        self.polled = now
        # A billed call matters only while a pending call could share its match window.
        self.billed = [c for c in self.billed if c["ts"] >= now - UNBILLED_AFTER_S - 2 * MATCH_WINDOW_S]
        # Every UTC day the match window of a pending call touches (an export row may fall just past midnight).
        days = sorted({datetime.fromtimestamp(c["ts"] + d, timezone.utc).strftime("%Y-%m-%d")
                       for c, _ in self.pending for d in (-MATCH_WINDOW_S, 0, MATCH_WINDOW_S)})
        try:
            rows = {r["request_id"]: r for d in days for r in self.billing(d)}
        except (httpx.HTTPError, OSError, ValueError, KeyError):
            return
        rows = [r for rid, r in rows.items() if rid not in self.used]
        # Billed calls are matched alongside, so a lost reply's time match cannot take a billed retry's row.
        calls = ([{**c, "id": ("p", i)} for i, (c, _) in enumerate(self.pending)]
                 + [{**c, "id": ("b", i)} for i, c in enumerate(self.billed)])
        matched = {m["id"]: m for m in reconcile(calls, rows)["matched"]}
        self.used |= {m["request_id"] for m in matched.values()}
        self.billed = [c for i, c in enumerate(self.billed) if ("b", i) not in matched]
        keep = []
        for i, (c, on_settle) in enumerate(self.pending):
            if ("p", i) in matched:
                m = matched[("p", i)]
                self.committed += m["billed_usd"]
                on_settle(m["billed_usd"], "export", m["request_id"])
            elif now - c["ts"] >= UNBILLED_AFTER_S:
                on_settle(0.0, "unbilled", None)
            else:
                keep.append((c, on_settle))
        self.pending = keep


_TRACE_LOCK = threading.Lock()


@dataclass
class Trace:
    path: Path | None = None
    events: list = field(default_factory=list)

    def write(self, event: str, **fields) -> dict:
        row = {"event": event, "ts": time.time(), **fields}
        with _TRACE_LOCK:  # the lead's review thread settles costs into the executor's trace too
            self.events.append(row)
            if self.path:
                with self.path.open("a") as f:
                    f.write(json.dumps(row) + "\n")
        return row


def billed_cost(body: object) -> float | None:
    """USD the provider says it billed, from `buyer_cost_micro`; None when absent."""
    usage = body.get("usage") if isinstance(body, dict) else None
    v = usage.get("buyer_cost_micro") if isinstance(usage, dict) else None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v / 1e6
    return None


_PS_MARK = "__CONFLUX_PIPESTATUS="
# Prepended to every command. The ERR trap counts failing simple commands outside conditions
# (bash restores `$?` and PIPESTATUS after it). The EXIT trap's first statement copies PIPESTATUS
# (the last pipeline's per-stage exits) into an array before anything resets it; printf prints it
# and the count as the final stderr line with explicit separators, so the command's IFS cannot change it.
PIPEFAIL = ("set -o pipefail\n"
            "__nf=0; trap '__nf=$((__nf+1))' ERR\n"
            f"trap '__ps=(\"${{PIPESTATUS[@]}}\"); "
            f"{{ printf \"\\n{_PS_MARK}\"; printf \"%s \" \"${{__ps[@]}}\"; "
            f"printf \"failed=%s\\n\" \"$__nf\"; }} >&2' EXIT\n")


_OMIT = "\n[... %d bytes omitted ...]\n"


def _wrap(command: str) -> str:
    return PIPEFAIL + command


def _split_pipestatus(stderr: str) -> tuple[str, list[int] | None, int | None]:
    """(stderr without the trailing marker, per-stage exits, failed simple commands); None, None
    when the marker is missing (killed, timed out, or the command replaced the trap or closed stderr).
    The last marker line counts wherever it is: a backgrounded child (`cmd &`) may write after it."""
    m = None
    for m in re.finditer(rf"(?:^|\n){_PS_MARK}([\d ]+)failed=(\d+)(?:\n|$)", stderr):
        pass
    if not m:
        return stderr, None, None
    return stderr[:m.start()] + stderr[m.end():], [int(x) for x in m[1].split()], int(m[2])


def _clip(text: str) -> str:
    """`text` if its UTF-8 fits in TAIL bytes, else its first HEAD and last TAIL - HEAD bytes around an
    omission marker, like `lab_shell`'s head/tail (a character cut at either edge becomes U+FFFD)."""
    b = text.encode()
    if len(b) <= TAIL:
        return text
    return (b[:HEAD].decode(errors="replace") + _OMIT % (len(b) - TAIL)
            + b[-(TAIL - HEAD):].decode(errors="replace"))


def execute(command: str, workdir: Path, timeout: float = EXEC_TIMEOUT) -> dict:
    t0 = time.monotonic()
    try:
        p = subprocess.run(["bash", "-c", _wrap(command)], cwd=workdir, capture_output=True,
                           text=True, errors="replace", timeout=timeout)
        stderr, ps, nf = _split_pipestatus(p.stderr)
        out = {"exit": p.returncode, "stdout": _clip(p.stdout), "stderr": _clip(stderr),
               "pipestatus": ps, "failed_cmds": nf, "timed_out": False}
    except subprocess.TimeoutExpired:
        out = {"exit": None, "stdout": "", "stderr": "", "pipestatus": None, "failed_cmds": None,
               "timed_out": True}
    out["duration_s"] = round(time.monotonic() - t0, 3)
    return out


def local_shell(workdir: Path) -> Shell:
    workdir.mkdir(parents=True, exist_ok=True)
    return lambda command, timeout: execute(command, workdir, timeout)


def local_remote(script: str) -> list[str]:
    """Test seam for `lab_shell`: the remote is this machine."""
    return ["bash", "-c", script]


def gcloud_remote(name: str) -> Callable[[str], list[str]]:
    """argv for one ssh round trip to lab `name`; the whole script is ONE `--command=` value."""
    cm = Path.home() / ".ssh"
    return lambda script: [
        "gcloud", "compute", "ssh", f"{LAB_PREFIX}{name}", f"--zone={LAB_ZONE}", "--internal-ip", "--quiet",
        "--strict-host-key-checking=no",
        "--ssh-flag=-oControlMaster=auto", f"--ssh-flag=-oControlPath={cm}/cm-%C",
        "--ssh-flag=-oControlPersist=10m", "--ssh-flag=-oServerAliveInterval=30",
        f"--command=bash -c {shlex.quote(script)}"]


_PROXY = f"http://127.0.0.1:{LAB_PROXY_PORT}"
_NO_PROXY = "localhost,127.0.0.1,169.254.169.254,metadata.google.internal"
PROXY_ENV = {"http_proxy": _PROXY, "https_proxy": _PROXY, "HTTP_PROXY": _PROXY, "HTTPS_PROXY": _PROXY,
             "no_proxy": _NO_PROXY, "NO_PROXY": _NO_PROXY}
_KEEP = " ".join(PROXY_ENV)
# Harness-owned lab setup: apt and sudo'd commands use the proxy too. The model is not told.
LAB_SETUP = (
    f"echo 'Acquire::http::Proxy \"{_PROXY}\"; Acquire::https::Proxy \"{_PROXY}\";' "
    "| sudo -n tee /etc/apt/apt.conf.d/95conflux-proxy >/dev/null && "
    f"echo 'Defaults env_keep += \"{_KEEP}\"' > /tmp/conflux-proxy.sudoers && "
    "sudo -n install -m 0440 /tmp/conflux-proxy.sudoers /etc/sudoers.d/conflux-proxy && "
    "{ sudo -n visudo -cf /etc/sudoers.d/conflux-proxy || { sudo -n rm -f /etc/sudoers.d/conflux-proxy; false; }; }")
EGRESS_CHECK = (  # waits for the tunnel's listener first
    f"for i in $(seq 30); do (exec 3<>/dev/tcp/127.0.0.1/{LAB_PROXY_PORT}) 2>/dev/null && break; sleep 2; done; "
    "for u in https://github.com https://pypi.org/simple/pip/; do "
    "c=$(curl -sS -o /dev/null -m 30 -w '%{http_code}' \"$u\"); echo \"$u $c\"; "
    "case $c in 2??|3??) ;; *) exit 1;; esac; done; sudo -n apt-get update -q >/dev/null && echo APT_OK")


async def _pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
    """Copy until EOF, then half-close `w` so the other direction can still finish."""
    try:
        while data := await r.read(65536):
            w.write(data)
            await w.drain()
        if w.can_write_eof():
            w.write_eof()
    except (ConnectionError, OSError):
        w.close()


async def _proxy_client(cr: asyncio.StreamReader, cw: asyncio.StreamWriter) -> None:
    """One proxied request: `CONNECT host:port` pipes bytes; absolute-form HTTP is forwarded as one
    request (`Connection: close`, `Proxy-*` headers dropped) and the response piped back."""
    try:
        head = await asyncio.wait_for(cr.readuntil(b"\r\n\r\n"), 60)
        line, *headers = head.decode("latin-1").split("\r\n")[:-2]
        method, target, version = line.split(" ")
        if method == "CONNECT":
            host, _, port = target.rpartition(":")
            ur, uw = await asyncio.wait_for(asyncio.open_connection(host.strip("[]"), int(port)), 30)
            cw.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await cw.drain()
        else:
            m = re.match(r"http://([^/:]+)(?::(\d+))?(/.*)?$", target)
            if not m:
                raise ValueError(target)
            ur, uw = await asyncio.wait_for(asyncio.open_connection(m[1], int(m[2] or 80)), 30)
            keep = [h for h in headers if not re.match(r"(proxy-|connection:)", h, re.I)]
            uw.write("\r\n".join([f"{method} {m[3] or '/'} {version}", *keep, "Connection: close", "", ""])
                     .encode("latin-1"))
    except (OSError, ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
        cw.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
        cw.close()
        return
    await asyncio.gather(_pipe(cr, uw), _pipe(ur, cw))
    cw.close()
    uw.close()


def egress_proxy() -> int:
    """Start the HTTP proxy on 127.0.0.1 in a daemon thread; return its port."""
    loop = asyncio.new_event_loop()
    server = loop.run_until_complete(asyncio.start_server(_proxy_client, "127.0.0.1", 0))
    threading.Thread(target=loop.run_forever, daemon=True).start()
    return server.sockets[0].getsockname()[1]


def gcloud_tunnel(name: str) -> Callable[[int], list[str]]:
    """argv that holds lab `name`'s 127.0.0.1:3128 forwarded to the controller's proxy `port`."""
    return lambda port: [
        "gcloud", "compute", "ssh", f"{LAB_PREFIX}{name}", f"--zone={LAB_ZONE}", "--internal-ip", "--quiet",
        "--strict-host-key-checking=no", "--ssh-flag=-N",
        f"--ssh-flag=-R{LAB_PROXY_PORT}:127.0.0.1:{port}", "--ssh-flag=-oExitOnForwardFailure=yes",
        "--ssh-flag=-oControlPath=none", "--ssh-flag=-oServerAliveInterval=30"]


def _supervise(argv: list[str], log: Path) -> subprocess.Popen:
    """Rerun `argv` whenever it exits, in its own session; every (re)start appends to `log`."""
    script = (f"while :; do echo \"TUNNEL-START $(date -u +%FT%TZ)\" >> {shlex.quote(str(log))}; "
              f"{shlex.join(argv)} >> {shlex.quote(str(log))} 2>&1; sleep {TUNNEL_RESTART_S}; done")
    return subprocess.Popen(["bash", "-c", script], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


def _remote_path(p: str) -> str:
    """Shell word for a remote path; a leading `~/` expands on the remote."""
    return '"$HOME"/' + shlex.quote(p[2:]) if p.startswith("~/") else shlex.quote(p)


def lab_shell(remote: Callable[[str], list[str]], workdir: str, deadline: float | None = None,
              poll_s: float | None = None, env: dict[str, str] | None = None) -> Shell:
    """Run each command as a detached job on the remote; poll for its exit code.

    The job's output lives in `~/.conflux-jobs/<id>/` on the remote, so a dropped ssh session
    loses nothing. Launch is idempotent: `mkdir` of the job dir is an atomic guard, so a retried
    launch recovers the running job's pid instead of starting it again. Launch and polls are
    bounded by `min(command end, deadline)`; killing and collecting output get `GRACE` more.
    Commands run under `pipefail` (`_wrap`), like `execute`. A transport failure that outlasts
    `TRANSPORT_RETRIES` attempts ends the command with no verdict (`exit: None`). Output that could not be fetched is listed in `unavailable`.
    `env` is exported to every job.
    """
    poll_s = POLL_S if poll_s is None else poll_s
    exports = "".join(f"export {k}={shlex.quote(v)}; " for k, v in (env or {}).items())
    lab_end = float("inf") if deadline is None else deadline

    def call(script: str, until: float) -> subprocess.CompletedProcess | None:
        for attempt in range(TRANSPORT_RETRIES):
            limit = min(TRANSPORT_TIMEOUT, until - time.monotonic())
            if limit <= 0:
                return None
            try:
                p = subprocess.run(remote(script), capture_output=True, text=True, errors="replace",
                                   timeout=limit)
            except subprocess.TimeoutExpired:
                continue
            if p.returncode == 0:
                return p
            if attempt + 1 < TRANSPORT_RETRIES:
                time.sleep(max(0.0, min(poll_s, until - time.monotonic())))
        return None

    def shell(command: str, timeout: float) -> dict:
        t0 = time.monotonic()
        stop_at = min(t0 + timeout, lab_end)
        collect_by = stop_at + GRACE
        job = f"{time.time_ns():x}"
        d = f'"$HOME"/.conflux-jobs/{job}'
        out = {"exit": None, "stdout": "", "stderr": "", "pipestatus": None, "failed_cmds": None,
               "timed_out": False, "job": job}

        def done(**kw) -> dict:
            kw.setdefault("deadline", time.monotonic() >= lab_end)
            return {**out, **kw, "duration_s": round(time.monotonic() - t0, 3)}

        if stop_at <= t0:
            return done(timed_out=True)
        b64 = base64.b64encode(_wrap(command).encode()).decode()
        launch = (f"set -e; d={d}; w={_remote_path(workdir)}; mkdir -p \"$HOME/.conflux-jobs\" \"$w\"; "
                  "if mkdir \"$d\" 2>/dev/null; then "
                  f"echo {b64} | base64 -d > \"$d/cmd.sh\"; cd \"$w\"; {exports}"
                  "nohup setsid bash -c 'bash \"$1/cmd.sh\" >\"$1/out\" 2>\"$1/err\"; "
                  "echo $? >\"$1/rc.tmp\"; mv \"$1/rc.tmp\" \"$1/rc\"' _ \"$d\" "
                  "</dev/null >/dev/null 2>&1 & echo $! > \"$d/pid.tmp\"; mv \"$d/pid.tmp\" \"$d/pid\"; fi; "
                  "for i in $(seq 50); do [ -f \"$d/pid\" ] && break; sleep 0.1; done; "
                  "echo \"PID=$(cat \"$d/pid\")\"")
        p = call(launch, stop_at)
        m = re.search(r"^PID=(\d+)$", p.stdout, re.M) if p else None
        if not m:
            # The job may have started before the transport failed: kill it if it did.
            call(f'd={d}; [ -f "$d/pid" ] && kill -KILL -- -"$(cat "$d/pid")" 2>/dev/null; true', collect_by)
            return done(transport_error="launch", timed_out=time.monotonic() >= stop_at)
        pid = m.group(1)
        rc = None
        transport_error = None
        while rc is None and time.monotonic() < stop_at:
            time.sleep(max(0.0, min(poll_s, stop_at - time.monotonic())))
            p = call(f'd={d}; cat "$d/rc" 2>/dev/null || echo RUNNING', stop_at)
            if p is None:
                if time.monotonic() < stop_at:
                    transport_error = "poll"
                break
            last = p.stdout.strip().splitlines()[-1:]
            if last and last[0].isdigit():
                rc = int(last[0])
        if rc is None:  # timeout, deadline or lost transport: kill the whole process group
            call(f"kill -TERM -- -{pid} 2>/dev/null; sleep 1; kill -KILL -- -{pid} 2>/dev/null; true",
                 collect_by)
        tails, unavailable = {}, []
        for stream in ("stdout", "stderr"):
            f = "out" if stream == "stdout" else "err"
            q = call(f'd={d}; f="$d/{f}"; n=$(wc -c 2>/dev/null <"$f") || n=0; '
                     f'if [ "$n" -le {TAIL} ]; then cat "$f" 2>/dev/null; else head -c {HEAD} "$f"; '
                     f'printf {shlex.quote(_OMIT)} $((n - {TAIL})); tail -c {TAIL - HEAD} "$f"; fi; true',
                     collect_by)
            tails[stream] = q.stdout if q else ""
            if q is None:
                unavailable.append(stream)
        if unavailable:
            tails["unavailable"] = unavailable
        tails["stderr"], tails["pipestatus"], tails["failed_cmds"] = _split_pipestatus(tails["stderr"])
        if transport_error:
            return done(**tails, transport_error=transport_error)
        if rc is None:
            return done(**tails, timed_out=True)
        return done(**tails, exit=rc)

    return shell


# ---------------------------------------------------------------- scratch (C slices 55-56)
# A lead's correction is checked in a scratch copy of the task machine before delivery
# (`~/evidence/exec-deliver-demo-2026-10-31/RESULTS.md`). On a lab a scratch is a private mount namespace held by one
# `sleep infinity`: an overlay of the live /home (upper dir under /var/tmp/conflux-scratch) and a private, empty /tmp; job dirs are
# hidden. Writes outside /home and /tmp are not isolated. `kill` only kills a namespace that is not the root one.

SCRATCH_SH = r"""set -u
R=${CONFLUX_SCRATCH_ROOT:-/var/tmp/conflux-scratch}; op=$1; ID=$2; S=$R/$ID
case $ID in ''|*[!A-Za-z0-9_-]*) echo "bad scratch id" >&2; exit 2;; esac
kill_ns() {  # every process in the scratch's mount namespace; fails closed: never the root namespace's
  [ -s "$1/pid" ] || return 0
  sudo -n bash -c 'ns=$(readlink /proc/$1/ns/mnt) || exit 0; root=$(readlink /proc/1/ns/mnt) || exit 0
    [ -n "$ns" ] && [ -n "$root" ] && [ "$ns" != "$root" ] || exit 0
    for d in /proc/[0-9]*; do [ "$(readlink $d/ns/mnt 2>/dev/null)" = "$ns" ] && kill -9 ${d#/proc/} 2>/dev/null; done
    true' _ "$(cat "$1/pid")"
  sleep 1; sudo -n rm -f "$1/pid"
}
case $op in
  kill) kill_ns "$S" ;;
  killall) for d in "$R"/*/; do [ -d "$d" ] && kill_ns "${d%/}"; done; true ;;
  rm) kill_ns "$S"; sudo -n rm -rf "$S" "$S.holder.log"; [ ! -e "$S" ] ;;
  purge) for d in "$R"/*/; do [ -d "$d" ] && kill_ns "${d%/}"; done; sudo -n rm -rf "$R"; [ ! -e "$R" ] ;;
  new)
    [ -f /etc/sudoers.d/zz-conflux-nopty ] || { echo 'Defaults !use_pty' > /tmp/zz-conflux-nopty &&
      sudo -n install -m 0440 /tmp/zz-conflux-nopty /etc/sudoers.d/zz-conflux-nopty &&
      { sudo -n visudo -cf /etc/sudoers.d/zz-conflux-nopty >/dev/null || sudo -n rm -f /etc/sudoers.d/zz-conflux-nopty; }; }
    kill_ns "$S"; sudo -n rm -rf "$S"; sudo -n mkdir -p "$S/up" "$S/wk" "$S/tmp"; sudo -n chmod 1777 "$S/tmp"
    holder='
      set -e
      mount -t overlay overlay -o "lowerdir=/home,upperdir=$1/up,workdir=$1/wk" /home
      mount --bind "$1/tmp" /tmp
      for d in /home/*/.conflux-jobs; do [ -d "$d" ] && mount -t tmpfs none "$d"; done
      echo $$ > "$1/pid.tmp"; mv "$1/pid.tmp" "$1/pid"
      exec sleep infinity'
    # $R is root's: the holder's log is opened by root too (sudo), never by the calling user
    sudo -n bash -c 'exec setsid nohup unshare -m --propagation private bash -c "$1" _ "$2" </dev/null \
      >"$2.holder.log" 2>&1' _ "$holder" "$S" </dev/null >/dev/null 2>&1 &
    for i in $(seq 100); do [ -s "$S/pid" ] && break; sleep 0.1; done
    [ -s "$S/pid" ] || { echo NEW_FAIL; sudo -n cat "$S.holder.log"; exit 1; }
    sudo -n rm -f "$S.holder.log"; echo "PID=$(cat "$S/pid")" ;;
  run)  # run ID B64 WORKDIR: the decoded script as the calling user inside the scratch, cwd WORKDIR (~/ expanded)
    p=$(cat "$S/pid" 2>/dev/null) || { echo "no scratch $ID" >&2; exit 98; }
    exec sudo -n -E nsenter -t "$p" -m -- sudo -n -E -u "$(id -un)" bash -c '
      w=$1; case $w in "~/"*) w=$HOME/${w#"~/"};; esac
      mkdir -p "$w" && cd "$w" || exit 97; exec bash -c "$2"' _ "$4" "$(echo "$3" | base64 -d)" </dev/null ;;
  *) echo "usage: new|run|rm|kill|killall|purge ID" >&2; exit 2 ;;
esac
"""


class ScratchError(RuntimeError):
    pass


class LabScratch:
    """Scratches on the lab behind `shell` (`lab_shell`); scratch commands run in the task `workdir`. Teardown (`rm`,
    `kill_all`, `purge`) goes through `teardown`, a shell whose deadline outlasts the task's (`run_lab`: + TEARDOWN_S),
    so it still runs when the task ended on its deadline; a teardown that did not complete raises ScratchError."""

    describe = ("The scratch is a copy-on-write view of the machine as it is now: your writes under /home and /tmp stay "
                "in the scratch (its /tmp starts empty); writes elsewhere (packages, /etc, mounts) also reach the "
                "agent's machine.")

    def __init__(self, shell: Shell, workdir: str, teardown: Shell | None = None):
        self.shell, self.workdir, self.teardown = shell, workdir, teardown or shell

    def _op(self, *args: str, timeout: float = 300, shell: Shell | None = None) -> dict:
        return (shell or self.shell)("exec bash -c " + shlex.quote(SCRATCH_SH) + " _ "
                                     + " ".join(map(shlex.quote, args)), timeout)

    def _down(self, *args: str) -> None:
        r = self._op(*args, shell=self.teardown)
        if r["exit"] != 0:
            raise ScratchError(f"scratch {' '.join(args)}: exit={r['exit']} timed_out={r['timed_out']} "
                               f"{(r['stdout'] + r['stderr'])[-300:]}")

    def new(self, sid: str) -> None:
        r = self._op("new", sid, timeout=120)
        if r["exit"] != 0 or "PID=" not in r["stdout"]:
            raise ScratchError(f"scratch {sid}: exit={r['exit']} {(r['stdout'] + r['stderr'])[-300:]}")

    def run(self, sid: str, command: str, timeout: float) -> dict:
        b64 = base64.b64encode(_wrap(command).encode()).decode()
        return self._op("run", sid, b64, self.workdir, timeout=timeout)

    def rm(self, sid: str) -> None:
        self._down("rm", sid)

    def kill_all(self) -> None:
        self._down("killall", "-")

    def purge(self) -> None:
        self._down("purge", "-")


class LocalScratch:
    """A scratch is a `cp -a` copy of the workdir (offline tests, local runs). Every command starts its own process
    group, kept per scratch until `rm` (background jobs outlive the command): `rm` and `kill_all` kill the groups."""

    describe = ("The scratch is a copy of the agent's workspace as it is now; paths outside the workspace are the "
                "agent's machine.")

    def __init__(self, workdir: Path, root: Path):
        self.workdir, self.root = workdir, root
        self.groups: dict[str, set[int]] = {}
        self.lock = threading.Lock()

    def new(self, sid: str) -> None:
        d = self.root / sid
        subprocess.run(["rm", "-rf", str(d)], check=True)
        self.root.mkdir(parents=True, exist_ok=True)
        if self.workdir.exists():
            subprocess.run(["cp", "-a", str(self.workdir), str(d)], check=True)
        else:
            d.mkdir()

    def run(self, sid: str, command: str, timeout: float) -> dict:
        t0 = time.monotonic()
        p = subprocess.Popen(["bash", "-c", _wrap(command)], cwd=self.root / sid, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True, errors="replace",
                             start_new_session=True, env={**os.environ, "CONFLUX_SCRATCH": self._mark(sid)})
        with self.lock:
            self.groups.setdefault(sid, set()).add(p.pid)
        timed_out = False
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._kill(p.pid)
            out, err = p.communicate()
        stderr, ps, nf = _split_pipestatus(err)
        killed = p.returncode is not None and p.returncode < 0
        return {"exit": None if timed_out or killed else p.returncode, "stdout": _clip(out), "stderr": _clip(stderr),
                "pipestatus": ps, "failed_cmds": nf, "timed_out": timed_out or killed,
                "duration_s": round(time.monotonic() - t0, 3)}

    def _mark(self, sid: str) -> str:
        return f"{self.root.resolve()}/{sid}"

    @staticmethod
    def _kill(pgid: int) -> None:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _kill_groups(self, sid: str, groups: set[int]) -> None:
        """Kill the processes still in `groups` that carry this scratch's CONFLUX_SCRATCH marker (a group id may have
        been reused by an unrelated process once all of its members ended)."""
        mark = f"CONFLUX_SCRATCH={self._mark(sid)}".encode()
        for proc in Path("/proc").glob("[0-9]*"):
            try:
                pgid = int((proc / "stat").read_text().rsplit(")", 1)[1].split()[2])
                if pgid in groups and mark in (proc / "environ").read_bytes().split(b"\0"):
                    os.kill(int(proc.name), signal.SIGKILL)
            except (OSError, ValueError, IndexError):
                continue

    def rm(self, sid: str) -> None:
        with self.lock:
            groups = self.groups.pop(sid, set())
        self._kill_groups(sid, groups)
        subprocess.run(["rm", "-rf", str(self.root / sid)], check=True)

    def kill_all(self) -> None:
        with self.lock:
            items = [(sid, set(gs)) for sid, gs in self.groups.items()]
        for sid, gs in items:
            self._kill_groups(sid, gs)

    def purge(self) -> None:
        with self.lock:
            sids = list(self.groups)
        for sid in sids:
            self.rm(sid)


def run_checks(checks: list[Check], shell: Shell) -> tuple[str | None, list[dict]]:
    """("pass" | "fail" | None, results). A check that ran and failed beats a timeout."""
    results = []
    for c in checks:
        r = shell(c.cmd, c.timeout)
        if r["timed_out"] or r["exit"] is None or (c.expect_stdout is not None
                                                     and "stdout" in r.get("unavailable", ())):
            ok = None
        else:
            ok = r["exit"] == 0 and (c.expect_stdout is None or r["stdout"].strip() == c.expect_stdout)
        results.append({"cmd": c.cmd, "expect_stdout": c.expect_stdout, "passed": ok, **r})
    if any(r["passed"] is False for r in results):
        return "fail", results
    if any(r["passed"] is None for r in results):
        return None, results
    return "pass", results


TRUNCATED = ("your reply was cut off at the model's output limit (reasoning counts against it); "
             "write large files in several smaller commands")


def reported_tokens(messages: list, body: object) -> tuple[int, int] | None:
    """(messages the reply's usage covers, tokens): the request's messages plus the reply's own assistant turn."""
    usage = body.get("usage") if isinstance(body, dict) else None
    p, c = (usage.get("prompt_tokens"), usage.get("completion_tokens")) if isinstance(usage, dict) else (None, None)
    if isinstance(p, int) and isinstance(c, int) and not isinstance(p, bool) and not isinstance(c, bool):
        return len(messages) + 1, p + c
    return None


def input_tokens(messages: list, tools: list | None, known: tuple[int, int] | None = None) -> int:
    """The provider's count for the known prefix plus an estimate (bytes / BYTES_PER_TOKEN) for the rest."""
    n, base = known if known and known[0] <= len(messages) else (0, 0)
    rest = len(json.dumps({"messages": messages[n:], "tools": tools}).encode())
    return base + -(-rest // BYTES_PER_TOKEN)


def max_output(model: str, messages: list, tools: list | None = None,
               known: tuple[int, int] | None = None) -> int | None:
    """max_tokens for a request: the model's own maximum, less only what the context window cannot hold
    (`input_tokens`). None (omit max_tokens: the provider applies the model maximum) for a model without a
    known limit."""
    cap = MAX_OUTPUT.get(model)
    if cap is None:
        return None
    if model in CONTEXT:
        cap = min(cap, max(1, CONTEXT[model] - input_tokens(messages, tools, known) - CONTEXT_MARGIN))
    return cap


def _truncated(body: object, limit: int | None) -> bool:
    """The reply hit the output limit: finish_reason "length", or completion tokens at the requested limit."""
    choices = body.get("choices") if isinstance(body, dict) else None
    if choices and choices[0].get("finish_reason") == "length":
        return True
    usage = body.get("usage") if isinstance(body, dict) else None
    return limit is not None and isinstance(usage, dict) and (usage.get("completion_tokens") or 0) >= limit


def policy(call: dict) -> tuple[str, dict, str | None]:
    """Deterministic admission of one tool call: (name, args, deny reason or None)."""
    fn = call.get("function") or {}
    name = fn.get("name")
    if name not in ("run_shell", "finish"):
        return str(name), {}, "unknown_tool"
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except json.JSONDecodeError:
        return name, {}, "bad_arguments"
    if not isinstance(args, dict):
        return name, {}, "bad_arguments"
    if name == "run_shell":
        cmd = args.get("command")
        if not isinstance(cmd, str) or not cmd.strip():
            return name, args, "empty_command"
        if len(cmd) > MAX_COMMAND:
            return name, args, "command_too_long"
        t = args.setdefault("timeout_s", EXEC_TIMEOUT)
        if not isinstance(t, int) or isinstance(t, bool) or not 1 <= t <= MAX_TIMEOUT:
            return name, args, "bad_timeout"
    return name, args, None


def _tool_result(r: dict, timeout: float) -> str:
    missing = "".join(f"\n({s} could not be fetched)" for s in r.get("unavailable", ()))
    if r["timed_out"]:
        head = f"timed out after {timeout}s (process group killed)"
    elif r["exit"] is None:
        return (f"no result: transport error ({r.get('transport_error')}); the command was stopped and "
                "may not have run")
    else:
        head = f"exit={r['exit']}"
        if len(r.get("pipestatus") or ()) > 1:
            head += " pipestatus=" + " ".join(map(str, r["pipestatus"]))
        if r["exit"] == 0 and r.get("failed_cmds"):
            head += f" failed_cmds={r['failed_cmds']}"
    return f"{head}\nstdout:\n{r['stdout']}\nstderr:\n{r['stderr']}{missing}"


def _check_feedback(results: list[dict]) -> str:
    lines = ["Acceptance checks failed:"]
    for r in results:
        if r["passed"] is False:
            want = f" (expected stdout {r['expect_stdout']!r})" if r["expect_stdout"] is not None else ""
            lines.append(f"- `{r['cmd']}`{want}: exit={r['exit']}, stdout={r['stdout'][-500:]!r}, "
                         f"stderr={r['stderr'][-500:]!r}")
    lines.append("Fix the work, then call finish again.")
    return "\n".join(lines)


def _goal_text(task: Task) -> str:
    if not task.checks:  # the task text alone (slices 39-43 lead runs: task.txt verbatim, no empty checks header)
        return task.goal
    checks = "\n".join(f"- `{c.cmd}`" + (f" must print {c.expect_stdout!r}" if c.expect_stdout is not None
                                         else " must exit 0") for c in task.checks)
    return f"{task.goal}\n\nAcceptance checks (run by the harness in the workspace):\n{checks}"


# ---------------------------------------------------------------- lead (C slices 39-48)
# A different-family model reviews the executor's trace every CADENCE_S of wall clock without blocking it (MISSION
# a594bbc), in the conversation layout (cda6dac): the data first, then one goal per turn, then the request. It keeps
# its own goal list (`GOAL: ` lines) and notes; its reply reaches the executor at the next turn. On a task with no
# checks, finish (and the step cap) is judged by a *fresh* lead: own init review, none of the running lead's notes,
# goal list or messages (slice 48: the live false DONE came from the run-long notes, 3/6 vs 0/6). Model, effort,
# cadence, layout and prompt text are the measured ones (`~/evidence/step-cap-demo-2026-10-29/demo.py`, slice 43).

LEAD = "kimi-k3"
LEAD_EFFORT = "low"   # glm-5.3/kimi-k3 low: reviews ~2-4 min (default effort 17-20 min, MISSION a594bbc)
CADENCE_S = 300       # a new review at most every 5 min of wall clock; never more than one in flight
LEAD_TIMEOUT = 1800
CLIP_OUT = 1500
CLIP_REASON = 1500
WINDOW_MAX = 60_000
INDEX_LINE = 200
CLIP_ANSWER = 2500
MAX_GOALS = 12
LEAD_SYSTEM = ("You supervise an agent that works through a shell on a lab machine toward the user's task. "
               "You cannot run commands yourself. The agent receives your final reply verbatim as a message from "
               "its supervisor.")
FINISH_ASK = "If the whole task is done and proven, make the last line of your reply exactly DONE."
GOAL_FORMAT = "one goal per line, each line starting with `GOAL: `"
INIT_ASK = f"From this, write our goal list ({GOAL_FORMAT}). Then give the agent its next steps."
FIRST_GOAL = "Check where we are with regard to our goals. Goal 1 of {n}:\nGOAL: {g}"
NEXT_GOAL = "Goal {i} of {n}:\nGOAL: {g}"
FINAL_ASK = (f"Now write the updated goal list ({GOAL_FORMAT}; revise, split, add or drop goals as the evidence "
             "requires) and give the agent its next steps.")
GOAL_RE = re.compile(r"(?m)^[ \t]*(?:[-*][ \t]*)?\**GOAL\**[ \t]*:\**[ \t]*(.+?)[ \t]*$")
PREFIX = "Message from your supervisor (a different model reviewing your work):\n\n"
CAP_SUMMARY = "(no finish: the step limit was reached)"

# Verify session (C slice 55's measured mechanism; texts and limits are the demo's, `demo.py` ASK/REPLAY_FB/FORCE/NUDGE):
# after a running review the lead gets `run_shell` on a persistent scratch and `deliver(commands, note)`; the harness
# replays the selection on a fresh scratch; one feedback turn if a replayed command fails; after it, the next selection
# is delivered whatever its replay. The scratch's own `describe` replaces the demo's sentence about how it was built.
VERIFY_MAX_CMDS = 40
VERIFY_EXTRA = 10
VERIFY_MAX_CALLS = 90
VERIFY_CMD_TIMEOUT = 1800
VERIFY_WALL_S = 6000
TEARDOWN_S = 600         # run_lab: scratch teardown may run this long past the task deadline
KILL_JOIN_S = 5         # Steering.close: kill scratch commands, wait this long, repeat while the review runs
VERIFY_ASK = ("Before your reply reaches the agent, check it in a scratch copy of the lab machine. {describe} Run "
              "commands in the scratch with run_shell, as the agent would; the scratch keeps its state between your "
              f"commands (files, builds, background jobs). Each result is numbered [command #N]; you have at most "
              f"{VERIFY_MAX_CMDS} commands. When your correction works, call deliver with the numbers of the commands "
              "that, run in that order on a fresh copy of the machine, carry it out, and a note for the agent. The "
              "harness re-runs exactly those commands on a fresh copy before delivery; the agent receives those "
              "commands verbatim and your note.")
REPLAY_FB = ("The harness re-ran your selected commands, in order, on a fresh copy of the machine. A command failed, "
             "so nothing was delivered. Results:\n\n{results}\n\nYour scratch is unchanged. Continue there "
             f"(up to {VERIFY_EXTRA} more commands), then call deliver again.")
VERIFY_FORCE = "Command limit reached: call deliver now."
VERIFY_NUDGE = "Call deliver to hand your correction to the agent."
DELIVER_HEAD = ("Your supervisor ran these commands in a scratch copy of the machine, and the harness re-ran them on a "
                "fresh copy. Run them in this order:")
SCRATCH_RUN_TOOL = {"type": "function", "function": {
    "name": "run_shell",
    "description": "Run one bash command in the scratch copy and return exit code, stdout and stderr (each up to 4 KB; "
                   "longer output keeps its first 1 KB and last 3 KB around a '[... N bytes omitted ...]' line). "
                   f"timeout_s defaults to 60; use up to {VERIFY_CMD_TIMEOUT} for long jobs.",
    "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "timeout_s": {"type": "integer"}},
                   "required": ["command"], "additionalProperties": False}}}
DELIVER_TOOL = {"type": "function", "function": {
    "name": "deliver",
    "description": "Hand the correction to the agent: the numbers of your scratch commands to run, in order, and a note.",
    "parameters": {"type": "object", "properties": {"commands": {"type": "array", "items": {"type": "integer"}},
                                                    "note": {"type": "string"}},
                   "required": ["commands"], "additionalProperties": False}}}


def deliver_text(reply: str, delivery: dict | None) -> str:
    """The message the executor receives: the review reply, then (when a selection was delivered) the note and the
    replayed commands verbatim, in the selected order."""
    if not delivery:
        return PREFIX + reply
    parts = [PREFIX + reply]
    if delivery.get("note"):
        parts.append(f"Note from your supervisor:\n{delivery['note']}")
    parts.append(DELIVER_HEAD)
    parts += [f"{j}. (timeout_s {c['timeout_s']})\n```bash\n{c['command']}\n```"
              for j, c in enumerate(delivery["commands"], 1)]
    return "\n\n".join(parts)


def _clip_head(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + f"\n[... {len(s) - n} chars clipped]"


def _clip_tail(s: str, n: int) -> str:
    return s if len(s) <= n else f"[{len(s) - n} chars clipped ...]\n" + s[-n:]


def command_index(messages: list) -> str:
    """One line per executed tool call over the whole run: step, result head, command."""
    lines, step, pending = [], 0, {}
    for m in messages:
        if m["role"] == "assistant":
            step += 1
            for c in m.get("tool_calls") or []:
                fn = c.get("function") or {}
                try:
                    cmd = json.loads(fn.get("arguments") or "{}").get("command", "")
                except (json.JSONDecodeError, AttributeError):
                    cmd = fn.get("arguments") or ""
                pending[c.get("id", "")] = (step, fn.get("name"), str(cmd))
        elif m["role"] == "tool" and m.get("tool_call_id", "") in pending:
            s, name, cmd = pending.pop(m["tool_call_id"])
            head = (m.get("content") or "").split("\n", 1)[0][:60]
            what = " ".join(cmd.split()) if name == "run_shell" else f"<{name}>"
            lines.append(f"{s:>3} | {head} | {what[:INDEX_LINE]}")
    return "\n".join(lines)


def activity(messages: list, start: int, hide: set[str]) -> str:
    """Executor turns and tool results from message index `start` on, newest kept if over WINDOW_MAX. User messages
    whose text is in `hide` (the running lead's own replies) are left out."""
    parts, step = [], sum(m["role"] == "assistant" for m in messages[:start])
    for m in messages[start:]:
        if m["role"] == "assistant":
            step += 1
            bits = [f"### step {step}"]
            if m.get("reasoning_content"):
                bits.append("agent reasoning (tail):\n" + _clip_tail(m["reasoning_content"], CLIP_REASON))
            if m.get("content"):
                bits.append("agent says:\n" + m["content"])
            for c in m.get("tool_calls") or []:
                fn = c.get("function") or {}
                bits.append(f"agent calls {fn.get('name')}: {_clip_head(fn.get('arguments') or '', 3000)}")
            parts.append("\n".join(bits))
        elif m["role"] == "tool":
            parts.append("result:\n" + _clip_head(m.get("content") or "", CLIP_OUT))
        elif m["role"] == "user" and m["content"] not in hide:
            parts.append("harness message to the agent:\n" + _clip_head(m["content"], CLIP_OUT))
    return _clip_tail("\n\n".join(parts), WINDOW_MAX)


def lead_data(task_text: str, notes: str, messages: list, start: int, finish_summary: str | None,
              hide: set[str]) -> str:
    """Conversation layout, first message: 'Analyze this:' and all the data; no request yet."""
    idx = command_index(messages)
    act = activity(messages, start, hide)
    text = (f"Analyze this:\n\nThe user's task (verbatim):\n{task_text.strip()}\n\n"
            f"Your notes from your last review (progress per goal, next steps you gave):\n"
            f"{notes or '(none: the run is starting)'}\n\n"
            f"All agent commands so far (step | result | command):\n{idx or '(none)'}\n\n"
            f"Agent activity since your last review:\n{act or '(none)'}")
    if finish_summary is not None:
        text += f"\n\nThe agent has called finish with this summary:\n{finish_summary}"
    return text


def parse_goals(text: str) -> list[str]:
    return [g.strip("* ") for g in GOAL_RE.findall(text) if g.strip("* ")][:MAX_GOALS]


def upto(messages: list, step: int) -> list:
    """Messages through executor step `step` (its tool results and the messages that follow them included)."""
    n, out = 0, []
    for m in messages:
        if m["role"] == "assistant":
            n += 1
            if n > step:
                break
        out.append(m)
    return out


def reply_text(status: int, body: object) -> str | None:
    """Usable lead reply: HTTP 200, content present, not cut off."""
    if status != 200 or not isinstance(body, dict) or not body.get("choices"):
        return None
    ch = body["choices"][0]
    content = ((ch.get("message") or {}).get("content") or "").strip()
    if not content or ch.get("finish_reason") == "length":
        return None
    return content


def surplus_lead(key: str, model: str = LEAD, effort: str | None = LEAD_EFFORT,
                 http: httpx.Client | None = None) -> Callable[..., tuple[int, object, float]]:
    """Lead requests through `surplus_post`: the discount floor and the model's own maximum output; `tools` only in
    a verify session."""
    http = http or httpx.Client(timeout=LEAD_TIMEOUT)

    def call(messages: list, timeout: float | None = None, tools: list | None = None) -> tuple[int, object, float]:
        n = max_output(model, messages, tools)
        return surplus_post(http, key, {"model": model, "messages": messages, **({"tools": tools} if tools else {}),
                                        **({"max_tokens": n} if n else {}),
                                        **({"reasoning_effort": effort} if effort else {})}, timeout, LEAD_TIMEOUT)
    return call


class Lead:
    """One lead: its goal list, notes and the messages it has seen; every request is admitted on the run's Budget and
    traced (`lead_call`, `lead_goals`). With no goal list yet a review is one turn (data + INIT_ASK); otherwise data +
    goal 1, one turn per goal, then FINAL_ASK. `ask` returns the final answer (None when a turn got no reply).
    `hide` is the set of the running lead's injected messages, left out of every lead's activity."""

    def __init__(self, call: Callable[..., tuple[int, object, float]], model: str, budget: Budget, trace: Trace,
                 task_text: str, hide: set[str], role: str = "running", deadline: float | None = None,
                 on_cost: Callable[[float], None] | None = None, may_spend: Callable[[], bool] | None = None):
        self.call, self.model, self.budget, self.trace, self.task_text = call, model, budget, trace, task_text
        self.hide, self.role, self.deadline, self.on_cost = hide, role, deadline, on_cost or (lambda usd: None)
        self.may_spend = may_spend or (lambda: True)  # the task's own cap (executor + lead spend)
        self.stopped = False  # set when the task ends: no further call starts
        self.notes, self.goals, self.seen, self.calls = "", [], 0, 0
        self.convo: list = []
        self.cancel_verify = False  # set while a finish review supersedes the running review (Steering)

    def _settled(self, step: int, turn: str, usd: float, kind: str, request_id: str | None) -> None:
        self.trace.write("lead_cost_resolved", role=self.role, step=step, turn=turn, cost_usd=usd, cost_kind=kind,
                         request_id=request_id)
        self.on_cost(usd)

    def _charge(self, status: int, body: object, step: int, turn: str) -> tuple[float, str, dict | None]:
        """Account one reply on the run's Budget: billed, no_usage, or pending until Surplus's billing data resolves
        it (MISSION a58a30e). (cost, kind, usage)."""
        settle = functools.partial(self._settled, step, turn)
        c, kind = billed_cost(body), "billed"
        usage = body.get("usage") if isinstance(body, dict) else None
        usage = usage if isinstance(usage, dict) else None
        for ts in (body.get("conflux_lost") or []) if isinstance(body, dict) else []:
            self.budget.defer({"model": self.model, "ts": ts, "usage": None}, settle)
        if c is None and status != 0 and not (isinstance(body, dict) and body.get("choices")) and not usage:
            c, kind = 0.0, "no_usage"
        if c is None:
            c, kind = 0.0, "pending"
            self.budget.defer({"model": self.model, "ts": time.time(), "usage": usage}, settle)
        elif kind == "billed" and usage:
            self.budget.observe({"model": self.model, "ts": time.time(), "usage": usage})
        self.budget.settle(0.0, c)
        self.on_cost(c)
        self.calls += 1
        return c, kind, usage

    def _turn(self, convo: list, step: int, turn: str, finish: bool) -> str | None:
        for attempt in (1, 2):
            if self.stopped:
                self.trace.write("lead_stopped", role=self.role, step=step, turn=turn)
                return None
            if not self.budget.admit(0.0) or not self.may_spend():
                self.trace.write("lead_denied", role=self.role, step=step, turn=turn, attempt=attempt)
                return None
            left = None if self.deadline is None else self.deadline - time.monotonic()
            if left is not None and left <= 0:
                self.trace.write("lead_deadline", role=self.role, step=step, turn=turn)
                return None
            status, body, lat = self.call(convo, left)
            c, kind, usage = self._charge(status, body, step, turn)
            text = reply_text(status, body)
            ch = (body.get("choices") or [{}])[0] if isinstance(body, dict) else {}
            msg = ch.get("message") or {}
            self.trace.write("lead_call", role=self.role, step=step, turn=turn, attempt=attempt, model=self.model,
                             status=status, id=body.get("id") if isinstance(body, dict) else None,
                             latency_s=round(lat, 3), usage=usage, cost_usd=c, cost_kind=kind, finish=finish,
                             prompt_chars=sum(len(m["content"]) for m in convo), finish_reason=ch.get("finish_reason"),
                             reasoning_chars=len(msg.get("reasoning_content") or msg.get("reasoning") or ""),
                             ask=convo[-1]["content"][-400:], reply=text, error=None if text else str(body)[:500])
            if text:
                return text
        return None

    def ask(self, messages: list, step: int, finish_summary: str | None = None) -> str | None:
        fin = finish_summary is not None
        data = lead_data(self.task_text, self.notes, messages, self.seen, finish_summary, self.hide)
        goals = list(self.goals)
        asks = ([("init", data + "\n\n" + INIT_ASK + (f"\n\n{FINISH_ASK}" if fin else ""))] if not goals else
                [(f"goal{i}", (data + "\n\n" + FIRST_GOAL.format(n=len(goals), g=g)) if i == 1 else
                  NEXT_GOAL.format(i=i, n=len(goals), g=g)) for i, g in enumerate(goals, 1)]
                + [("final", FINAL_ASK + (f"\n\n{FINISH_ASK}" if fin else ""))])
        convo = [{"role": "system", "content": LEAD_SYSTEM}]
        answers, text = [], None
        for turn, content in asks:
            convo.append({"role": "user", "content": content})
            text = self._turn(convo, step, turn, fin)
            if text is None:
                self.trace.write("lead_no_reply", role=self.role, step=step, turn=turn)
                return None
            convo.append({"role": "assistant", "content": text})
            if turn.startswith("goal"):
                answers.append(f"GOAL: {goals[int(turn[4:]) - 1]}\n{_clip_head(text, CLIP_ANSWER)}")
        new = parse_goals(text)
        self.trace.write("lead_goals", role=self.role, step=step, goals=new or goals, parsed=len(new),
                         kept_previous=not new)
        self.goals = new or goals
        self.notes = "\n\n".join(answers + [f"Your final answer last time:\n{text}"])
        self.seen = len(messages)
        self.convo = convo  # the review conversation, final answer included (`verify` continues it)
        return text

    def verify(self, step: int, scratch, wall_s: float = VERIFY_WALL_S) -> dict | None:
        """Continue the last review in a verify session (C slice 55): `run_shell` on a persistent scratch, then
        `deliver`; the selection is replayed on a fresh scratch. Returns {ids, note, commands, replay_ok} or None (no
        delivery: no deliver call, empty selection, stopped, budget, deadline, provider or scratch error). Every call
        is admitted, accounted and traced like a review turn; every scratch is removed on exit."""
        t_start = time.monotonic()
        tag = f"v{step}-{time.time_ns() % 16 ** 8:08x}"
        msgs = list(self.convo) + [{"role": "user", "content": VERIFY_ASK.format(describe=scratch.describe)}]
        cmds: list[dict] = []
        made: list[str] = []
        limit, forced, nudged, fb_used = VERIFY_MAX_CMDS, False, False, False
        calls, replays, why, out = 0, 0, None, None

        def new(sid: str) -> None:
            made.append(sid)
            scratch.new(sid)

        def replay(ids: list[int]) -> tuple[bool, str]:
            nonlocal replays
            replays += 1
            sid = f"{tag}-r{replays}"
            new(sid)
            res = []
            for k, i in enumerate(ids, 1):
                if self.stopped or self.cancel_verify:
                    raise _Stopped
                c = cmds[i - 1]
                r = scratch.run(sid, c["command"], c["timeout_s"])
                res.append((k, i, r, c["timeout_s"]))
            scratch.rm(sid)
            ok = all(r["exit"] == 0 and not r["timed_out"] for _, _, r, _ in res)
            self.trace.write("scratch_replay", role=self.role, step=step, k=replays, ids=ids, ok=ok,
                             exits=[r["exit"] for _, _, r, _ in res])
            report = "\n\n".join(f"[replay {k} of {len(res)}: your command #{i}]\n{_tool_result(r, t)}"
                                 for k, i, r, t in res) or "(no commands selected)"
            return ok, report

        try:
            new(f"{tag}-s")
            while True:
                if calls >= VERIFY_MAX_CALLS:
                    why = "max_calls"
                    break
                if self.stopped or self.cancel_verify:
                    raise _Stopped
                if not self.budget.admit(0.0) or not self.may_spend():
                    why = "budget"
                    break
                left = max(60.0, wall_s - (time.monotonic() - t_start) + 1800)
                if self.deadline is not None:
                    left = min(left, self.deadline - time.monotonic())
                    if left <= 0:
                        why = "deadline"
                        break
                tools = [DELIVER_TOOL] if forced else [SCRATCH_RUN_TOOL, DELIVER_TOOL]
                status, body, lat = self.call(msgs, left, tools=tools)
                calls += 1
                turn = f"verify{calls}"
                c, kind, usage = self._charge(status, body, step, turn)
                ch = (body.get("choices") or [{}])[0] if isinstance(body, dict) and body.get("choices") else {}
                msg = ch.get("message") or {}
                reasoning = msg.get("reasoning_content") or msg.get("reasoning")
                tcs = msg.get("tool_calls") or []
                self.trace.write("lead_call", role=self.role, step=step, turn=turn, attempt=1, model=self.model,
                                 status=status, id=body.get("id") if isinstance(body, dict) else None,
                                 latency_s=round(lat, 3), usage=usage, cost_usd=c, cost_kind=kind, finish=False,
                                 tools=[t["function"]["name"] for t in tools], n_tool_calls=len(tcs),
                                 finish_reason=ch.get("finish_reason"), reasoning_chars=len(reasoning or ""),
                                 reply=msg.get("content"), error=None if ch else str(body)[:500])
                if status != 200 or not ch or ch.get("finish_reason") == "length":
                    why = f"provider_{status}" if status != 200 or not ch else "truncated"
                    break
                a = {"role": "assistant", "content": msg.get("content") or ""}
                if tcs:
                    a["tool_calls"] = tcs
                if reasoning:
                    a["reasoning_content"] = reasoning
                msgs.append(a)
                if not tcs:
                    if nudged:
                        why = "no_deliver"
                        break
                    msgs.append({"role": "user", "content": VERIFY_NUDGE})
                    nudged = True
                    continue
                delivered, note, pending = None, None, None
                for tc in tcs:
                    fn = tc.get("function") or {}
                    name = fn.get("name")
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = None
                    tm = {"role": "tool", "tool_call_id": tc.get("id", ""), "content": ""}
                    if not isinstance(args, dict):
                        tm["content"] = "invalid arguments: expected a JSON object"
                    elif name == "run_shell" and not forced:
                        cmd, t = args.get("command"), args.get("timeout_s", EXEC_TIMEOUT)
                        if not isinstance(cmd, str) or not cmd.strip():
                            tm["content"] = "invalid arguments: empty command"
                        elif len(cmd) > MAX_COMMAND:
                            tm["content"] = f"invalid arguments: command longer than {MAX_COMMAND} bytes"
                        elif not isinstance(t, int) or isinstance(t, bool) or t < 1:
                            tm["content"] = "invalid arguments: timeout_s must be a positive integer"
                        elif len(cmds) >= limit:
                            tm["content"] = "command limit reached; command not run"
                        else:
                            if self.stopped or self.cancel_verify:
                                raise _Stopped
                            t = min(t, VERIFY_CMD_TIMEOUT)
                            r = scratch.run(f"{tag}-s", cmd, t)
                            cmds.append({"command": cmd, "timeout_s": t})
                            self.trace.write("scratch_exec", role=self.role, step=step, n=len(cmds), command=cmd,
                                             timeout_s=t, **r)
                            tm["content"] = f"[command #{len(cmds)}]\n" + _tool_result(r, t)
                    elif name == "deliver" and delivered is None:
                        ids = args.get("commands")
                        if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool)
                                                                for i in ids):
                            tm["content"] = "invalid arguments: commands must be a list of command numbers"
                        elif bad := [i for i in ids if not 1 <= i <= len(cmds)]:
                            tm["content"] = f"invalid command numbers {bad}; run so far: 1..{len(cmds)}"
                        else:
                            delivered, note, pending = ids, args.get("note"), tm
                    else:
                        tm["content"] = f"tool {name} is not available now"
                    msgs.append(tm)
                if delivered is not None:
                    ok, report = replay(delivered)
                    if ok or fb_used:
                        pending["content"] = "delivered"
                        why = "delivered" if delivered else "empty_selection"
                        if delivered:
                            out = {"ids": delivered, "note": note if isinstance(note, str) else None,
                                   "commands": [cmds[i - 1] for i in delivered], "replay_ok": ok}
                        break
                    pending["content"] = REPLAY_FB.format(results=report)
                    fb_used, forced = True, False
                    limit = len(cmds) + VERIFY_EXTRA
                    continue
                if not forced and (len(cmds) >= limit or time.monotonic() - t_start >= wall_s):
                    forced = True
                    msgs.append({"role": "user", "content": VERIFY_FORCE})
        except _Stopped:
            why, out = "stopped", None
        except ScratchError as e:
            why, out = "scratch_error", None
            self.trace.write("lead_error", role=self.role, step=step, error=str(e)[:500])
        finally:
            for sid in made:
                try:
                    scratch.rm(sid)
                except Exception as e:  # cleanup must not hide the session's result
                    self.trace.write("lead_error", role=self.role, step=step, error=f"scratch rm {sid}: {e!r}"[:500])
        self.trace.write("lead_deliver", role=self.role, step=step, why=why, ids=out and out["ids"],
                         note=out and out["note"], replay_ok=out and out["replay_ok"], n_cmds=len(cmds), calls=calls,
                         replays=replays, feedback=fb_used, wall_s=round(time.monotonic() - t_start, 1))
        return out


class _Stopped(Exception):
    """The task ended, or a finish review superseded the review, during a verify session: no delivery."""


class Steering:
    """The running lead, never blocking the executor (MISSION a594bbc). At each executor turn (`turn`) a finished
    review's reply is appended to the messages first; then, if no review is in flight and CADENCE_S has passed since
    the last one started (or none has), a review starts in a thread on a snapshot of the messages."""

    def __init__(self, lead: Lead, cadence_s: float = CADENCE_S, scratch=None):
        self.lead, self.cadence_s, self.scratch = lead, cadence_s, scratch
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.reply: tuple | None = None
        self.inflight = False  # a review started and its reply not yet taken
        self.started: float | None = None
        self.n = 0

    def _review(self, snapshot: list, step: int, n: int, t0: float) -> None:
        try:
            text = self.lead.ask(snapshot, step)
        except Exception as e:  # a review thread must never take the run down; the executor goes on without it
            self.lead.trace.write("lead_error", step=step, review=n, error=repr(e)[:500])
            text = None
        delivery = None
        if text and self.scratch is not None and not self.lead.stopped and not self.lead.cancel_verify:
            try:  # the review's correction is checked in a scratch before it reaches the executor (C slice 55)
                delivery = self.lead.verify(step, self.scratch)
            except Exception as e:
                self.lead.trace.write("lead_error", step=step, review=n, error=repr(e)[:500])
        with self.lock:
            self.reply = (text, n, step, time.monotonic() - t0, delivery)

    def turn(self, messages: list, step: int) -> None:
        # One critical section: a review is "in flight" until its reply is taken here, so a review finishing during
        # this turn can never let a successor start (and overwrite its reply) before that reply is injected.
        with self.lock:
            done, self.reply = self.reply, None
            if done is not None:
                self.inflight = False
            start = not self.inflight and not self.lead.stopped and (
                self.started is None or time.monotonic() - self.started >= self.cadence_s)
            if start:
                self.inflight = True
                self.n += 1
                self.started = time.monotonic()
        if done and done[0]:
            content = deliver_text(done[0], done[4])
            self.lead.hide.add(content)
            messages.append({"role": "user", "content": content})
            self.lead.trace.write("lead_inject", step=step, review=done[1], reviewed_step=done[2],
                                  review_s=round(done[3], 1), chars=len(done[0]),
                                  delivered=done[4]["ids"] if done[4] else None)
        if start:
            snap = json.loads(json.dumps(messages))
            self.thread = threading.Thread(target=self._review, args=(snap, step, self.n, self.started), daemon=True)
            self.lead.trace.write("lead_start", step=step, review=self.n)
            self.thread.start()

    def _drain(self, step: int, event: str) -> None:
        """Wait for an in-flight review (its call is accounted when it returns) and drop its reply."""
        if self.thread is not None:
            self.thread.join()
        with self.lock:
            if self.reply is not None:
                self.lead.trace.write(event, step=step, review=self.reply[1])
            self.reply, self.inflight = None, False

    def _cancel_scratch(self, step: int) -> None:
        """While the review thread runs: kill its scratch commands (again, if one started after the last kill) so it
        reaches a cancellation check promptly; an in-flight model call completes and is accounted."""
        while self.scratch is not None and self.thread is not None and self.thread.is_alive():
            try:
                self.scratch.kill_all()
            except Exception as e:
                self.lead.trace.write("lead_error", step=step, error=f"scratch kill_all: {e!r}"[:500])
                break
            self.thread.join(KILL_JOIN_S)

    def settle_for_finish(self, step: int) -> None:
        """Before a finish review: the finish review supersedes an in-flight review's reply, and its verify session is
        cancelled (no delivery)."""
        self.lead.cancel_verify = True
        try:
            self._cancel_scratch(step)
            self._drain(step, "lead_superseded")
        finally:
            self.lead.cancel_verify = False

    def close(self, step: int) -> None:
        """At the task's end, on every exit path: no new review or call starts; an in-flight call completes and is
        accounted before the task's results are written."""
        self.lead.stopped = True
        self._cancel_scratch(step)
        self._drain(step, "lead_dropped")
        if self.scratch is not None and self.n:
            try:  # backstop: no scratch outlives its task (each session already removes its own)
                self.scratch.purge()
            except Exception as e:
                self.lead.trace.write("lead_error", step=step, error=f"scratch purge: {e!r}"[:500])


# ---------------------------------------------------------------- self-audit (work item F, D1)

FAIL_TEXT = re.compile(r"(?im)^.*\b(error|failed|fatal|cannot|can't|no such file|not found|denied|"
                       r"undefined reference|traceback|exception|\*\*\*)\b.*$")
BENIGN_TEXT = re.compile(r"(?i)^\s*MAKECONF file:.*\(File not found\)\s*$")  # NetBSD build.sh banner, every run
# awk is a read only when its whole program is inline and cannot run commands: no system(), no `|` (command pipes;
# _scan already split the unquoted ones off, so a `|` left in the segment is inside the program), and no program
# source D1 cannot see (`-f`/`--file`, gawk `-E`/`--exec`, `-i`/`--include`, `@include`).
READ_ONLY = re.compile(r"^(cat|head|tail|sed -n|less|grep|rg|ls|find|wc|stat|file|readlink|du|df|echo|pwd|which|ps|tr|tac|"
                       r"awk(?![^|]*(\bsystem\s*\(|\||\s-[a-zA-Z]*[fEi]|\s--(file|exec|include)|@include))|"
                       r"type|command -v|git( -[cC] \S+)* (log|show|diff|status|branch|remote|rev-parse|ls-files)|"
                       r"apt(-cache)? (search|show|list|policy)|dpkg (-l|-s|-L)|od|xxd|hexdump|"
                       r"(\S*/)?([\w.]+-)*(objdump|readelf|nm|strings)|(\S*/)?[\w.-]*make( \S+)* -n|sleep)\b")


def _scan(cmd: str) -> tuple[list[str], bool]:
    """(segments, captures_status). Segments: the command split on `;` `&&` `||` `|` and newlines outside quotes,
    comments, empty and `cd` segments dropped. captures_status: some `$?` is expanded by the shell (not single
    quoted, escaped or commented)."""
    segs, cur, quote, status, i = [], "", None, False, 0
    while i < len(cmd):
        ch = cmd[i]
        if ch == "\\" and quote != "'":
            cur += cmd[i:i + 2]
            i += 2
            continue
        if quote:
            quote = None if ch == quote else quote
        elif ch == "#" and (not cur or cur[-1].isspace()):
            while i < len(cmd) and cmd[i] != "\n":
                i += 1
            continue
        elif ch in "'\"":
            quote = ch
        elif ch in ";|\n" or cmd.startswith("&&", i):
            segs.append(cur)
            cur = ""
            i += 2 if cmd.startswith(("&&", "||"), i) else 1
            continue
        if quote != "'" and cmd.startswith("$?", i):
            status = True
        cur += ch
        i += 1
    segs.append(cur)
    return [s.strip() for s in segs if s.strip() and not re.match(r"cd(\s|$)", s.strip())], status


def audit(rows: list[dict]) -> list[dict]:
    """D1: a model step that exited 0 although its own output reports a failure, i.e. a failure that looked like
    success. Exempt: the model capturing `$?` itself, and `failed_cmds` > 0 (the result header named the failure).
    For pure reads only stderr counts (stdout is file content); known informational lines (`BENIGN_TEXT`) never
    count."""
    findings = []
    for r in rows:
        if r.get("event") != "exec" or r.get("source") != "model" or r.get("exit") != 0 or r.get("failed_cmds"):
            continue
        cmd = r.get("command") or ""
        segs, status = _scan(cmd)
        if status:
            continue
        reads = bool(segs) and all(READ_ONLY.match(s) for s in segs)
        text = ("" if reads else (r.get("stdout") or "")) + "\n" + (r.get("stderr") or "")
        hits = [h for h in FAIL_TEXT.finditer(text) if not BENIGN_TEXT.match(h.group(0))]
        if hits:
            findings.append({"check": "D1", "step": r.get("step"), "command": cmd[:200],
                             "evidence": hits[-1].group(0).strip()[:200]})
    return findings

def run_task(task: Task, chat: Chat, shell: Shell, trace: Trace, budget: Budget,
             model: str = MODEL, deadline: float | None = None,
             lead_call: Callable[..., tuple[int, object, float]] | None = None, lead_model: str = LEAD,
             cadence_s: float = CADENCE_S, scratch=None) -> dict:
    """With `lead_call`, a running lead steers (`Steering`); on a task with no checks a fresh lead's finish review
    is the stop rule: DONE ends the run `unverified` (`finish_review_done`; acceptance needs executed checks),
    otherwise its reply goes to the executor and the run goes on. Executor and lead spend count against
    `task.max_usd` together. The lead is closed on every exit, an exception included. With `scratch`
    (`LabScratch` / `LocalScratch`), each running review is followed by a verify session (`Lead.verify`)."""
    held: dict = {}
    try:
        return _run_task(task, chat, shell, trace, budget, model, deadline, lead_call, lead_model, cadence_s, held,
                         scratch)
    except BaseException:
        if held.get("steering"):
            held["steering"].close(-1)
        raise


def _run_task(task: Task, chat: Chat, shell: Shell, trace: Trace, budget: Budget, model: str,
              deadline: float | None, lead_call: Callable[..., tuple[int, object, float]] | None, lead_model: str,
              cadence_s: float, held: dict, scratch=None) -> dict:
    t0 = time.monotonic()
    steps = retries = 0
    cost = lead_cost = 0.0
    price_ceiling = CEILINGS[model][0]
    trace.write("task_start", task=task.id, model=model, max_steps=task.max_steps, max_usd=task.max_usd)

    result: dict = {}  # returned by `end`; a cost resolved later updates it in place

    def end(status: str, reason: str) -> dict:
        if steering:  # an in-flight lead call completes and is accounted before the results are written
            steering.close(steps)
        budget.resolve(force=True)
        findings = audit([e for e in trace.events if e.get("task") == task.id])
        trace.write("audit", task=task.id, findings=findings)
        # Calls still pending here are resolved later (a `cost_resolved` row after task_end) or by `reconcile`.
        row = trace.write("task_end", task=task.id, status=status, reason=reason, steps=steps,
                          retries=retries, cost_usd=round(cost, 8), audit_hits=len(findings),
                          **({"lead_cost_usd": round(lead_cost, 8)} if lead_call else {}),
                          pending_calls=sum(c.get("task") == task.id for c, _ in budget.pending),
                          latency_s=round(time.monotonic() - t0, 2))
        result.update({k: v for k, v in row.items() if k not in ("event", "ts")})
        return result

    def resolved(step: int, attempt: int, usd: float, kind: str, request_id: str | None) -> None:
        nonlocal cost
        cost += usd
        trace.write("cost_resolved", task=task.id, step=step, attempt=attempt, cost_usd=usd, cost_kind=kind,
                    request_id=request_id)
        if result:  # settled after task_end: refresh the returned result (run summaries are summed from it)
            result["cost_usd"] = round(result["cost_usd"] + usd, 8)
            result["pending_calls"] -= 1

    def past_deadline() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    def lead_charged(usd: float) -> None:
        nonlocal lead_cost
        lead_cost += usd
        if result and usd:  # settled after task_end
            result["lead_cost_usd"] = round(result["lead_cost_usd"] + usd, 8)

    def may_spend() -> bool:
        return cost + lead_cost < task.max_usd

    steering = None
    if lead_call is not None:
        lead_trace = Trace(trace.path.with_name("lead.jsonl") if trace.path else None)
        steering = held["steering"] = Steering(Lead(lead_call, lead_model, budget, lead_trace, task.goal, set(),
                                                    "running", deadline, lead_charged, may_spend), cadence_s, scratch)

    def finish_review(summary: str) -> tuple[str | None, str | None]:
        """A fresh lead (no notes, goal list or injected messages of the running lead): init review through step
        k-10, then the finish review. (verdict "pass" | "fail" | None, reply)."""
        steering.settle_for_finish(steps)
        running = steering.lead
        fresh = Lead(lead_call, lead_model, budget, running.trace, task.goal, running.hide, "finish", deadline,
                     lead_charged, may_spend)
        k = max(1, steps - 10)
        text = fresh.ask(upto(messages, k), k) and fresh.ask(messages, steps, summary)
        if not text:
            return None, None
        return ("pass" if text.strip().splitlines()[-1].strip() == "DONE" else "fail"), text

    if task.setup:
        r = shell(task.setup, EXEC_TIMEOUT)
        trace.write("exec", source="setup", command=task.setup, **r)
        if r.get("deadline"):
            return end("unverified", "lab_deadline")
        if r["exit"] != 0:
            return end("unverified", "setup_failed")

    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _goal_text(task)}]
    known = None  # provider-reported tokens of the conversation so far (`reported_tokens`)
    while steps < task.max_steps:
        if past_deadline():
            return end("unverified", "lab_deadline")
        steps += 1
        if task.inject and steps == task.inject_step:
            messages.append({"role": "user", "content": task.inject})
            trace.write("inject", task=task.id, step=steps, content=task.inject)
        if steering:
            steering.turn(messages, steps)
        limit = max_output(model, messages, TOOLS, known)
        request = {"model": model, "messages": messages, "tools": TOOLS,
                   **({"max_tokens": limit} if limit is not None else {})}
        # Input only: the output's cost is settled from the reply, never reserved at max_tokens x price (90b27cd).
        bound = len(json.dumps(request).encode()) * price_ceiling
        # One retry when no HTTP response came back (transport error or timeout); each attempt is admitted and settled.
        for attempt in (1, 2):
            budget.resolve()
            if not may_spend():
                return end("unverified", "task_budget")
            if not budget.admit(bound):
                return end("unverified", "run_budget")
            status, body, latency = chat(messages, TOOLS,
                                         timeout=None if deadline is None else deadline - time.monotonic())
            c, kind = billed_cost(body), "billed"
            usage = body.get("usage") if isinstance(body, dict) else None
            for ts in (body.get("conflux_lost") or []) if isinstance(body, dict) else []:
                # an earlier lost attempt inside surplus_post's retries may still be billed: the export settles it
                budget.defer({"task": task.id, "step": steps, "model": model, "ts": ts, "usage": None},
                             functools.partial(resolved, steps, attempt))
            answered = isinstance(body, dict) and bool(body.get("choices"))
            if c is None and status != 0 and not answered and not usage:
                # An HTTP error reply without usage was not billed (slice 39: a 200 `no_healthy_sellers` settled at its
                # $0.66 input bound).
                c, kind = 0.0, "no_usage"
            if c is None:
                # Ambiguous (no buyer_cost_micro, or a lost reply that may still be billed): Surplus's billing data
                # resolves it (MISSION a58a30e). Slice 43 lead-s2: 14 such replies settled at usage x ceilings ($1.59
                # vs $0.029 billed) ended the run at step 107.
                c, kind = 0.0, "pending"
                budget.defer({"task": task.id, "step": steps, "model": model, "ts": time.time(),
                              "usage": usage if isinstance(usage, dict) else None},
                             functools.partial(resolved, steps, attempt))
            elif kind == "billed" and isinstance(usage, dict):
                budget.observe({"task": task.id, "step": steps, "model": model, "ts": time.time(), "usage": usage})
            budget.settle(bound, c)
            cost += c
            choices = body.get("choices") if isinstance(body, dict) else None
            msg = choices[0].get("message") if status == 200 and choices else None
            trace.write("model_call", task=task.id, step=steps, attempt=attempt, model=model, status=status,
                        id=body.get("id") if isinstance(body, dict) else None,
                        latency_s=round(latency, 3), usage=body.get("usage") if isinstance(body, dict) else None,
                        cost_usd=c, cost_kind=kind, bound_usd=bound, message=msg,
                        finish_reason=choices[0].get("finish_reason") if msg else None,
                        error=None if msg else (body.get("error") if isinstance(body, dict) else str(body)))
            if past_deadline():
                return end("unverified", "lab_deadline")
            if status != 0:
                break
        known = reported_tokens(messages, body) or known
        if not isinstance(msg, dict):
            # No seller for the whole availability window: the provider's state, never the executor failing.
            return end("unverified", "provider_unavailable" if _unavailable(status, body) else f"provider_{status}")
        calls = msg.get("tool_calls") or []
        reasoning = msg.get("reasoning_content")
        # DeepSeek needs its reasoning passed back on every later turn of a tool-call loop (MISSION c36f507).
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         **({"reasoning_content": reasoning} if isinstance(reasoning, str) and reasoning else {}),
                         **({"tool_calls": calls} if calls else {})})
        truncated = _truncated(body, limit)
        finished = not calls and not truncated
        summary = msg.get("content") or ""
        if truncated and not calls:
            messages.append({"role": "user", "content": TRUNCATED})
        for call in calls:
            name, args, deny = policy(call)
            if truncated and deny == "bad_arguments":
                deny = "truncated_at_max_tokens"
            trace.write("policy", task=task.id, step=steps, tool=name, decision="deny" if deny else "allow",
                        reason=deny)
            if deny:
                content = f"denied: {deny}" + (f"; {TRUNCATED}" if deny == "truncated_at_max_tokens" else "")
            elif name == "finish":
                finished = True
                summary = str(args.get("summary") or "")
                content = "finish recorded; the harness is running the acceptance checks"
            else:
                r = shell(args["command"], args["timeout_s"])
                trace.write("exec", task=task.id, step=steps, source="model", command=args["command"],
                            timeout_s=args["timeout_s"], **r)
                if r.get("deadline"):
                    return end("unverified", "lab_deadline")
                content = _tool_result(r, args["timeout_s"])
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": content})
        if finished and steering and not task.checks:
            verdict, text = finish_review(summary)
            trace.write("finish_review", task=task.id, step=steps, verdict=verdict, reply=text)
            if verdict == "pass":
                return end("unverified", "finish_review_done")
            if verdict is None:
                return end("unverified", "lab_deadline" if past_deadline() else "finish_review_no_reply")
            retries += 1
            messages.append({"role": "user", "content": PREFIX + text})
        elif finished:
            verdict, results = run_checks(task.checks, shell)
            trace.write("acceptance", task=task.id, step=steps, verdict=verdict, results=results)
            if any(r.get("deadline") for r in results):
                return end("unverified", "lab_deadline")
            if verdict == "pass":
                return end("accepted", "checks_passed")
            if verdict is None:
                return end("unverified", "check_no_verdict")
            retries += 1
            messages.append({"role": "user", "content": _check_feedback(results)})

    if steering and not task.checks:
        verdict, text = finish_review(CAP_SUMMARY)
        trace.write("finish_review", task=task.id, step=steps, verdict=verdict, reply=text)
        if verdict == "pass":
            return end("unverified", "finish_review_done_at_step_cap")
        if verdict is None:
            return end("unverified", "lab_deadline" if past_deadline() else "finish_review_no_reply")
        return end("unverified", "step_cap")  # a review is not an executed check: no verdict
    verdict, results = run_checks(task.checks, shell)
    trace.write("acceptance", task=task.id, step=steps, verdict=verdict, results=results)
    if any(r.get("deadline") for r in results):
        return end("unverified", "lab_deadline")
    if verdict == "pass":
        return end("accepted", "checks_passed_at_step_cap")
    if verdict is None:
        return end("unverified", "check_no_verdict")
    return end("failed", "step_cap")


# ---------------------------------------------------------------- provider + accounting


def load_key(name: str) -> str:
    return (SECRETS / name).read_text().strip()


def _unavailable(status: int, body: object) -> bool:
    """No seller can serve the call right now: `404 minimum_discount_not_met` (MISSION 5ee7a8b), any 429/5xx, or
    an error body without choices (slice 39: HTTP 200 `no_healthy_sellers` for pro ended a run at step 107)."""
    if status in (429, 500, 502, 503, 504):
        return True
    err = body.get("error") if isinstance(body, dict) else None
    if not isinstance(err, dict) or body.get("choices"):
        return False
    return (status == 404 and err.get("code") == "minimum_discount_not_met") or status == 200


def surplus_post(http: httpx.Client, key: str, payload: dict, timeout: float | None = None,
                 timeout_cap: float | None = None) -> tuple[int, object, float]:
    """One Surplus chat completion bought only at >= MIN_DISCOUNT % off (MISSION 5ee7a8b). While no seller can serve
    it (`_unavailable`: below the floor, or an outage), wait AVAILABILITY_BACKOFF_S and retry, for up to
    AVAILABILITY_WINDOW_S and within `timeout`; then return the last reply (never a lower floor).

    A lost reply (the server closed the connection, a transport error, or no complete reply within the request's
    time limit, counted over the whole body, not per read) takes the same backoff path. Such a request may still be
    billed: the wall-clock times of the lost attempts before the returned one are in the body's `conflux_lost`."""
    t0 = time.monotonic()
    lost: list[float] = []
    timeout_cap = CHAT_TIMEOUT if timeout_cap is None else timeout_cap
    for attempt in itertools.count():
        elapsed = time.monotonic() - t0
        limit = timeout_cap if timeout is None else min(timeout_cap, timeout - elapsed)
        if attempt:  # a retry also ends with the availability window (PR #47 review)
            limit = min(limit, AVAILABILITY_WINDOW_S - elapsed)
        if limit <= 0:
            return _with_lost(status, body, lost[:-1] if status == 0 else lost, elapsed) if attempt else (
                0, {"error": "TimeoutBeforeSend"}, elapsed)
        sent = time.monotonic()
        try:
            # Surplus's compressed bodies break httpx decoding.
            with http.stream("POST", f"{SURPLUS}/chat/completions", timeout=max(0.1, limit), json=payload,
                             headers={"Authorization": f"Bearer {key}", "Accept-Encoding": "identity",
                                      "X-Min-Discount": str(MIN_DISCOUNT)}) as resp:
                raw = b""
                for chunk in resp.iter_bytes():  # each read is bounded by `limit`; the whole body is bounded here
                    raw += chunk
                    if time.monotonic() - sent > limit:
                        raise httpx.ReadTimeout("reply not complete within the request's time limit")
            status = resp.status_code
            try:
                body = json.loads(raw)
            except ValueError:
                body = {"error": raw.decode(errors="replace")[:500]}
        except httpx.HTTPError as e:
            status, body = 0, {"error": type(e).__name__}
            lost.append(time.time())
        wait = AVAILABILITY_BACKOFF_S[min(attempt, len(AVAILABILITY_BACKOFF_S) - 1)]
        elapsed = time.monotonic() - t0  # after the response: a slow refusal uses up time too (PR #47 review)
        if not (status == 0 or _unavailable(status, body)) or elapsed + wait > AVAILABILITY_WINDOW_S or (
                timeout is not None and timeout - elapsed <= wait):
            # a returned lost reply is the caller's to settle; only the earlier lost attempts are reported
            return _with_lost(status, body, lost[:-1] if status == 0 else lost, time.monotonic() - t0)
        time.sleep(wait)


def _with_lost(status: int, body: object, lost: list[float], elapsed: float) -> tuple[int, object, float]:
    if lost and isinstance(body, dict):
        body = {**body, "conflux_lost": lost}
    return status, body, elapsed


def surplus_chat(key: str, model: str = MODEL, http: httpx.Client | None = None) -> Chat:
    http = http or httpx.Client(timeout=CHAT_TIMEOUT)

    known = [None]  # provider-reported tokens of this conversation's prefix (`reported_tokens`)

    def chat(messages: list, tools: list, timeout: float | None = None) -> tuple[int, object, float]:
        n = max_output(model, messages, tools, known[0])
        status, body, latency = surplus_post(http, key, {"model": model, "messages": messages, "tools": tools,
                                                         **({"max_tokens": n} if n else {})}, timeout)
        known[0] = reported_tokens(messages, body) or known[0]
        return status, body, latency

    return chat


def fetch_export(key: str, day: str) -> list[dict]:
    with httpx.Client(timeout=60) as http:
        r = http.get(EXPORT, params={"format": "csv", "from": day, "to": day},
                     headers={"Authorization": f"Bearer {key}"})
        if r.status_code in (301, 302, 303, 307, 308):
            # The pre-signed URL rejects a second auth mechanism: no Authorization header.
            r = http.get(r.headers["location"])
        r.raise_for_status()
        return list(csv.DictReader(io.StringIO(r.text)))


def _parse_ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def reconcile(calls: list[dict], rows: list[dict], window: float = MATCH_WINDOW_S) -> dict:
    """Match model_call events to export rows by model + token counts + nearest time.

    The export's `request_id` is not the response `id`, so ids cannot be joined. A call
    whose response carried no usage (e.g. a body that failed to decode) may still have been
    billed: after the token pass it takes the nearest unused row of its model (`match: "time"`).
    """
    used: set[int] = set()
    matched, unmatched = [], []

    def nearest(call: dict, by_tokens: bool) -> int | None:
        usage = call.get("usage") or {}
        best = None
        for i, row in enumerate(rows):
            if i in used or row.get("model") != call.get("model"):
                continue
            try:
                same = (int(row["input_tokens"]) == usage.get("prompt_tokens")
                        and int(row["output_tokens"]) == usage.get("completion_tokens"))
                dt = abs(_parse_ts(row["created_at"]) - call["ts"])
            except (KeyError, TypeError, ValueError):
                continue
            if (same or not by_tokens) and dt <= window and (best is None or dt < best[1]):
                best = (i, dt)
        return None if best is None else best[0]

    with_usage = [c for c in calls if c.get("usage")]
    for call in with_usage + [c for c in calls if not c.get("usage")]:
        i = nearest(call, by_tokens=bool(call.get("usage")))
        ref = {"task": call.get("task"), "step": call.get("step"), "id": call.get("id"),
               **({"lead": call["lead"]} if call.get("lead") else {})}
        if i is None:
            unmatched.append(ref)
            continue
        used.add(i)
        row = rows[i]
        matched.append({**ref, "match": "tokens" if call.get("usage") else "time",
                        "request_id": row["request_id"], "billed_usd": float(row["buyer_cost_usd"]),
                        "in_flight_usd": call.get("cost_usd"), "settlement": row.get("settlement_status")})
    return {"matched": matched, "unmatched": unmatched,
            "billed_usd": round(sum(m["billed_usd"] for m in matched), 8),
            "in_flight_usd": round(sum(c.get("cost_usd") or 0 for c in calls), 8)}


def parse_ledger_total(text: str) -> float:
    m = re.search(r"\*\*Metered total: \$([0-9]+(?:\.[0-9]+)?)\*\*", text)
    if not m:
        raise ValueError("LEDGER.md has no '**Metered total: $X**' line")
    return float(m.group(1))


def _load_events(out: Path, event: str) -> list[dict]:
    rows = []
    for p in sorted(out.glob("*/trace.jsonl")):
        rows += [r for r in map(json.loads, p.read_text().splitlines()) if r["event"] == event]
    return rows


def _billed_calls(out: Path) -> list[dict]:
    """Every paid call of a run directory: executor `model_call`s and lead `lead_call`s. A lead call is attributed to
    its task (the directory) and tagged `lead:<role>` with its review step and turn."""
    calls = _load_events(out, "model_call")
    for p in sorted(out.glob("*/lead.jsonl")):
        for r in map(json.loads, p.read_text().splitlines()):
            if r["event"] == "lead_call":
                calls.append({**r, "task": p.parent.name, "lead": f"lead:{r.get('role')}:{r.get('turn')}"})
    return calls


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_lab(tasks: list[Task], chat: Chat, budget: Budget, out: Path, name: str, workdir: str,
            hours: float, model: str = MODEL, remote: Callable[[str], list[str]] | None = None,
            tunnel: Callable[[int], list[str]] | None = None,
            lead_call: Callable[..., tuple[int, object, float]] | None = None, lead_model: str = LEAD,
            scratch: bool = True) -> dict:
    """Own one lab's lifecycle: up, egress tunnel, smoke, setup + egress check, tasks in order (stop at
    the first non-accepted one), stop.

    The deadline starts when `devbox-lab up` is issued; the tunnel is killed and `devbox-lab stop`
    runs on every exit path. A failed egress check ends the run before any model call.
    """
    out.mkdir(parents=True, exist_ok=True)
    lab = {"name": name, "workdir": workdir, "hours": hours, "started": _utc()}
    deadline = time.monotonic() + hours * 3600
    results: list[dict] = []
    tunnel_proc: subprocess.Popen | None = None
    tunnel_log = out / "tunnel.log"
    try:
        subprocess.run(["devbox-lab", "up", name], check=True, capture_output=True, text=True, timeout=600)
        shell = lab_shell(remote or gcloud_remote(name), workdir, deadline, env=PROXY_ENV)
        teardown = lab_shell(remote or gcloud_remote(name), workdir, deadline + TEARDOWN_S, env=PROXY_ENV)
        for _ in range(SSH_WAIT_TRIES):  # a fresh VM takes a while to accept ssh
            if shell("true", 60)["exit"] == 0 or time.monotonic() >= deadline:
                break
        tunnel_proc = _supervise((tunnel or gcloud_tunnel(name))(egress_proxy()), tunnel_log)
        lab["smoke"] = shell("whoami && nproc && df -h ~ | tail -n 1 && "
                             "{ sudo -n true && echo SUDO_OK || echo SUDO_NO; }", 120)
        if lab["smoke"]["exit"] == 0:
            lab["setup"] = shell(LAB_SETUP, 120)
            lab["egress"] = shell(EGRESS_CHECK, 300)
        if lab["smoke"]["exit"] != 0:
            lab["stopped_reason"] = "smoke_failed"
        elif lab["setup"]["exit"] != 0 or lab["egress"]["exit"] != 0:
            lab["stopped_reason"] = "egress_failed"
        else:
            for task in tasks:
                if time.monotonic() >= deadline:
                    lab["stopped_reason"] = "lab_deadline"
                    break
                d = out / task.id
                d.mkdir(parents=True, exist_ok=False)
                res = run_task(task, chat, shell, Trace(d / "trace.jsonl"), budget, model, deadline,
                               lead_call, lead_model, scratch=LabScratch(shell, workdir, teardown) if lead_call and scratch
                               else None)
                results.append(res)
                print(json.dumps(res), flush=True)
                if res["status"] != "accepted":
                    lab["stopped_reason"] = f"{task.id}:{res['reason']}"
                    break
    finally:
        if tunnel_proc is not None:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(tunnel_proc.pid, sig)
                    tunnel_proc.wait(timeout=30)
                    break
                except ProcessLookupError:
                    break
                except subprocess.TimeoutExpired:
                    continue
            lab["tunnel_starts"] = tunnel_log.read_text().count("TUNNEL-START") if tunnel_log.exists() else 0
        try:
            stop_exit = subprocess.run(["devbox-lab", "stop", name], capture_output=True, text=True,
                                       timeout=600).returncode
        except (OSError, subprocess.SubprocessError) as e:
            stop_exit = repr(e)
        budget.resolve(force=True)  # late settlements refresh the task results summed below
        lab.update(stopped=_utc(), stop_exit=stop_exit,
                   wall_s=round(time.monotonic() - (deadline - hours * 3600), 1),
                   keep_disk=bool(results) and results[0]["status"] == "accepted")
        summary = {"model": model, "allowance_usd": budget.allowance, "committed_usd": budget.committed,
                   "lab": lab, "runs": results,
                   "accepted": sum(r["status"] == "accepted" for r in results),
                   "cost_usd": round(sum(r["cost_usd"] for r in results), 8),
                   "audit_hits": sum(r["audit_hits"] for r in results)}
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="conflux.core")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--tasks", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--repeats", type=int, default=1)
    run.add_argument("--only", default="")
    run.add_argument("--cap", type=float, default=RUN_CAP)
    run.add_argument("--model", default=MODEL)
    run.add_argument("--lab", default="", help="devbox-lab name: run tasks in order on that lab")
    run.add_argument("--workdir", default="~/conflux-work", help="lab workdir (with --lab)")
    run.add_argument("--lab-hours", type=float, default=4.0, help="lab wall-time deadline (with --lab)")
    run.add_argument("--lead", default="", help="lead model (e.g. kimi-k3): steers; judges finish on tasks without checks")
    run.add_argument("--lead-effort", default=LEAD_EFFORT)
    run.add_argument("--no-scratch", action="store_true", help="lead reviews without a verify session (baselines)")
    rec = sub.add_parser("reconcile")
    rec.add_argument("--out", type=Path, required=True)
    rec.add_argument("--day", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    aud = sub.add_parser("audit", help="D1 self-audit of recorded trace.jsonl files")
    aud.add_argument("traces", type=Path, nargs="+")
    a = ap.parse_args(argv)
    if a.cmd == "audit":
        for p in a.traces:
            rows = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
            print(json.dumps({"trace": str(p), "findings": audit(rows)}))
        return 0
    if a.cmd == "run" and a.model not in CEILINGS:
        ap.error(f"no admission ceilings for {a.model!r}; add it to core.CEILINGS")
    key = load_key("surplus.key")

    if a.cmd == "reconcile":
        rows = fetch_export(key, a.day)
        report = reconcile(_billed_calls(a.out), rows)
        report["lead_billed_usd"] = round(sum(m["billed_usd"] for m in report["matched"] if m.get("lead")), 8)
        (a.out / "reconciled.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({k: v for k, v in report.items() if k != "matched"}, indent=2))
        return 0

    tasks = [Task.from_dict(d) for d in json.loads(a.tasks.read_text())]
    if a.only:
        tasks = [t for t in tasks if t.id in a.only.split(",")]
    remaining = CAMPAIGN_BUDGET - parse_ledger_total(LEDGER.read_text())
    budget = Budget(min(a.cap, remaining), billing=lambda day: fetch_export(key, day))
    chat = surplus_chat(key, a.model)
    lead = surplus_lead(key, a.lead, a.lead_effort or None) if a.lead else None
    if a.lab:
        run_lab(tasks, chat, budget, a.out, a.lab, a.workdir, a.lab_hours, a.model, lead_call=lead,
                lead_model=a.lead or LEAD, scratch=not a.no_scratch)
        return 0
    a.out.mkdir(parents=True, exist_ok=True)
    results = []
    for n in range(1, a.repeats + 1):
        for task in tasks:
            d = a.out / f"{task.id}-{n}"
            d.mkdir(parents=True, exist_ok=False)
            res = run_task(task, chat, local_shell(d / "work"), Trace(d / "trace.jsonl"), budget, a.model,
                           lead_call=lead, lead_model=a.lead or LEAD,
                           scratch=LocalScratch(d / "work", d / "scratch") if lead and not a.no_scratch else None)
            results.append(res)
            print(json.dumps(res))
    budget.resolve(force=True)  # late settlements refresh the task results summed below
    summary = {"model": a.model, "allowance_usd": budget.allowance, "committed_usd": budget.committed,
               "runs": results,
               "accepted": sum(r["status"] == "accepted" for r in results),
               "cost_usd": round(sum(r["cost_usd"] for r in results), 8),
               "audit_hits": sum(r["audit_hits"] for r in results)}
    (a.out / "summary.json").write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
