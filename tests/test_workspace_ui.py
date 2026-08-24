from __future__ import annotations

import unittest

from llm_super import graph_ui, history_ui, ui, workspace_ui


class WorkspaceUIContractTests(unittest.TestCase):
    def test_workspace_is_a_downward_nested_conversation_graph(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn("Downward-growing conversation graph", page)
        self.assertIn("Conversation messages flow downward", page)
        self.assertIn("each assistant message contains its workflow instance", page)
        self.assertIn('class="endeavor-envelope"', page)
        self.assertIn('class="conversation-envelope"', page)
        self.assertIn('class="workflow-shell ${expanded?', page)
        self.assertIn('data-workflow-shell="${esc(workflow.instance_id)}"', page)
        self.assertIn("WORKFLOW RUN · ASSISTANT OUTPUT", page)
        self.assertIn("depth[n.node_id]", page)

    def test_terminal_makes_both_message_fields_editable_and_recalculates(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn('markdownEditorMarkup("nodeInput"', page)
        self.assertIn('"assistant.input.md"', page)
        self.assertIn('markdownEditorMarkup("nodeOutput"', page)
        self.assertIn('"assistant.output.md"', page)
        self.assertIn("body.querySelectorAll(\"[data-markdown-editor]\").forEach(wireMarkdownEditor)", page)
        self.assertIn("Save & recalculate dependents", page)
        self.assertIn("Prior values remain in the revision ledger", page)
        self.assertIn("/recalculate", page)
        self.assertIn('nodeAction(node.node_id,"pause")', page)
        self.assertIn('nodeAction(node.node_id,"resume")', page)

    def test_endeavors_visibly_contain_conversations_in_one_navigation_tree(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn(
            "An endeavor is a larger objective. Its conversations are the indented chat threads beneath it.",
            page,
        )
        self.assertIn('class="conversation-children"', page)
        self.assertIn("data-parent-endeavor", page)
        self.assertIn("Not in an endeavor", page)
        self.assertNotIn('id="conversationList"', page)
        self.assertIn(
            'priorSession!==state.graph?.conversation?.session){state.selected=null',
            page,
        )

    def test_new_chat_uses_one_markdown_terminal_without_a_title_gate(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn('id="conversationWelcome"', page)
        self.assertIn('id="composer"', page)
        self.assertIn('id="messageTerminalInput"', page)
        self.assertIn('id="messagePreview"', page)
        self.assertIn('data-markdown-command="bold"', page)
        self.assertIn('data-markdown-command="italic"', page)
        self.assertIn('data-markdown-command="list"', page)
        self.assertIn('data-markdown-command="code"', page)
        self.assertIn("function applyMarkdown(command,input=", page)
        self.assertIn("input.setRangeText(replacement", page)
        self.assertIn("function renderComposerPreview()", page)
        self.assertNotIn('id="messageRichEditor"', page)
        self.assertNotIn("data-composer-mode", page)
        self.assertIn("Ask, direct, or continue this conversation…", page)
        self.assertIn('"starts this conversation"', page)
        self.assertNotIn("This conversation is empty.", page)
        self.assertNotIn('id="conversationStart"', page)
        self.assertNotIn('id="messageInput"', page)
        self.assertIn("function createConversation()", page)
        self.assertIn('body:"{}"', page)
        self.assertIn('$("#addConversation").onclick=createConversation', page)
        self.assertNotIn("function openConversationModal()", page)
        self.assertIn("An LLM will name this conversation", page)

    def test_new_endeavor_uses_the_same_conversational_workspace_without_a_title_gate(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn("async function createEndeavor()", page)
        self.assertIn("JSON.stringify({create_conversation:true})", page)
        self.assertIn(
            "load({endeavor:e.id,conversation:conversation.session})", page
        )
        self.assertIn("const conversation=e.conversation||await api", page)
        self.assertIn(
            '$("#newEndeavor").addEventListener("click",createEndeavor)', page
        )
        self.assertIn(
            '$("#addEndeavor").addEventListener("click",createEndeavor)', page
        )
        self.assertIn(">Endeavor +</button>", page)
        self.assertNotIn("Goal +", page)
        self.assertNotIn("function openEndeavorModal()", page)
        self.assertIn("New endeavor · first conversation", page)
        self.assertIn("Use the same composer below", page)
        self.assertIn('id="endeavorTitle" title="Rename endeavor"', page)
        self.assertIn("function beginEndeavorRename()", page)
        self.assertIn("async function renameEndeavor()", page)

    def test_network_failure_explains_an_expired_workspace_server(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn("Workspace API is unavailable", page)
        self.assertIn("stopped or expired server", page)
        self.assertIn('$("#syncState").textContent="disconnected"', page)

    def test_conversation_title_is_inline_renameable(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn('id="conversationTitle" title="Rename conversation"', page)
        self.assertIn('id="conversationRenameInput"', page)
        self.assertIn("function beginConversationRename()", page)
        self.assertIn("async function renameConversation()", page)
        self.assertIn('method:"PATCH",body:JSON.stringify({title})', page)
        self.assertIn("Object.assign(conversation,data.conversation", page)

    def test_prompt_terminal_uses_a_measured_block_cursor(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn('id="terminalBlockCursor"', page)
        self.assertIn(".terminal-block-cursor", page)
        self.assertIn("caret-color:transparent", page)
        self.assertIn("function positionTerminalCursor(input)", page)
        self.assertIn("input.selectionStart", page)
        self.assertIn("marker.getBoundingClientRect()", page)
        self.assertIn('input.addEventListener("scroll",()=>positionTerminalCursor(input))', page)

    def test_workflow_instances_are_observed_graphs_with_lazy_full_evidence(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn('id="workflowOverlays"', page)
        self.assertIn('data-expand-workflow="${esc(workflow.instance_id)}"', page)
        self.assertIn("function expandWorkflowOverlay(instance,sourceElement)", page)
        self.assertIn("function renderWorkflowOverlays()", page)
        self.assertIn("function workflowGraphMarkup(workflow,compact=false)", page)
        self.assertIn("Complete workflow run · observed path highlighted", page)
        self.assertIn("same definition and observed path as Agent Graphs", page)
        self.assertIn("observed_transitions", page)
        self.assertIn("function workflowStageDetail(workflow,node,execution)", page)
        self.assertIn("LLM input and output", page)
        self.assertIn("Call configuration and accounting", page)
        self.assertIn('.model-step-grid pre{text-transform:none}', page)
        self.assertIn('observed.has(node.id)?"observed stage":"not observed"', page)
        self.assertIn('observed?"observed":node.runtime_status||"idle"', page)
        self.assertIn("function workflowStageStatus(workflow,node", page)
        self.assertIn("const stageStatus=workflowStageStatus(workflow,node);", page)
        self.assertIn("/execution`", page)
        self.assertNotIn('nodes.map(node=>workflowCard(workflow,node))', page)

    def test_unpinned_workflow_overlays_morph_back_and_pinned_overlays_stack(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn(".workflow-shell.expanded-source{visibility:hidden}", page)
        self.assertIn("function scheduleWorkflowCollapse(instance)", page)
        self.assertIn("function closeWorkflowOverlay(instance)", page)
        self.assertIn('overlay.classList.add("closing")', page)
        self.assertIn("source.left-target.left", page)
        self.assertIn("to.left-from.left", page)
        self.assertIn("function toggleWorkflowPin(instance)", page)
        self.assertIn('aria-pressed="${entry.pinned}"', page)
        self.assertIn("function bringWorkflowOverlayFront(instance)", page)
        self.assertIn('data-switch-workflow="${esc(item.instance_id)}"', page)
        self.assertIn("Workflow instances in this conversation", page)
        self.assertIn('open?" · open":" · open next"', page)
        self.assertIn("expandWorkflowOverlay(instance,workflowSource(instance))", page)
        self.assertIn("parent.output_text||parent.input_text||parent.label", page)
        self.assertIn("if(state.activeWorkflowOverlay)closeWorkflowOverlay", page)

    def test_expanded_workflow_overlays_can_be_dragged_and_resized(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn("function wireWorkflowOverlayGeometry(overlay,entry)", page)
        self.assertIn("function wireWorkflowGraphPan(canvas)", page)
        self.assertIn("data-workflow-drag", page)
        self.assertIn("workflow-move-hint", page)
        self.assertIn('aria-label="Drag workflow overlay"', page)
        self.assertIn("data-workflow-resize", page)
        self.assertIn('aria-label="Resize workflow overlay"', page)
        self.assertIn("drag.setPointerCapture(e.pointerId)", page)
        self.assertIn("resize.setPointerCapture(e.pointerId)", page)
        self.assertIn("entry.position={left,top}", page)
        self.assertIn("entry.size={width,height}", page)
        self.assertIn("entry.interacting", page)
        self.assertIn("entry.collapseHoldUntil=Date.now()+900", page)
        self.assertIn("host.clientWidth-rect.width-8", page)

    def test_compact_workflow_graph_reports_hidden_llm_work(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn("WORKFLOW RUN · ASSISTANT OUTPUT", page)
        self.assertIn("model_step_count", page)
        self.assertIn("LLM calls", page)
        self.assertIn("runtime_event_count", page)
        self.assertIn("trace_event_count", page)

    def test_pending_governed_action_is_decided_and_continued_inline(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn("Operator decision required", page)
        self.assertIn("Approve once & continue", page)
        self.assertIn("Block & continue", page)
        self.assertIn("/admin/workspace/actions/", page)
        self.assertIn("pendingForNode(node)", page)
        self.assertIn("renderApprovalInbox()", page)

    def test_workflow_palette_covers_ensemble_context_human_and_stores(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn("Multi-model ensemble", page)
        self.assertIn("Pause for user input", page)
        self.assertIn("Required prompt context", page)
        self.assertIn("Retrieve from a vector store", page)
        self.assertIn("Save to a vector store", page)
        self.assertIn("Apply this workflow edit globally", page)
        self.assertIn('"candidate_mode":"diverse_models"', page)
        self.assertIn('"temperatures":[0.2,0.7,1.0]', page)

    def test_workspace_never_exposes_an_execution_backend_selector(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn("agent cannot retarget", page)
        self.assertIn('id="backendLockButton"', page)
        self.assertIn('id="executionModal"', page)
        self.assertIn("operator-owned security boundary", page)
        self.assertIn("read-only validation probe", page)
        self.assertIn("controller restart", page)
        self.assertNotIn('value="docker"', page)
        self.assertNotIn('value="local"', page)
        self.assertNotIn("spawn_local", page)

    def test_nodes_are_draggable_without_recalculating_conversation_content(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn("function wireNodeDrag()", page)
        self.assertIn("position_x:x,position_y:y,auto_recalculate:false", page)
        self.assertIn("(e.clientX-drag.startX)/state.zoom", page)
        self.assertNotIn("active?1000:5000", page)
        self.assertIn("function focusNode(id)", page)
        self.assertIn('classList.toggle("console-empty",!state.selected)', page)
        self.assertIn(".console-subtitle{display:none}", page)
        self.assertIn(".console-actions .quiet-btn{display:inline-flex", page)

    def test_all_existing_primary_surfaces_link_to_workspace(self) -> None:
        for page in (ui.PAGE, history_ui.PAGE, graph_ui.PAGE):
            self.assertIn('href="/workspace">Workspace</a>', page)


    def test_thread_view_is_the_default_with_graph_as_a_toggle(self) -> None:
        page = workspace_ui.PAGE
        self.assertIn('id="transcript"', page)
        self.assertIn('id="viewThread"', page)
        self.assertIn('id="viewGraph"', page)
        self.assertIn('id="viewport" hidden', page)
        self.assertIn(',view:"thread",threadTraceOpen:{}', page)
        self.assertIn("function renderTranscript()", page)
        self.assertIn("function transmissionMarkup(", page)
        self.assertIn("function threadTraceMarkup(", page)
        self.assertIn("data-thread-node", page)
        self.assertIn("data-thread-workflow-node", page)
        self.assertIn("OPERATOR", page)
        self.assertIn("LLM—SUPER", page)
        # thread transcript renders full markdown, not the truncated preview
        self.assertIn("copyText?rich(copyText)", page)
        # live updates re-render the transcript alongside the graph
        self.assertIn("renderGraph();wireNodeDrag();renderTranscript();", page)
        # the trace is an execution trace: observed stages, inline recorded IO
        self.assertIn("Execution trace ·", page)
        self.assertIn("function threadStageDetail(", page)
        self.assertIn("Input — what this stage received", page)
        self.assertIn("Output — what it produced", page)
        self.assertIn("data-thread-trace-idle", page)
        self.assertIn("data-trace-open-run", page)
        self.assertIn('if(status==="idle"&&!showIdle)return"";', page)
        self.assertIn("if(open)loadWorkflowExecution(instance);", page)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
