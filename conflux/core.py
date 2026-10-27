"""Minimal replacement core: one explicit execution loop (rebuild work item C).

DeepSeek (Surplus chat, plain OpenAI `tools`) proposes shell actions. Deterministic code
admits each call against the budget, checks each proposal against a permissive policy,
executes it, and owns acceptance: the task's checks are shell commands the harness runs
itself. Every model call's cost is the provider's `buyer_cost_micro`; when absent, the
call is settled at its admission bound (`cost_kind: "bound"`). After a run, `reconcile`
matches the calls against the Surplus buyer usage export, the authoritative billed cost.

Commands run through a `Shell`: `local_shell` (a subprocess in a workdir) or `lab_shell`
(a detached job on a `devbox-lab` VM, polled over ssh, all waits capped by one deadline that
starts when the lab comes up). Every command runs under `pipefail`, and its result carries
`pipestatus`, the exit status of each stage of the last pipeline it ran (founder decision: the
executor must not mask pipeline failures). Labs have no internet egress, so `run_lab` serves an
HTTP proxy on the controller (`egress_proxy`), reverse-tunnels it to the lab's 127.0.0.1:3128 over
ssh, and exports `PROXY_ENV` to every lab command; an egress check gates the first model call.

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
MAX_TOKENS = 2048          # flash reasoning tokens count against this
PRICE_CEILING = 4e-7       # $/byte of request, admission bound: tokens <= bytes, > v4.1-flash's top input list rate ($3e-7/tok)
OUTPUT_CEILING = 2.4e-6    # $/output token, admission bound: 2x v4.1-flash's top output list rate ($1.2e-6/tok)
CAMPAIGN_BUDGET = 50.00
RUN_CAP = 0.20
EXEC_TIMEOUT = 60
CHAT_TIMEOUT = 180
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
TAIL = 4096
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
                       "(last 4 KB each). timeout_s defaults to 60; use up to 10800 for long jobs.",
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

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(**{**d, "checks": [Check(**c) for c in d["checks"]]})


class Budget:
    """Run-level admission: bounds are reserved before a call, replaced by cost after it."""

    def __init__(self, allowance: float):
        self.allowance = allowance
        self.committed = 0.0

    def admit(self, bound: float) -> bool:
        if self.committed + bound > self.allowance:
            return False
        self.committed += bound
        return True

    def settle(self, bound: float, cost: float) -> None:
        self.committed += cost - bound


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


_PS_MARK = "__CONFLUX_PIPESTATUS="
# Prepended to every command. The EXIT trap's first statement copies PIPESTATUS (the last pipeline's
# per-stage exits) into an array before anything resets it; printf prints it as the final stderr
# line with an explicit separator, so the command's IFS cannot change it.
PIPEFAIL = ("set -o pipefail\n"
            f"trap '__ps=(\"${{PIPESTATUS[@]}}\"); "
            f"{{ printf \"\\n{_PS_MARK}\"; printf \"%s \" \"${{__ps[@]}}\"; printf \"\\n\"; }} >&2' EXIT\n")


def _wrap(command: str) -> str:
    return PIPEFAIL + command


def _split_pipestatus(stderr: str) -> tuple[str, list[int] | None]:
    """(stderr without the trailing marker, per-stage exits); None when the marker is missing
    (killed, timed out, or the command replaced the trap or closed stderr)."""
    m = re.search(rf"\n?{_PS_MARK}([\d ]+)\n?$", stderr)
    if not m:
        return stderr, None
    return stderr[:m.start()], [int(x) for x in m[1].split()]


def execute(command: str, workdir: Path, timeout: float = EXEC_TIMEOUT) -> dict:
    t0 = time.monotonic()
    try:
        p = subprocess.run(["bash", "-c", _wrap(command)], cwd=workdir, capture_output=True,
                           text=True, errors="replace", timeout=timeout)
        stderr, ps = _split_pipestatus(p.stderr)
        out = {"exit": p.returncode, "stdout": p.stdout[-TAIL:], "stderr": stderr[-TAIL:],
               "pipestatus": ps, "timed_out": False}
    except subprocess.TimeoutExpired:
        out = {"exit": None, "stdout": "", "stderr": "", "pipestatus": None, "timed_out": True}
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
        out = {"exit": None, "stdout": "", "stderr": "", "pipestatus": None, "timed_out": False, "job": job}

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
            q = call(f'd={d}; tail -c {TAIL} "$d/{f}" 2>/dev/null; true', collect_by)
            tails[stream] = q.stdout if q else ""
            if q is None:
                unavailable.append(stream)
        if unavailable:
            tails["unavailable"] = unavailable
        tails["stderr"], tails["pipestatus"] = _split_pipestatus(tails["stderr"])
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
READ_ONLY = re.compile(r"^(cat|head|tail|sed -n|less|grep|rg|ls|find|wc|stat|file|readlink|du|df|echo|pwd|which|"
                       r"type|command -v|git (log|show|diff|status|branch|remote|rev-parse|ls-files)|"
                       r"apt(-cache)? (search|show|list|policy)|dpkg (-l|-s|-L))\b")


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
    success. Exempt: the model capturing `$?` itself. For pure reads only stderr counts (stdout is file content)."""
    findings = []
    for r in rows:
        if r.get("event") != "exec" or r.get("source") != "model" or r.get("exit") != 0:
            continue
        cmd = r.get("command") or ""
        segs, status = _scan(cmd)
        if status:
            continue
        reads = bool(segs) and all(READ_ONLY.match(s) for s in segs)
        text = ("" if reads else (r.get("stdout") or "")) + "\n" + (r.get("stderr") or "")
        hits = list(FAIL_TEXT.finditer(text))
        if hits:
            findings.append({"check": "D1", "step": r.get("step"), "command": cmd[:200],
                             "evidence": hits[-1].group(0).strip()[:200]})
    return findings

def run_task(task: Task, chat: Chat, shell: Shell, trace: Trace, budget: Budget,
             model: str = MODEL, deadline: float | None = None) -> dict:
    t0 = time.monotonic()
    steps = retries = 0
    cost = 0.0
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
    while steps < task.max_steps:
        if past_deadline():
            return end("unverified", "lab_deadline")
        steps += 1
        request = {"model": model, "messages": messages, "tools": TOOLS, "max_tokens": MAX_TOKENS}
        bound = len(json.dumps(request).encode()) * PRICE_CEILING + MAX_TOKENS * OUTPUT_CEILING
        if cost + bound > task.max_usd:
            return end("unverified", "task_budget")
        if not budget.admit(bound):
            return end("unverified", "run_budget")
        status, body, latency = chat(messages, TOOLS,
                                     timeout=None if deadline is None else deadline - time.monotonic())
        c, kind = billed_cost(body), "billed"
        if c is None:
            c, kind = bound, "bound"
        budget.settle(bound, c)
        cost += c
        choices = body.get("choices") if isinstance(body, dict) else None
        msg = choices[0].get("message") if status == 200 and choices else None
        trace.write("model_call", task=task.id, step=steps, model=model, status=status,
                    id=body.get("id") if isinstance(body, dict) else None,
                    latency_s=round(latency, 3), usage=body.get("usage") if isinstance(body, dict) else None,
                    cost_usd=c, cost_kind=kind, bound_usd=bound, message=msg,
                    error=None if msg else (body.get("error") if isinstance(body, dict) else str(body)))
        if past_deadline():
            return end("unverified", "lab_deadline")
        if not isinstance(msg, dict):
            return end("unverified", f"provider_{status}")
        calls = msg.get("tool_calls") or []
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         **({"tool_calls": calls} if calls else {})})
        finished = not calls
        for call in calls:
            name, args, deny = policy(call)
            trace.write("policy", task=task.id, step=steps, tool=name, decision="deny" if deny else "allow",
                        reason=deny)
            if deny:
                content = f"denied: {deny}"
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


def surplus_chat(key: str, model: str = MODEL, http: httpx.Client | None = None) -> Chat:
    http = http or httpx.Client(timeout=CHAT_TIMEOUT)

    def chat(messages: list, tools: list, timeout: float | None = None) -> tuple[int, object, float]:
        t0 = time.monotonic()
        try:
            resp = http.post(f"{SURPLUS}/chat/completions", timeout=CHAT_TIMEOUT if timeout is None
                             else max(0.1, min(CHAT_TIMEOUT, timeout)),
                             # Surplus's compressed bodies break httpx decoding.
                             headers={"Authorization": f"Bearer {key}", "Accept-Encoding": "identity"},
                             json={"model": model, "messages": messages, "tools": tools,
                                   "max_tokens": MAX_TOKENS})
        except httpx.HTTPError as e:
            return 0, {"error": type(e).__name__}, time.monotonic() - t0
        try:
            body = resp.json()
        except ValueError:
            body = {"error": resp.text[:500]}
        return resp.status_code, body, time.monotonic() - t0

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
