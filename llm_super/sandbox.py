"""Execution power: run model-produced code in a sandbox and capture evidence.

Text-based verification judges what an answer *says*; this module observes
what the code *does*. The transcript (exit code, stdout, stderr, doctest
results) feeds the verifier as ground evidence and the repair loop as
targeted feedback. Strategy: test in the sandbox first; only after
verification does anything touch the host (SPEC §5.8).

Backends:
  local   — subprocess in a temp dir with a timeout. Fast; shares the host
            Python but never the working tree.
  gcloud  — ephemeral low-cost Compute Engine VM (default e2-micro, ~$0.008/h,
            billed per second): create → run → delete. Slow to start (~1-2
            min) but fully isolated from the host; use for untrusted or
            system-touching code.
  off     — execution disabled.

If the produced code contains doctests (>>> lines), they are run and counted;
otherwise the code is simply executed.
"""

from __future__ import annotations

import asyncio
import re
import shlex
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

_CODE_BLOCK = re.compile(r"```(?:python|py)\n(.*?)```", re.DOTALL)

_RUNNER = """\
import doctest, importlib.util, sys
spec = importlib.util.spec_from_file_location("snippet", "snippet.py")
m = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(m)
except Exception as e:
    print(f"IMPORT ERROR: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(3)
r = doctest.testmod(m, verbose=False)
print(f"DOCTESTS: {r.attempted} attempted, {r.failed} failed")
sys.exit(1 if r.failed else 0)
"""


@dataclass
class ExecutionResult:
    ran: bool
    ok: bool
    backend: str
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0.0
    note: str = ""

    def transcript(self, limit: int = 2000) -> str:
        if not self.ran:
            return f"(code was not executed: {self.note})"
        return (
            f"backend={self.backend} exit_code={self.exit_code} "
            f"duration={self.duration_s:.1f}s\n"
            f"--- stdout ---\n{self.stdout[:limit]}\n"
            f"--- stderr ---\n{self.stderr[:limit]}"
        )


def extract_python(text: str) -> str | None:
    m = _CODE_BLOCK.search(text)
    return m.group(1) if m else None


def _wants_doctest(code: str) -> bool:
    return ">>>" in code


async def _run_cmd(cmd: list[str], timeout: float, cwd: str | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "", f"timed out after {timeout}s"
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def run_local(code: str, timeout: float = 30.0) -> ExecutionResult:
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="llmsuper-exec-") as d:
        Path(d, "snippet.py").write_text(code)
        if _wants_doctest(code):
            Path(d, "runner.py").write_text(_RUNNER)
            cmd = ["python3", "-I", "runner.py"]
        else:
            cmd = ["python3", "-I", "snippet.py"]
        rc, out, err = await _run_cmd(cmd, timeout, cwd=d)
    return ExecutionResult(
        ran=True, ok=rc == 0, backend="local", exit_code=rc,
        stdout=out, stderr=err, duration_s=time.monotonic() - start,
    )


async def run_gcloud(
    code: str,
    *,
    zone: str = "us-central1-a",
    machine_type: str = "e2-micro",
    timeout: float = 120.0,
    keep_instance: bool = False,
) -> ExecutionResult:
    """Create an ephemeral VM, run the code, delete the VM.

    Requires an authenticated `gcloud` CLI with a default project. The
    instance is deleted even on failure unless keep_instance is set.
    """
    start = time.monotonic()
    name = f"llmsuper-{uuid.uuid4().hex[:8]}"
    create = [
        "gcloud", "compute", "instances", "create", name,
        f"--zone={zone}", f"--machine-type={machine_type}",
        "--image-family=debian-12", "--image-project=debian-cloud",
        "--no-scopes", "--no-service-account", "--quiet",
    ]
    rc, out, err = await _run_cmd(create, 180)
    if rc != 0:
        return ExecutionResult(ran=False, ok=False, backend="gcloud",
                               note=f"instance create failed: {err[-400:]}")
    try:
        runner = _RUNNER if _wants_doctest(code) else None
        remote = (
            "cat > snippet.py <<'LLMSUPER_EOF'\n" + code + "\nLLMSUPER_EOF\n"
            + (("cat > runner.py <<'LLMSUPER_EOF'\n" + runner + "\nLLMSUPER_EOF\n") if runner else "")
            + ("python3 -I runner.py" if runner else "python3 -I snippet.py")
        )
        # SSH can take a few tries while the VM boots.
        for attempt in range(6):
            rc, out, err = await _run_cmd(
                ["gcloud", "compute", "ssh", name, f"--zone={zone}", "--quiet",
                 "--command", remote],
                timeout,
            )
            if "Connection refused" not in err and "Connection timed out" not in err \
                    and "permission denied" not in err.lower():
                break
            await asyncio.sleep(10)
        return ExecutionResult(
            ran=True, ok=rc == 0, backend="gcloud", exit_code=rc,
            stdout=out, stderr=err, duration_s=time.monotonic() - start,
        )
    finally:
        if not keep_instance:
            await _run_cmd(
                ["gcloud", "compute", "instances", "delete", name,
                 f"--zone={zone}", "--quiet"],
                180,
            )


async def run(code: str, backend: str, **kw) -> ExecutionResult:
    if backend == "off":
        return ExecutionResult(ran=False, ok=True, backend="off", note="execution disabled")
    if backend == "local":
        return await run_local(code)
    if backend == "gcloud":
        return await run_gcloud(code, **kw)
    return ExecutionResult(ran=False, ok=True, backend=backend, note=f"unknown backend {backend!r}")
