# `gpt2-codegolf` supervised GCE run

- Date: 2026-07-21
- Terminal-Bench task: `gpt2-codegolf` (hard)
- Execution boundary: agent commands ran only in
  `tb-gpt2-codegolf-supervised` on GCE VM `llmsuper-tbench-gpt2-0721`, project
  `project96-sar`, zone `us-central1-b`, workdir `/app`
- Boundary fingerprint:
  `b7475d0c1b26b59bcca9575b9c5dd9831c96b799ed7b7d9901f6baf3eb85fb35`
- Machine: `e2-standard-2`; initially Spot with termination action `STOP` and
  retained boot disk, briefly converted to standard after three preemptions
- Task image: `alexgshaw/gpt2-codegolf:20251031`, image ID
  `sha256:537e7bd26b02db5c761230515fa09dc05f89403c6737fbdae4b5793ebc2c7066`
- Final source: `gpt2-codegolf-final.c`, 4,520 bytes, SHA-256
  `3366dda75dbc93b5e4c4af2e1c79f10a7dae69746758fa9047144bcb8f70c004`
- Official verifier: 1/1 passed in 18.71 seconds; reward `1`
- CTRF SHA-256:
  `cd70b55677075db91a0218f1052bd8af07ff3d02246fab41df4c84874d6d5316`
- Reward-file SHA-256:
  `4355a46b19d348dc2f57c046f8ef63d4538ebb936000f3c9ee954a27460dd865`
- Repository validation: 219 tests passed on GCE in 17.760 seconds

The prompt ladder is
`prompts/terminal-bench-gpt2-codegolf-hard.txt` followed by numbered
continuations through `terminal-bench-gpt2-codegolf-hard-continuation-22.txt`.
Matching JSON transcripts and the durable controller database are in this
artifact directory.

Observed defects converted into implementation or deterministic guardrails:

- bounded atomic source writes inside the immutable remote container boundary;
- durable background-job start/watch/inspect/signal/collect operations;
- empty assistant reply retry and resumable transcript normalization;
- governor-correction task identity preservation;
- pipeline and sequential-command exit-status propagation;
- read-only falsification checks that cannot self-certify derived output;
- Spot boot-disk retention and verified recovery after preemption.

Lifecycle: final artifacts were copied and hash-verified before teardown. The
benchmark VM and its separately retained boot disk were deleted after the final
GCE regression suite.
