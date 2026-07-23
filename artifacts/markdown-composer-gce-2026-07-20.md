# Markdown composer and GCE boundary acceptance

Acceptance was performed on the ephemeral GCE instance `llmsuper-markdown-composer-0720` in `us-central1-a`. It used the cheapest intended profile: an `e2-micro` Spot VM with a 10 GB `pd-standard` boot disk. No application code or test suite was executed on the local workstation.

## Automated verification

- Focused workspace/UI suite: 29 passed, 0 failed.
- Full suite: 187 passed, 0 failed.
- Trace totals: 0 input tokens, 0 output tokens, $0 model cost.

## Browser acceptance

- The prompt composer has exactly one editable surface: a Markdown textarea.
- Bold, italic, list, and code controls modify that Markdown source.
- The adjacent live rendering is non-editable and rendered bold and list content from the same source.
- The native caret is hidden while the measured block cursor remains inside the editor.
- The GCE lock opens a read-only execution-boundary inspector for backend, project, account, zone, machine type, provisioning, lifecycle, and configuration source.
- The inspector contains no backend selector or mutable configuration control.
- A clean reload produced no console errors, warnings, or issues.
- The only network requests were `GET /workspace` and `GET /admin/workspace/bootstrap`; both returned HTTP 200.

## Evidence and cleanup

- `markdown-composer-focused.log` and `markdown-composer-full.log` contain the test output.
- `markdown-composer-server.log` contains the browser fixture server requests.
- `markdown-terminal-and-gce-boundary.png` captures the single-source Markdown terminal and its rendered output.
- `gce-execution-boundary-inspector.png` captures the read-only execution-boundary inspector.
- The temporary firewall rule was deleted.
- The Spot VM and its boot disk were deleted after the evidence was copied.
- Follow-up instance, disk, and firewall queries returned no matching resources.
