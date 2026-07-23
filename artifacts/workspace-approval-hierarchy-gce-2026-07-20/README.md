# Workspace approval and hierarchy acceptance evidence

- Date: 2026-07-20
- VM: `llmsuper-ui-fix-0720`
- Project / zone: `project96-sar` / `us-central1-a`
- Machine: `e2-micro`, Spot provisioning, 10 GB `pd-standard` auto-delete boot disk
- Boundary: all Python tests, fixture execution, and application serving ran on the GCE VM; the local process was only an explicit SSH transport/tunnel.
- Focused tests: 25 passed.
- Final full suite: 177 passed.
- Browser acceptance: nested endeavor/conversation navigation, unassigned-history import, inline held-action focus, exact proposal display, operator denial, automatic continuation, and cross-conversation selection reset exercised through Chrome DevTools MCP.
- Browser diagnostics: zero console warnings/errors/issues; workspace document and bootstrap requests returned HTTP 200.
- Cleanup: VM and boot disk are deleted after the evidence files are copied back and absence is verified.

`llmsuper-final-tests.log` contains the complete final test run. The PNGs
capture the release-sized hierarchy and inline approval surfaces.
