"""Acceptance test for the run-12 NetBSD stall (work item A).

Read-only checks that name only absolute files must scope to exactly those
reads. In run 12 the scope gate read grep patterns ('I/TC:'), option values
(`tail -n 1`) and fd numbers (`2>&1`) as relative paths, so correct checks
were rated non-low risk, sent to a soundness checker that failed closed on
HTTP 402, recorded as postcheck_failed, and their identical re-checks held for
a human. Evidence: tests/fixtures/run12_netbsd/manifest.json.

The failing baseline was pinned by strict xfail; the T1 fix flipped it.
"""

import json
import pathlib

import pytest

from conflux.decider import _shell_effects

MANIFEST = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "run12_netbsd" / "manifest.json").read_text())
RECORDED = {a["action_id"]: a["command"] for a in MANIFEST["actions"]}


def scope(command):
    unproven: list[str] = []
    return set(_shell_effects(command, None, unproven=unproven)), unproven


@pytest.mark.parametrize("command, reads", [
    ("/usr/bin/grep -q 'I/TC:' /tmp/x/log", {"/tmp/x/log"}),
    ("/usr/bin/tail -n 1 /tmp/x/log", {"/tmp/x/log"}),
    ("/usr/bin/head -n 8 /tmp/x/log", {"/tmp/x/log"}),
    ("ls -l /dev/kvm >/dev/null 2>&1", {"/dev/kvm"}),
    (RECORDED["act_40f7d6d6a49345c3"], {"/tmp/conflux-agent/optee-run-serial-sw.log",
                                        "/tmp/conflux-agent/optee-run.log"}),
    (RECORDED["act_c64ca4d4a70d4832"], {
        "/tmp/conflux-agent/baseline-env.txt", "/tmp/conflux-agent/toolchain-env.txt",
        "/tmp/conflux-agent/source-manifest.txt", "/tmp/conflux-agent/host-build-deps.txt",
        "/tmp/conflux-agent/optee-build3.log", "/tmp/conflux-agent/optee-run.log",
        "/tmp/conflux-agent/optee-run-serial-sw.log", "/tmp/conflux-agent/optee-run-serial.log"}),
])
def test_read_only_check_scopes_to_exactly_its_files(command, reads):
    effects, unproven = scope(command)
    assert unproven == []
    assert effects == {(path, "read") for path in reads}


@pytest.mark.parametrize("action_id", ["act_716b22ec52c6403b", "act_36ddd48525f642fb",
                                       "act_94d8ee95c80346c8"])
def test_recorded_checks_name_no_phantom_relative_paths(action_id):
    # These also run programs the gate cannot classify (df) or expand $c;
    # only the false relative paths are in scope here.
    _, unproven = scope(RECORDED[action_id])
    assert not [r for r in unproven if r.startswith("relative path")]


@pytest.mark.parametrize("command, effects, relative", [
    ("cat 2 >/tmp/o", {("/tmp/o", "write")}, ["2"]),
    ("echo x >&/tmp/f", {("/tmp/f", "write")}, []),
    ("echo x 2>&- > -", set(), ["-"]),
    ("grep -f pats /tmp/x", {("/tmp/x", "read")}, ["pats"]),
    ("grep -e 'a/b' /tmp/x", {("/tmp/x", "read")}, []),
    ("grep -ea/b /tmp/x", {("/tmp/x", "read")}, []),
    ("grep -f/tmp/pats /tmp/x", {("/tmp/pats", "read"), ("/tmp/x", "read")}, []),
    ("grep -fn /tmp/x", {("/tmp/x", "read")}, ["n"]),
    ("grep --file=/tmp/pats /tmp/x", {("/tmp/pats", "read"), ("/tmp/x", "read")}, []),
    ("grep 'x' 'it''s 2>' /tmp/y", {("/tmp/y", "read")}, ["its 2>"]),
    ("tail -n 1 rel", set(), ["rel"]),
    ("grep - /etc/passwd /tmp/allowed", {("/etc/passwd", "read"), ("/tmp/allowed", "read")}, []),
    ("grep x - /tmp/a", {("/tmp/a", "read")}, []),
    (r"cat /tmp/private\&2>/dev/null", {("/tmp/private&2", "read")}, []),
    (r"cat /tmp/a\ 2>/dev/null", {("/tmp/a 2", "read")}, []),
    (r"cat /tmp/b\;3</tmp/in", {("/tmp/b;3", "read"), ("/tmp/in", "read")}, []),
    ("grep --reg=x /etc/passwd /tmp/allowed", {("/etc/passwd", "read"), ("/tmp/allowed", "read")}, []),
    ("grep --rege x /etc/passwd", {("/etc/passwd", "read")}, ["x"]),
    ("true;2>/tmp/private", {("/tmp/private", "write")}, []),
    ("true;>/tmp/private", {("/tmp/private", "write")}, []),
    ("true|2>/tmp/private; cat /tmp/allowed", {("/tmp/private", "write"), ("/tmp/allowed", "read")}, []),
    ("echo x &>>/tmp/log 2>&1", {("/tmp/log", "write")}, []),
    ("cat <>/tmp/dev", {("/tmp/dev", "write")}, []),
])
def test_gate_still_names_real_operands(command, effects, relative):
    # The fix must drop only non-path operands; real files stay scoped or unproven.
    scoped, unproven = scope(command)
    assert scoped == effects
    assert [r.split("'")[1] for r in unproven if r.startswith("relative path")] == relative
