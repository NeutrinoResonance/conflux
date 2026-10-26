# Agent notes (Codex and Claude Code)

- Read `docs/rebuild/MISSION.md` (contract, budgets, stop conditions) and `docs/rebuild/STATE.md`
  (current hypothesis / next action) before working. Resources: `docs/rebuild/RESOURCES.md`.
- Base branch for all work: `rebuild/conflux-core-20261026`. Never push to `main`.
- Tests: `python -m pytest tests -q`. CI runs the same on every PR.
- Verifier scores must use the letter scale (A–T), never digits.
- Never print or commit provider keys; read them from `~/.config/devbox/secrets/` at runtime.
