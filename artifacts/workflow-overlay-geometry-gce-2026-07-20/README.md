# Workflow overlay drag and resize evidence

Deterministic validation performed on 2026-07-20 using the disposable GCE VM
`llmsuper-workflow-geometry-0720` (`e2-micro`, Spot, `us-central1-a`). No model
or token-consuming calls were made.

- Focused workspace UI suite: 11 tests passed.
- Full suite: 180 tests passed.
- Browser acceptance used real pointer drags through Chrome DevTools.
- The overlay moved from `(103, 16)` to `(198, 8)` and remained inside its viewport.
- The overlay resized from `986 x 670` to `320 x 220`, reflowing from four columns to one.
- The saved position and size survived an overlay re-render exactly.
- Browser console: no warnings or errors.
- Browser network: only the workspace document and bootstrap request, both HTTP 200.

The VM and its boot disk were deleted after evidence collection.
