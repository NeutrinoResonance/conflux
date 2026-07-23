# Assistant workflow-run UI — GCE acceptance

Validated on 2026-07-20 using the ephemeral VM
`llmsuper-workflow-run-ui-0720` in `us-central1-a`.

## Isolated execution boundary

- Machine: `e2-micro`
- Provisioning: Spot / preemptible
- Boot disk: 10 GB
- Browser port: `31849`, firewall-scoped to the operator's single `/32`
- Application code and all test commands ran on this GCE VM. The workstation was
  used only for source editing, GCE orchestration, browser control, and saving
  evidence.
- The browser fixture records two synthetic model exchanges and makes zero live
  provider calls. It does not execute the proposed migration command.

## Results

- Focused workspace suite: 31/31 passed.
- Full suite: 189/189 passed.
- Browser console warnings/errors/issues: 0.
- Browser requests for the page, bootstrap, and lazy workflow-execution detail:
  all HTTP 200.

The fixture demonstrates a 14-stage declared workflow interrupted at human
approval after five observed stages. The compact assistant-message graph reports
the five observed stages and two synthetic LLM calls. Its expanded run uses the
same graph, highlights the observed route, and exposes stage identity,
capabilities, model input/output, call configuration, accounting, and durable
events. Selecting the executor reports `observed` consistently in both the run
inspector and editable workflow-node terminal.

The selected assistant message exposes `assistant.input.md` and
`assistant.output.md` through the same single-source Markdown editor widget as
the conversation composer, including toolbar insertion, live rich preview, and
the terminal block cursor.

## Evidence

- `workflow-run-ui-focused-final.log`
- `workflow-run-ui-full-final.log`
- `workflow-run-ui-fixture.json`
- `workflow-run-ui-server-final.log`
- `workflow-run-ui-browser-acceptance.json`
- `workflow-run-expanded-evidence-final.png`
- `assistant-message-shared-markdown-editor-final.png`

The VM, disk, and temporary firewall rule are deleted after the evidence is
copied back to the repository.
