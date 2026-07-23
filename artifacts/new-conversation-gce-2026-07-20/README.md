# New conversation workflow evidence

Validated on 2026-07-20 using the disposable GCE VM
`llmsuper-new-chat-0720` (`e2-micro`, Spot, `us-central1-a`).

- Layered focused suites: 33 tests passed.
- Full regression suite: 185 tests passed.
- Clicking `Chat +` created and selected a second conversation immediately.
- The rich editor received focus without a title dialog.
- Prompt terminal and rich editor modes switched while preserving draft text.
- Inline rename updated both the workspace header and navigation tree.
- Deterministic service tests verified LLM title generation and that a human
  rename wins a concurrent title-generation race.
- Browser console: no warnings or errors.
- All browser requests completed successfully.
- Trace ledger totals during browser acceptance: 0 input tokens, 0 output
  tokens, and $0.00. Browser automation accidentally submitted one draft while
  inserting a newline; the configured providers failed before any tokens were
  consumed, and this also exercised the visible provider-failure state.

The VM and boot disk were deleted after evidence collection.
