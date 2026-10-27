"""Acceptance test for the run-12 NetBSD stall (work item A).

Read-only checks that name only absolute files must scope to exactly those
reads. In run 12 the scope gate read grep patterns ('I/TC:'), option values
(`tail -n 1`) and fd numbers (`2>&1`) as relative paths, so correct checks
were rated non-low risk, sent to a soundness checker that failed closed on
HTTP 402, recorded as postcheck_failed, and their identical re-checks held for
a human. Evidence: tests/fixtures/run12_netbsd/manifest.json.

Strict xfail pins the failing baseline; the fix flips it.
"""

import json
import pathlib

import pytest

from conflux.decider import _shell_effects

pytestmark = pytest.mark.xfail(
    strict=True, reason="_shell_effects maps non-path operands to relative paths (run 12)")

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
