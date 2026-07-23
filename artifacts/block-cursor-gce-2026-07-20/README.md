# Prompt-terminal block cursor evidence

Validated on 2026-07-20 using the disposable GCE Spot VM
`llmsuper-block-cursor-0720` (`e2-micro`, `us-central1-a`). The VM was
preempted once, restarted with its retained standard boot disk, and then
completed validation.

- Focused workspace UI suite: 14 tests passed.
- Full regression suite: 186 tests passed.
- Chrome measured the rendered block at `7.23 x 18.59` pixels.
- The native textarea caret was transparent.
- The block moved from the start of the line to selection offset 14 and back
  to offset 0 after the Home key.
- The cursor remained within the prompt-terminal text bounds.
- Browser console: no warnings or errors.
- Browser network: only the workspace and bootstrap GETs, both HTTP 200.
- No messages or model requests were submitted.

The VM and boot disk were deleted after evidence collection.
