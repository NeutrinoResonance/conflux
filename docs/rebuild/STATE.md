# Rebuild state

Keep this short and current. One entry per decision; newest first.

MISSION-STATUS: ACTIVE

- **Goal:** work item A — reproduce the NetBSD / child-model mapping failure from evidence.
- **Current hypothesis:** none yet (do not assume a version-parser bug).
- **Evidence:** `~/evidence/optee-ctl-runs/run12/` (paused at goal (b), NetBSD driver), earlier aborted runs.
- **Decision:** —
- **Known contract violation (2026-10-27, PR #1):** `conflux/verifier.py` `_parse_point` still accepts
  digit scores (`<score>7</score>`); pinned by strict xfail in `tests/test_letter_scale_contract.py`.
- **Next action:** read run 12 transcript/senate log around the NetBSD step; locate the first incorrect
  transformation or missing context boundary; write a failing acceptance test.
