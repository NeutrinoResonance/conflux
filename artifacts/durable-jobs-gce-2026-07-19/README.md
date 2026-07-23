# Durable GCE job verification evidence (2026-07-19)

Execution target:

- backend: `gce`, locked and not agent-selectable;
- VM: `llmsuper-durable-jobs-0719`;
- project: `project96-sar`;
- zone: `us-central1-a`;
- machine: Spot/preemptible `e2-micro`, 10 GB `pd-standard`;
- service account/scopes: none.

The workstation acted only as the control plane and fixed-shape `gcloud
compute ssh` transport. Every model-authored command ran inside a durable job
envelope on the VM.

## Prompt ladder evidence

- `job_704f6084476241699cec34de`: easiest ordered progress test, completed,
  exit 0.
- `job_1d2d40b345a8446690ce6ef9`: split stream/artifact test, completed,
  stdout cursors `0→256→512→560`, stderr cursors `0→208→336`, and
  `result.txt` preserved.
- `job_71953621eceb48d78434c7da`: exact cancellation regression, interrupt sent
  only to the owned process group, stdout cursors `0→472→914`, stderr cursor
  `0→92`, terminal exit 130, with no repeated bytes.
- `job_068e79ff6ee145339c12a96d`: first full-suite job, correctly stopped with
  36 staging errors after finding the missing `agent_flows.yaml`.
- `job_0098c10e042f40fba95c0e3e`: one evidence-guided retry, completed all 149
  tests with zero failures and zero errors, exit 0.

The local `traces.db` retains the authoritative job rows, action decisions,
soundness checks, graph runs, and job-event payloads. The `remote-jobs/`
directory contains the VM-side envelopes copied before teardown: separate
stdout/stderr logs, PIDs, heartbeat, exit records, metadata, and artifacts.

## Bugs found and fixed while watching

1. The critic demanded terminal/artifact evidence from a launch operation.
   Launch now declares only falsifiable owned-running-job evidence; later
   watch/inspect/collect establish completion.
2. Signal returned byte sizes that the agent mistook for cursors. Signal now
   returns the last persisted cursors in `next`, and watch/collect reject every
   rewind or skip.
3. Inspect/watch/collect treated a nonzero workload exit as a tool failure.
   Durable observation operations now distinguish workload state from
   transport/tool success.
4. Empty terminal collection could overwrite the retained log tail. Empty
   deltas now preserve the accumulated bounded tail.

Browser MCP verified the graph UI after the live jobs existed: draggable
nodes, background panning, fit/reset, clickable edge conditions, declared/run
layers, remote job inspector, compact retained-log disclosure, clean approval
queue, and no console or network errors.

Teardown status: the evidence was copied before the exact disposable VM and
its disk were deleted; unrelated project instances were not modified.
