"""Continuous logprob-based verification (LLM-as-a-Verifier, arXiv:2607.05391).

Instead of a discrete pass/fail, the verifier reasons, then emits
<score>N</score> on a 1..scale scale. We read the top-k logprob distribution
at the score-token position and take the expectation over valid score tokens,
yielding a continuous reward in [0, 1]. Scaling axes: K repeats (averaged)
and C criteria (averaged) per Eq. 3.1 of the paper.

The score is expressed as a single capital letter A..T (A=1 … T=20), per the
paper: multi-digit numbers split into multiple tokens on some tokenizers
(Qwen emits "20" as "2","0"), which silently corrupts the distribution read.
A letter is one token everywhere. If no letter token is found, we fall back
to the text-parsed score at probability 1.0 — degraded to a discrete judge,
recorded as such.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .config import Config, Model
from .providers import Client

DEFAULT_CRITERIA = [
    "Specification: does the response satisfy every explicit constraint of the task "
    "(and the contract checklist, if given)?",
    "Completeness: is the work fully done — no stubs, placeholders, omissions, or "
    "work deferred back to the user?",
    "Output quality: is the response well-formed, coherent, and directly usable as requested?",
]

_PROMPT = """You are an expert reviewer verifying another model's work.

Evaluation criterion: {criterion}

Task given to the model:
---
{task}
---

Contract (explicit requirements extracted from the task):
{contract}

The model's response:
---
{output}
---

Analyze the response against the criterion. Quote specific evidence. Be
skeptical: unsupported claims of success count against it. Then end your
reply with your score as a SINGLE CAPITAL LETTER on the A-{top} scale, where
A = clearly fails, {mid} = borderline, {top} = clearly satisfies, formatted
exactly as: <score>X</score>"""


@dataclass
class CriterionScore:
    criterion: str
    expected: float            # expectation over score tokens, 1..scale
    point: int                 # text-parsed score
    continuous: bool           # False = degraded to discrete judge
    reasoning_tail: str = ""


@dataclass
class VerifyReport:
    score: float               # normalized [0,1], averaged over criteria & repeats
    passed: bool
    criteria: list[CriterionScore] = field(default_factory=list)
    feedback: str = ""         # for the repair loop
    cost_usd: float = 0.0
    tokens: int = 0
    verifier: str = ""


def _letter_value(tok: str, scale: int) -> int | None:
    # Tokenizers may fuse the letter with tag punctuation (Qwen emits '>T').
    t = tok.strip().lstrip(">").rstrip("<")
    if len(t) == 1 and "A" <= t <= chr(ord("A") + scale - 1):
        return ord(t) - ord("A") + 1
    return None


def _score_from_logprobs(
    lp_content: list[dict[str, Any]], text: str, scale: int
) -> tuple[float, int, bool]:
    """Return (expected score, point score, was_continuous)."""
    point = _parse_point(text, scale)
    # Locate the first letter token at/after the LAST '<score>' in the text.
    acc = ""
    starts = []
    for tok in lp_content:
        starts.append(len(acc))
        acc += tok.get("token", "")
    tag = acc.rfind("<score>")
    if tag < 0:
        return float(point), point, False
    idx = None
    for i, tok in enumerate(lp_content):
        if starts[i] >= tag and _letter_value(tok.get("token", ""), scale) is not None:
            idx = i
            break
    if idx is None:
        return float(point), point, False
    dist: dict[int, float] = {}
    for a in lp_content[idx].get("top_logprobs") or []:
        v = _letter_value(a.get("token", ""), scale)
        if v is not None:
            dist[v] = dist.get(v, 0.0) + math.exp(a["logprob"])
    if not dist:
        return float(point), point, False
    total = sum(dist.values())
    expected = sum(v * p for v, p in dist.items()) / total
    return expected, point, True


def _parse_point(text: str, scale: int) -> int:
    import re

    m = re.findall(r"<score>\s*([A-Za-z])\s*</score>", text)
    if m:
        v = _letter_value(m[-1].upper(), scale)
        if v is not None:
            return v
    m = re.findall(r"<score>\s*(\d{1,2})\s*</score>", text)
    if m:
        return max(1, min(scale, int(m[-1])))
    return 1


class Verifier:
    def __init__(self, client: Client, cfg: Config):
        self.client = client
        self.cfg = cfg

    async def verify(
        self,
        *,
        task: str,
        output: str,
        contract: list[str],
        executor_family: str,
        criteria: list[str] | None = None,
        repeats: int | None = None,
    ) -> VerifyReport:
        sup = self.cfg.supervision
        scale = sup.score_scale
        criteria = criteria or DEFAULT_CRITERIA
        repeats = repeats or sup.verify_repeats
        model: Model = self.cfg.pick_verifier(executor_family)

        contract_text = "\n".join(f"- {c}" for c in contract) if contract else "(none extracted)"
        scores: list[CriterionScore] = []
        cost = 0.0
        tokens = 0
        worst: CriterionScore | None = None

        for criterion in criteria:
            expected_sum = 0.0
            point_last = 1
            continuous_all = True
            tail = ""
            for k in range(repeats):
                # Aggregators return logprobs flakily (~75% observed on Nous):
                # retry before degrading to a discrete judge.
                for attempt in range(3):
                    res = await self.client.chat(
                        model,
                        [
                            {
                                "role": "user",
                                "content": _PROMPT.format(
                                    criterion=criterion,
                                    task=task[:8000],
                                    contract=contract_text,
                                    output=output[:12000],
                                    top=chr(ord("A") + scale - 1),
                                    mid=chr(ord("A") + scale // 2 - 1),
                                ),
                            }
                        ],
                        max_tokens=1500,
                        temperature=0.0 if repeats == 1 else 0.6,
                        logprobs=True,
                    )
                    cost += res.cost_usd
                    tokens += res.tokens_in + res.tokens_out
                    expected, point, continuous = _score_from_logprobs(
                        res.logprob_content, res.text, scale
                    )
                    if continuous or not model.logprobs:
                        break
                expected_sum += expected
                point_last = point
                continuous_all = continuous_all and continuous
                tail = res.text.rsplit("<score>", 1)[0][-500:]

            cs = CriterionScore(
                criterion=criterion.split(":")[0],
                expected=expected_sum / repeats,
                point=point_last,
                continuous=continuous_all,
                reasoning_tail=tail,
            )
            scores.append(cs)
            if worst is None or cs.expected < worst.expected:
                worst = cs

        norm = (sum(c.expected for c in scores) / len(scores) - 1) / (scale - 1)
        passed = norm >= sup.pass_threshold
        feedback = ""
        if not passed and worst is not None:
            feedback = (
                f"An independent reviewer scored this response "
                f"{worst.expected:.1f}/{scale} on '{worst.criterion}'. "
                f"Reviewer notes: {worst.reasoning_tail.strip()}"
            )
        return VerifyReport(
            score=norm,
            passed=passed,
            criteria=scores,
            feedback=feedback,
            cost_usd=cost,
            tokens=tokens,
            verifier=model.name,
        )
