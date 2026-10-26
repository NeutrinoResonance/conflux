# Conflux self-learning review — follow-up (2026-10-22)

> ChatGPT (GPT-6 via Oracle) reply to the operator's pushback on docs/oracle-review-self-learning-2026-10-22.md. Advisory.

Verdict: Accept the operator's Milestone A proposal, strengthen the benchmark design, and postpone the senate cascade decision until measured. The operator is right on most points. I would make three substantive corrections.

## 1. Scope: Build Milestone A only

AGREE. The 11 deliverables were a roadmap, not a sensible single implementation assignment. Milestone A is the correct experimental unit.

Implement the four proposed changes inside the existing `supervised_tool_turn` Python execution path, not merely in `agent_flows.yaml`.

One important addition: obligation enforcement must be independent of model approval. A senator's low danger score cannot clear its own correctness objection.

Minimum acceptance criteria:

- Every senator's objection survives aggregation, including objections from lower-scoring members.
- Material objections and executor predictions become durable, evidence-linked obligations.
- Postcheck evaluates baseline invariants and records `passed`, `failed`, or `unresolved`.
- Target provenance is established before disposability claims, and revalidated before consequential writes.
- Failed or unresolved material obligations prevent an unqualified success verdict.

Where the operator is slightly wrong: Discovering PSCI through replay proves information-flow repair, not self-learning. That's perfectly acceptable for Milestone A, but label the result correctly.

Defer the lesson ledger. Retain enough obligation provenance that it can be added without redesign.

## 2. Benchmark contamination

AGREE with the criticism; strengthen the proposed safeguards.

My original examples mirrored the incidents too closely. They are useful regression tests but insufficient evidence of generalization.

Mandatory leave-one-domain-out testing is good. Cheap-model-generated scenarios with deterministic ground truth are also good.

However, independent authorship does not guarantee independent information. Cheap models can reproduce the same patterns from common training data or inadvertently receive hints from the benchmark generator.

I recommend four protections:

1. Separate construction from evaluation. Freeze the intervention design and candidate selection before revealing held-out scenarios.
2. Hold out failure mechanisms as well as domains. A symlink escape inside a database deployment is still the same failure mechanism as a symlink escape in NetBSD.
3. Generate negative controls and distractors. Include legitimate subsystem replacement, harmless symlinks, intentionally changed baselines, and safe operations that look dangerous.
4. Use executable ground truth. Independently verify the injected defect and whether the proposed intervention detects or prevents it.

A fifth useful test is naturally occurring regressions from unfamiliar repositories, rather than exclusively synthetic faults.

The evaluation should answer whether Conflux improves clean completion, not merely whether it recognizes recognizable hazards.

## 3. Single senator versus panel

AGREE with the operator. My earlier preference for a cascade was premature.

The October result is a strong counterexample to trusting one cheap reviewer: only GLM identified PSCI displacement.

More importantly, escalation based on a single senator's reported uncertainty can fail precisely when that senator is confidently wrong.

A cascade needs an independent trigger, such as an unresolved obligation, meaningful change in an existing resource, missing provenance, or failed baseline comparison.

### Minimum experiment

Extend `step_lab` to run the same recorded action contexts through several configurations:

| Configuration                             | Purpose                          |
| ----------------------------------------- | -------------------------------- |
| Single senator, each candidate separately | Establish individual recall      |
| Two independent model families            | Measure marginal complementarity |
| Existing four-member panel                | Establish coverage baseline      |
| Single senator + deterministic escalation | Test adaptive savings            |
| Two senators + conditional expansion      | Test intermediate cost/coverage  |

Use structured, evidence-backed objections, not the existing A–T danger threshold, as the primary detection signal.

For an initial selection experiment, I would target approximately 100–200 independently labeled action cases, including at least 30–50 material hazards spanning several failure mechanisms. These are planning targets, not a statistical guarantee. With only 30 positive cases, even perfect recall leaves substantial uncertainty about the true miss rate.

Measure:

- Material-hazard recall and missed severity.
- Unique hazards caught by each additional senator.
- Unnecessary holds and probes.
- Cost, latency, provider failures, and parse failures.
- Final defect detection after obligations and postchecks.

Evaluate configurations on paired cases and report confidence intervals. Hold out complete tasks and repositories, not individual steps from the same run.

Decision rule: Choose the cheapest configuration that meets a prespecified reliability requirement on held-out cases. Keep the full panel as the default where the evidence is insufficient for a cheaper configuration.

The October observation alone cannot establish that four senators are necessary. Nor can it establish that one is sufficient.

## 4. Cheapest faithful October replay

Use offline deterministic replay first, then one live rerun if needed.

No mid-run snapshot exists. Reconstructing one from a transcript would require reproducing environment state, not merely replaying commands.

I recommend this sequence:

Phase 1 — Offline evidence replay

Feed the recorded senate responses, executor predictions, baseline observations, and final boot output through the new obligation engine.

Expected result: the PSCI objection survives, and disappearance of `psci0` fails a preservation obligation.

This tests whether the new plumbing correctly handles information already available.

Phase 2 — Live rerun from clean baseline

Run the actual updated Conflux against an isolated copy of the clean snapshot.

Verify that objections reach the executor, checks run at the correct time, and the system either corrects the displacement or refuses an unqualified completion.

Phase 3 — Reconstructed branch rollout (optional)

Only reconstruct the step-10 environment if the full rerun is prohibitively expensive or nondeterministic. Validate filesystem, source, build artifacts, VM state, and command context before calling the reconstruction faithful.

Important distinction: Offline replay must be causally ordered. The objection must appear at the point it was originally produced; future observations cannot retroactively influence action authorization.

A replay that detects missing `psci0` after the fact proves detection capability. It does not prove that the live system would have taken the necessary test or repaired the defect.

One correction: The clean disk snapshot alone may not capture the full initial environment. Preserve or reconstruct source trees, object directories, symlinks, build products, and execution configuration as separate state.

## 5. What remains wrong or misleading

Several issues in `docs/model-blind-spots.md` deserve correction.

A. Knowledge versus process gaps are not cleanly separable.

Failure to discover an available tool is simultaneously a retrieval failure, a planning failure, and potentially a missing-knowledge failure.

Use K/P as descriptive tags, not mutually exclusive causal diagnoses or model-training labels.

B. Baseline diffs are not automatically regressions.

The statement that lost lines surface without domain knowledge is correct for detection, but not for interpretation.

A missing component can be an intended replacement, a formatting change, or a genuine defect. The harness should establish a regression candidate and demand clarification rather than automatically classify damage.

C. Feeding every supervisor's `how` back to the executor is too indiscriminate.

Preserve every objection, but pass evidence-grounded, deduplicated, actionable obligations to the executor.

Retain the original text for audit. Do not automatically promote speculative supervisor prose into authoritative facts.

D. `realpath`, ownership, and creation time do not prove disposability.

Disposability requires authorized scope and a credible restoration or abandonment decision. Resource identity should be checked at execution time where possible; otherwise symlink races remain.

E. The proposed `step_lab` calibration is circular if based on model judgments.

The attached implementation's judge stage evaluates candidate actions with other models. These are not observed outcomes.

Use executable outcome labels for selecting thresholds and panel configurations. Cross-family model grades are auxiliary signals.

F. The document understates a separate security concern.

The README explicitly says the governor's heuristics are not a security boundary, and raw model routes bypass supervision.

For Milestone A, don't claim deterministic target checks make arbitrary tool execution secure. Enforcement must occur at the actual execution boundary, with restricted capabilities or isolation where necessary.

G. No objection does not imply no defect.

The PSCI case is convenient because GLM generated the right warning. The harder failure class is when nobody predicts the problem.

Baseline preservation checks must operate independently of whether a senator noticed a hazard. Otherwise the system simply becomes better at remembering errors it already recognizes.

## Final decision for the operator

Proceed with Milestone A exactly as proposed, with two requirements:

First, obligations must influence both action authorization and final verification, while generic baseline checks operate independently of model-generated objections.

Second, demonstrate two distinct outcomes: the historical PSCI defect is caught in causal offline replay, and the integrated system behaves correctly in an isolated live execution.

Keep the existing senate panel until `step_lab` establishes an outcome-grounded risk–cost comparison. Build the lesson ledger only after Milestone A demonstrates improved execution behavior.

The main engineering objective is now clear:

Conflux should stop losing useful intelligence it already generated before spending money generating more intelligence.
