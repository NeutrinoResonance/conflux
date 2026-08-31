"""Calibration harness: seeded answers, per-family false-pass metrics."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from conflux import verifier_calibration as cal
from conflux.config import (
    AdminAuth, Config, Execution, Model, Provider, Supervision,
)
from conflux.providers import ChatResult


def _cfg() -> Config:
    def model(name: str, family: str) -> Model:
        return Model(
            name=name, provider="p", id=name, family=family,
            roles=("verifier", "executor"), logprobs=True,
            top_logprobs_max=20, price_in_per_m=1.0, price_out_per_m=2.0,
        )
    return Config(
        providers={"p": Provider("p", "https://x.test/v1", "env:K")},
        models={"sharp": model("sharp", "fam-a"),
                "sycophant": model("sycophant", "fam-b")},
        default_executor="sharp", utility="sharp",
        verifier_pool=["sharp", "sycophant"],
        supervision=Supervision(verify_repeats=1),
        execution=Execution(backend="off", locked_backend=None),
        admin=AdminAuth(),
    )


def _scored_response(letter: str) -> ChatResult:
    return ChatResult(
        text=f"Analysis complete. <score>{letter}</score>",
        tokens_in=100, tokens_out=50, cost_usd=0.0005,
        logprob_content=[
            {"token": "<score>", "top_logprobs": []},
            {"token": letter,
             "top_logprobs": [{"token": letter, "logprob": -0.01}]},
        ],
    )


class _StubClient:
    """'sharp' discriminates (T for good, C for flawed); 'sycophant' says T
    to everything — the saturation failure from field report 2026-07-17."""

    def __init__(self):
        self.calls = 0

    async def chat(self, model, messages, **kw):
        self.calls += 1
        prompt = messages[0]["content"]
        if model.name == "sycophant":
            return _scored_response("T")
        good_markers = ("return (ordered[mid - 1] + ordered[mid]) / 2",
                        "11\n13\n17\n19\n23",
                        "Total revenue: 50.00")
        letter = "T" if any(m in prompt for m in good_markers) else "C"
        return _scored_response(letter)


class CalibrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_metrics_expose_saturated_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "t.db"
            result = await cal.run_calibration(
                _cfg(), _StubClient(), db_path=db)
            sharp = result["families"]["sharp (fam-a)"]
            syco = result["families"]["sycophant (fam-b)"]

            self.assertEqual(sharp["false_pass_rate"], 0.0)
            self.assertEqual(sharp["false_fail_rate"], 0.0)
            self.assertGreater(sharp["discrimination"], 0.5)
            self.assertEqual(sharp["errors"], 0)

            self.assertEqual(syco["false_pass_rate"], 1.0)
            self.assertAlmostEqual(syco["discrimination"], 0.0, places=3)
            self.assertEqual(syco["saturation_rate"], 1.0)
            self.assertEqual(len(syco["false_passes"]),
                             sum(1 for c in cal.CALIBRATION_CASES
                                 for a in c.answers if a.kind == "flawed"))

            # Persisted and rebuildable.
            latest = cal.latest_report(db)
            self.assertEqual(latest["run_id"], result["run_id"])
            self.assertEqual(
                latest["families"]["sycophant (fam-b)"]["false_pass_rate"],
                1.0)

            text = cal.format_report(result)
            self.assertIn("FALSE PASS", text)
            self.assertIn("sycophant", text)

    async def test_seeded_suite_has_good_and_flawed_answers_per_case(self) -> None:
        for case in cal.CALIBRATION_CASES:
            kinds = {a.kind for a in case.answers}
            self.assertEqual(kinds, {"good", "flawed"}, case.id)
            for answer in case.answers:
                if answer.kind == "flawed":
                    self.assertTrue(answer.flaw, f"{case.id}/{answer.id}")

    async def test_empty_pool_is_an_error(self) -> None:
        cfg = _cfg()
        cfg.verifier_pool = []
        with self.assertRaises(ValueError):
            await cal.run_calibration(cfg, _StubClient())


if __name__ == "__main__":
    unittest.main()
