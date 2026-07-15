# Failure Taxonomy

The deficiency catalog for this project. Imported from UC Berkeley's **MAST**
(Multi-Agent System Failure Taxonomy) — Cemri, Pan, Yang et al., *"Why Do
Multi-Agent LLM Systems Fail?"* ([arXiv:2503.13657](https://arxiv.org/abs/2503.13657),
[repo](https://github.com/multi-agent-systems-failure-taxonomy/MAST)) — then
extended with single-model deficiencies observed in practice that MAST does not
cover. Every runtime monitor in the system (see `SPEC.md` §5) is keyed to a
failure-mode ID from this file.

MAST was derived from 150+ annotated execution traces across 7 multi-agent
frameworks (inter-annotator agreement κ = 0.88). Category-level frequencies
from the paper are noted below.

## FC1 — Specification & System Design Failures (41.8% of observed failures)

| ID | Name | Definition |
|----|------|------------|
| FM-1.1 | Disobey task specification | Failure to adhere to specified constraints, guidelines, or requirements of the task. |
| FM-1.2 | Disobey role specification | Failure to adhere to the defined responsibilities of an assigned role; agent behaves like a different agent. |
| FM-1.3 | Step repetition | Unnecessarily repeats a phase, task, or stage that has already been completed. |
| FM-1.4 | Loss of conversation history | Unexpected context truncation; disregards recent interaction history and reverts to an earlier conversational state. |
| FM-1.5 | Unaware of termination conditions | Fails to adhere to the criteria that should trigger termination, wasting turns and resources. |

## FC2 — Inter-Agent Misalignment (36.9%)

| ID | Name | Definition |
|----|------|------------|
| FM-2.1 | Conversation reset | Unexpected or unwarranted restart of a dialogue, losing context and progress. |
| FM-2.2 | Fail to ask for clarification | Does not request additional information when faced with unclear or incomplete data. |
| FM-2.3 | Task derailment | Deviation from the intended objective or focus of the task. |
| FM-2.4 | Information withholding | Possesses critical information but fails to share it with agents that depend on it. |
| FM-2.5 | Ignored other agent's input | Does not properly consider input or recommendations provided by other agents. |
| FM-2.6 | Reasoning–action mismatch | Discrepancy between the agent's stated reasoning/conclusions and the actions or outputs it actually produces. |

## FC3 — Task Verification & Termination (21.3%)

| ID | Name | Definition |
|----|------|------------|
| FM-3.1 | Premature termination | Ends before all necessary information has been exchanged or objectives have been met. |
| FM-3.2 | No or incomplete verification | Omission of proper checking of task outcomes; errors propagate undetected. |
| FM-3.3 | Incorrect verification | Verification exists but is shallow or wrong; fails to cover essential requirements, so bad solutions are accepted. |

## Extensions (FM-X) — single-model deficiencies not in MAST

MAST catalogs *system-level* failures. The models this project targets also
exhibit *model-level* deficiencies that monitors must detect directly:

| ID | Name | Definition | Typically observed in |
|----|------|------------|----------------------|
| FM-X.1 | Effort collapse ("laziness") | Produces a stub, partial implementation, or `// rest omitted` placeholder while claiming completion. | DeepSeek |
| FM-X.2 | Breadth thrash | Explores many superficial solution candidates in sequence, abandoning each before meaningful depth; no candidate is carried to a testable state. | GLM |
| FM-X.3 | Hallucinated environment state | Asserts tool output, file contents, or test results that were never actually observed. | all |
| FM-X.4 | Overconfident self-report | Declares success ("all tests pass") without evidence in the trace. | all |
| FM-X.5 | Instruction dilution under long context | Adherence to early instructions decays as context grows (distinct from FM-1.4: context is present but ignored). | small models esp. |
| FM-X.6 | Sycophantic revision | Abandons a correct answer when challenged, rather than defending it with evidence. | all |
| FM-X.7 | Format/protocol drift | Breaks required output structure (tool-call JSON, diff format), stalling the agent loop. | small models esp. |

## Mapping: observed deficiencies → taxonomy

| Observed behavior | Primary mode(s) |
|---|---|
| DeepSeek: doesn't do enough to complete the task | FM-3.1, FM-X.1 |
| GLM: explores many superficial solutions in sequence | FM-X.2, FM-2.3, FM-1.3 |
| Both: no self-checking | FM-3.2, FM-3.3, FM-X.4 |
| Blatantly ignoring instructions / "acting lazy" | FM-1.1, FM-X.1, FM-X.5 |

## Key empirical finding from the paper

Better prompting and self-verification alone gave only modest gains (~14%
improvement in the paper's case studies); structural fixes — clear role
specifications, explicit termination conditions, and *independent* (cross-agent)
verification — were required for larger gains. This is the core design bet of
this project: verification must be performed by a **different model** than the
one that produced the work.
