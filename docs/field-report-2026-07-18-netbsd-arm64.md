# Field report — remote NetBSD/AArch64 agent exercise (2026-07-18)

Status: **accepted**. The release, image, emulated boot, guest validation, and
final supervised response all completed successfully. This report remains the
durable issue log for the exercise.

Cost-control state: after final verification, the VM was stopped and verified
`TERMINATED`; its 100 GB persistent boot disk remains `READY` with all
artifacts. Compute charges are stopped, while persistent-disk storage charges
continue. The instance was not deleted.

Companion records:

- [Full chronological forensic report](./netbsd-arm64-endeavor-forensic-report-2026-07-18.md)
- [Exact 113-call agent tool ledger](./netbsd-arm64-agent-tool-ledger-2026-07-18.md)
- [Evidence-backed history UI redesign](./history-ui-redesign-2026-07-18.md)
- [Reusable trace acceptance audit](./agentic-trace-audit.sql)

## Exercise and safety boundary

The task is deliberately long-running and stateful: use llm-super to drive an
agent that cross-compiles NetBSD for AArch64 on an x86_64 Google Compute Engine
host, then boots that image with `qemu-system-aarch64` under TCG. All build,
installation, scripting, and emulation workload must run on one existing VM:

- account: `gce-operator@example.com`
- project: `project96-sar`
- zone: `us-central1-a`
- VM: `llmsuper-netbsd-arm64`

Hermes and llm-super run locally as the client and proxy. They are not to move
the workload onto the local machine. Every legitimate `gcloud compute ssh`
call carries all four selectors explicitly; the exercise must not depend on
mutable global gcloud defaults.

## Final remote state

- The VM was created successfully and independently checked: Debian 12,
  `n2-standard-8`, Intel x86_64, 100 GB disk, and no attached service account.
- Official NetBSD `netbsd-10` source is in
  `/home/operator/netbsd-src`.
- `build.sh -m evbarm -a aarch64` produced working cross tools; the compiler
  reports `aarch64--netbsd`.
- The `GENERIC64` AArch64 kernel built successfully. Its compressed artifact
  is 7,389,749 bytes with SHA-256
  `32fffc3db189222854740fc4e3bbac4066fbeb5c6e0198233a0dbb77a6373207`.
- The durable `release` build exited zero at 08:19:44 UTC. Its QEMU-ready
  `releasedir/evbarm-aarch64/binary/gzimg/arm64.img.gz` is 303,656,165 bytes
  with SHA-256
  `e241129af24cd3b52d0455aa3915d29c15c377adc8c6bf1a8be66a6d42beaff5`;
  the working raw image is 8 GiB. The standalone
  `disk-image=arm64` target is avoided on this branch because its kernel-name
  precheck does not match `GENERIC64`.
- The saved QEMU command explicitly uses `qemu-system-aarch64` and
  `-machine virt,accel=tcg`. The serial log records resize/reboot followed by
  NetBSD `10.1_STABLE`, `MACHINE=evbarm`, `ARCH=aarch64`,
  `hw.machine_arch=aarch64`, the required validation markers, and a clean
  poweroff. `boot.exit` contains `0`, `validation.txt` records `QEMU_EXIT=0`,
  and no QEMU process remains.
- Durable boot evidence is under
  `/home/operator/llmsuper-netbsd-run/`: `qemu-command.txt`, `serial.log`,
  `validation.txt`, `driver.out`, and `boot.exit`. SHA-256 values are
  `076f9deee675690a12eba55b40a6c6989e98585b5308bd5239049a3533161b32`
  for `qemu-command.txt`,
  `b88140b9ebfbef2119bdcbd0ef6724eae375acdfec85a1149f4ada8b72032194`
  for `serial.log`, and
  `c40e298115bd0a1c42248aa1a5ee181f1a31f1c0523696c93b46e00e67cd148a`
  for `validation.txt`.

## Deficiencies and failures found

### 1. Hermes credential refresh was both misleading and unreachable

The first live agent request failed with Nous HTTP 401. `hermes auth status
nous` can report a still-unexpired session as logged in, but does not force
rotation of an inference key that the service has rejected. The proven forced
refresh is:

```bash
hermes auth add nous --type oauth --no-browser
# accept: Import these credentials? [Y/n]
```

With existing shared Nous OAuth state, this rehydrates the session and writes
a new `providers.nous.agent_key` to `~/.hermes/auth.json`. The exact procedure
is now documented in `README.md`, and `llm_super/keys.py` has an unattended
version guarded by the presence of shared state.

A second bug made that new hook ineffective for Hermes traffic at the time of
failure: `Client.chat()` retried 401/403 through `try_refresh()`, while
`Client.raw_chat()`—the tool-carrying path—did not. The live failure required a
manual refresh. Provider fallback did not save the run: the OpenCode Go
fallback returned HTTP 400 for the raw Hermes request. The patch now uses a
shared auth-refresh path in both methods, normalizes credential lookup failures
as provider failures, and covers raw 401/403 retry and fallback behavior.

### 2. Agentic supervision is mostly absent between tool calls

Direct `traces.db` inspection shows that tool-carrying requests create
`agent_turn` and `tool_step` events plus request/upstream/response exchanges,
but the exercised `run_tool_turn()` implementation did not:

- extract or persist a contract;
- call the cross-turn failure-mode monitors;
- record rows in `turns`;
- create or consume checkpoints;
- enforce pause at ingress or before returning a tool call; or
- verify anything until a final text response arrives.

At the latest clean-run snapshot, session `a7ac14a9f48f` had 69 complete tool
steps with exactly one `agent_turn`, `client_request`, `upstream`,
`client_response`, and `tool_step` per task—but zero `verify` and zero
`agent_end`. The database therefore correctly says the overall task is still
in progress, but it cannot represent progress milestones or resume a tool
loop.

The patch now records exactly one History row, `client_response`, and
`agent_end` for a final agent answer, including budget and verifier-error exits;
intermediate tool steps intentionally remain exchange-only. Agentic contract
extraction, cross-turn monitors, and resumable tool-loop checkpoints remain
open.

### 3. Pause and restart semantics are unsafe for agentic work

The exercised `run_tool_turn()` never checked `ControlState.paused`. A
dashboard pause could therefore leave an agent spending tokens and issuing new
tool decisions. A pause cannot cancel a terminal command already executing
outside llm-super, but it must stop the next model/tool-decision boundary.

Restart also lost `armed_sessions`, while the gate recognized prior work via
normal `History` rows. Because agentic sessions have no `turns` rows, the first
mid-loop request after a server restart can be mistaken for a new conversation
and gated. Persisted library/session existence must participate in the gate,
and final agent answers—not every polling step—should enter normal history.

The patch now enforces pause before agentic spend and again after an in-flight
model call before releasing a proposed tool action. The new-session gate also
uses the persisted `sessions` table, so accepted tool conversations survive a
proxy restart. A running external terminal command still cannot be cancelled
by llm-super; pause applies at the next model/tool boundary.

### 4. Conversation identity and Hermes resume were not reliable

An attempted Hermes `--resume` did not deliver the prior task context on its
first API request. The model invented a VM name and started a recovery against
the wrong cloud context. llm-super hashes the first user message to derive its
session ID, so a rewritten recovery prompt becomes a separate session even
when it belongs to the same operational lineage. There is no explicit stable
session ID supported by the API, and tool-call arguments are omitted from
history divergence comparison.

The safe operational workaround was a new, fully self-contained prompt with
the exact VM state and immutable cloud selectors. The product fix should add
an explicit validated session identifier (header or metadata), retain the
first-user hash only as a fallback, and include tool IDs/names/arguments in
edit/rewind detection.

### 5. Cloud safety was prompt-only and failed during recovery

The bad recovery session `c0904cb7dd7d` contains 16 terminal calls, including
8 `gcloud config set` calls and 7 references to prohibited accounts/projects;
none met the exact-selector boundary. No prohibited resource was mutated, and
the process was interrupted immediately, but a text instruction was the only
guardrail.

The replacement session `a7ac14a9f48f` is clean at the latest DB snapshot:
all 65 terminal calls include the exact VM, project, personal account, and
zone; there are zero config/auth mutations and zero prohibited references.
This boundary should be enforceable in a purpose-built remote-exec tool rather
than left to free-form terminal commands.

### 6. Polling turned one remote process into dozens of model turns

The initial agent polled the detached build every few seconds. The DB reached
69 completed model/tool steps for one still-running release build; 13 terminal
commands began with a local `sleep`, and several calls used background process
wrappers. This is expensive, bloats context, and makes the dashboard noisy
without improving supervision.

Once the remote process was proven durable (`PPID 1`, persistent log and exit
files), the Hermes polling process was stopped. Per user direction, subsequent
model guidance is driven directly through llm-super's completion API without
the large Hermes system prompt. Long waits belong inside one remote command or
the operator's monitor, not in repeated model decisions.

### 7. The first background strategy was not durable

One full release attempt was launched through a local Hermes process manager
with a 600-second timeout. When that wrapper was interrupted, the remote build
died with it. The repaired launch uses a remote script plus `nohup`, writes an
explicit numeric exit file, and has parent PID 1. Long remote jobs need a
durable-job contract and acceptance checks, not merely `background=true` on a
client-side tool.

### 8. Raw OpenAI compatibility has several gaps

Code and trace review found these additional tool-path defects:

- `raw_chat()` removed `stream` but left orphaned `stream_options` in the
  non-stream upstream request. All clean-run raw requests showed this. The
  patch now removes both before forwarding.
- `_sse_raw()` dropped provider extension fields such as `reasoning_details`
  and did not emit the requested final usage chunk. The patch now preserves
  extensions and emits usage only when requested.
- the outer supervised non-streaming response built by `_completion_body()`
  reported `prompt_tokens=0`, `completion_tokens=0`, and `total_tokens=0` even
  when the trace and trailer contain real model usage and cost. OpenAI clients
  therefore cannot meter a supervised call from its response. The local
  follow-up patch now accumulates every accounted supervision call into
  `TurnReport`, returns those totals in non-stream responses, and emits the
  requested final usage chunk for streamed responses; command, gate, and
  pre-dispatch pause replies retain zero usage. A live retest returned 3,899
  prompt, 5,907 completion, and 9,806 total tokens, matching the DB events.
- the normal supervised proxy drops the request's output-token limit before
  orchestration. A live request with `max_tokens: 2500` produced an `execute`
  event with `tokens_out=5586`: the proxy passes only `messages` to
  `run_turn()`, while `_execute()` always substitutes
  `supervision.max_output_tokens`. This remains open; a correct fix must thread
  a per-request clamp through single-turn, ensemble, planned-unit, and
  synthesis executor calls without changing independent verifier limits.
- registry model names were routed through text-only passthrough before the
  proxy checked for tools, silently dropping tool semantics. Tool-bearing
  registry requests now use raw passthrough, including streaming extensions.
- provider-specific output-token parameters/caps are not normalized for each
  fallback candidate; the exact cause of the observed Go HTTP 400 still needs
  a capability probe rather than guesswork.
- budget exhaustion and verifier exceptions could return a final agent
  response without recording the matching `client_response` exchange. All
  final tool-turn exits now use one recorder and have regression coverage.

### 9. Database paths remain cwd-relative

As in the previous field report, starting the server from another working
directory can silently open a different `traces.db`. For an operational resume
test this looks like total state loss. The server needs an explicit `--db` or
data-directory option resolved independently of the launch cwd.

### 10. A high verifier score did not replace target review

The direct completion's verifier correctly rejected the first QEMU plan
because its proposed success marker could be echoed rather than observed from
the guest. The repaired plan received a final score near 1.0, but still
contained two unverified defects: `cp ~/arm64.img.gz` named a nonexistent
source instead of the actual release-directory artifact, and the proposed
Expect sequence `set logfile [open ...]; log_file $logfile` had questionable
channel/path semantics. Continuous target-machine review caught both, so the
plan was not executed verbatim. This is concrete evidence for the dual-source
operating rule below even when the independent verifier reports full
confidence.

## Direct bounded client

[`direct_vm_tool_loop.py`](../scripts/direct_vm_tool_loop.py) replaces Hermes
for this narrow exercise. It sends only the user's task—no Hermes system
prompt—to the non-streaming `/v1/chat/completions` endpoint and advertises
exactly one `run_on_authorized_vm` function. The model controls only its
`command`; the target selectors are frozen client-side and every execution is
an argv-only `gcloud compute ssh` call with explicit VM, project, account, and
zone. It never invokes a local shell or mutates gcloud configuration.

```bash
python3 scripts/direct_vm_tool_loop.py \
  --vm llmsuper-netbsd-arm64 \
  --project project96-sar \
  --account gce-operator@example.com \
  --zone us-central1-a \
  'Inspect the target, reconcile the trace, and report the next safe step.'
```

The task can instead arrive on stdin. `--max-steps`, per-request API and SSH
timeouts, a total timeout, response limits, and bounded JSON tool results keep
the loop finite. Raw assistant messages and tool-call IDs are carried forward
unchanged. Stdout contains only the final answer, while concise redacted
stderr events expose every completion decision, tool command boundary, exit
status, and timeout without printing prompts or remote output. Nine no-cloud
unit tests cover the exact subprocess argv and selector boundary, malformed
arguments, bounded results, safe progress, transcript progression, step
limiting, and the HTTP POST:

```bash
python3 -m unittest tests.test_direct_vm_tool_loop -v
```

A live smoke run through this client created session `91f5e1ddd105`: one tool
step followed by a final response, verifier score approximately 1.0,
non-escalated `agent_end`, two balanced client request/response pairs, six
upstream calls, and one final History row. Independent remote reconciliation
confirmed every validation flag and `active_qemu=0`; the stderr progress was
visible at both model decisions and around the tool execution.

## Checks derived from the database

The reusable read-only CLI audit is
[`agentic-trace-audit.sql`](./agentic-trace-audit.sql). It binds the target
session and immutable cloud selectors at invocation time, then checks trace
shape, payload completeness, terminal boundaries, durable-job evidence, and
final verifier/`agent_end` closure without baking live counts into assertions.
For an external client, however, `traces.db` records the
`run_on_authorized_vm` command and result—not the client-side `gcloud` argv
that supplied its immutable selectors. The DB therefore cannot prove the
chosen target by itself; acceptance also requires the unit-tested exact argv
boundary plus an independent target-machine identity check.

**Operating rule:** every future long-running agent exercise requires
continuous dual-source monitoring at each decision boundary: reconcile the
message/tool/DB trace with direct target-machine process, log, exit-file,
artifact, and runtime evidence. A model's progress or success claim never
counts as evidence until the target machine independently corroborates it.

This run was accepted after all of the following became true:

1. Every completed tool-step task has balanced `client_request`, `upstream`,
   `client_response`, `agent_turn`, and `tool_step` records.
2. Every remote terminal call names the exact authorized VM/project/account/
   zone, with no `gcloud config set`, account activation, prohibited reference,
   or local workload command.
3. The release process is either alive with PID/PPID/log evidence or has an
   explicit zero exit status; disappearance without `release.exit` is failure.
4. The remote host reports x86_64 and the cross compiler reports
   `aarch64--netbsd`.
5. The release image exists with size and SHA-256 evidence.
6. The saved QEMU command uses `qemu-system-aarch64` and
   `-machine virt,accel=tcg`.
7. The non-echoed serial transcript proves a real NetBSD boot and contains
   `MACHINE=evbarm`, `ARCH=aarch64`, and a completed validation marker.
8. The final model response produces a verifier event and `agent_end`; if it
   does not, that is a framework failure even when the VM artifacts succeed.

The final direct acceptance session, `3e90d8f1cf59`, passed verification at
approximately 1.0 with balanced exchanges. After deploying the usage patch,
its live non-streaming response reported nonzero usage of 3,899 prompt, 5,907
completion, and 9,806 total tokens.

## Fixes and tests

- Implemented forced Hermes shared-state credential refresh, provider raw-auth
  parity, raw request/SSE compatibility, persisted restart knownness, agentic
  pause boundaries, complete final trace/history recording, and supervised
  usage propagation.
- Added the direct fixed-boundary client and reusable DB audit.
- The full repository suite passes 36/36 tests; `compileall` and
  `git diff --check` are clean. The remaining open defects are recorded above.
