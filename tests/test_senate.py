import asyncio
import json
import math

from conflux import senate
from conflux.config import Model
from conflux.providers import ChatResult, ProviderError


def _model(name, family):
    return Model(name, "p", name, family, (), True, 5, 0.0, 0.0)


def _call(command):
    return {"function": {"name": "run", "arguments": json.dumps({"command": command})}}


def test_referenced_files_finds_script_written_in_an_earlier_step():
    script = "import subprocess\nsubprocess.run(['dd', 'if=/tmp/a', 'of=/dev/nbd0p2'])"
    transcript = [
        {"role": "assistant", "tool_calls": [_call(f"cat > /tmp/t/run.py << 'PYEOF'\n{script}\nPYEOF")]},
        {"role": "tool", "content": "ok"},
    ]
    files = senate.referenced_files("python3 /tmp/t/run.py 2>&1", transcript)
    assert "of=/dev/nbd0p2" in files and files.startswith("# /tmp/t/run.py")
    assert senate.referenced_files("ls /etc", transcript) == ""


class _FakeClient:
    def __init__(self, replies):
        self.replies = replies

    async def chat(self, model, messages, **kwargs):
        reply = self.replies[model.name]
        if isinstance(reply, Exception):
            raise reply
        text, letter_probs = reply
        logprobs = [{"token": "<danger>", "top_logprobs": []},
                    {"token": max(letter_probs, key=letter_probs.get),
                     "top_logprobs": [{"token": k, "logprob": math.log(v)} for k, v in letter_probs.items()]}]
        return ChatResult(text, 10, 10, 0.001, logprob_content=logprobs)


def test_convene_takes_most_cautious_member_and_keeps_spread():
    class Cfg:
        models = {"a": _model("a", "x"), "b": _model("b", "y"), "c": _model("c", "z")}
        def model(self, name):
            return self.models[name]

    client = _FakeClient({
        "a": ("reads only <danger>A</danger><how>none</how>", {"A": 1.0}),
        "b": ("overwrites the root fs <danger>T</danger><how>dd replaces userspace</how>", {"T": 0.75, "J": 0.25}),
        "c": ProviderError("c", 500, "down"),
    })
    verdict = asyncio.run(senate.convene(client, Cfg(), ["a", "b", "c"], goal="g", context="",
                                         files="", tool="run", command="dd ..."))
    assert [r.error == "" for r in verdict.ratings] == [True, True, False]
    expected_b = (20 * 0.75 + 10 * 0.25 - 1) / 19
    assert abs(verdict.danger - expected_b) < 1e-9
    assert verdict.how == "b: dd replaces userspace"
    assert abs(verdict.spread - expected_b) < 1e-9


def test_every_members_concern_survives_a_tied_rating():
    class Cfg:
        models = {m: _model(m, f) for m, f in (("q", "qwen"), ("d", "deepseek"), ("g", "glm"))}
        def model(self, name):
            return self.models[name]

    client = _FakeClient({
        "q": ("<danger>J</danger><how>could corrupt the build</how>", {"J": 1.0}),
        "d": ("<danger>J</danger><how>overwrites optee.c without a backup</how>", {"J": 1.0}),
        "g": ("<danger>J</danger><how>matches the PSCI node and displaces the psci driver</how>", {"J": 1.0}),
    })
    verdict = asyncio.run(senate.convene(client, Cfg(), ["q", "d", "g"], goal="g", context="",
                                         files="", tool="run", command="cat > optee.c"))
    assert {r.model for r in verdict.objections} == {"q", "d", "g"}
    assert "displaces the psci driver" in verdict.how
    assert "without a backup" in verdict.how


def test_shadow_senate_logs_and_snapshots_without_blocking(tmp_path, monkeypatch):
    import json as _json
    from conflux import senate

    verdict = senate.SenateVerdict([
        senate.Rating("a", "fa", 18.0, 18, True, how="overwrites the root partition"),
        senate.Rating("b", "fb", 3.0, 3, True),
    ])

    async def fake_convene(client, cfg, members, **action):
        assert "dd if=x of=/dev/nbd0p2" in action["command"]
        return verdict

    class _Client:
        def __init__(self, cfg):
            pass

        async def aclose(self):
            pass

    monkeypatch.setattr(senate, "convene", fake_convene)
    monkeypatch.setattr(senate, "Client", _Client)
    snapshots = []
    shadow = senate.ShadowSenate(None, ["a", "b"], str(tmp_path / "s.jsonl"),
                                 snapshot_at=0.5, snapshot=lambda step: snapshots.append(step) or f"snap-{step}")
    messages = [{"role": "user", "content": "goal"}]
    assert shadow(7, "run", {"command": "dd if=x of=/dev/nbd0p2"}, messages) is verdict
    row = _json.loads((tmp_path / "s.jsonl").read_text())
    assert snapshots == [7] and row["snapshot"] == "snap-7"
    assert row["how"] == "a: overwrites the root partition" and len(row["ratings"]) == 2

    async def broken(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(senate, "convene", broken)
    assert shadow(8, "run", {"command": "ls"}, messages) is None  # never raises
    assert "provider down" in (tmp_path / "s.jsonl").read_text().splitlines()[-1]


def _verdict(*dangers):
    return senate.SenateVerdict([
        senate.Rating(model=f"m{i}", family="f", danger=1 + 19 * d, point=0, continuous=False)
        for i, d in enumerate(dangers)
    ])


def test_decision_methods_combine_member_ratings():
    v = _verdict(0.0, 0.2, 0.9)
    assert v.approves(0.5, "max") is False
    assert v.approves(0.5, "median") is True
    assert v.approves(0.5, "mean") is True
    assert v.approves(0.5, "quorum", quorum=1) is False
    assert v.approves(0.5, "quorum", quorum=2) is True
    assert senate.SenateVerdict([]).approves(0.5) is None


def test_senate_settings_validate_and_load(tmp_path):
    from conflux import config
    import pytest

    with pytest.raises(ValueError):
        config.SenateSettings(decision="vibes")
    with pytest.raises(ValueError):
        config.SenateSettings(concerns="loudest")
    defaults = config.SenateSettings()
    assert (defaults.decision, defaults.concerns, defaults.approve_below) == ("max", "all", 0.5)
