# Unified bottom composer evidence

Validated on 2026-07-20 using disposable GCE Spot VM
`llmsuper-unified-composer-0720` (`e2-micro`, `us-central1-a`).

- Focused workspace stack: 29 tests passed.
- Full regression suite: 187 tests passed.
- The rich editor and raw prompt terminal render inside one persistent bottom
  composer; no second central input surface remains.
- A draft survived switching from the prompt terminal back to the rich editor.
- The measured WezTerm-style block cursor remained inside the bottom terminal.
- New, empty conversations show one welcome treatment and the composer says
  that the message “starts this conversation.”
- Simulated offline mode surfaced an actionable stopped/expired-server message
  instead of the browser's opaque “Failed to fetch.”
- A clean reload had no console warnings/errors and only two successful GETs.
- No prompt was submitted: 0 input tokens, 0 output tokens, and $0.00.

The disposable firewall rule, VM, and boot disk were deleted after evidence
collection.
