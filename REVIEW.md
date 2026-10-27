# Review policy — Conflux core rebuild

Contract: `docs/rebuild/MISSION.md`. Integration base: `rebuild/conflux-core-20261026`.

## Extra passes

- **False acceptance.** Any path that can report a task, check or probe as successful without
  independent evidence (executed check output, verified artifact) is Important. Missing evidence must
  stay distinct from a check that ran and failed.
- **Probabilities.** Fabricated, defaulted or digit-scale "probabilities" are Important. Logprob-based
  scoring uses the letter scale (A–T); grounded criticism must not be presented as a probability.
- **Budget and acceptance authority.** Model output must never raise budgets or accept work. Changes
  that let a model (including Jev) decide these are Important.
- **Execution model routing.** Changes that silently move ordinary execution off DeepSeek to a more
  expensive model, or route development tools (Claude Code/Codex) through Surplus, are Important.
- **Secrets.** Keys, tokens, credential-bearing logs or raw private traces in the diff are Important.
- **Accounting.** Cost/quota/usage numbers must come from provider responses or documented prices,
  and subscription usage must be tracked separately from cash.
- **Abstraction stacking.** A new layer, registry, framework or generic scheduler without a
  demonstrated requirement that direct code cannot meet is Important when it adds code paths the
  mission defers (DAG scheduler, workflow editor, store framework, broad UI).
- **Demo before build.** A PR that adds or changes how Conflux uses agents (new layer, detector,
  classifier, model/route, prompt, policy, critic/decider wiring) without citing a demo's
  `~/evidence/<demo>/RESULTS.md` whose numbers support the change is Important. Fixes for observed
  harness faults need a regression test reproducing the fault instead.
- **Evaluation claims.** Claims of improvement must cite matched held-out runs; a single favorable
  demo or a model's self-grade is not evidence.

## Known exclusions

- Deleting legacy implementation files is expected on this branch (preserved at tag
  `conflux-baseline-20261026`). Review the replacement, not the deletion.
- `artifacts/` evidence is retained outside Git; do not request committing it.
- File-access scope is not a security boundary (founder decision 2026-10-27: agents run on disposable
  scratch VMs). File-access scope, scope-check bypasses, sandbox escapes and path-permission
  precision are not blocking — Nit at most. Over-holding harmless actions is the bug class this
  rebuild fixes.
