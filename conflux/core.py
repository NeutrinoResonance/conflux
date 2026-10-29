"""Minimal replacement core: one explicit execution loop (rebuild work item C).

DeepSeek (Surplus chat, plain OpenAI `tools`) proposes shell actions. Deterministic code
admits each call against the budget, checks each proposal against a permissive policy,
executes it, and owns acceptance: the task's checks are shell commands the harness runs
itself. Every model call's cost is the provider's `buyer_cost_micro`; when absent, the
call is settled at its reported token usage times the executor's ceilings (`cost_kind:
"usage_bound"`), or, when usage is absent too, at its admission bound if no reply came back (`"bound"`) and at 0 if
the provider answered with an error and no choices (`"no_usage"`). After a run, `reconcile`
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
transport error, lab deadline).

Usage:
  python -m conflux.core run --tasks tests/fixtures/core_loop/tasks.json --out DIR --repeats 2
  python -m conflux.core run --tasks tests/fixtures/core_loop/optee_goal_a.json --out DIR \
      --lab c2 --workdir '~/optee-work' --lab-hours 4
  python -m conflux.core reconcile --out DIR --day 2026-10-27
  python -m conflux.core audit DIR/*/trace.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
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
# list rate bounds input; output is 2x the top output list rate (used only to settle a reply that reports usage but no
# cost). Admission charges the input bound alone. An executor without an entry is refused (KeyError).
CEILINGS = {
    "deepseek-v4.1-flash": (4e-7, 2.4e-6),  # top list $0.3/M in, $1.2/M out
    "deepseek-v4-pro": (2e-6, 7.6e-6),      # top list $1.73/M in, $3.796/M out (2026-10-27 /v1/prices, C slice 18)
}
CAMPAIGN_BUDGET = 50.00
MIN_DISCOUNT = 90          # X-Min-Discount on every Surplus request (MISSION 5ee7a8b); never lowered
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
    """Run-level money cap on settled cost (MISSION 90b27cd): a call is admitted while the spend so far is below the
    allowance; no per-call bound is reserved. Slice 39b: a 250 KB deepseek-v4-pro request's input bound (~$0.3-0.5)
    refused calls that bill ~$0.0001 and ended a run at step 63 with $0.002 spent. One call may overshoot by its cost."""

    def __init__(self, allowance: float):
        self.allowance = allowance
        self.committed = 0.0

    def admit(self, bound: float) -> bool:
        return self.committed < self.allowance

    def settle(self, bound: float, cost: float) -> None:
        self.committed += cost


@dataclass
class Trace:
    path: Path | None = None
    events: list = field(default_factory=list)

    def write(self, event: str, **fields) -> dict:
        row = {"event": event, "ts": time.time(), **fields}
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


def usage_bound(body: object, price_ceiling: float, output_ceiling: float) -> float | None:
    """Upper bound on a call's charge from its reported usage (ceilings exceed the top list rates per token);
    None without token counts. Pro omitted `buyer_cost_micro` on 7/27 calls in C slice 20: settled at the request
    bound instead, they summed to $0.94 against $0.0007 billed and ended the task at `task_budget`."""
    usage = body.get("usage") if isinstance(body, dict) else None
    p, c = (usage.get("prompt_tokens"), usage.get("completion_tokens")) if isinstance(usage, dict) else (None, None)
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (p, c)):
        return None
    return p * price_ceiling + c * output_ceiling


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
    checks = "\n".join(f"- `{c.cmd}`" + (f" must print {c.expect_stdout!r}" if c.expect_stdout is not None
                                         else " must exit 0") for c in task.checks)
    return f"{task.goal}\n\nAcceptance checks (run by the harness in the workspace):\n{checks}"


# ---------------------------------------------------------------- self-audit (work item F, D1)

FAIL_TEXT = re.compile(r"(?im)^.*\b(error|failed|fatal|cannot|can't|no such file|not found|denied|"
                       r"undefined reference|traceback|exception|\*\*\*)\b.*$")
BENIGN_TEXT = re.compile(r"(?i)^\s*MAKECONF file:.*\(File not found\)\s*$")  # NetBSD build.sh banner, every run
READ_ONLY = re.compile(r"^(cat|head|tail|sed -n|less|grep|rg|ls|find|wc|stat|file|readlink|du|df|echo|pwd|which|"
                       r"type|command -v|git( -[cC] \S+)* (log|show|diff|status|branch|remote|rev-parse|ls-files)|"
                       r"apt(-cache)? (search|show|list|policy)|dpkg (-l|-s|-L)|od|xxd|hexdump|"
                       r"(\S*/)?([\w.]+-)*(objdump|readelf|nm|strings)|(\S*/)?[\w.-]*make( \S+)* -n|sleep)\b")
# A quoted literal the command itself prints (`|| echo "Cannot write to X"`): the model's own message, not a tool's.
OWN_TEXT = re.compile(r"""^(?:echo|printf)(?:\s+-\w+)*\s+(["'])(.*)\1\s*$""", re.S)


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
    For pure reads only stderr counts (stdout is file content); known informational lines (`BENIGN_TEXT`) and lines
    that equal a literal the command echoes itself (`OWN_TEXT`) never count."""
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
        own = {m[2].replace("\\n", "").strip() for m in map(OWN_TEXT.match, segs) if m}
        hits = [h for h in FAIL_TEXT.finditer(text)
                if not BENIGN_TEXT.match(h.group(0)) and h.group(0).strip() not in own]
        if hits:
            findings.append({"check": "D1", "step": r.get("step"), "command": cmd[:200],
                             "evidence": hits[-1].group(0).strip()[:200]})
    return findings

def run_task(task: Task, chat: Chat, shell: Shell, trace: Trace, budget: Budget,
             model: str = MODEL, deadline: float | None = None) -> dict:
    t0 = time.monotonic()
    steps = retries = 0
    cost = 0.0
    price_ceiling, output_ceiling = CEILINGS[model]
    trace.write("task_start", task=task.id, model=model, max_steps=task.max_steps, max_usd=task.max_usd)

    def end(status: str, reason: str) -> dict:
        findings = audit([e for e in trace.events if e.get("task") == task.id])
        trace.write("audit", task=task.id, findings=findings)
        row = trace.write("task_end", task=task.id, status=status, reason=reason, steps=steps,
                          retries=retries, cost_usd=round(cost, 8), audit_hits=len(findings),
                          latency_s=round(time.monotonic() - t0, 2))
        return {k: v for k, v in row.items() if k not in ("event", "ts")}

    def past_deadline() -> bool:
        return deadline is not None and time.monotonic() >= deadline

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
        limit = max_output(model, messages, TOOLS, known)
        request = {"model": model, "messages": messages, "tools": TOOLS,
                   **({"max_tokens": limit} if limit is not None else {})}
        # Input only: the output's cost is settled from the reply, never reserved at max_tokens x price (90b27cd).
        bound = len(json.dumps(request).encode()) * price_ceiling
        # One retry when no HTTP response came back (transport error or timeout); each attempt is admitted and settled.
        for attempt in (1, 2):
            if cost >= task.max_usd:
                return end("unverified", "task_budget")
            if not budget.admit(bound):
                return end("unverified", "run_budget")
            status, body, latency = chat(messages, TOOLS,
                                         timeout=None if deadline is None else deadline - time.monotonic())
            c, kind = billed_cost(body), "billed"
            if c is None:
                c, kind = usage_bound(body, price_ceiling, output_ceiling), "usage_bound"
            if c is None:
                # An HTTP reply without usage is an error the provider did not bill (slice 39: a 200
                # `no_healthy_sellers` settled at its $0.66 input bound); a lost reply (status 0) may still be billed.
                answered = isinstance(body, dict) and bool(body.get("choices"))
                c, kind = (0.0, "no_usage") if status != 0 and not answered else (bound, "bound")
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
                content = "finish recorded; the harness is running the acceptance checks"
            else:
                r = shell(args["command"], args["timeout_s"])
                trace.write("exec", task=task.id, step=steps, source="model", command=args["command"],
                            timeout_s=args["timeout_s"], **r)
                if r.get("deadline"):
                    return end("unverified", "lab_deadline")
                content = _tool_result(r, args["timeout_s"])
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": content})
        if finished:
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
    AVAILABILITY_WINDOW_S and within `timeout`; then return the last reply (never a lower floor)."""
    t0 = time.monotonic()
    timeout_cap = CHAT_TIMEOUT if timeout_cap is None else timeout_cap
    for attempt in itertools.count():
        elapsed = time.monotonic() - t0
        limit = timeout_cap if timeout is None else min(timeout_cap, timeout - elapsed)
        if attempt:  # a retry also ends with the availability window (PR #47 review)
            limit = min(limit, AVAILABILITY_WINDOW_S - elapsed)
        if limit <= 0:
            return (resp.status_code, body, elapsed) if attempt else (0, {"error": "TimeoutBeforeSend"}, elapsed)
        try:
            resp = http.post(f"{SURPLUS}/chat/completions", timeout=max(0.1, limit),
                             # Surplus's compressed bodies break httpx decoding.
                             headers={"Authorization": f"Bearer {key}", "Accept-Encoding": "identity",
                                      "X-Min-Discount": str(MIN_DISCOUNT)},
                             json=payload)
        except httpx.HTTPError as e:
            return 0, {"error": type(e).__name__}, time.monotonic() - t0
        try:
            body = resp.json()
        except ValueError:
            body = {"error": resp.text[:500]}
        wait = AVAILABILITY_BACKOFF_S[min(attempt, len(AVAILABILITY_BACKOFF_S) - 1)]
        elapsed = time.monotonic() - t0  # after the response: a slow refusal uses up time too (PR #47 review)
        if not _unavailable(resp.status_code, body) or elapsed + wait > AVAILABILITY_WINDOW_S or (
                timeout is not None and timeout - elapsed <= wait):
            return resp.status_code, body, time.monotonic() - t0
        time.sleep(wait)


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
        ref = {"task": call.get("task"), "step": call.get("step"), "id": call.get("id")}
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


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_lab(tasks: list[Task], chat: Chat, budget: Budget, out: Path, name: str, workdir: str,
            hours: float, model: str = MODEL, remote: Callable[[str], list[str]] | None = None,
            tunnel: Callable[[int], list[str]] | None = None) -> dict:
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
                res = run_task(task, chat, shell, Trace(d / "trace.jsonl"), budget, model, deadline)
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
        report = reconcile(_load_events(a.out, "model_call"), rows)
        (a.out / "reconciled.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({k: v for k, v in report.items() if k != "matched"}, indent=2))
        return 0

    tasks = [Task.from_dict(d) for d in json.loads(a.tasks.read_text())]
    if a.only:
        tasks = [t for t in tasks if t.id in a.only.split(",")]
    remaining = CAMPAIGN_BUDGET - parse_ledger_total(LEDGER.read_text())
    budget = Budget(min(a.cap, remaining))
    chat = surplus_chat(key, a.model)
    if a.lab:
        run_lab(tasks, chat, budget, a.out, a.lab, a.workdir, a.lab_hours, a.model)
        return 0
    a.out.mkdir(parents=True, exist_ok=True)
    results = []
    for n in range(1, a.repeats + 1):
        for task in tasks:
            d = a.out / f"{task.id}-{n}"
            d.mkdir(parents=True, exist_ok=False)
            res = run_task(task, chat, local_shell(d / "work"), Trace(d / "trace.jsonl"), budget, a.model)
            results.append(res)
            print(json.dumps(res))
    summary = {"model": a.model, "allowance_usd": budget.allowance, "committed_usd": budget.committed,
               "runs": results,
               "accepted": sum(r["status"] == "accepted" for r in results),
               "cost_usd": round(sum(r["cost_usd"] for r in results), 8),
               "audit_hits": sum(r["audit_hits"] for r in results)}
    (a.out / "summary.json").write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
