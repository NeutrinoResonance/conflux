# Observability & conversation mechanics

Reference for what the dashboard shows, how scores are computed, and how
conversation identity/attach/resend actually behave. Written 2026-07-18
after the first live Hermes hookup surfaced most of these questions.

## 1. Conversation identity, !attach, and what "sending a message" does

- A conversation (session) is **content-addressed**: its id is the hash of
  the FIRST user message of the request. A client that rewrites or
  annotates its prefix (Hermes does, routinely) silently creates a new
  conversation per rewrite.
- `!conversations` lists recent sessions (id · age · turns · title, with
  `← you are here`). `!attach <id-prefix>` pins the *current client
  thread* onto an existing conversation via a persistent alias table
  resolved at ingress; `!attach off` detaches. No model calls.
- **After attaching, sending a message runs a normal new supervised turn
  inside that conversation**: it is recorded there, cross-turn monitors
  read that conversation's history, checkpoints/edit history accrue
  there, and the gate treats the thread as known. Nothing is re-run or
  replayed by attaching itself. The model's context is still whatever
  your client sends as message history, plus the supervisor's cross-turn
  session notes.

## 2. "⧉ request" vs !attach — the data-loss question

Resending the copied request text re-keys to the same session AND the
same checkpoint key, so:
- a **decomposed** turn resumes: completed units are NOT re-run (their
  outputs and spend are checkpointed); `!rewind <unit#>` forgets one.
- a **single** (non-decomposed) turn has no unit checkpoint: resending
  re-runs the whole ladder from attempt 1. Repair lessons (verifier
  feedback, referee decisions) from the previous run are NOT carried
  into the new run — they exist in the trace but are not fed back.
So yes: for single turns the resend mechanism loses the learning. The
"⧉ request" button is therefore for *locating* the message in a client
(edit/rewind); for continuing work, `!attach` + a follow-up message is
strictly better — the previous answer and your reaction to it ride in as
conversation context. Carrying repair state across identical resends via
the checkpoint table is possible future work.

## 3. Timeline (task card) legend

Chronological trace events per turn. Hierarchy: unit-tagged events fold
into `unit N` groups; events inside a fan-out (best/union/fuse) are
**indented** under their `⑂ strategy` row until the `★ winner` row.

- `goal started` — turn began; shows routed executor.
- `☑ checklist extracted` — contract call (criteria for the verifier);
  expandable to the constraint list. Also classifies difficulty
  (trivial→cheap executor + lite verify).
- `⑂ <mode> strategy` — fan-out start: candidate models, cutoff if set.
- `⚙ attempt N — model` — an executor call. Expand → **load model
  output** fetches the exact upstream response inline.
- `⏵ sandbox passed/FAILED` — code blocks extracted from that answer were
  EXECUTED (local subprocess or a gcloud VM, per `!sandbox`). Expand for
  stdout/stderr. The transcript is handed to the verifier as
  execution evidence ("Errors" criterion); a failure raises FM-X.3 and
  drives the repair loop. This is why confident-but-broken code cannot
  pass: the interpreter outranks any model's opinion.
- `◇ candidate verified` / `✓/✗ verified by <model>` — a verification;
  expand for the full score math (below).
- `↻ referee after failed attempt N` — the repair decision point (this is
  what "restarts" an attempt): `retry feedback` (free rule retries),
  then structural moves — `switch model → X`, `escalate verification`,
  `decompose`, `ask user`. Expand for the rationale. The next `⚙ attempt`
  row is the retry it triggered.
- `Σ merge/assembly call` — union/fuse merge or unit synthesis: candidate
  outputs + reviewer scores become the prompt; the result must out-score
  the best input or it is `✂ merge rejected`. Expand → load the merged
  output inline.
- `⚡ short-circuit` — a candidate hit the `!cutoff`; pending candidates
  cancelled.
- `⚠ FM-x.y` — failure-mode monitor hit (heuristic or cross-turn).
- `🚪 gate` — new-conversation warning was returned; nothing ran.
- `✓/⛔ finished` — turn end with score and spend.

## 4. Score math (what the verify expansion shows)

Continuous logprob verification (arXiv:2607.05391, SPEC §6): the
cross-family reviewer writes an analysis ending in `<score>X</score>`
where X is a SINGLE letter A..T (A=1 … T=20). Letters, never digits —
multi-digit numbers tokenize into several tokens on Qwen-family
tokenizers and corrupt the read (docs/mini-paper.md §3).

Per criterion (Specification / Completeness / Output quality, + Errors
when execution evidence exists; contract constraints become extra
criteria at the adversarial tier):

    E = Σ letter_value · P(letter)

with P read from the top-5 logprobs at the score-tag position and
renormalized over valid letters. If no usable logprob distribution comes
back (flaky on aggregators), the criterion degrades to the text-parsed
letter at probability 1.0 and is marked "discrete read".

Combination:

    score = (mean over criteria of E − 1) / (scale − 1)   ∈ [0, 1]

K repeats average E per criterion (K=1 standard, K=3 adversarial).
`pass` = score ≥ supervision.pass_threshold (0.70). The verify node's
expansion shows every criterion's distribution, E, and this formula with
the actual numbers.

## 5. Where things appear in the Pipeline graph

Graph nodes mirror the timeline: candidates carry their verify score and
a `▶✓ / ▶✗` sandbox marker in the sub-label; the referee appears as a
node on the single path; merges appear as union/fusion nodes whose
sub-label shows score and rejection. The graph is a map — the timeline
rows (and their expansions) are the territory.
