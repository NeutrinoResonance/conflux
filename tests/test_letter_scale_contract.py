"""Regression pin for the verifier letter-scale contract (CLAUDE.md,
docs/mini-paper.md §3): scores are a single capital letter A..T (20 levels),
never digits — multi-digit numbers tokenize into several tokens on Qwen and
corrupt the logprob-expectation read."""

import math
import string

import pytest

from conflux.config import Supervision
from conflux.verifier import _letter_value, _parse_point, _score_from_logprobs

SCALE = Supervision().score_scale


def test_scale_is_twenty_letters_a_to_t():
    assert SCALE == 20
    accepted = [c for c in string.printable if _letter_value(c, SCALE) is not None]
    assert "".join(accepted) == "ABCDEFGHIJKLMNOPQRST"
    assert all(len(c) == 1 and c.isupper() for c in accepted)
    assert [_letter_value(c, SCALE) for c in accepted] == list(range(1, 21))


@pytest.mark.parametrize(
    "tok", [str(d) for d in range(10)] + ["10", "20", " 7", ">7", "7<"]
)
def test_letter_value_rejects_digit_tokens(tok):
    assert _letter_value(tok, SCALE) is None


def test_logprob_distribution_ignores_digit_alternatives():
    lp = [
        {"token": "<score>"},
        {"token": "M", "top_logprobs": [
            {"token": "M", "logprob": math.log(0.5)},
            {"token": "7", "logprob": math.log(0.2)},
            {"token": "N", "logprob": math.log(0.2)},
            {"token": "20", "logprob": math.log(0.1)},
        ]},
        {"token": "</score>"},
    ]
    expected, point, continuous, dist = _score_from_logprobs(
        lp, "<score>M</score>", SCALE
    )
    assert continuous
    assert point == 13
    assert set(dist) == {"M", "N"}
    assert expected == pytest.approx((13 * 0.5 + 14 * 0.2) / 0.7)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "conflux/verifier.py _parse_point falls back to digit scores: "
        "<score>N</score> is accepted and returned as N (clamped to 1..scale), "
        "violating the letter-only A–T contract (CLAUDE.md, docs/mini-paper.md §3); "
        "product code intentionally left unchanged"
    ),
)
def test_parse_point_rejects_digit_scores():
    assert _parse_point("<score>7</score>", SCALE) == _parse_point("<score></score>", SCALE)
