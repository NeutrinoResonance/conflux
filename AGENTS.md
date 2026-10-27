# Agent notes (Codex and Claude Code)

- Read `docs/rebuild/MISSION.md` (contract, budgets, stop conditions) and `docs/rebuild/STATE.md`
  (current hypothesis / next action) before working. Resources: `docs/rebuild/RESOURCES.md`.
- Open PRs against your Shepherd session's base branch (normally `rebuild/conflux-core-20261026`);
  never retarget a PR to another base. Never push to `main`.
- Demo before build: any conjectured change to how Conflux uses agents (new layer, detector, classifier,
  model/route, prompt, policy, critic/decider wiring) first gets a throwaway, cost-capped demo on
  recorded traces with numbers in `~/evidence/<demo>/RESULTS.md`. Build only what it supports; cite it
  in the PR. See the 2026-10-27 founder decision in `docs/rebuild/MISSION.md`.
- Tests: `python -m pytest tests -q`. CI runs the same on every PR.
- Verifier scores must use the letter scale (A–T), never digits.
- Never print or commit provider keys; read them from `~/.config/devbox/secrets/` at runtime.
