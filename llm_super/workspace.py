"""Execution service for the editable conversation workspace."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from . import flow_match
from .conversation_graph import ConversationGraphStore
from .flow_match import DEFAULT_FLOW_ID
from .orchestrator import Orchestrator, TurnOptions


class WorkspaceService:
    """Binds durable graph edits to supervised, cancellable execution.

    Agent-selected code execution remains inside the orchestrator's configured
    execution backend.  This service only schedules control-plane coroutine
    work and never exposes a local process-spawn primitive.
    """

    def __init__(self, store: ConversationGraphStore, orchestrator: Orchestrator,
                 library: Any, trace: Any):
        self.store = store
        self.orchestrator = orchestrator
        self.library = library
        self.trace = trace
        self._conversation_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._tasks_by_node: dict[str, asyncio.Task] = {}
        self._tasks_by_job: dict[str, asyncio.Task] = {}

    _UNTITLED = {"New conversation", "Untitled conversation"}
    _UNTITLED_ENDEAVORS = {"Untitled endeavor", "My first endeavor"}

    async def _maybe_generate_title(
        self, session: str, user_text: str, assistant_text: str
    ) -> None:
        """Name the first completed chat, unless the human already named it."""
        conversation = self.store.conversation(session)
        if conversation["title"] not in self._UNTITLED:
            endeavor_id = conversation["endeavor_id"]
            if self.store.endeavor(endeavor_id)["title"] in self._UNTITLED_ENDEAVORS:
                self.store.rename_endeavor(endeavor_id, conversation["title"])
            setter = getattr(self.library, "set_session_title", None)
            if callable(setter):
                setter(session, conversation["title"])
            return
        generator = getattr(self.orchestrator, "generate_conversation_title", None)
        if not callable(generator) or not assistant_text.strip():
            return
        try:
            title = str(await generator(session, user_text, assistant_text)).strip()
        except Exception:
            # A metadata call must never turn a completed answer into a failure.
            return
        if not title:
            return
        # Re-read after the model call so a human rename always wins the race.
        if self.store.conversation(session)["title"] not in self._UNTITLED:
            return
        renamed = self.store.rename_conversation(session, title)
        endeavor_id = conversation["endeavor_id"]
        endeavor = self.store.endeavor(endeavor_id)
        if endeavor["title"] in self._UNTITLED_ENDEAVORS:
            # Re-read immediately before writing so a human rename that lands
            # during title generation always wins the race.
            if self.store.endeavor(endeavor_id)["title"] in self._UNTITLED_ENDEAVORS:
                self.store.rename_endeavor(endeavor_id, title)
        setter = getattr(self.library, "set_session_title", None)
        if callable(setter):
            setter(session, renamed["title"])

    def _track(self, node_id: str, job_id: str, task: asyncio.Task) -> None:
        self._tasks_by_node[node_id] = task
        self._tasks_by_job[job_id] = task

        def done(_: asyncio.Task) -> None:
            if self._tasks_by_node.get(node_id) is task:
                self._tasks_by_node.pop(node_id, None)
            if self._tasks_by_job.get(job_id) is task:
                self._tasks_by_job.pop(job_id, None)

        task.add_done_callback(done)

    def _declared_flows(self) -> list[dict[str, Any]]:
        return [
            {"id": flow.id, "label": flow.label, "description": flow.description}
            for flow in self.store.registry.flows.values()
        ]

    def send(self, session: str, content: str, *, parent_id: str | None = None,
             flow_id: str = "auto") -> dict[str, Any]:
        """Queue a message pair, resolving which graph runs it.

        ``auto`` picks the deterministic heuristic match immediately (so the
        instance the UI shows is real) and defers the model-based refinement
        to execution start; ``synthesize`` runs on the default flow's shape
        until the synthesized graph replaces it at execution start; an
        explicit flow id is final.
        """
        requested = str(flow_id or "auto").strip() or "auto"
        if requested == "synthesize":
            base_flow = DEFAULT_FLOW_ID
            decision: dict[str, Any] = {
                "mode": "synthesize", "status": "pending_synthesis",
                "flow_id": base_flow,
                "reason": "a bespoke graph will be synthesized from this prompt",
            }
        elif requested == "auto":
            match = flow_match.heuristic_match(content, self._declared_flows())
            base_flow = match["flow_id"]
            decision = {"mode": "auto", "status": "pending_model_match", **match}
        else:
            base_flow = requested
            decision = {
                "mode": "manual", "status": "final", "flow_id": requested,
                "method": "manual", "reason": "flow selected in the composer",
            }
        pair = self.store.create_message_pair(
            session, content, parent_id=parent_id, flow_id=base_flow,
            flow_decision=decision,
        )
        assistant = pair["assistant"]
        job = self.store.create_job(session, assistant["node_id"], "message")
        task = asyncio.create_task(self._run_assistant(assistant["node_id"], job["job_id"]))
        self._track(assistant["node_id"], job["job_id"], task)
        return {"pair": pair, "job": job}

    def pause(self, node_id: str) -> dict[str, Any]:
        node = self.store.node(node_id)
        if node["role"] != "assistant":
            raise ValueError("only assistant message execution can be paused")
        task = self._tasks_by_node.get(node_id)
        if task and not task.done():
            task.cancel()
        self.store.set_node_status(node_id, "paused")
        if node.get("workflow_instance_id"):
            self.store.set_workflow_runtime(
                node["workflow_instance_id"], status="paused",
                active_node=self.store.workflow(node["workflow_instance_id"])["active_node"],
            )
        for job in self.store.jobs(session=node["session"]):
            if job["root_node_id"] == node_id and job["status"] in {"queued", "running"}:
                self.store.update_job(job["job_id"], status="paused")
        return self.store.node(node_id)

    def resume(self, node_id: str) -> dict[str, Any]:
        node = self.store.node(node_id)
        if node["role"] != "assistant":
            raise ValueError("only assistant message execution can be resumed")
        current = self._tasks_by_node.get(node_id)
        if current and not current.done():
            return {"node": node, "job": None, "already_running": True}
        self.store.set_node_status(node_id, "queued")
        job = self.store.create_job(node["session"], node_id, "resume")
        task = asyncio.create_task(self._run_assistant(node_id, job["job_id"]))
        self._track(node_id, job["job_id"], task)
        return {"node": self.store.node(node_id), "job": job, "already_running": False}

    def edit_node(self, node_id: str, patch: Mapping[str, Any], *,
                  auto_recalculate: bool = True) -> dict[str, Any]:
        if patch and set(patch).issubset({"position_x", "position_y"}):
            before = self.store.node(node_id)
            self.store.set_position(
                node_id, patch.get("position_x", before["position_x"]),
                patch.get("position_y", before["position_y"]),
            )
            return {"node": self.store.node(node_id), "job": None}
        before = self.store.node(node_id)
        edited = self.store.update_node(node_id, patch)
        if before["role"] == "assistant" and "input_text" in patch:
            edited = self.store.set_node_status(node_id, "stale")
            edited["invalidated_node_ids"] = self.store.descendants(node_id)
        stale = list(edited.get("invalidated_node_ids") or [])
        should_run_self = edited["role"] == "assistant" and edited["status"] == "stale"
        if not auto_recalculate or (not stale and not should_run_self):
            return {"node": edited, "job": None}
        job = self.store.create_job(edited["session"], node_id, "recalculate")
        task = asyncio.create_task(
            self._recalculate(node_id, job["job_id"], include_root=should_run_self)
        )
        self._track(node_id, job["job_id"], task)
        return {"node": edited, "job": job}

    def recalculate(self, node_id: str, *, include_root: bool = False) -> dict[str, Any]:
        node = self.store.node(node_id)
        job = self.store.create_job(node["session"], node_id, "recalculate")
        task = asyncio.create_task(
            self._recalculate(node_id, job["job_id"], include_root=include_root)
        )
        self._track(node_id, job["job_id"], task)
        return job

    async def _recalculate(self, root_node_id: str, job_id: str, *,
                           include_root: bool) -> None:
        root = self.store.node(root_node_id)
        candidates = ([root_node_id] if include_root else []) + self.store.descendants(root_node_id)
        nodes = [self.store.node(node_id) for node_id in candidates]
        nodes.sort(key=lambda item: (item["ordinal"], item["node_id"]))
        self.store.update_job(
            job_id, status="running",
            progress={"completed": 0, "total": len(nodes), "current_node_id": None},
        )
        try:
            async with self._conversation_locks[root["session"]]:
                completed = 0
                for node in nodes:
                    self.store.update_job(
                        job_id,
                        progress={"completed": completed, "total": len(nodes),
                                  "current_node_id": node["node_id"]},
                    )
                    if node["role"] == "assistant":
                        outcome = await self._execute_assistant(node["node_id"], job_id=None)
                        if outcome in {"awaiting_input", "awaiting_approval"}:
                            self.store.update_job(
                                job_id, status=outcome,
                                progress={"completed": completed, "total": len(nodes),
                                          "current_node_id": node["node_id"]},
                            )
                            return
                        if outcome in {"failed", "needs_attention"}:
                            failed = self.store.node(node["node_id"])
                            self.store.update_job(
                                job_id, status=outcome,
                                error=str((failed.get("config") or {}).get("escalated") or ""),
                                progress={"completed": completed, "total": len(nodes),
                                          "current_node_id": node["node_id"]},
                            )
                            return
                    elif node["status"] == "stale":
                        self.store.set_node_status(node["node_id"], "complete")
                    completed += 1
                self.store.update_job(
                    job_id, status="complete",
                    progress={"completed": completed, "total": len(nodes),
                              "current_node_id": None},
                )
        except asyncio.CancelledError:
            self.store.update_job(job_id, status="paused")
            raise
        except Exception as exc:
            self.store.update_job(job_id, status="failed", error=str(exc))

    async def _run_assistant(self, node_id: str, job_id: str) -> None:
        node = self.store.node(node_id)
        self.store.update_job(
            job_id, status="running",
            progress={"completed": 0, "total": 1, "current_node_id": node_id},
        )
        try:
            async with self._conversation_locks[node["session"]]:
                outcome = await self._execute_assistant(node_id, job_id=job_id)
            if outcome in {"awaiting_input", "awaiting_approval"}:
                self.store.update_job(
                    job_id, status=outcome,
                    progress={"completed": 0, "total": 1, "current_node_id": node_id},
                )
            elif outcome in {"failed", "needs_attention"}:
                failed = self.store.node(node_id)
                self.store.update_job(
                    job_id, status=outcome,
                    error=str((failed.get("config") or {}).get("escalated") or ""),
                    progress={"completed": 0, "total": 1, "current_node_id": node_id},
                )
            else:
                self.store.update_job(
                    job_id, status="complete",
                    progress={"completed": 1, "total": 1, "current_node_id": None},
                )
        except asyncio.CancelledError:
            self.store.set_node_status(node_id, "paused")
            self.store.update_job(job_id, status="paused")
            raise
        except Exception as exc:
            self.store.set_node_status(node_id, "failed")
            self.store.update_job(job_id, status="failed", error=str(exc))

    def _event_node(self, workflow: dict[str, Any], plan: dict[str, Any],
                    kind: str, data: Mapping[str, Any]) -> str | None:
        nodes = workflow["graph"].get("nodes", [])
        def first(*types: str) -> str | None:
            return next((node["id"] for node in nodes if node.get("type") in types), None)
        if kind.startswith("ensemble_") or data.get("ensemble"):
            return plan.get("ensemble_node_id") or first("ensemble", "agent")
        if kind in {"execute", "executor_fallback", "synthesis"}:
            return first("agent")
        if kind in {"verify", "verify_error", "ensemble_fusion_rejected"}:
            return first("verifier", "checker")
        if kind in {"fm_event", "contract", "contract_failed", "contract_skipped", "plan"}:
            return first("ingress", "policy")
        if kind == "turn_end":
            return first("terminal")
        return None

    def _pending_actions(self, session: str, task_id: str) -> list[dict[str, Any]]:
        """Find approvals created by this exact workspace turn.

        The action store is the authority.  We intentionally do not infer an
        approval pause from response prose: a model or provider can emit the
        same words, but only a durable ``human_pending`` record can stop and
        later release execution.
        """
        action_store = getattr(self.orchestrator, "action_store", None)
        if action_store is None:
            return []
        return [
            item for item in action_store.list(status="human_pending", limit=100)
            if str(item.get("session") or "") == session
            and str(item.get("task") or "") == task_id
        ]

    async def _resolve_flow_decision(self, node: dict[str, Any]) -> None:
        """Finish a deferred send-time flow choice before the first model call.

        The pre-send preview is a prediction; this is the decision.  Every
        failure degrades to the graph the message already carries — routing
        and synthesis must never fail a turn on their own.
        """
        decision = dict((node.get("config") or {}).get("flow_decision") or {})
        status = decision.get("status")
        if status not in {"pending_synthesis", "pending_model_match"}:
            return
        instance_id = node.get("workflow_instance_id")
        if not instance_id:
            return
        task_text = str(node.get("input_text") or "")
        if status == "pending_synthesis":
            synthesizer = getattr(self.orchestrator, "synthesize_workspace_flow", None)
            if not callable(synthesizer):
                decision.update(status="final", method="synthesis_unavailable")
            else:
                try:
                    graph = await synthesizer(task_text)
                    applied = self.store.apply_synthesized_workflow(instance_id, graph)
                    decision.update(
                        status="final", method="synthesized",
                        flow_id=applied["flow_id"],
                        reason="graph synthesized from this prompt",
                    )
                except Exception as exc:
                    decision.update(
                        status="final", method="synthesis_failed",
                        error=str(exc)[:500],
                        reason="synthesis failed; the declared default flow ran instead",
                    )
        else:
            selector = getattr(self.orchestrator, "select_workspace_flow", None)
            if not callable(selector):
                decision.update(status="final", method=decision.get("method") or "heuristic")
            else:
                try:
                    choice = dict(await selector(task_text) or {})
                    flow_id = str(choice.get("flow_id") or "")
                    if flow_id and flow_id in self.store.registry.flows:
                        self.store.retarget_workflow(instance_id, flow_id)
                        decision.update(
                            status="final", flow_id=flow_id,
                            method=str(choice.get("method") or "model"),
                            reason=str(choice.get("reason") or ""),
                        )
                    else:
                        decision.update(status="final",
                                        method=decision.get("method") or "heuristic")
                except Exception as exc:
                    decision.update(
                        status="final",
                        method=decision.get("method") or "heuristic",
                        error=str(exc)[:500],
                    )
        self.store.set_node_status(
            node["node_id"], node["status"],
            config_patch={"flow_decision": decision},
        )

    async def synthesize_instance(self, instance_id: str,
                                  prompt: str = "") -> dict[str, Any]:
        """Explicit command: synthesize a graph and install it on one message."""
        workflow = self.store.workflow(instance_id)
        owner = self.store.node(workflow["owner_node_id"])
        if owner["status"] in {"running", "queued"}:
            raise ValueError("pause the message before replacing its workflow")
        synthesizer = getattr(self.orchestrator, "synthesize_workspace_flow", None)
        if not callable(synthesizer):
            raise ValueError("flow synthesis is not available on this server")
        task_text = str(prompt or "").strip() or str(owner.get("input_text") or "")
        if not task_text.strip():
            raise ValueError("a synthesis prompt is required")
        graph = await synthesizer(task_text)
        applied = self.store.apply_synthesized_workflow(instance_id, graph)
        self.store.set_node_status(
            owner["node_id"], owner["status"],
            config_patch={"flow_decision": {
                "mode": "synthesize", "status": "final", "method": "synthesized",
                "flow_id": applied["flow_id"], "prompt": task_text[:500],
                "reason": "graph synthesized on demand",
            }},
        )
        return applied

    async def _execute_assistant(self, node_id: str, job_id: str | None) -> str:
        node = self.store.node(node_id)
        if node["role"] != "assistant":
            raise ValueError("execution target must be an assistant message")
        instance_id = node.get("workflow_instance_id")
        if not instance_id:
            raise ValueError("assistant message has no workflow instance")
        await self._resolve_flow_decision(node)
        node = self.store.node(node_id)
        workflow = self.store.workflow(instance_id)
        plan = self.store.workflow_plan(instance_id)
        entry = workflow["graph"].get("entry")
        self.store.set_node_status(node_id, "running")
        self.store.set_workflow_runtime(
            instance_id, status="running", active_node=entry, node_status="complete"
        )

        human_node_id = plan.get("human_input_node_id")
        if human_node_id:
            self.store.set_node_status(
                node_id, "awaiting_input",
                config_patch={"awaiting_workflow_node": human_node_id},
            )
            self.store.set_workflow_runtime(
                instance_id, status="awaiting_input",
                active_node=human_node_id, node_status="awaiting_input",
            )
            return "awaiting_input"

        messages = self.store.prompt_messages(node_id)
        if not messages:
            raise ValueError("assistant message has no prompt ancestry")
        task_text = next(
            (str(message.get("content") or "") for message in reversed(messages)
             if message.get("role") == "user"), ""
        )

        # Store reads come from the prompt lineage plus directly wired feeds
        # — a feeds edge never pulls its source's own ancestry along.
        ancestor_ids = list(self.store.lineage_ancestors(node_id))
        for edge in self.store.feeds_sources(node_id):
            if edge["source_id"] not in ancestor_ids:
                ancestor_ids.append(edge["source_id"])
        ancestor_nodes = [self.store.node(value) for value in ancestor_ids]
        graph_store_reads = [
            {
                "id": item["node_id"], "type": "store_read",
                "config": item.get("config") or {},
            }
            for item in ancestor_nodes if item["kind"] == "store_read"
        ]
        workflow_node_ids = {
            item["id"] for item in workflow["graph"].get("nodes", [])
        }

        # Store reads are performed before the model call and included as
        # bounded system context.  The store id and query prompt are operator-
        # visible workflow fields, never inferred connection credentials.
        for read_node in [*graph_store_reads, *plan.get("store_reads", [])]:
            config = dict(read_node.get("config") or {})
            store_id = str(config.get("store_id") or "")
            if not store_id:
                continue
            if read_node["id"] in workflow_node_ids:
                self.store.set_workflow_runtime(
                    instance_id, status="running", active_node=read_node["id"],
                    node_status="running",
                )
            else:
                self.store.set_node_status(read_node["id"], "running")
            records = self.store.query_store(
                store_id, task_text, top_k=int(config.get("top_k", 5)),
                query_prompt=str(config.get("query_prompt") or ""),
            )
            if records:
                rendered = "\n\n".join(
                    f"[memory {index + 1}, relevance {record['score']:.3f}]\n{record['text']}"
                    for index, record in enumerate(records)
                )
                messages.insert(0, {
                    "role": "system",
                    "content": "Workflow-authorized knowledge-store context:\n" + rendered[:20_000],
                })
            if read_node["id"] in workflow_node_ids:
                self.store.set_workflow_runtime(
                    instance_id, status="running", active_node=read_node["id"],
                    node_status="complete",
                )
            else:
                self.store.set_node_status(read_node["id"], "complete")

        ensemble = dict(plan.get("ensemble") or {})
        temperatures = ensemble.get("temperatures") or []
        if isinstance(temperatures, str):
            temperatures = [value.strip() for value in temperatures.split(",") if value.strip()]
        executor_prompt = "\n\n".join(plan.get("executor_prompts") or [])
        executor_node = next(
            (item for item in workflow["graph"].get("nodes", []) if item.get("type") == "agent"),
            {},
        )
        executor_config = dict(executor_node.get("config") or {})
        options = TurnOptions(
            strategy=str(ensemble.get("mode") or ""),
            ensemble_n=int(ensemble.get("candidate_count", 0) or 0),
            candidate_mode=str(ensemble.get("candidate_mode") or "diverse_models"),
            temperatures=tuple(float(value) for value in temperatures),
            cutoff=(float(ensemble["cutoff"]) if ensemble.get("cutoff") not in {None, ""} else None),
            executor_model=str(executor_config.get("model") or ""),
            executor_prompt=executor_prompt,
            verification_requirements=tuple(plan.get("verification_prompts") or []),
        )

        last_active: list[str | None] = [workflow.get("active_node")]
        def on_event(kind: str, data: dict[str, Any]) -> None:
            target = self._event_node(workflow, plan, kind, data)
            if not target or target == last_active[0]:
                return
            if last_active[0]:
                self.store.set_workflow_runtime(
                    instance_id, status="running", active_node=last_active[0],
                    node_status="complete",
                )
            self.store.set_workflow_runtime(
                instance_id, status="running", active_node=target,
                node_status="running",
            )
            last_active[0] = target

        report = await self.orchestrator.run_turn(
            node["session"], messages, options=options, event_hook=on_event
        )
        if last_active[0]:
            self.store.set_workflow_runtime(
                instance_id, status="running", active_node=last_active[0],
                node_status="complete",
            )
        pending_actions = self._pending_actions(node["session"], report.task_id)
        awaiting_approval = bool(pending_actions)
        escalated = bool(report.escalated)
        terminal_ids = {"blocked", "job_blocked"} if escalated else {"completed", "job_complete"}
        terminal = next(
            (item["id"] for item in workflow["graph"].get("nodes", [])
             if item.get("type") == "terminal" and item["id"] in terminal_ids),
            next((item["id"] for item in workflow["graph"].get("nodes", [])
                  if item.get("type") == "terminal"), None),
        )
        human_approval = next(
            (item["id"] for item in workflow["graph"].get("nodes", [])
             if item.get("type") == "approval"),
            None,
        )
        outcome = (
            "awaiting_approval" if awaiting_approval
            else "failed" if escalated and not report.text.strip()
            else "needs_attention" if escalated
            else "complete"
        )
        rendered_output = (
            "Operator approval is required. Review the exact proposed action "
            "below. Approving or blocking it will continue this message "
            "automatically."
            if awaiting_approval else report.text
        )
        if outcome == "failed":
            rendered_output = (
                "Execution stopped before a response was produced.\n\n"
                f"Reason: {report.escalated}"
            )
        self.store.set_workflow_runtime(
            instance_id, status=outcome,
            active_node=human_approval if awaiting_approval else terminal,
            node_status=("awaiting_approval" if awaiting_approval
                         else "complete" if terminal else None),
        )
        self.store.set_node_status(
            node_id, outcome, output_text=rendered_output, run_id=report.task_id,
            config_patch={
                "task_id": report.task_id, "executor": report.executor,
                "score": report.verify.score if report.verify else None,
                "cost_usd": report.cost_usd, "attempts": report.attempts,
                "escalated": report.escalated,
                "pending_action_ids": [
                    str(item.get("action_id") or "") for item in pending_actions
                ],
            },
        )
        self.library.touch_session(node["session"], task_text)
        if not awaiting_approval:
            await self._maybe_generate_title(
                node["session"], task_text, report.text
            )

        # A held proposal is not output evidence and must never be written to
        # an attached knowledge store.  The approved retry will perform any
        # configured write after it reaches a real terminal result.
        if awaiting_approval:
            return outcome

        direct_targets = {
            edge["target_id"] for edge in self.store.edges(node["session"])
            if edge["source_id"] == node_id
        }
        graph_store_writes = [
            {
                "id": item["node_id"], "type": "store_write",
                "config": item.get("config") or {},
            }
            for item in self.store.nodes(node["session"])
            if item["node_id"] in direct_targets and item["kind"] == "store_write"
        ]
        for write_node in [*plan.get("store_writes", []), *graph_store_writes]:
            config = dict(write_node.get("config") or {})
            store_id = str(config.get("store_id") or "")
            if not store_id:
                continue
            if write_node["id"] in workflow_node_ids:
                self.store.set_workflow_runtime(
                    instance_id, status="running", active_node=write_node["id"],
                    node_status="running",
                )
            else:
                self.store.set_node_status(write_node["id"], "running")
            self.store.save_record(
                store_id, report.text, source_node_id=node_id,
                metadata={
                    "session": node["session"], "task_id": report.task_id,
                    "save_prompt": str(config.get("save_prompt") or ""),
                },
            )
            if write_node["id"] not in workflow_node_ids:
                self.store.set_node_status(write_node["id"], "complete")
            self.store.set_workflow_runtime(
                instance_id, status="complete", active_node=terminal,
                node_status="complete" if terminal else None,
            )
        return outcome
