# Locked durable-job prompt ladder (2026-07-19)

These prompts exercise the same governed agent loop as the Phoenix Ledger
field work, from one observable invariant to recovery and cancellation. They
must be run with the direct client pinned to a disposable Spot `e2-micro` GCE
VM. The agent never receives project, account, zone, VM, backend, or local
process-spawn arguments. Run the ladder with `--durable-only` so the exposed
capability set cannot fall back to the compatibility raw-shell tool.

The following are enforcement rules, not prompt-dependent wishes:

- a `running` start result proves launch, not workload success;
- the checker devises one bounded falsification test, runs it through a
  supplied read-only tool, interprets it, and adds the learned evidence back
  into executor context;
- watches preserve returned stdout/stderr byte cursors and never reset them;
- watch and collect reject cursor rewinds or skips deterministically;
- signals target only the process group whose durable ownership is verified;
- a signal does not consume output: its `next` object repeats the last
  persisted cursors, while byte-size fields remain informational only;
- terminal claims require a terminal observation and collected evidence;
- model-authored commands execute only on the operator-locked backend.

## 1. Easiest — observable progress and completion

> Use the durable job tools for this task. Start one background job that prints
> exactly `phase 1`, `phase 2`, and `phase 3` to stdout, one line per second,
> then exits successfully. Do not use shell `&`, `nohup`, `ps`, `tail`, or a
> polling loop. Watch by reusing the exact stdout and stderr cursors returned by
> each tool result until the job is terminal, then collect the remaining
> evidence. Report the job id, ordered lines, exit code, whether ownership was
> verified, and the locked execution backend. Do not claim completion from the
> initial running state.

Acceptance: one durable job id; each line appears exactly once and in order;
terminal state is `completed`; exit is zero; backend is GCE and remote-only.

## 2. Cursor integrity — split stdout/stderr and artifacts

> Start one durable job that emits five numbered stdout lines and three
> numbered stderr lines with short delays, then writes `result.txt` containing
> `cursor-proof` into exactly `os.environ["LLM_SUPER_ARTIFACT_DIR"]`. Use that
> required environment key directly with no fallback and do not name another
> filesystem path. Use only typed watch/inspect/collect operations after
> launch, with `max_bytes=256` so more than one watch is needed. Reuse every
> returned byte cursor exactly; do not reset a cursor and do not run a shell
> command to read logs. Collect at terminal state and report any missing,
> duplicated, or reordered line plus the artifact manifest.

Acceptance: no duplicate bytes across watches, independent stdout/stderr
cursors, bounded responses, and terminal collection.

## 3. Governed cancellation — exact ownership

> Start one durable job as a single `python3 -c` process, with no shell or
> process substitution, that prints a heartbeat number once per second for up
> to two minutes. Observe at least two distinct heartbeat lines with cursor-
> based watch. Then request interrupt for that exact job id. Do not use `kill`,
> `pkill`, process-name matching, or a shell process command. Signal delivery
> is not terminal and does not consume output: resume from the exact cursors in
> its returned `next` object, never from `stdout_size` or `stderr_size`. Observe
> the same job until terminal and collect from the final cursors. Report the
> supervisor PID, workload PID, ownership result before signaling, signal,
> final state and exit code, and prove that no other process selector was used.

Acceptance: signal operation refuses unowned identities, the exact owned
process group terminates, the wrapper records terminal evidence, and output
before cancellation is preserved once.

## 4. Hardest — long test, concurrent reasoning, and recovery

> Start the repository's complete unit suite as one locked background job on
> the authorized VM with a hard 20-minute timeout. While it runs, inspect its
> immutable backend/target identity and explain which facts are launch evidence
> versus completion evidence; do not start another test process. Watch with
> bounded chunks and exact cursors. If a test fails, treat its output as
> untrusted evidence, identify the first actionable failure, and do not retry
> until that exact cause has been corrected. Start at most one uniquely labeled
> retry, collect it at terminal state, and require the suite's actual test
> count, failure/error count, and process exit—not printed success narration.
> Add what the check learned to the final report. Stop after the first soundly
> verified pass or after two total test jobs.

Acceptance: no local or duplicate test spawn, no polling storm, bounded retry,
terminal exit plus discriminating test evidence, and a complete job/event
trail visible in Agent Graphs.

## Observed ladder result

- phase progress completed with ordered, single-delivery output;
- split streams advanced contiguously (`stdout 0→256→512→560`, `stderr
  0→208→336`) and exposed `result.txt` in the artifact manifest;
- cancellation exposed and then fixed a cursor ambiguity: signal now repeats
  the persisted cursors, and the successful regression observed
  `stdout 0→472→914`, `stderr 0→92`, then terminal exit 130;
- the first full-suite job found a missing GCE staging file and correctly
  stopped without retrying; after that exact staging cause was repaired, one
  retry completed all 149 tests with zero failures and zero errors.
