# llm-super: A Supervisor That Makes Cheap Open-Source Models Check Each Other's Work

*Progress report · 2026-07-16 · repo state at commit `c606ae5`*

## Abstract

Open-source models fail in predictable ways: DeepSeek stops before the work
is done, GLM skims across shallow attempts, and all of them skip
self-checking and sometimes ignore instructions. We built a working system
that catches these failures automatically. It looks like a normal model API
to any coding tool, but behind it every answer is checked by a *different*
model before you see it, bad answers are sent back for repair with specific
feedback, and you can pause, redirect, or cap the cost of the whole thing at
any moment. Total supervision overhead in our tests: about a third of a cent
per task.

## 1. What it can do today

**Ability 1 — It works with tools you already use.**
The system runs as a local server that speaks the standard OpenAI API.
Point OpenCode, Aider, or any similar tool at `http://127.0.0.1:8055/v1`,
select the model named `super`, and every request is silently supervised.
No plugin, no fork, no changes to the tool.

**Ability 2 — It turns your request into a checklist before any work starts.**
A small cheap model (Gemma, ~$0.0001 per call) reads the task and extracts
the explicit requirements ("function must be named `median`", "reply with
only code"). This matters because the largest single cause of agent failures
— 41.8% in UC Berkeley's MAST study of 150+ failed agent runs — is simply
not following the specification. You can't enforce a spec you never wrote
down.

**Ability 3 — It catches laziness without calling any model at all.**
Pattern-based monitors scan every answer for the signatures of known failure
modes: stubs and placeholders ("TODO", "rest omitted for brevity"), work
deferred back to the user ("you can implement the rest"), and success claims
with no evidence ("all tests pass" with no test run in sight). Each hit is
tagged with a failure-mode ID from our taxonomy and becomes repair
instructions. These checks are free and instant.

**Ability 4 — Every answer is graded by a different model family, using the
model's actual uncertainty.**
The core idea (from Stanford/Berkeley's "LLM-as-a-Verifier", arXiv:2607.05391):
don't ask a model to grade work pass/fail — ask it to reason, then emit a
score, and read the *probability distribution* the model assigned over all
possible scores at that moment. A grader that says "14" while holding 40% of
its belief on lower scores is telling you something a plain "14" hides. We
read that distribution directly from the model's token probabilities and take
the average. Two rules make it trustworthy: the grader is always from a
different model family than the worker (models don't share blind spots with
their cousins the way they share them with themselves), and an answer is
graded on three separate questions — did it follow the spec, is it complete,
is the output usable — rather than one vague "is it good?".

**Ability 5 — Bad work gets fixed before you see it.**
Fail the grade or trip a monitor, and the system sends the answer back to the
worker with specific feedback quoting what was wrong ("the task said reply
with only a code block; you added commentary"). Two repair attempts maximum —
after that it stops burning money and escalates to you with its best attempt,
clearly labeled. This hard stop exists because "keep retrying the same thing"
is itself one of the failure modes we're defending against.

**Ability 6 — You can always see it, steer it, and stop it.**
From inside your normal chat tool, message `!pause`, `!resume`,
`!use kimi-k2.6`, `!budget 0.25`, or `!status` — these are intercepted and
never reach any model. Every step (who ran, what it cost, which failure
modes fired, what the grade was) is written to a local SQLite trace you can
query while it runs. Each task has a dollar budget; crossing it halts work
mid-task.

## 2. Does the grading actually work?

The discrimination test, run live against real providers:

| Input to the verifier | Grade | Monitors |
|---|---|---|
| Correct `median()` with doctests | **20/20** on all three criteria, passed first try | none |
| Seeded lazy version: `pass  # TODO`, "all tests pass", "implement the rest yourself" | **1/20** | laziness ×2, false-claim ×1 |

Full supervision of a real coding turn — checklist, execution, monitoring,
independent grading — cost **$0.003** and one extra round-trip.

## 3. What we found out the hard way

These cost us debugging time so you don't have to rediscover them:

1. **Most hosted providers silently drop the probability data.** NanoGPT
   accepts the request parameter and returns nothing — across 5 model
   families and all 15 of its selectable upstream providers. Ollama Cloud
   doesn't support it at all. The Nous inference API is the best channel
   found (5 of 6 families work); OpenCode Go works for DeepSeek and Qwen.
   Docs cannot be trusted on this; only probing tells the truth.
2. **Even on a good provider, the data is flaky per-request** (~75%
   presence on Nous, and Gemma's capable upstream disappeared between
   yesterday and today). The system retries, and only degrades to a plain
   discrete grade — recorded as such — when it must.
3. **Never score on a number scale.** Qwen writes "20" as two tokens
   ("2", "0"); reading the distribution at the second token graded a perfect
   answer 1.3/20. Scores must be a single letter (A–T), which is one token
   on every tokenizer we tested — and even then, one tokenizer fused the
   letter to the tag bracket (`>T`) and had to be unfused.
4. **Credentials rotate.** The Nous key changes roughly daily, so the system
   re-reads it from disk on every request instead of caching it.

## 4. What it cannot do yet

It supervises one turn at a time — it does not yet reconstruct multi-turn
agent trajectories, so failure modes that only show up *across* turns
(repeating steps, thrashing between shallow approaches) have detectors
designed but not yet wired to live data. Grading is text-based: the verifier
judges what the answer says, not what happens when the code runs. Pause
takes effect between steps, not mid-generation. And routing is static — the
plan is for repair outcomes to teach the router which model to trust for
what, but no learning happens yet.

## 5. Foundations

- Cemri, Pan, Yang et al., *Why Do Multi-Agent LLM Systems Fail?* (MAST),
  arXiv:2503.13657 — the failure taxonomy this project detects against
  (imported and extended in `docs/failure-taxonomy.md`).
- Kwok et al., *LLM-as-a-Verifier: A General-Purpose Verification Framework*,
  arXiv:2607.05391 — continuous probability-based grading, verified
  independently here down to its tokenizer caveats.
- Full design: `SPEC.md`. Code: `llm_super/` (~1,100 lines, Python).
