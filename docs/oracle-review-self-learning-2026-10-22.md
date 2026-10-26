# Conflux: Self-Improving Supervision Architecture

> ChatGPT (GPT-6, via Oracle browser mode) answer to the prompt in this session, 2026-10-22. Inputs: docs/model-blind-spots.md, conflux/senate.py, agent_flows.yaml, scripts/step_lab.py, README.md. Advisory; code claims spot-checked by the operator.

## Executive verdict

Conflux should learn from discrepancies between predictions, actions, observations, and delayed outcomes—not primarily from model-generated explanations of what went wrong.

That is the central architectural decision I recommend.

The NetBSD/OP-TEE experiment demonstrates something more interesting than weak models lacking technical knowledge: the system sometimes possessed enough information to prevent a defect, but failed to turn that information into an enforceable obligation.

Three examples from the supplied evidence establish this:

- PSCI displacement: GLM-5.2 correctly identified that the new OP-TEE driver's compatibility matching could displace the existing PSCI driver. Its danger score was 0.47, so the action proceeded. Its explanation never reached the executor.
- Missing regression detection: The baseline boot showed `psci0`, while the final boot did not. The executor had even predicted this possibility. Nothing converted that prediction into a required comparison.
- False disposability: Senators repeatedly described paths as disposable although symlinks led into the user's actual source and object trees. They reasoned from an assumed environment rather than an observed one.

These failures suggest six priorities.

| Priority | Mechanism                                               | Why                                                                    |
| -------- | ------------------------------------------------------- | ---------------------------------------------------------------------- |
| P0       | Preserve and act on supervisor objections               | Recovers information the cheap models already produce                  |
| P0       | Evidence-backed environment facts and target provenance | Stops plausible but fabricated safety assumptions                      |
| P0       | Prediction-to-obligation conversion                     | Makes recognized risks trigger tests                                   |
| P1       | Reversibility discovery with verified rollback          | Reduces the consequences of mistakes without requiring superior models |
| P1       | Automatic discrepancy mining and lesson validation      | Gives Conflux durable, revisable experience                            |
| P1       | Outcome-calibrated senate decisions                     | Replaces arbitrary rating anchors with measured effectiveness          |

I would not begin by building a sophisticated memory system. First, fix the information-loss and execution-feedback paths. Otherwise the memory system will repeatedly rediscover lessons that the active pipeline remains structurally unable to use.

There are also two important corrections to the proposed framing.

First, a model-generated blind-spot ledger is not automatically evidence of learning. Conflux should demonstrate that its lessons change decisions and improve outcomes on subsequent runs.

Second, avoiding command dictionaries is sensible, but avoiding deterministic machinery is not. The models should discover risks, possible remedies, and environment-specific workflows. Deterministic code should validate identities, enforce capabilities, track obligations, and measure whether predictions came true.

The desirable division of labor is:

Cheap models generate hypotheses. Tools establish facts. The governor enforces constraints. Experiments determine what deserves to persist.

## 1. A self-generating, continuously revised lessons ledger

I would build this as a small evidence and hypothesis system, tentatively called Conflux Experience Ledger (CEL).

It should not be a Markdown file that an agent rewrites after each task. Markdown is a rendered view of the ledger. The underlying representation belongs in structured SQLite tables connected to trace events.

### 1.1 The fundamental unit is a falsifiable lesson

A lesson should not merely say:

> Always take QEMU snapshots before changing disk images.

That is both too specific and potentially wrong. A disposable scratch image may not need protection, while a cloud disk modified outside QEMU might need a completely different mechanism.

A better lesson is:

> Before modifying state whose loss would affect the task or existing work, establish whether the target can be restored to a verified earlier state. If reversibility is unknown, obtain evidence or choose an isolated execution target.

The abstraction is general, but its use still depends on observed facts.

Each lesson should have five essential elements:

1. Trigger: Under what circumstances might this matter?
2. Failure hypothesis: What could go wrong, and why?
3. Evidence: Which trace events support that hypothesis?
4. Discriminator: What observable result would confirm or refute it?
5. Intervention: What behavior should change?

I recommend a schema along these lines:

```

{
  "lesson_id": "L-000184",
  "revision": 3,
  "status": "validated",
  "scope": "general",
  "trigger": {
    "kind": "modifies_existing_state",
    "preconditions": [
      "target_is_not_proven_disposable",
      "restore_capability_is_unknown"
    ]
  },
  "hypothesis": "An action may destroy a usable state without a verified recovery path.",
  "intervention": {
    "kind": "require_evidence",
    "evidence_needed": "verified_rollback_capability",
    "fallback": "isolate_or_escalate"
  },
  "support": [
    {
      "run_id": "july-optee",
      "event_id": "step-176",
      "observation": "write occurred before usable backup"
    }
  ],
  "counterevidence": [],
  "validation": {
    "independent_runs": 2,
    "successful_counterfactuals": 0,
    "last_tested": null
  },
  "confidence": "supported_not_causally_proven"
}

```

This record is an example of the proposed format, not an existing Conflux record.

Notice the distinction between supported and causally proven. Observing two destructive incidents supports the risk hypothesis. It does not establish that a particular proposed guard would have prevented either one.

### 1.2 Mine five types of evidence

Suggested learning path. Live supervision consumes only validated or explicitly provisional interventions; trace mining does not itself grant execution authority.

The mining system should inspect five classes of anomaly:

| Source                     | Trigger                                              | Example                                          |
| -------------------------- | ---------------------------------------------------- | ------------------------------------------------ |
| Prediction discrepancy     | A stated expected result does not occur              | `dd` failure followed by a success claim         |
| State regression           | A relevant baseline observable disappears or changes | `psci0` present before, absent after             |
| Supervisor warning         | A reviewer identifies a concrete failure mode        | GLM's PSCI attachment warning                    |
| Verification contradiction | Proof fails to establish the claimed property        | Version fields decoded incorrectly               |
| Delayed outcome            | New evidence invalidates earlier completion          | A later boot reveals a corrupted root filesystem |

A sixth useful source is repeated ineffective behavior: rebuilding after the same failure, rediscovering dependencies, or applying unsuccessful patches without changing the hypothesis.

But these should initially produce candidate lessons, not automatic policy changes.

### 1.3 Mining triggers

I would implement three main triggers, plus one inexpensive online trigger.

At run completion: Launch an asynchronous, budgeted mining job over the completed trace. This is the main path for discovering cross-step failures, wasted effort, unsupported success claims, and missed opportunities to verify.

At verifier or soundness failure: Mine a focused window around the failed claim, including relevant earlier state-changing actions. This supports immediate recovery while the environment is still available.

When delayed outcomes arrive: Link the outcome to the original run and reopen lessons that depend on it. This must support outcomes such as later compilation failures, acceptance-test results, unexpected system damage, user corrections, or an artifact's subsequent failure.

During live execution: Detect deterministic contradictions without requiring full mining. If the executor predicted a device would remain present and the postcheck shows it disappeared, create an unresolved obligation immediately.

The online path should be narrow and inexpensive. Deep lesson synthesis belongs outside the critical action loop.

### 1.4 Extraction: require two-sided evidence

Every candidate should point to concrete trace evidence, not simply reference a run.

For example:

```

{
  "claim": "The new driver may displace an existing device driver.",
  "evidence": {
    "warning": "october:senate:step10:glm:how",
    "baseline": "october:transcript:m232",
    "prediction": "october:transcript:m306",
    "outcome": "october:transcript:m331"
  },
  "proposed_test": "Compare device attachment observations before and after the modification.",
  "unresolved": "Whether attachment displacement has been causally isolated"
}

```

The mining model should be required to supply both the evidence supporting its interpretation and any evidence that contradicts it.

A deterministic citation resolver then checks that:

- Each referenced event actually exists.
- Quoted text occurs in that event.
- Event ordering is consistent with the hypothesis.
- Relevant output was not truncated.
- The purported observation came from a real tool or external outcome, rather than a model's own claim.

This validation cannot prove the hypothesis semantically. It can eliminate fabricated citations and a large category of evidentiary errors.

I would use a cheap model to propose candidate interpretations and a different-family cheap model to challenge their causality. Neither should be permitted to promote a lesson by consensus alone.

### 1.5 Lifecycle: candidates must be able to lose

Use a versioned lifecycle:

Candidate

Supported

Validated

Retired / Scoped

Promotion requirements should increase with the consequence of the intervention.

A lesson that merely suggests a cheap read-only test could become active with one well-supported failure and a reproducible discriminator. A lesson that blocks execution, imposes substantial resource cost, or changes authorization boundaries should require stronger evidence, such as replay-tested benefit and independent validation.

Importantly, refutation is not necessarily deletion.

Suppose a lesson states that modifying a VM disk requires a snapshot, but new evidence shows that certain jobs already run against ephemeral overlays. The correct response is to narrow the lesson's applicability, not discard the underlying principle.

Preserve each revision and the evidence that caused it. Never silently overwrite historical explanations.

### 1.6 Prevent self-reinforcing false lessons

This is the most important part of the learning design.

Without controls, Conflux could invent a lesson, retrieve it into later prompts, produce outputs consistent with that lesson, and interpret those outputs as independent confirmation.

That is not learning. It is recursive confirmation bias.

I recommend four hard protections.

Evidence independence. A model statement that repeats a retrieved lesson is not new evidence. Only new external observations, tool results, independent artifacts, or separately measured outcomes can increase evidentiary confidence.

Retrieval lineage. Record exactly which lesson IDs each executor, senator, and verifier saw. If a lesson influenced a run, that run is marked as an exposed sample and cannot count as an independent discovery of the same hypothesis.

Counterfactual evaluation. Replay similar steps with and without the lesson. Compare proposed actions, test coverage, cost, and eventual outcomes. Distinguish a model agreeing with a lesson from the lesson actually changing behavior.

Contradiction search. On promotion and periodically thereafter, actively retrieve cases where the trigger occurred without the predicted failure or where the intervention caused harm or unnecessary blockage.

I would also reserve a small percentage of safe, reversible tasks for a lesson-off control. Never disable essential security or authorization controls in this experiment. The control should concern optional learned guidance, not foundational safety boundaries.

### 1.7 Retrieval without a dictionary explosion

Do not retrieve the entire ledger.

Use three tiers.

| Consumer        | What it receives                                                 | Maximum default |
| --------------- | ---------------------------------------------------------------- | --------------- |
| Executor        | Relevant failure hypothesis and required observation             | 3 lessons       |
| Senate / critic | Evidence-backed hazards, uncertainty, verified environment facts | 3 lessons       |
| Verifier        | Applicable obligations and known failure modes to falsify        | 5 lessons       |

Retrieval should combine structured action context with semantic similarity.

For example, the trigger `modifies_existing_state` might match a proposed filesystem write even if the specific command has never appeared in the ledger.

That is not a dictionary of dangerous commands. It is a reusable description of an action's effects.

The retrieval score should consider:

\\[ R = \text{relevance} \times \text{evidence strength} \times \text{expected utility} \\]

with penalties for redundancy, uncertainty, and repeated ineffective retrieval.

The executor should see instructions such as:

> Existing evidence suggests this action might modify a target with unverified rollback. Establish a restore method or use an isolated target before proceeding.

The senate should receive the factual basis and unresolved questions, not a prefabricated danger number.

The verifier should receive the testable obligation, not the historical diagnosis as an assumed truth.

This separation reduces anchoring across model roles.

Finally, keep the ledger distinct from Conflux's existing workspace store. The README describes a bounded `sqlite-vector` retrieval mechanism with hashed-token embeddings and a recent-record scan. That is a reasonable first-stage candidate retriever, but lesson status, trace citations, contradiction evidence, and causal outcomes need relational storage.

Use retrieval to find candidates; use SQLite evidence and lifecycle rules to decide whether they are trustworthy.

## 2. Evaluation: measure the learning system, not just its ability to write a report

The proposed evaluation—compare Conflux's self-generated ledger against the operator's `model-blind-spots.md`—is useful but insufficient.

It tests whether cheap models can reconstruct an explanation that a stronger model already discovered. It does not test whether those explanations prevent failures.

I would use the operator's list as a diagnostic benchmark, not the principal optimization target.

### 2.1 Four levels of evaluation

## 1

Discovery quality

Can Conflux independently recover real failure mechanisms from raw traces, with valid citations and correct temporal and causal interpretation?

## 2

Intervention quality

Does the resulting lesson cause an executor or supervisor to propose a materially better check or recovery step?

## 3

Observed outcome improvement

Does enabling the learned intervention reduce defects, lost state, unsupported claims, or wasted work in a real continuation?

## 4

Transfer and generalization

Does the intervention still help on different repositories, operating systems, tools, and tasks without relying on OP-TEE-specific knowledge?

Level 4 is the strongest evidence for the owner's thesis.

A system that learns to warn about `arm,psci-*` but cannot recognize analogous resource displacement in another driver subsystem has memorized an incident, not generalized from it.

### 2.2 Scoring against the reference ledger

I would decompose the operator's findings into distinct atomic failures. For each failure, assess:

| Measure                 | Requirement                                                     |
| ----------------------- | --------------------------------------------------------------- |
| Discovery recall        | Identifies the underlying failure, not merely its symptoms      |
| Evidence precision      | Points to the correct trace observations                        |
| Causal accuracy         | Distinguishes cause from correlation or speculation             |
| Intervention validity   | Proposes a relevant, testable prevention or detection mechanism |
| Abstraction quality     | Applies beyond the original named tool or platform              |
| Novel finding precision | Discovers a real failure omitted from the operator's list       |

For example, spotting that `psci0` disappeared is a valid observation. Explaining that an FDT compatibility collision caused it is a causal hypothesis that requires more evidence. Proposing baseline-and-diff is a general intervention.

These should not all receive the same score.

The reference list itself should not be treated as infallible. It includes operator interpretations, inferred causes, and findings of different evidentiary strength. The uploaded document explicitly acknowledges operator errors and environmental contamination.&#x20;

attachments-bundle.txt



### 2.3 The main benchmark: reversible fault-injection tasks

Create a benchmark suite containing small, realistic development environments with seeded but undisclosed failure opportunities.

Examples:

| Scenario                                                                      | Ground-truth oracle                               |
| ----------------------------------------------------------------------------- | ------------------------------------------------- |
| A working driver stops attaching after a new one is added                     | Compare enumerated devices before and after       |
| A script changes an unexpected filesystem target through a symlink            | Compare canonical paths and file hashes           |
| A backup preserves bytes but fails to restore a bootable system               | Actually boot the restored image                  |
| A command reports success after one component fails                           | Capture subprocess exit statuses                  |
| A generated program reports the wrong interpretation of a specification field | Run fixture assertions against known values       |
| A long-running process finishes after the agent declares success              | Compare finalization time with terminal job state |
| A build appears to succeed while executing an older artifact                  | Verify artifact identities at execution time      |

These tests can be generated by conventional programs or cheap models, but the expected outcome must be independently executable.

For a seeded bug, deterministic fixtures can establish both the intended behavior and the actual defect. Cheap models can generate candidate scenarios, while the test harness independently verifies that the failure is real before admitting the case into the benchmark.

This avoids making frontier-model review a mandatory part of each test.

### 2.4 Three experimental arms

Run matched tasks with:

- A: Unsupervised cheap executor.
- B: Current Conflux supervision, without learned lessons.
- C: Current Conflux supervision, with the experience ledger and new evidence obligations.

Ideally add a fourth arm, D, that receives the same extra compute as C but uses generic verification rather than retrieved lessons. This separates the value of memory from the value of spending more tokens and running more tests.

Use identical initial state, comparable provider availability, pinned model versions where possible, and randomized assignment. Measure both strict task success and regressions.

I would use this as the headline metric:

\\[ \text{Verified clean completion rate} = \frac{\text{tasks passing goal and regression checks}} {\text{all attempted tasks}} \\]

Report alongside it the total dollars, tokens, wall-clock time, human interventions, and irreversible failures.

For the stated business objective, also measure verified clean completions per dollar, but never optimize that ratio alone: a model that quits immediately can reduce cost while delivering nothing.

### 2.5 Why offline replay is insufficient

The attached `step_lab.py` can sample alternative next actions and obtain cross-family model judgments without executing the workload. This is valuable for screening candidate models and prompts.

But it cannot establish that an alternative action would have succeeded. Its own documentation says it replays requests without rerunning the workload. The current `judge` stage produces model judgments for progress, correctness, and safety rather than empirical outcomes.&#x20;

attachments-bundle.txt

attachments-bundle.txt



I would extend it to support three evaluation modes:

`offline_score`: fast, cheap-model judgment, used for initial filtering.

`fixture_test`: execute a candidate action against an isolated deterministic fixture.

`branch_rollout`: restore a checkpoint and run the alternative sequence forward to a meaningful outcome.

Only the latter two can provide direct evidence of changed execution outcomes, and even fixture success should not be mistaken for generalization.

### 2.6 Prevent benchmark contamination

The operator's reference document should never appear in the mining agent's inputs or runtime filesystem. The attached evidence reports that the October agent could inspect evaluator-owned files left on the VM.

Use a separate evaluator process and storage boundary, rather than relying on the executor to ignore those files.

For each test, save an immutable manifest of task inputs, fixture identity, source commit, available tools, scorer version, and outcome hashes. This makes future scoring changes auditable.

The most revealing evaluation is leave-one-domain-out transfer: derive lessons from the NetBSD experiment, then test them on unrelated domains such as database migrations, web deployments, package builds, and infrastructure operations. Rotate the held-out domain.

The success condition is not recalling the word PSCI. It is detecting that a change displaced a previously functioning subsystem.

## 3. Critique of the ten general mechanisms

My classification is below.

| #  | Mechanism                       | Assessment                         | Main correction                                                 |
| -- | ------------------------------- | ---------------------------------- | --------------------------------------------------------------- |
| 1  | Reversibility survey            | Strong, partly knowledge-dependent | Discover and verify usable rollback, not just list tools        |
| 2  | Work on copies; promote         | Strong                             | Isolation and promotion must cover non-file state               |
| 3  | Baseline and diff               | Strong                             | Require relevance and interpret semantic changes                |
| 4  | Predict, then compare           | Highest value                      | Convert predictions into durable test obligations               |
| 5  | Feed supervisor reasoning back  | Highest immediate value            | Propagate structured objections, not unfiltered prose           |
| 6  | Provenance before disposability | Essential                          | Determine identity, ownership, effects and restoration evidence |
| 7  | Proof that reproduces           | Essential, partly domain-dependent | Distinguish reproduced output from validated interpretation     |
| 8  | Outcome calibration             | Essential                          | Requires actual outcomes, not just model grades                 |
| 9  | Process and budget hygiene      | Strong                             | Build into execution infrastructure, not model prompts          |
| 10 | Outage classification           | Necessary infrastructure           | Separate model unavailability from action risk                  |

The document's mechanisms are directionally good. The main weakness is that several descriptions assume the existence of trustworthy observations and executable tests without explaining who produces them or how their validity is established.

### Mechanism 1: Reversibility survey

I agree with the owner that Conflux should attempt to make the environment reversible before important modifications.

But I would not have the system simply ask a model to list possible snapshot commands.

A cheap model can plausibly identify `qcow2`, `savevm`, cloud snapshots, reflinks, or Git worktrees without understanding whether they cover the actual state being modified.

The correct abstraction is restore coverage, not snapshot availability.

For every proposed protection, establish:

- Which resources does it cover?
- At what point in time is the recoverable state captured?
- What changes are excluded?
- Has restoration actually been tested?
- What does restoration cost?
- Can the protection itself cause damage?

For example, QEMU `-snapshot` can provide disposable disk writes for a suitable VM execution, but it does not preserve arbitrary host-side source changes. A Git worktree isolates tracked source files, not necessarily build outputs elsewhere or a database server. A cloud disk snapshot does not automatically establish consistency for actively written application state.

Similarly, `savevm` is not a universal rollback primitive; its availability and behavior depend on the VM and storage configuration.

I would implement a reversibility capability registry created by runtime discovery.

```

{
  "resource": "vm-root-disk",
  "identity": "verified-resource-fingerprint",
  "method": "qcow2-overlay",
  "covers": ["guest-block-writes"],
  "excludes": ["host-source", "external-services"],
  "restore_test": "passed",
  "captured_at": "checkpoint-12",
  "estimated_cost": "low",
  "confidence": "verified"
}

```

A cheap-model discovery agent can propose how to establish these records by inspecting available tooling, help output, system metadata, and existing artifacts.

A deterministic controller must check the resulting evidence before accepting the capability.

The system should not claim a rollback capability merely because a plausible command exists.

An important economic optimization: discover reversibility early, but create expensive snapshots only when their expected protective value justifies them. Cheap isolated working copies can often be established at session start.

### Mechanism 2: Work on copies; promote at the end

Strongly recommended, with one reservation: a Git worktree or disk overlay is not enough for tasks that modify external state.

The mechanism should apply to resources rather than filesystem paths alone. Database migrations, cloud infrastructure, API calls, and process controls may have side effects that cannot simply be discarded with a copy.

Model the execution environment as a set of resource identities with separate scopes and permitted effects.

Also distinguish proposed changes from authorized promotion. An agent successfully building a changed kernel in isolation should not automatically gain permission to overwrite the original artifact.

Promotion is a separate governed action, with its own diff, reversibility record, and authorization.

### Mechanism 3: Baseline and diff

This is one of the best general-purpose mechanisms in the document.

A baseline can reveal something that neither a weak executor nor a weak verifier knows how to anticipate.

However, recording every observable in a large system is costly, and raw diffs are noisy.

Use three layers:

Generic baseline: resource identities, running jobs, principal file targets, test outcomes, and artifact fingerprints.

Goal-derived baseline: observable properties that the task intends to preserve or modify.

On-demand baseline: additional observables requested by the critic, senate, or executor when a risk is identified.

The key distinction is between expected changes and unexplained changes.

A new driver attaching is expected. An unrelated, previously working driver disappearing is a regression candidate.

Conflux should not automatically reject every difference. It should require an explanation or an independent test for material unexpected differences.

For the OP-TEE case, a comparison of device attachment lines would have found the missing `psci0` without needing the system to understand the entire NetBSD autoconfiguration subsystem.

### Mechanism 4: Predict, then compare

This is my highest-priority general mechanism.

The attached evidence demonstrates that the executor already recognized the possibility of a conflicting attachment but did not follow through.

Instead of treating an agent's prediction as disposable prose, make it a structured obligation.

```

{
  "action_id": "write-driver-10",
  "expected_effects": [
    "new_driver_attaches",
    "smc_call_succeeds"
  ],
  "preservation_claims": [
    "existing_power_management_driver_remains"
  ],
  "uncertainties": [
    {
      "claim": "device_binding_may_overlap",
      "testable": true,
      "required_probe": "compare_attachment_observations"
    }
  ]
}

```

After execution, Conflux must mark each obligation as `passed`, `failed`, or `unresolved`, and record the evidence.

A technically important point: absence of a failure observation is not proof of preservation. If the system never checks the existing power-management driver, the preservation claim remains unresolved.

Not every prediction should require a test. Restrict mandatory obligations to material outcomes and hazards, using a cost-aware selection policy.

This mechanism complements the lesson ledger: past lessons can suggest predictions, but fresh observations decide whether the obligations passed.

### Mechanism 5: Feed supervisor reasoning back

I agree with the intent, but not with feeding every entire `how` explanation indiscriminately.

That would create prompt bloat, duplicate warnings, and opportunities for inaccurate supervisor speculation to become assumed truth.

Instead, each senator should return structured objections with:

- affected resource or claimed property;
- predicted failure;
- cited evidence;
- uncertainty;
- suggested discriminator;
- whether the issue concerns harm, correctness, or task completion.

The governor should deduplicate objections, retain their source-model identities, and select which require checking.

Even approved actions should deliver unresolved objections to the executor.

For the PSCI warning, I would go further: a concrete, testable correctness objection should create a mandatory postcheck obligation. A benign danger rating should not erase it.

### Mechanism 6: Provenance facts instead of disposability assumptions

This is essential but underspecified.

`realpath`, owner, and creation time are useful, but they do not prove that a resource is disposable.

A resource created during the run may now contain hours of valuable work. A temporary-looking path may point to an existing production resource. A hash-verified backup may still be unusable.

I recommend a resource fact store containing:

| Fact                            | Provenance                                |
| ------------------------------- | ----------------------------------------- |
| Canonical target identity       | Filesystem or backend observation         |
| Relationship to authorized root | Resolved path and capability boundary     |
| Created during run              | Recorded creation event                   |
| Pre-existing user data          | Initial inventory or explicit declaration |
| Known-good restoration point    | Successfully tested restore               |
| Last verified state             | Tool observation and timestamp            |
| Disposal authorization          | Policy or explicit user/operator decision |

These facts should have expiration and invalidation rules.

A path checked at proposal time might be replaced before execution. For important writes, the controller should revalidate the target at the actual execution boundary, preferably using stable resource handles or backend-enforced isolation where available.

`realpath` alone does not eliminate time-of-check/time-of-use races.

### Mechanism 7: Proof that reproduces

Necessary, but two different tasks are being conflated.

Reproducing a command establishes that it produces the same observed result.

Validating the interpretation establishes that the result means what the agent claims.

A repeated SMC call can return the same register values while the agent continues to decode them incorrectly.

So the verifier needs a claim-to-evidence mapping:

```

Claim
  → supporting observed output
  → interpretation rule or specification
  → executable assertion, when possible
  → independent result

```

The difficult part is deriving the right specification and assertion without operator knowledge.

Cheap-model-compatible techniques include reading available headers, tests, upstream examples, protocol definitions, and build recipes, then generating assertions that can be mechanically checked.

But when the specification is unavailable or ambiguous, the correct result is `unverified`, not an invented assertion.

A regex checking UUID length can identify a malformed string. It cannot establish that a well-formed UUID is the correct one.

Likewise, proof of a successful SMC call is narrower than proof of a complete OP-TEE communication driver. The supplied report says the October driver did not implement `EXCHANGE_CAPABILITIES`, `CALL_WITH_ARG`, or sessions. Those gaps should be reflected in the completion contract rather than obscured by a successful lower-level demonstration.&#x20;

attachments-bundle.txt



### Mechanism 8: Outcomes set calibration

Agree, but distinguish observed risk from preventable risk.

A dangerous action may succeed because its operator was lucky. A harmless action may coincide with an unrelated later failure.

Calibration needs outcome attribution, not merely a binary run-success label.

I address the redesign in Section 4.

### Mechanisms 9 and 10: Hygiene and outages

Both should be built into infrastructure.

Models should not need to remember to collect exit codes, distinguish cancellation from transport failures, preserve work across restarts, or wait for owned jobs to reach a terminal state.

The report says some outage-related fixes were implemented on October 22. Treat those as existing work to regression-test, rather than redesign from scratch.

One specific remaining concern is reporting infrastructure unavailability as a safety objection. An absent senate response means unknown risk, not maximum danger. That distinction should be preserved even when the execution policy elects to hold the action.

### What the ten mechanisms are missing

Three general mechanisms deserve explicit addition.

A. Evidence obligation accounting. Every important promise, prediction, and objection should have a durable status. An obligation must not disappear when context is truncated, a model changes, or a run resumes.

B. Artifact identity and dependency provenance. Conflux should establish which executable, kernel, image, configuration, and source revision actually produced a result. This would address stale-kernel execution, ambiguous boot paths, and rebuilds that did not produce a changed artifact. It is more general than simply hashing files.

C. Causal experiment selection. When several explanations fit a failure, Conflux should select an inexpensive discriminator before undertaking expensive repairs. The document contains examples of spending many steps guessing firmware load addresses while relevant build recipes were available. A structured hypothesis-and-test loop would reduce this waste.

These additions are especially suitable for weaker models because they reduce the amount of state and uncertainty that a single model invocation must manage.

## 4. Senate redesign: replace danger letters with outcome-oriented decisions

The existing senate has two separable defects:

1. Its numerical scale is not empirically calibrated.
2. Its decision interface discards information that would have helped even without accurate numerical calibration.

The second defect is more immediately damaging.

### 4.1 What the current implementation actually does

The supplied `conflux/senate.py` defines 20 letter categories, with A representing harmless reading, J meaningful but recoverable risk, and T likely irreversible loss.

It normalizes the numerical letter score as:

\\[ d=\frac{\text{letter score}-1}{19} \\]

A J therefore corresponds to \\(9/19\approx0.474\\), which is below the configured threshold of 0.5.

The `SenateVerdict.danger` property uses the maximum valid member score. `SenateVerdict.how` returns only the explanation from the highest-scoring member.

That creates two important effects.

First, the scale's semantics invite the model to classify a broad variety of nontrivial but supposedly recoverable actions as J.

Second, an explanation from a lower-scoring senator can disappear from the aggregate decision even if that senator identified the most important failure.

The logger does preserve individual `how` fields, but the aggregate interface and action pipeline do not guarantee that these objections become executable checks.&#x20;

attachments-bundle.txt



I would remove J as an operational decision category and stop treating the A–T scale as a probability of damage.

A normalized letter score is not automatically a calibrated probability, and averaging token probabilities across letter choices does not change that.

### 4.2 Separate three things the present design merges

Harm risk

Could the action lose, corrupt, or expose important state?

Correctness risk

Could it break the intended behavior or another component?

Evidence gap

What is unknown, and what observation would resolve it?

The three dimensions should affect different decisions.

High harm risk may warrant isolation, a verified rollback point, or human approval.

High correctness risk may warrant a targeted test before or after execution.

An evidence gap should prompt an inexpensive information-gathering step when one exists.

A low-harm but technically incorrect action should not pass silently. That was precisely the PSCI case.

### 4.3 Proposed senator output

Use structured JSON with schema validation. Each senator evaluates independently and must supply its own objections.

```

{
  "action_id": "write-driver-10",
  "assessment": {
    "harm_likelihood": "low",
    "harm_impact": "moderate",
    "correctness_concern": "high",
    "reversibility": "unverified"
  },
  "objections": [
    {
      "id": "driver-attachment-overlap",
      "type": "correctness",
      "failure_mode": "New driver may displace an existing driver.",
      "evidence": [
        "observed existing attachment",
        "proposed matching behavior"
      ],
      "discriminator": "Compare device attachments before and after",
      "test_cost": "low"
    }
  ],
  "recommended_next_step": "probe",
  "unknowns": [
    "Whether the two drivers match the same device-tree node"
  ]
}

```

The values shown are illustrative.

I would begin with ordinal likelihood and impact descriptors, not force the models to invent percentages.

The harness can later estimate empirical probabilities from features of the responses and outcomes.

### 4.4 Aggregate objections, not just scalar scores

Retain all objections with their originating model and evidence.

Group semantically similar objections, but do not assume that a consensus of models is a consensus of independently grounded evidence.

Two models sharing a mistaken premise can agree confidently and still be wrong.

A useful aggregate might look like:

```

Action: write driver
Harm: no verified severe-loss scenario
Correctness objections:
  - Possible existing-driver displacement [GLM]
  - FDT match target not confirmed [Qwen]
Environment facts:
  - Existing PSCI attachment observed
  - Device-tree target not inspected
Decision: require a bounded attachment probe

```

The key is the decision's provenance.

It should be possible to answer: Why did Conflux require this check? Which model raised it? Which evidence supported it? What result cleared it?

### 4.5 Calibration from outcomes

Do not choose the threshold by eyeballing a collection of model grades.

Instead, treat the senate as a candidate feature generator and the action controller as a decision policy.

For an action \\(a\\), let:

- \\(p_a\\) be the estimated probability of an avoidable adverse outcome;
- \\(L_a\\) be the estimated consequence;
- \\(C_a\\) be the cost of the proposed protective intervention;
- \\(q_a\\) be the estimated fraction of adverse outcomes the intervention prevents.

Then a simplified protection rule is:

\\[ \text{Protect if } p_aL_aq_a>C_a \\]

This is a decision-theoretic target, not a requirement for the LLM to invent precise numerical estimates. Initially, the system can use measured outcome frequencies, ordinal severity, and broad uncertainty intervals.

For high-consequence failures, use conservative bounds and retain hard authorization requirements regardless of the learned prediction.

The training target should be closer to:

> Would this proposed intervention have prevented or detected a material adverse outcome at an acceptable cost?

That is considerably more useful than:

> How dangerous does this command sound?

### 4.6 How to obtain training labels

I would build an outcome dataset with separate fields for:

```

{
  "action_id": "...",
  "executed": true,
  "observed_regression": true,
  "regression_type": "lost_existing_functionality",
  "causally_attributed": "supported",
  "rollback_was_available": false,
  "suggested_probe": "compare_before_after",
  "probe_would_detect": true,
  "probe_cost": 0.002,
  "outcome_source": "deterministic_fixture"
}

```

Some labels can be established directly by deterministic tests. Others will remain uncertain.

Do not label every action in a successful run safe. Do not label every action preceding a failed run dangerous.

For actions that were blocked, the actual outcome is unobserved. This creates selection bias: once the senate starts preventing risky actions, the system cannot learn their failure frequencies from routine execution alone.

Address that with isolated replay experiments and explicit logging of the policy's decision probability. Do not deliberately execute potentially destructive actions on valuable systems merely to obtain calibration data.

Also separate adverse outcomes from action effectiveness. A snapshot can prevent permanent loss without preventing the underlying defect. A preflight probe may detect a defect but have no effect unless the executor responds appropriately.

### 4.7 Model selection and thresholds

Extend `step_lab.py` to evaluate alternative senator configurations on a fixed set of outcome-labeled cases.

For each configuration, measure:

- recall of preventable adverse events;
- false protective-action rate;
- severity-weighted loss;
- additional token and tool cost;
- rate of useful, evidence-backed objections;
- failure rate of parsing and provider responses;
- calibration on held-out tasks.

I would report the risk-versus-cost frontier, not a single winner.

Illustrative protection-policy tradeoff

Hypothetical evaluation values; not measured Conflux results.

Missed adverse outcomes (%)Unnecessary holds (%)

030609012001248

The chart illustrates why an unqualified maximization of recall would be a poor policy. Protecting every action could prevent many failures while making the system economically useless.

Choose a point on the measured frontier subject to constraints on severe failures, completion rate, and cost.

For prompt selection, compare a small number of candidates using run-level holdouts, with nested validation when tuning thresholds or membership. Freeze the chosen configuration before evaluating it on the held-out set. Otherwise the prompt search will overfit the same handful of OP-TEE incidents.

### 4.8 A cheaper senate is probably better

Four reasoning-heavy models on every action may be excessive.

My preferred design is a cascade:

Stage 1 — Deterministic context collector

Resource targets, canonical identities, action dependencies, known rollback, existing obligations

Stage 2 — One inexpensive senator

Structured risks, objections, and suggested discriminators

Stage 3 — Conditional independent review

Additional model families only for material uncertainty, conflicts, or consequence

Stage 4 — Evidence-based governor decision

Release, probe, protect, escalate, or deny

The optimization target should be verified correctness gained per additional dollar.

The four-member senate may still prove worthwhile in some circumstances. But the current evidence does not justify running it indiscriminately.

Logprobs can remain an experimental signal for providers that support them reliably. They should not be required for safety semantics or normal operation.

I would also fix the current `referenced_files()` implementation. Its matching depends on syntactically extracted path names and transcript-written content; basename matching can select the wrong file, and it does not establish the current contents of a remote script. The critic needs a trusted execution-target manifest containing actual file identity and content hash, not just historical transcript text.&#x20;

attachments-bundle.txt



## 5. Integration into `supervised_tool_turn`

There is an important architectural constraint in the supplied README.

`agent_flows.yaml` is not an executable graph interpreter.

The graph is a declarative control surface and a runtime-status projection. The fixed Python `Orchestrator` determines actual execution. Adding YAML edges alone will not introduce new behavior.&#x20;

attachments-bundle.txt



Accordingly, I recommend retaining `supervised_tool_turn` and extending both its declared graph and the corresponding Python execution hooks. Do not introduce a separate top-level learning graph yet.

### 5.1 Proposed graph

Proposed extension of the existing supervision pipeline. Lesson mining runs after or outside the active turn; its output informs subsequent runs through retrieval.

### 5.2 Node-by-node changes

| Existing point           | Change                                                          | Responsibility                                |
| ------------------------ | --------------------------------------------------------------- | --------------------------------------------- |
| `ingress`                | Add environment discovery and resource-fact initialization      | Deterministic adapter + cheap discovery model |
| Before `executor`        | Retrieve relevant validated lessons                             | SQLite retrieval                              |
| `executor`               | Emit predicted effects, preserved invariants, and uncertainties | Executor model                                |
| `policy_gate`            | Bind action to verified resource identities                     | Governor                                      |
| `action_critic`          | Incorporate structured senate objections                        | Cross-family models                           |
| `preflight`              | Check missing evidence and available rollback                   | Governor + bounded probe                      |
| Before `action_released` | Add obligation/protection gate                                  | Deterministic controller                      |
| `postcheck`              | Reconcile exit status, predictions and baseline differences     | Deterministic checks                          |
| `soundness_checker`      | Select targeted falsification experiments                       | Cheap independent model                       |
| `final_verifier`         | Reconcile all material obligations and final claims             | Evidence-first verifier                       |
| After terminal outcome   | Extract and adjudicate candidate lessons                        | Asynchronous mining worker                    |

Three implementation details are particularly important.

First, protection happens before action release. A snapshot captured after the action cannot undo its damage.

Second, postcheck obligations should survive model restarts. They need durable IDs and statuses in SQLite, not just conversational context.

Third, terminal completion must be distinguished from an independently confirmed successful outcome. A failed, blocked, or interrupted run can still contain valuable learning evidence.

### 5.3 Concrete edge changes

Retain the existing nodes and edges unless the following additions or redirects require modification:

```

# Conceptual patch; corresponding node types and capabilities
# must be supported by the Python orchestrator/compiler.

# NEW nodes
- id: experience_retrieval
  type: store_read
- id: environment_survey
  type: probe
- id: obligation_gate
  type: policy
- id: outcome_miner
  type: store_write

# NEW or redirected edges
- {source: ingress, target: environment_survey}
- {source: environment_survey, target: experience_retrieval}
- {source: experience_retrieval, target: executor}

- {source: action_critic, target: obligation_gate,
   label: approved with recorded objections}
- {source: preflight, target: obligation_gate,
   label: evidence established}
- {source: obligation_gate, target: action_released,
   label: obligations satisfied}
- {source: obligation_gate, target: human_approval,
   label: unresolved material risk}

- {source: final_verifier, target: outcome_miner,
   label: verified completion}
- {source: outcome_miner, target: completed,
   label: evidence recorded}

```

This is a logical integration sketch, not a drop-in validated `agent_flows.yaml` patch.

The existing `store_write` semantics described in the README are not sufficient for this learning system because they copy completed report text into a knowledge store. The experience miner needs failure outcomes, individual action evidence, and structured versioned records. I would implement its storage through a dedicated service while reusing the existing node vocabulary where practical.

Likewise, the experience miner must run on failures and interruption, not exclusively through the successful `final_verifier → completed` route.

A practical implementation would have the Python controller emit `run_terminal` and `outcome_received` events to a durable mining queue. The YAML graph would display or configure that operation, without pretending that its edges independently schedule the work.

### 5.4 Minimal persistence schema

Do not build a separate graph database.

The existing SQLite infrastructure is sufficient.

```

CREATE TABLE experience_lessons (
    lesson_id TEXT PRIMARY KEY,
    current_revision INTEGER NOT NULL,
    status TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    trigger_json TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    intervention_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE lesson_evidence (
    evidence_id TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    run_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    evidence_hash TEXT NOT NULL,
    FOREIGN KEY (lesson_id)
        REFERENCES experience_lessons(lesson_id)
);

CREATE TABLE action_obligations (
    obligation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    assertion_json TEXT NOT NULL,
    status TEXT NOT NULL,
    result_evidence_id TEXT
);

CREATE TABLE lesson_exposures (
    run_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    lesson_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    consumer TEXT NOT NULL,
    PRIMARY KEY (
        run_id, action_id, lesson_id, consumer
    )
);

CREATE TABLE lesson_trials (
    trial_id TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL,
    fixture_id TEXT NOT NULL,
    intervention_enabled INTEGER NOT NULL,
    measured_outcome_json TEXT NOT NULL,
    cost_usd REAL
);

```

I would additionally use append-only revision and adjudication tables in production. The schema above shows the core separation: lessons, evidence, live obligations, retrieval exposure, and measured interventions are different objects.

Where trace databases are pruned, evidence references need durable content hashes and preservation of the relevant payloads. Otherwise the ledger will gradually accumulate citations that can no longer be independently checked.

## 6. Execution order by expected value per engineering effort

This is the order I would give the autonomous development agent.

The effort and value ratings are judgments based on the supplied code and experiment, not measured project estimates.

| Order | Deliverable                                  | Effort      | Expected value | Acceptance test                                                        |
| ----- | -------------------------------------------- | ----------- | -------------- | ---------------------------------------------------------------------- |
| 1     | Preserve every senator's objection           | Low         | Very high      | PSCI warning reaches executor and verifier regardless of danger letter |
| 2     | Durable prediction and objection obligations | Medium      | Very high      | Predicted displacement cannot silently disappear                       |
| 3     | Outcome reconciliation and baseline diffs    | Medium      | Very high      | Missing `psci0` creates unresolved regression                          |
| 4     | Trusted resource provenance                  | Medium      | Very high      | Symlink target cannot be classified disposable from its name           |
| 5     | Reversibility discovery and verified restore | Medium–high | Very high      | Recovery point demonstrably restores initial state                     |
| 6     | Claim-to-proof reconciliation                | Medium      | High           | Incorrect revision interpretation and incomplete proof are rejected    |
| 7     | Trace discrepancy miner                      | Medium      | High           | Cheap models generate cited candidate lessons from raw traces          |
| 8     | Versioned lesson store and retrieval         | Medium      | High           | Relevant validated lesson is retrieved with full provenance            |
| 9     | Fault-injection and branch replay            | High        | Very high      | Intervention benefit measured by executed outcomes                     |
| 10    | Outcome-calibrated adaptive senate           | High        | High           | Threshold and membership chosen on held-out fixtures                   |
| 11    | Automatic lesson promotion and retirement    | Medium–high | High, later    | Refuted lessons lose authority without manual edits                    |

I would group these into three implementation milestones.

### Milestone A: Make existing intelligence actionable

Implement items 1–4, then replay the October OP-TEE sequence.

This should establish whether the failure was primarily preventable through better information flow and local tests, without yet requiring a self-improving memory architecture.

Specific regression tests:

- The GLM warning about PSCI attachment remains available even when another senator produces a higher scalar danger rating.
- An objection creates a required verification check rather than merely an advisory paragraph.
- The initial presence and later absence of `psci0` creates a regression candidate.
- A symlink whose canonical target is outside the authorized root cannot be treated as disposable based on its lexical name or directory.
- No success claim can silently clear a failed or unresolved obligation.

This is the fastest route to proving the value of the architecture.

### Milestone B: Make actions reversible and claims falsifiable

Implement items 5–6.

Test restoration independently from the same source state, including bootability where relevant.

Do not accept the presence of a snapshot or a matching backup checksum as sufficient proof of recovery.

For the final proof, check the intended claims separately: SMC communication, expected driver attachment, preservation of existing functionality, artifact provenance, and any additional functionality required by the task contract.

### Milestone C: Learn and improve from repeated experiments

Implement items 7–11, initially with human-controlled promotion for expensive or blocking interventions.

Generate candidate lessons from both historical runs without providing the operator-authored report to the models.

Then run two evaluations:

1. Compare the generated lessons to the operator reference.
2. More importantly, evaluate whether enabling the lessons improves clean completion on fresh, isolated scenarios.

Only after this works should lesson promotion become largely automatic.

## 7. Where I disagree with the owner and operator

The owner's underlying objective is sound: use structure, repeated reasoning, and verification to raise the effectiveness of inexpensive models.

But there are four assumptions I would challenge.

### A. Self-improvement is not synonymous with self-explanation

A weak model may be excellent at generating plausible retrospective explanations and poor at identifying the true cause.

The system must measure whether an explanation predicts observations and whether an intervention helps.

A ledger with 200 impressive lessons that never changes execution is less useful than five tested interventions that consistently prevent defects.

### B. Generalization has a cost

The instruction to use the most general technique possible is directionally right, but should not mean maximizing abstraction without limit.

For example, a general rule like verify all important assumptions provides little operational guidance.

A more useful general mechanism is:

> If a supervisor predicts a material, observable side effect, persist that prediction and require an appropriate observation before claiming the action succeeded.

That is general enough to transfer across domains and specific enough to implement.

Choose the narrowest mechanism that covers the demonstrated causal failure across materially different tasks. Widen it when new evidence justifies widening.

### C. Cheap-model supervision cannot eliminate the need for ground truth

Cross-family agreement is helpful for generating alternative hypotheses. It is not an independent substitute for measurement.

In the OP-TEE experiment, multiple layers of model supervision failed to notice defects that were exposed by ordinary state comparison and direct specification checks.

Adding more senators without improving observability risks multiplying cost without materially improving reliability.

The strongest architecture uses cheap models to decide what to test, and tools to decide what happened.

### D. Do not let models redefine the safety boundary

The owner wants models to rate danger rather than rely on large command dictionaries. I agree.

But a model rating should determine which extra precautions may be useful, not whether the underlying authorization boundary exists.

Canonical target resolution, allowed execution roots, human approval of unresolved irreversible actions, tool capabilities, and exact released-action identity should remain deterministic.

A learned lesson may request a stricter check. It should not grant a capability that the governor otherwise prohibits.

## 8. What I would actually build first

If I were directing the next Conflux implementation cycle, I would give the agent one concentrated assignment:

Implement an Evidence Obligation Engine inside `supervised_tool_turn`.

Its job would be to capture, persist, and reconcile material predictions and objections.

The interface is small:

```
class EvidenceObligations:    def register_prediction(self, action_id, claim, evidence):        ...    def register_objection(self, action_id, model, objection):        ...    def bind_test(self, obligation_id, test_spec):        ...    def record_observation(self, obligation_id, result):        ...    def unresolved_for_action(self, action_id):        ...    def unresolved_for_run(self, run_id):        ...
```

Every senate response, critic finding, executor uncertainty, soundness test, and final verifier finding should be able to create or update an obligation.

The engine should reject fabricated evidence references, track unresolved tests, and prevent the final verifier from treating untested material claims as proven.

The governor remains responsible for deciding whether an unresolved obligation is blocking, permits conditional continuation, or merely limits what can be claimed in the final answer.

This module becomes the bridge between the existing supervisors and the subsequent self-improvement ledger.

Once the obligation engine works, the self-miner can analyze a much cleaner signal:

- Which obligations were raised?
- Which were ignored?
- Which tests detected actual failures?
- Which tests were unnecessary?
- Which failures had no preceding obligation?
- Which interventions prevented recurrence?

Those are the raw ingredients of useful autonomous learning.

## Final recommendation

The owner is looking for a way to make Conflux progressively more capable without continually inserting a frontier model's knowledge into its prompts or policies.

The most promising approach is not to ask cheap models to become their own expert postmortem authors. It is to make Conflux an experimental system in which models continuously propose hypotheses, execution produces evidence, contradictions trigger targeted tests, and reusable interventions survive only when they demonstrate value.

I would measure success against three concrete targets, in this order:

1. Recover the known PSCI failure using only the cheap models' recorded observations and objections.
2. Generate the corresponding prevention mechanism automatically from the trace, without showing the system the operator's blind-spot document.
3. Demonstrate that the mechanism detects analogous regressions on previously unseen tasks, at a lower total cost than an equally funded alternative.

Until the third target passes, the project has demonstrated promising supervised execution and retrospective analysis—not yet autonomous generalizable learning.

The architectural principle I would commit to is: every material prediction becomes a testable obligation, every consequential outcome becomes evidence, and every persistent lesson remains falsifiable.

That is the path most likely to turn Conflux's existing multi-model machinery into a system that actually improves with experience rather than simply producing more elaborate supervision.
