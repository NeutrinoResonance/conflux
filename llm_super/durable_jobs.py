"""Durable, backend-neutral jobs with a GCE execution adapter.

Only the GCE adapter starts workload processes in this module.  Its local
subprocess is a fixed-shape ``gcloud compute ssh`` transport; the agent's shell
command is encoded into a remote job envelope and is never executed by the
controller host.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import posixpath
import re
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from .execution_backends import ExecutionBoundaryError


START_JOB_TOOL = "start_locked_job"
WATCH_JOB_TOOL = "watch_locked_job"
INSPECT_JOB_TOOL = "inspect_locked_job"
SIGNAL_JOB_TOOL = "signal_locked_job"
COLLECT_JOB_TOOL = "collect_locked_job"

JOB_TOOL_OPERATIONS = {
    START_JOB_TOOL: "start",
    WATCH_JOB_TOOL: "watch",
    INSPECT_JOB_TOOL: "inspect",
    SIGNAL_JOB_TOOL: "signal",
    COLLECT_JOB_TOOL: "collect",
}


def _object_schema(properties: Mapping[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": required,
        "additionalProperties": False,
    }


JOB_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": START_JOB_TOOL,
            "description": (
                "Start a durable background process on the operator-locked execution "
                "backend. The backend and target are immutable trusted configuration, "
                "not arguments. Returns a durable job_id immediately. Use this instead "
                "of shell &, nohup, or polling commands for work that may outlive one "
                "tool call; then use watch_locked_job with the returned cursors."
            ),
            "parameters": _object_schema(
                {
                    "command": {"type": "string", "minLength": 1, "maxLength": 32768},
                    "cwd": {
                        "type": "string",
                        "description": "Working directory within /tmp/llm-super-agent.",
                        "default": "/tmp/llm-super-agent",
                    },
                    "timeout_s": {
                        "type": "integer", "minimum": 1, "maximum": 86400,
                        "default": 3600,
                    },
                    "label": {"type": "string", "minLength": 1, "maxLength": 120},
                },
                ["command", "label", "timeout_s"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": WATCH_JOB_TOOL,
            "description": (
                "Wait inside one tool call for a locked job's stdout, stderr, or state "
                "to change. This consumes no model turns while waiting. Pass the exact "
                "next cursors returned by the previous start/watch/collect result so "
                "output is not duplicated."
            ),
            "parameters": _object_schema(
                {
                    "job_id": {"type": "string", "pattern": "^job_[a-f0-9]{24}$"},
                    "stdout_cursor": {"type": "integer", "minimum": 0, "default": 0},
                    "stderr_cursor": {"type": "integer", "minimum": 0, "default": 0},
                    "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 60,
                                     "default": 30},
                    "max_bytes": {"type": "integer", "minimum": 256,
                                  "maximum": 131072, "default": 32768},
                },
                ["job_id", "stdout_cursor", "stderr_cursor"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": INSPECT_JOB_TOOL,
            "description": (
                "Read authoritative liveness, ownership, exit, byte-count, heartbeat, "
                "and target metadata for one job owned by this locked backend. Also "
                "returns the exact persisted output cursors for the next watch/collect."
            ),
            "parameters": _object_schema(
                {"job_id": {"type": "string", "pattern": "^job_[a-f0-9]{24}$"}},
                ["job_id"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": SIGNAL_JOB_TOOL,
            "description": (
                "Signal exactly one owned locked job. The adapter verifies durable "
                "ownership and the process group before signaling; broad PID matching "
                "is never used. Signaling does not read output or advance its cursors; "
                "continue with the exact cursors in the returned next object until "
                "terminal, then collect final evidence."
            ),
            "parameters": _object_schema(
                {
                    "job_id": {"type": "string", "pattern": "^job_[a-f0-9]{24}$"},
                    "signal": {"type": "string",
                               "enum": ["interrupt", "terminate", "kill"]},
                },
                ["job_id", "signal"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": COLLECT_JOB_TOOL,
            "description": (
                "Collect bounded remaining output, terminal status, and an artifact "
                "manifest for a locked job. Pass the exact persisted cursors; rewinds "
                "and skips are rejected to prevent duplicate or lost output. Collection "
                "never deletes the remote evidence."
            ),
            "parameters": _object_schema(
                {
                    "job_id": {"type": "string", "pattern": "^job_[a-f0-9]{24}$"},
                    "stdout_cursor": {"type": "integer", "minimum": 0, "default": 0},
                    "stderr_cursor": {"type": "integer", "minimum": 0, "default": 0},
                    "max_bytes": {"type": "integer", "minimum": 256,
                                  "maximum": 262144, "default": 65536},
                },
                ["job_id", "stdout_cursor", "stderr_cursor"],
            ),
        },
    },
]


_JOB_ID = re.compile(r"^job_[a-f0-9]{24}$")
_SELECTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]*$")
_JOB_ROOT = "/tmp/llm-super-agent/.jobs"
_ALLOWED_CWD = "/tmp/llm-super-agent"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)


def _preview(command: str, limit: int = 180) -> str:
    one_line = " ".join(command.split())
    one_line = re.sub(r"(?i)(token|secret|password|api[_-]?key)=\S+",
                      r"\1=<redacted>", one_line)
    one_line = re.sub(r"(['\"]).*?\1", "<quoted>", one_line)
    if re.match(r"(?is)^\s*(echo|printf)\b", one_line):
        one_line = re.sub(r"(?is)^(\s*(?:echo|printf))\b.*", r"\1 <redacted-output>",
                          one_line)
    return one_line if len(one_line) <= limit else one_line[: limit - 1] + "…"


def _validate_job_id(job_id: Any) -> str:
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
        raise ExecutionBoundaryError("invalid durable job id")
    return job_id


def _nonnegative(value: Any, field: str, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
        raise ExecutionBoundaryError(f"{field} must be an integer from 0 to {maximum}")
    return value


class DurableJobStore:
    """Restart-safe controller ledger and cursor/event stream."""

    def __init__(self, database: str | Path | sqlite3.Connection = "traces.db") -> None:
        self._owns_connection = not isinstance(database, sqlite3.Connection)
        self._conn = (sqlite3.connect(str(database), check_same_thread=False)
                      if self._owns_connection else database)
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS durable_jobs (
                    job_id TEXT PRIMARY KEY,
                    backend TEXT NOT NULL,
                    boundary_fingerprint TEXT NOT NULL,
                    target_json TEXT NOT NULL,
                    session TEXT NOT NULL,
                    task TEXT NOT NULL,
                    label TEXT NOT NULL,
                    command_sha256 TEXT NOT NULL,
                    command_preview TEXT NOT NULL,
                    cwd TEXT NOT NULL,
                    timeout_s INTEGER NOT NULL,
                    remote_dir TEXT NOT NULL,
                    state TEXT NOT NULL,
                    pid INTEGER,
                    workload_pid INTEGER,
                    owned INTEGER NOT NULL DEFAULT 0,
                    exit_code INTEGER,
                    stdout_size INTEGER NOT NULL DEFAULT 0,
                    stderr_size INTEGER NOT NULL DEFAULT 0,
                    stdout_cursor INTEGER NOT NULL DEFAULT 0,
                    stderr_cursor INTEGER NOT NULL DEFAULT 0,
                    started_at REAL,
                    ended_at REAL,
                    heartbeat_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    collected_at REAL,
                    last_stdout TEXT NOT NULL DEFAULT '',
                    last_stderr TEXT NOT NULL DEFAULT '',
                    error TEXT
                )"""
            )
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS durable_job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    job_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    data_json TEXT NOT NULL DEFAULT '{}'
                )"""
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS durable_job_events_job_id "
                "ON durable_job_events(job_id,id)"
            )
            self._conn.commit()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def _event(self, job_id: str, kind: str, state: str, summary: str,
               data: Mapping[str, Any] | None = None) -> None:
        self._conn.execute(
            "INSERT INTO durable_job_events(ts,job_id,kind,state,summary,data_json) "
            "VALUES(?,?,?,?,?,?)",
            (time.time(), job_id, kind, state, summary, _json(data or {})),
        )

    def create(self, *, job_id: str, backend: str, boundary_fingerprint: str,
               target: Mapping[str, str], context: Mapping[str, str], label: str,
               command: str, cwd: str, timeout_s: int, remote_dir: str) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                """INSERT INTO durable_jobs(
                    job_id,backend,boundary_fingerprint,target_json,session,task,label,
                    command_sha256,command_preview,cwd,timeout_s,remote_dir,state,
                    created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, backend, boundary_fingerprint, _json(target),
                 str(context.get("session") or "-"), str(context.get("task") or "-"),
                 label, hashlib.sha256(command.encode()).hexdigest(), _preview(command),
                 cwd, timeout_s, remote_dir, "launching", now, now),
            )
            self._event(job_id, "job_created", "launching",
                        f"Bound {label} to the locked {backend} backend")
            self._conn.commit()

    def observe(self, job_id: str, observation: Mapping[str, Any], *,
                kind: str, summary: str) -> dict[str, Any]:
        _validate_job_id(job_id)
        allowed = {
            "state", "pid", "workload_pid", "owned", "exit_code", "stdout_size",
            "stderr_size", "stdout_cursor", "stderr_cursor", "started_at", "ended_at",
            "heartbeat_at", "collected_at", "error",
        }
        fields = {k: observation[k] for k in allowed if k in observation}
        if "owned" in fields:
            fields["owned"] = int(bool(fields["owned"]))
        fields["updated_at"] = time.time()
        with self._lock:
            current = self._conn.execute(
                "SELECT state,last_stdout,last_stderr FROM durable_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
            if not current:
                raise ExecutionBoundaryError("job is not owned by this controller ledger")
            for output_name, column, previous in (
                ("stdout", "last_stdout", current[1]),
                ("stderr", "last_stderr", current[2]),
            ):
                delta = str(observation.get(output_name) or "")
                if delta:
                    fields[column] = (str(previous or "") + delta)[-12000:]
            assignments = ",".join(f"{name}=?" for name in fields)
            self._conn.execute(
                f"UPDATE durable_jobs SET {assignments} WHERE job_id=?",
                (*fields.values(), job_id),
            )
            event_data = {
                k: observation[k] for k in (
                    "stdout", "stderr", "stdout_cursor", "stderr_cursor", "exit_code",
                    "changed", "more", "signal",
                ) if k in observation
            }
            self._event(job_id, kind, str(fields.get("state") or current[0]),
                        summary, event_data)
            self._conn.commit()
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        _validate_job_id(job_id)
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM durable_jobs WHERE job_id=?", (job_id,)
            )
            row = cur.fetchone()
            if not row:
                raise ExecutionBoundaryError("job is not owned by this controller ledger")
            item = dict(zip((c[0] for c in cur.description), row))
        item["target"] = json.loads(item.pop("target_json"))
        item["owned"] = bool(item["owned"])
        return item

    def list(self, *, limit: int = 100, state: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._lock:
            if state:
                cur = self._conn.execute(
                    "SELECT * FROM durable_jobs WHERE state=? "
                    "ORDER BY updated_at DESC LIMIT ?", (state, limit)
                )
            else:
                cur = self._conn.execute(
                    "SELECT * FROM durable_jobs ORDER BY updated_at DESC LIMIT ?", (limit,)
                )
            columns = [c[0] for c in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        for item in rows:
            item["target"] = json.loads(item.pop("target_json"))
            item["owned"] = bool(item["owned"])
        return rows

    def events(self, job_id: str, *, after: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        self.get(job_id)
        with self._lock:
            cur = self._conn.execute(
                "SELECT id,ts,job_id,kind,state,summary,data_json "
                "FROM durable_job_events WHERE job_id=? AND id>? ORDER BY id LIMIT ?",
                (job_id, max(0, int(after)), max(1, min(int(limit), 1000))),
            )
            columns = [c[0] for c in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        for item in rows:
            item["data"] = json.loads(item.pop("data_json"))
        return rows


class GCEAuthorizedTarget:
    def __init__(self, vm: str, project: str, account: str, zone: str) -> None:
        values = {"vm": vm, "project": project, "account": account, "zone": zone}
        for name, value in values.items():
            if not isinstance(value, str) or not _SELECTOR.fullmatch(value):
                raise ExecutionBoundaryError(
                    f"invalid {name}: expected one non-option selector token"
                )
        self.vm, self.project, self.account, self.zone = vm, project, account, zone

    @property
    def descriptor(self) -> dict[str, str]:
        return {"vm": self.vm, "project": self.project,
                "account": self.account, "zone": self.zone}


def gcloud_ssh_argv(target: GCEAuthorizedTarget, command: str) -> list[str]:
    if not isinstance(command, str) or not command.strip() or "\x00" in command:
        raise ExecutionBoundaryError("remote command must be non-empty and contain no NUL")
    if len(command.encode()) > 131072:
        raise ExecutionBoundaryError("remote transport envelope exceeds 131072 bytes")
    return [
        "gcloud", "compute", "ssh", target.vm,
        "--project", target.project, "--account", target.account,
        "--zone", target.zone, "--quiet", "--command", command,
    ]


_REMOTE_STATUS = r'''
def read_number(path, cast=float):
    try:
        return cast(open(path).read().strip())
    except (OSError, ValueError):
        return None
def proc_owned(pid, needle):
    if not pid:
        return False
    try:
        raw=open('/proc/%d/cmdline'%pid,'rb').read().replace(b'\0',b' ').decode('utf-8','replace')
        os.kill(pid,0)
        return needle in raw
    except (OSError, ValueError):
        return False
def status(root):
    pid=read_number(os.path.join(root,'pid'),int)
    workload=read_number(os.path.join(root,'workload.pid'),int)
    code=read_number(os.path.join(root,'exit_code'),int)
    owned=proc_owned(pid,os.path.join(root,'wrapper.py'))
    state=('completed' if code==0 else 'failed') if code is not None else ('running' if owned else 'lost')
    return {'state':state,'pid':pid,'workload_pid':workload,'owned':owned,
      'exit_code':code,'stdout_size':os.path.getsize(os.path.join(root,'stdout.log')) if os.path.exists(os.path.join(root,'stdout.log')) else 0,
      'stderr_size':os.path.getsize(os.path.join(root,'stderr.log')) if os.path.exists(os.path.join(root,'stderr.log')) else 0,
      'started_at':read_number(os.path.join(root,'started_at')),
      'ended_at':read_number(os.path.join(root,'ended_at')),
      'heartbeat_at':read_number(os.path.join(root,'heartbeat'))}
'''


_START_PROGRAM = r"""
import json,os,subprocess,sys,time
p=json.loads(PAYLOAD)
root=p['root']; allowed='/tmp/llm-super-agent'
os.makedirs(allowed,mode=0o700,exist_ok=True)
cwd=os.path.realpath(p['cwd'])
if not (cwd==allowed or cwd.startswith(allowed+'/')): raise SystemExit('cwd escapes authorized root')
if not os.path.isdir(cwd): raise SystemExit('cwd does not exist')
os.makedirs(root,mode=0o700,exist_ok=False)
command_path=os.path.join(root,'command.sh'); wrapper_path=os.path.join(root,'wrapper.py')
open(command_path,'w').write(p['command']); os.chmod(command_path,0o700)
wrapper=r'''import json,os,signal,subprocess,sys,time
p=json.loads(PAYLOAD); root=p['root']
def atomic(name,value):
 t=os.path.join(root,name+'.tmp'); open(t,'w').write(str(value)); os.replace(t,os.path.join(root,name))
atomic('started_at',time.time())
out=open(os.path.join(root,'stdout.log'),'ab',buffering=0); err=open(os.path.join(root,'stderr.log'),'ab',buffering=0)
env=os.environ.copy(); env['LLM_SUPER_JOB_ID']=p['job_id']; env['LLM_SUPER_JOB_DIR']=root; env['LLM_SUPER_ARTIFACT_DIR']=os.path.join(root,'artifacts')
child=subprocess.Popen(['/usr/bin/timeout','--signal=TERM','--kill-after=5',str(p['timeout_s'])+'s','/bin/sh',os.path.join(root,'command.sh')],cwd=p['cwd'],stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True,env=env)
atomic('workload.pid',child.pid)
while child.poll() is None:
 atomic('heartbeat',time.time()); time.sleep(1)
code=child.wait(); code=128+(-code) if code < 0 else code
atomic('heartbeat',time.time()); atomic('exit_code',code); atomic('ended_at',time.time())
out.close(); err.close()
'''.replace('PAYLOAD',repr(json.dumps(p,separators=(',',':'))))
open(wrapper_path,'w').write(wrapper); os.chmod(wrapper_path,0o700)
open(os.path.join(root,'meta.json'),'w').write(json.dumps({k:p[k] for k in ('job_id','label','timeout_s','command_sha256')},sort_keys=True))
os.makedirs(os.path.join(root,'artifacts'),mode=0o700,exist_ok=True)
open(os.path.join(root,'stdout.log'),'ab').close(); open(os.path.join(root,'stderr.log'),'ab').close()
proc=subprocess.Popen([sys.executable,wrapper_path],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,close_fds=True)
t=os.path.join(root,'pid.tmp'); open(t,'w').write(str(proc.pid)); os.replace(t,os.path.join(root,'pid'))
print(json.dumps({'ok':True,'state':'running','job_id':p['job_id'],'pid':proc.pid,'owned':True,'stdout_size':0,'stderr_size':0,'stdout_cursor':0,'stderr_cursor':0}))
"""


_INSPECT_PROGRAM = _REMOTE_STATUS + r'''
import json,os
p=json.loads(PAYLOAD); root=p['root']
if not os.path.isdir(root): raise SystemExit('job directory missing')
r=status(root); r.update({'ok':True,'job_id':p['job_id']}); print(json.dumps(r))
'''


_WATCH_PROGRAM = _REMOTE_STATUS + r'''
import json,os,time
p=json.loads(PAYLOAD); root=p['root']
if not os.path.isdir(root): raise SystemExit('job directory missing')
deadline=time.monotonic()+p['wait_seconds']
while True:
 r=status(root)
 if r['stdout_size']>p['stdout_cursor'] or r['stderr_size']>p['stderr_cursor'] or r['state'] in ('completed','failed','lost') or time.monotonic()>=deadline: break
 time.sleep(.25)
budget=p['max_bytes']
def delta(name,cursor):
 global budget
 path=os.path.join(root,name); size=os.path.getsize(path) if os.path.exists(path) else 0
 cursor=min(cursor,size)
 with open(path,'rb') as f: f.seek(cursor); raw=f.read(budget)
 budget-=len(raw)
 return raw.decode('utf-8','replace'),cursor+len(raw),cursor+len(raw)<size
stdout,so,more_out=delta('stdout.log',p['stdout_cursor'])
stderr,se,more_err=delta('stderr.log',p['stderr_cursor'])
r.update({'ok':True,'job_id':p['job_id'],'stdout':stdout,'stderr':stderr,'stdout_cursor':so,'stderr_cursor':se,'changed':bool(stdout or stderr or r['state'] in ('completed','failed','lost')),'more':more_out or more_err})
print(json.dumps(r))
'''


_SIGNAL_PROGRAM = _REMOTE_STATUS + r'''
import json,os,signal,time
p=json.loads(PAYLOAD); root=p['root']; r=status(root)
if r['state']!='running' or not r['owned']: raise SystemExit('job is not a live owned process')
wpid=r['workload_pid']
if not wpid: raise SystemExit('owned workload pid is unavailable')
try:
 if os.getpgid(wpid)!=wpid: raise SystemExit('workload process group is not isolated')
except OSError: raise SystemExit('workload process no longer exists')
sigs={'interrupt':signal.SIGINT,'terminate':signal.SIGTERM,'kill':signal.SIGKILL}
os.killpg(wpid,sigs[p['signal']])
r.update({'ok':True,'job_id':p['job_id'],'signal':p['signal'],'state':'signaled'})
print(json.dumps(r))
'''


_COLLECT_PROGRAM = _REMOTE_STATUS + r'''
import json,os
p=json.loads(PAYLOAD); root=p['root']; r=status(root)
budget=p['max_bytes']
def delta(name,cursor):
 global budget
 path=os.path.join(root,name); size=os.path.getsize(path) if os.path.exists(path) else 0
 cursor=min(cursor,size)
 with open(path,'rb') as f: f.seek(cursor); raw=f.read(budget)
 budget-=len(raw)
 return raw.decode('utf-8','replace'),cursor+len(raw),cursor+len(raw)<size
stdout,so,mo=delta('stdout.log',p['stdout_cursor']); stderr,se,me=delta('stderr.log',p['stderr_cursor'])
artifacts=[]; ad=os.path.join(root,'artifacts')
if os.path.isdir(ad):
 for base,dirs,files in os.walk(ad,followlinks=False):
  dirs[:]=[d for d in dirs if not os.path.islink(os.path.join(base,d))]
  for name in files:
   path=os.path.join(base,name)
   if not os.path.islink(path): artifacts.append({'path':os.path.relpath(path,ad),'bytes':os.path.getsize(path)})
   if len(artifacts)>=100: break
  if len(artifacts)>=100: break
r.update({'ok':True,'job_id':p['job_id'],'stdout':stdout,'stderr':stderr,'stdout_cursor':so,'stderr_cursor':se,'more':mo or me,'artifacts':artifacts,'collected':r['state'] in ('completed','failed','lost')})
print(json.dumps(r))
'''


class GCEJobBackend:
    """Durable-job adapter whose workloads can spawn only on one fixed GCE VM."""

    backend_name = "gce"

    def __init__(
        self,
        target: GCEAuthorizedTarget,
        store: DurableJobStore,
        *,
        boundary_fingerprint: str,
        ssh_timeout_s: float = 120.0,
        runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
        job_id_factory: Callable[[], str] | None = None,
        flow_runtime: Any | None = None,
    ) -> None:
        if ssh_timeout_s <= 0 or not math.isfinite(ssh_timeout_s):
            raise ValueError("ssh_timeout_s must be finite and positive")
        self.target = target
        self.store = store
        self.boundary_fingerprint = boundary_fingerprint
        self.ssh_timeout_s = ssh_timeout_s
        self._runner = runner
        self._job_id_factory = job_id_factory or (lambda: f"job_{uuid.uuid4().hex[:24]}")
        self.flow_runtime = flow_runtime

    def _graph_start(self, job_id: str, label: str, command: str,
                     context: Mapping[str, str]) -> None:
        if self.flow_runtime is None:
            return
        flow = self.flow_runtime.registry.flows["durable_locked_job"]
        self.flow_runtime.start(
            "durable_locked_job",
            {"job_id": job_id, "label": label,
             "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
             "backend": self.backend_name, "target": self.target.descriptor},
            dict(flow.budgets), list(flow.capabilities), run_id=job_id,
            session=str(context.get("session") or "-"),
            task=str(context.get("task") or label),
        )
        self.flow_runtime.transition(
            job_id, "execution_lock", "execution_boundary_verified",
            summary="Adapter and exact target match the immutable backend lock",
            data={"backend": self.backend_name,
                  "boundary_fingerprint": self.boundary_fingerprint},
        )

    def _graph_move(self, job_id: str, node: str, kind: str, summary: str,
                    *, status: str = "running", data: Mapping[str, Any] | None = None,
                    allow_jump: bool = False) -> None:
        if self.flow_runtime is None:
            return
        try:
            self.flow_runtime.transition(
                job_id, node, kind, status=status, summary=summary,
                data=dict(data or {}), allow_jump=allow_jump,
            )
        except (KeyError, ValueError, sqlite3.Error):
            # The job ledger is the execution authority. Graph projection is
            # additive observability and cannot make a remote process unsafe.
            return

    @property
    def target_descriptor(self) -> Mapping[str, str]:
        return self.target.descriptor

    def _payload_command(self, program: str, payload: Mapping[str, Any]) -> str:
        source = "PAYLOAD=" + repr(_json(payload)) + "\n" + program
        encoded = base64.b64encode(source.encode()).decode("ascii")
        return "python3 -c \"import base64;exec(base64.b64decode('" + encoded + "'))\""

    def _transport_argv(self, command: str) -> list[str]:
        """The only backend-specific seam: how one command reaches the target.

        Every remote program, cursor rule, ownership check, and evidence
        bound is shared across adapters; a new backend overrides just this.
        """
        return gcloud_ssh_argv(self.target, command)

    def _remote(self, program: str, payload: Mapping[str, Any], *,
                timeout_s: float | None = None) -> dict[str, Any]:
        argv = self._transport_argv(self._payload_command(program, payload))
        try:
            completed = self._runner(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, shell=False, check=False,
                timeout=min(self.ssh_timeout_s, timeout_s or self.ssh_timeout_s),
            )
        except subprocess.TimeoutExpired:
            return {"ok": False,
                    "error": f"{self.backend_name} transport timed out"}
        except OSError as exc:
            return {"ok": False,
                    "error": f"{self.backend_name} transport failed: "
                             f"{str(exc)[:300]}"}
        stdout = (completed.stdout or b"").decode("utf-8", "replace")
        stderr = (completed.stderr or b"").decode("utf-8", "replace")
        if completed.returncode != 0:
            return {"ok": False, "error": "remote job operation failed",
                    "transport_exit_code": completed.returncode,
                    "transport_stderr": stderr[-2000:]}
        for line in reversed(stdout.splitlines()):
            try:
                result = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(result, dict):
                result["execution"] = {
                    "remote_only": True, "backend": self.backend_name,
                    "target": self.target.descriptor,
                    "boundary_fingerprint": self.boundary_fingerprint,
                }
                return result
        return {"ok": False, "error": "remote operation returned no JSON result"}

    def _owned(self, job_id: str) -> dict[str, Any]:
        item = self.store.get(_validate_job_id(job_id))
        if item["backend"] != self.backend_name:
            raise ExecutionBoundaryError("job belongs to another backend")
        if item["boundary_fingerprint"] != self.boundary_fingerprint:
            raise ExecutionBoundaryError("job belongs to another execution boundary")
        if item["target"] != self.target.descriptor:
            raise ExecutionBoundaryError("job belongs to another backend target")
        return item

    def start(self, command: str, *, cwd: str, timeout_s: int, label: str,
              context: Mapping[str, str]) -> Mapping[str, Any]:
        if not isinstance(command, str) or not command.strip() or "\x00" in command:
            raise ExecutionBoundaryError("command must be non-empty and contain no NUL")
        if len(command.encode()) > 32768:
            raise ExecutionBoundaryError("command exceeds the 32768-byte job limit")
        if not isinstance(label, str) or not label.strip() or len(label) > 120:
            raise ExecutionBoundaryError("label must contain 1 to 120 characters")
        timeout_s = _nonnegative(timeout_s, "timeout_s", 86400)
        if timeout_s < 1:
            raise ExecutionBoundaryError("timeout_s must be at least 1")
        if not isinstance(cwd, str) or "\x00" in cwd or not cwd.startswith("/"):
            raise ExecutionBoundaryError("cwd must be an absolute path")
        normalized = posixpath.normpath(cwd)
        if normalized != _ALLOWED_CWD and not normalized.startswith(_ALLOWED_CWD + "/"):
            raise ExecutionBoundaryError("cwd is outside /tmp/llm-super-agent")
        job_id = _validate_job_id(self._job_id_factory())
        remote_dir = f"{_JOB_ROOT}/{job_id}"
        self.store.create(
            job_id=job_id, backend=self.backend_name,
            boundary_fingerprint=self.boundary_fingerprint,
            target=self.target.descriptor, context=context, label=label.strip(),
            command=command, cwd=normalized, timeout_s=timeout_s, remote_dir=remote_dir,
        )
        self._graph_start(job_id, label.strip(), command, context)
        payload = {
            "job_id": job_id, "root": remote_dir, "command": command,
            "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
            "cwd": normalized, "timeout_s": timeout_s, "label": label.strip(),
        }
        result = self._remote(_START_PROGRAM, payload)
        if not result.get("ok"):
            self.store.observe(job_id, {"state": "launch_failed",
                                       "error": str(result.get("error") or "launch failed")},
                               kind="job_launch_failed", summary="Remote launch failed")
            self._graph_move(job_id, "job_blocked", "job_launch_failed",
                             "Remote process ownership was not established",
                             status="failed")
            result["job_id"] = job_id
            return result
        self.store.observe(job_id, result, kind="job_started",
                           summary="Durable remote process started")
        self._graph_move(job_id, "durable_start", "job_started",
                         "Durable remote process started",
                         data={"job_id": job_id, "pid": result.get("pid")})
        result["next"] = {
            "tool": WATCH_JOB_TOOL, "stdout_cursor": 0, "stderr_cursor": 0,
            "instruction": "Watch with these exact cursors; reuse returned cursors.",
        }
        return result

    def inspect(self, job_id: str) -> Mapping[str, Any]:
        item = self._owned(job_id)
        result = self._remote(_INSPECT_PROGRAM,
                              {"job_id": job_id, "root": item["remote_dir"]})
        if result.get("ok"):
            self.store.observe(job_id, result, kind="job_inspected",
                               summary=f"Job is {result.get('state', 'unknown')}")
            result["next"] = {
                "tool": WATCH_JOB_TOOL,
                "stdout_cursor": item["stdout_cursor"],
                "stderr_cursor": item["stderr_cursor"],
                "instruction": "Resume observation from these exact persisted cursors.",
            }
        return result

    @staticmethod
    def _require_exact_cursors(item: Mapping[str, Any], stdout_cursor: int,
                               stderr_cursor: int) -> None:
        expected_stdout = int(item["stdout_cursor"])
        expected_stderr = int(item["stderr_cursor"])
        if stdout_cursor != expected_stdout or stderr_cursor != expected_stderr:
            raise ExecutionBoundaryError(
                "output cursor rewind or skip rejected; expected "
                f"stdout_cursor={expected_stdout}, stderr_cursor={expected_stderr}"
            )

    def watch(self, job_id: str, *, stdout_cursor: int, stderr_cursor: int,
              wait_seconds: int, max_bytes: int) -> Mapping[str, Any]:
        item = self._owned(job_id)
        stdout_cursor = _nonnegative(stdout_cursor, "stdout_cursor", 2**63 - 1)
        stderr_cursor = _nonnegative(stderr_cursor, "stderr_cursor", 2**63 - 1)
        self._require_exact_cursors(item, stdout_cursor, stderr_cursor)
        wait_seconds = _nonnegative(wait_seconds, "wait_seconds", 60)
        max_bytes = _nonnegative(max_bytes, "max_bytes", 131072)
        if max_bytes < 256:
            raise ExecutionBoundaryError("max_bytes must be at least 256")
        result = self._remote(
            _WATCH_PROGRAM,
            {"job_id": job_id, "root": item["remote_dir"],
             "stdout_cursor": stdout_cursor, "stderr_cursor": stderr_cursor,
             "wait_seconds": wait_seconds, "max_bytes": max_bytes},
            timeout_s=wait_seconds + 15,
        )
        if result.get("ok"):
            summary = (f"Job changed: {result.get('state')}" if result.get("changed")
                       else f"No change before {wait_seconds}s watch timeout")
            self.store.observe(job_id, result, kind="job_watch", summary=summary)
            self._graph_move(
                job_id, "change_watch", "job_watch", summary,
                data={"job_id": job_id, "state": result.get("state"),
                      "stdout_cursor": result.get("stdout_cursor"),
                      "stderr_cursor": result.get("stderr_cursor")},
            )
        return result

    def signal(self, job_id: str, *, signal_name: str) -> Mapping[str, Any]:
        item = self._owned(job_id)
        if signal_name not in {"interrupt", "terminate", "kill"}:
            raise ExecutionBoundaryError("signal must be interrupt, terminate, or kill")
        result = self._remote(
            _SIGNAL_PROGRAM,
            {"job_id": job_id, "root": item["remote_dir"], "signal": signal_name},
        )
        if result.get("ok"):
            result["next"] = {
                "tool": WATCH_JOB_TOOL,
                "stdout_cursor": item["stdout_cursor"],
                "stderr_cursor": item["stderr_cursor"],
                "instruction": (
                    "Signal delivery did not read output. Continue from these exact "
                    "persisted cursors; stdout_size/stderr_size are byte counts, not cursors."
                ),
            }
            self.store.observe(job_id, result, kind="job_signaled",
                               summary=f"Sent {signal_name} to the owned process group")
            # A signal immediately after start first establishes the watch
            # checkpoint so every cancellation has an observable before/after.
            self._graph_move(job_id, "change_watch", "job_watch_checkpoint",
                             "Established cancellation observation checkpoint")
            self._graph_move(job_id, "exact_signal", "job_signaled",
                             f"Sent {signal_name} to the exact owned process group",
                             data={"signal": signal_name})
        return result

    def collect(self, job_id: str, *, stdout_cursor: int, stderr_cursor: int,
                max_bytes: int) -> Mapping[str, Any]:
        item = self._owned(job_id)
        stdout_cursor = _nonnegative(stdout_cursor, "stdout_cursor", 2**63 - 1)
        stderr_cursor = _nonnegative(stderr_cursor, "stderr_cursor", 2**63 - 1)
        self._require_exact_cursors(item, stdout_cursor, stderr_cursor)
        max_bytes = _nonnegative(max_bytes, "max_bytes", 262144)
        if max_bytes < 256:
            raise ExecutionBoundaryError("max_bytes must be at least 256")
        result = self._remote(
            _COLLECT_PROGRAM,
            {"job_id": job_id, "root": item["remote_dir"],
             "stdout_cursor": stdout_cursor, "stderr_cursor": stderr_cursor,
             "max_bytes": max_bytes},
        )
        if result.get("ok"):
            observation = dict(result)
            if result.get("collected"):
                observation["collected_at"] = time.time()
            self.store.observe(job_id, observation, kind="job_collected",
                               summary="Collected bounded output and artifact manifest")
            self._graph_move(job_id, "change_watch", "job_watch_checkpoint",
                             "Established collection observation checkpoint")
            self._graph_move(
                job_id, "evidence_collect", "job_collected",
                "Collected bounded output, state, and artifact evidence",
                data={"state": result.get("state"),
                      "stdout_cursor": result.get("stdout_cursor"),
                      "stderr_cursor": result.get("stderr_cursor"),
                      "artifacts": result.get("artifacts", [])},
            )
            if result.get("collected"):
                self._graph_move(job_id, "job_complete", "job_evidence_preserved",
                                 "Terminal job evidence is durably preserved")
        return result


class DockerAuthorizedTarget:
    """One immutable local/remote container as the job boundary target."""

    def __init__(self, container: str) -> None:
        if not isinstance(container, str) or not _SELECTOR.fullmatch(container):
            raise ExecutionBoundaryError(
                "invalid container: expected one non-option selector token"
            )
        self.container = container

    @property
    def descriptor(self) -> dict[str, str]:
        return {"container": self.container}


def docker_exec_argv(target: DockerAuthorizedTarget, command: str) -> list[str]:
    if not isinstance(command, str) or not command.strip() or "\x00" in command:
        raise ExecutionBoundaryError("remote command must be non-empty and contain no NUL")
    if len(command.encode()) > 131072:
        raise ExecutionBoundaryError("remote transport envelope exceeds 131072 bytes")
    return ["docker", "exec", target.container, "/bin/sh", "-c", command]


class DockerJobBackend(GCEJobBackend):
    """Durable-job adapter whose workloads spawn in one fixed container.

    Proof of the backend-neutral protocol: every remote program (start
    wrapper, status, cursor-windowed watch, ownership-exact signal, bounded
    collect), every cursor rule, and every ownership/fingerprint check is
    inherited unchanged from the shared implementation — only the transport
    argv differs (``docker exec`` instead of ``gcloud compute ssh``). The
    container needs python3 and coreutils (e.g. the ``python:3.11-slim``
    image). Backend and target are trusted operator configuration; there is
    no agent-visible backend or target argument.
    """

    backend_name = "docker"

    def __init__(
        self,
        target: DockerAuthorizedTarget,
        store: DurableJobStore,
        *,
        boundary_fingerprint: str,
        exec_timeout_s: float = 120.0,
        runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
        job_id_factory: Callable[[], str] | None = None,
        flow_runtime: Any | None = None,
    ) -> None:
        super().__init__(
            target,  # duck-typed: only .descriptor is used by shared code
            store,
            boundary_fingerprint=boundary_fingerprint,
            ssh_timeout_s=exec_timeout_s,
            runner=runner,
            job_id_factory=job_id_factory,
            flow_runtime=flow_runtime,
        )

    def _transport_argv(self, command: str) -> list[str]:
        return docker_exec_argv(self.target, command)
