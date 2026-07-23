# Workflow overlay GCE validation

Deterministic UI validation run on a disposable GCE `e2-micro` Spot VM.

- Focused workspace UI contract tests: 10 passed.
- Full test suite: 179 passed.
- Browser fixture: stored workspace records only; no model calls, tool execution, or approvals.
- Browser checks: full 14-card text rendering, source-list hiding, pinning, multi-overlay stacking and switching, explicit close, and animated unpinned collapse.

The VM and its boot disk were deleted after the evidence below was saved.
