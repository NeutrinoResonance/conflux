"""Admission, accounting, classification and redaction seams of scripts/provider_probe.py."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

_spec = importlib.util.spec_from_file_location(
    "provider_probe", Path(__file__).resolve().parents[1] / "scripts/provider_probe.py")
pp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pp)


# ---------------------------------------------------------------- admission


def test_admit_refuses_at_experiment_cap():
    b = pp.Budget(ledger_total=0.0)
    assert b.admit(0.60) == (True, None)
    b.settle(0.60, 0.55)
    assert b.admit(0.50) == (False, "experiment_cap")
    assert not b.paused()
    # Once refused, nothing else is admitted.
    assert b.admit(0.0001) == (False, "experiment_cap")


def test_admit_refuses_at_campaign_remainder():
    b = pp.Budget(ledger_total=49.99)
    assert b.admit(0.02) == (False, "campaign_budget")
    assert b.paused()
    assert b.report()["mission_status"] == "PAUSED"


def test_reservations_count_against_allowance():
    b = pp.Budget(ledger_total=0.0)
    assert b.admit(0.7)[0]
    assert b.admit(0.4) == (False, "experiment_cap")


def test_price_ceiling_floor_and_unknown():
    # deepseek-v4-flash lists ~$0.18/1M completion: floored to $30/1M.
    assert pp.price_ceiling({"prompt": "0.000000091", "completion": "0.000000182"}) == pp.PRICE_FLOOR
    assert pp.price_ceiling({"prompt": "0.00002", "completion": "0.00004"}) == pytest.approx(8e-5)
    assert pp.price_ceiling(None) == pp.PRICE_UNKNOWN
    assert pp.price_ceiling({"prompt": "n/a"}) == pp.PRICE_UNKNOWN


def test_charge_bound_uses_jev_minimum_input():
    assert pp.charge_bound(100, 0, 1e-6, min_input=300) == pytest.approx(300e-6)
    assert pp.charge_bound(1000, 512, 1e-6) == pytest.approx(1512e-6)


def test_parse_ledger_total():
    assert pp.parse_ledger_total("x\n**Metered total: $12.345**\n") == pytest.approx(12.345)
    with pytest.raises(ValueError):
        pp.parse_ledger_total("| no total here |")


def test_repo_ledger_parses():
    pp.parse_ledger_total(pp.LEDGER.read_text())


# ---------------------------------------------------------------- settlement


def test_actual_cost_above_bound_is_recorded_and_stops():
    b = pp.Budget(ledger_total=0.0)
    assert b.admit(0.01)[0]
    assert b.settle(0.01, 0.05) == "actual"
    assert b.actual == pytest.approx(0.05)  # the known charge, not the lower bound
    assert b.estimated == 0
    assert b.stop_reason == "cost_exceeded_bound"
    assert b.admit(0.0001)[0] is False


def test_overrun_feeds_campaign_status():
    b = pp.Budget(ledger_total=49.90)
    assert b.admit(0.05)[0]
    b.settle(0.05, 0.20)
    r = b.report()
    assert r["spent_usd"] == pytest.approx(0.20)
    assert r["campaign_overrun_usd"] == pytest.approx(0.10)
    assert r["mission_status"] == "PAUSED"


def test_experiment_overrun_reported():
    b = pp.Budget(ledger_total=0.0)
    assert b.admit(0.9)[0]
    b.settle(0.9, 1.3)
    r = b.report()
    assert r["experiment_overrun_usd"] == pytest.approx(0.3)
    assert r["mission_status"] == "ACTIVE"


def test_missing_cost_records_labeled_estimate_and_stops():
    b = pp.Budget(ledger_total=0.0)
    assert b.admit(0.03)[0]
    assert b.settle(0.03, None) == "estimate"
    assert b.estimated == pytest.approx(0.03)
    assert b.actual == 0
    assert b.stop_reason == "unknown_accounting"
    assert b.reserved == pytest.approx(0.0)


def test_billed_cost_reads_buyer_cost_micro():
    assert pp.billed_cost({"usage": {"buyer_cost_micro": 1234}}) == pytest.approx(0.001234)
    assert pp.billed_cost({"buyer_cost_micro": 10}) == pytest.approx(0.00001)
    assert pp.billed_cost({"usage": {"total_tokens": 9}}) is None
    assert pp.billed_cost({"usage": {"buyer_cost_micro": True}}) is None
    assert pp.billed_cost(None) is None


# ---------------------------------------------------------------- classifiers


def test_tool_call_classification():
    msg = {"role": "assistant", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}]}
    assert pp.classify_tool_call({"choices": [{"message": msg}]}) == ("tool_call", msg)
    assert pp.classify_tool_call({"choices": [{"message": {"content": "hi"}}]})[0] == "no_tool_call"
    assert pp.classify_tool_call({})[0] == "malformed"
    assert pp.classify_final_text({"choices": [{"message": {"content": "18 C"}}]}) == "text"
    assert pp.classify_final_text({"choices": [{"message": {"content": ""}}]}) == "empty"


def test_logprobs_outcomes_are_distinct():
    present = {"choices": [{"logprobs": {"content": [{"token": "B", "top_logprobs": [{}]}]}}]}
    assert pp.classify_logprobs(200, present) == "present"
    assert pp.classify_logprobs(200, {"choices": [{"logprobs": None}]}) == "absent"
    assert pp.classify_logprobs(400, {"error": {}}) == "rejected"
    assert pp.classify_logprobs(503, {}) == "error"


def test_stream_classification():
    text = "\n".join([
        'data: {"choices":[{"delta":{"content":"1,"}}]}',
        'data: {"choices":[{"delta":{"content":"2"}}]}',
        'data: {"choices":[],"usage":{"total_tokens":5,"buyer_cost_micro":3}}',
        "data: [DONE]",
    ])
    s = pp.classify_stream(*pp.parse_sse(text))
    assert s["outcome"] == "streamed"
    assert s["chunks"] == 3
    assert pp.billed_cost({"usage": s["usage"]}) == pytest.approx(3e-6)
    assert pp.classify_stream(*pp.parse_sse('data: {"choices":[]}'))["outcome"] == "not_streamed"


def test_decision_classification():
    choice = {"q1": {"choice": "accept", "probabilities": {"accept": 0.99, "retry": 0.01}}}
    assert pp.classify_decision(200, choice, "choice") == "choice_probabilities"
    assert pp.classify_decision(200, {"q1": {"score": 1}}, "score") == "no_probabilities"
    assert pp.classify_decision(502, {}, "score") == "error"


# ---------------------------------------------------------------- redaction


def test_recorder_scrubs_keys(tmp_path):
    key = "fake-probe-key-0123"
    rec = pp.Recorder(tmp_path / "p.jsonl", [key, ""])
    rec.write(note=f"echo {key}", body={"error": {"message": f"bad key {key}"}})
    rec.fh.close()
    text = (tmp_path / "p.jsonl").read_text()
    assert key not in text
    assert "<redacted>" in json.loads(text)["note"]


def test_sanitize_fields_drops_private_keys():
    out = pp.sanitize_fields({"email": "a@b.c", "balance": 4.2, "user": {"id": "u1"}, "stripeSubscriptionId": "sub_x",
                              "limits": [{"type": "TOKENS", "percentage": 12}]})
    assert out == {"balance": 4.2, "limits.0.type": "TOKENS", "limits.0.percentage": 12}


# ---------------------------------------------------------------- derived cost

JEV_PRICING = {"prompt": "0.0000000420", "completion": "0.0000000000"}


def test_derived_cost_uses_price_and_minimum_input():
    body = {"usage": {"input_tokens": 355, "output_tokens": 32}}
    assert pp.derived_cost(body, JEV_PRICING, 300) == pytest.approx(355 * 42e-9)
    small = {"usage": {"input_tokens": 120, "output_tokens": 5}}
    assert pp.derived_cost(small, JEV_PRICING, 300) == pytest.approx(300 * 42e-9)
    assert pp.derived_cost({"usage": {"total_tokens": 9}}, JEV_PRICING, 300) is None
    assert pp.derived_cost({"usage": {"input_tokens": 9}}, None) is None
    assert pp.derived_cost(None, JEV_PRICING) is None


def test_derived_settlement_is_labeled_and_keeps_running():
    b = pp.Budget(ledger_total=0.0)
    assert b.admit(0.01)[0]
    assert b.settle(0.01, 0.000015, "derived") == "derived"
    assert b.derived == pytest.approx(0.000015)
    assert b.actual == 0 and b.estimated == 0
    assert b.stop_reason is None
    assert b.report()["derived_usd"] == pytest.approx(0.000015)
    assert b.admit(0.01)[0]


def _prober(handler, tmp_path, only=None):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    rec = pp.Recorder(tmp_path / "p.jsonl", ["fake-probe-key-0123"])
    return pp.PaidProber(http, "fake-probe-key-0123", pp.Budget(0.0, cap=0.10), rec, {"jev-1.14": JEV_PRICING}, only)


def test_jev_decision_without_billed_cost_settles_derived(tmp_path):
    def handler(request):
        return httpx.Response(200, json={
            "answers": {"q1": {"score": 1.3, "probabilities": {"0": 0.3, "1": 0.1, "2": 0.6}}},
            "usage": {"input_tokens": 340, "output_tokens": 30}})
    p = _prober(handler, tmp_path)
    p.decision("score", 0)
    assert p.results["jev-1.14"]["decision_score"][0]["outcome"] == "score_probabilities"
    assert p.budget.derived == pytest.approx(340 * 42e-9)
    assert p.budget.stop_reason is None
    resp = [json.loads(l) for l in (tmp_path / "p.jsonl").read_text().splitlines()
            if json.loads(l).get("event") == "response"]
    assert resp[0]["cost_kind"] == "derived"


def test_every_paid_request_carries_the_discount_floor(tmp_path):
    # MISSION a58a30e: kimi-k3.1-pro rows billed at 60% off after the 90% floor took effect; every paid request this
    # script sends (chat, stream, decisions) must carry X-Min-Discount like core.surplus_post.
    seen = []

    def handler(request):
        seen.append(request.headers.get("x-min-discount"))
        return httpx.Response(200, json={"answers": {}, "usage": {"input_tokens": 340, "output_tokens": 0}})
    p = _prober(handler, tmp_path)
    p.decision("score", 0)
    p._post(pp.SURPLUS + "/chat/completions", {"model": "m", "messages": []}, 0.0, {"model": "m"})
    p._post(pp.SURPLUS + "/chat/completions", {"model": "m", "messages": []}, 0.0, {"model": "m"}, stream=True)
    assert seen == ["90", "90", "90"]


def test_jev_decision_without_usage_still_stops(tmp_path):
    p = _prober(lambda r: httpx.Response(200, json={"answers": {}}), tmp_path)
    p.decision("choice", 0)
    assert p.budget.stop_reason == "unknown_accounting"


def test_only_selector_schedules_untested_probes(tmp_path):
    p = _prober(lambda r: httpx.Response(500), tmp_path, only=[
        "decision_choice", "decision_score", "deepseek-v4-pro:logprobs", "stream_usage"])
    assert [(m, c) for m, c, _, _ in p.plan()] == [
        ("jev-1.14", "decision_choice"), ("jev-1.14", "decision_score"),
        ("deepseek-v4-pro", "logprobs"),
        ("deepseek-v4-flash", "stream_usage"), ("deepseek-v4-pro", "stream_usage")]
    assert len(_prober(lambda r: httpx.Response(500), tmp_path).plan()) == 8
