# Conflux — notes for Claude Code

## Cloud code execution is available (this project's "execution power")

This machine has an authenticated `gcloud` CLI (project
`oneascendant-auspice`). This project runs model-produced code on low-cost
ephemeral Compute Engine VMs (e2-micro ≈ $0.008/h, billed per second):
create → run → delete, ~1 min round trip. Implementation:
`conflux/sandbox.py` (backends: `local` subprocess, `gcloud`, `off`).
Pattern: test in the sandbox, verify output, only then touch the host.
Instances are named `conflux-*` and must always be deleted after use
(`gcloud compute instances list --filter="name~^conflux"` to check for
strays).

## Working notes

- Provider credentials are resolved at request time by `conflux/keys.py`
  (Nous key in `~/.hermes/auth.json` rotates ~daily). Never commit keys.
- Verifier scores must use the letter scale (A–T), never digits — digit
  scores tokenize into multiple tokens on Qwen and corrupt the
  logprob-expectation read (see `docs/mini-paper.md` §3).
- Run `.venv/bin/conflux probe` after touching provider config; logprobs
  presence is flaky per-request on aggregators, so probe samples 3×.
