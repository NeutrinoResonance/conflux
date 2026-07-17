"""The supervised turn: contract → (plan) → execute → monitor → verify → repair.

Implements the SPEC §4 lifecycle with the durability layer:
- executor fallback chains (a provider outage fails over, models.yaml
  `fallbacks:`), and verifier failover inside Verifier
- task decomposition for intense prompts (planner units, each supervised
  independently, then synthesized)
- the anti-loop rule (max_repairs, then escalate to the user) and shared
  per-task budget gates across all units
Every step is traced.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import asyncio

from . import contract as contract_mod
from . import planner
from . import sandbox
from .checkpoint import Checkpoints, turn_key
from .config import Config, Model
from .control import ControlState
from .monitors import FMEvent, run_monitors
from .providers import ChatResult, Client, ProviderError
from .trace import Trace
from .verifier import Verifier, VerifyReport


@dataclass
class Budget:
    cap: float
    spent: float = 0.0

    def add(self, cost: float) -> None:
        self.spent += cost

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.cap


@dataclass
class UnitResult:
    text: str
    attempts: int
    verify: VerifyReport | None
    fm_events: list[str] = field(default_factory=list)
    escalated: str = ""
    evidence: str = ""         # sandbox transcript of the best attempt


@dataclass
class TurnReport:
    text: str
    task_id: str
    executor: str
    attempts: int
    verify: VerifyReport | None
    fm_events: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    escalated: str = ""
    units: int = 0

    def trailer(self) -> str:
        if self.verify is None and not self.escalated:
            return ""
        lines = ["", "---"]
        if self.verify is not None:
            plan_note = f" units={self.units}" if self.units else ""
            lines.append(
                f"[llm-super] executor={self.executor} attempts={self.attempts}"
                f"{plan_note} verifier={self.verify.verifier} "
                f"score={self.verify.score:.2f} cost=${self.cost_usd:.4f}"
            )
        if self.fm_events:
            lines.append(f"[llm-super] failure modes detected: {', '.join(self.fm_events)}")
        if self.escalated:
            lines.append(f"[llm-super] NEEDS YOUR INPUT: {self.escalated}")
        return "\n".join(lines)


class Orchestrator:
    UNIT_CONCURRENCY = 3   # parallel units per wave (provider-rate friendly)

    def __init__(self, cfg: Config, client: Client, trace: Trace, control: ControlState,
                 checkpoints: Checkpoints | None = None):
        self.cfg = cfg
        self.client = client
        self.trace = trace
        self.control = control
        self.verifier = Verifier(client, cfg)
        self.checkpoints = checkpoints or Checkpoints(":memory:")

    # ---------- durable executor call (fallback chain) ----------

    async def _execute(self, chain: list[Model], messages: list[dict],
                       log, attempt: int) -> tuple[ChatResult, Model] | None:
        last: ProviderError | None = None
        for i, model in enumerate(chain):
            try:
                res = await self.client.chat(model, messages, max_tokens=8192)
                if i:
                    log("executor_fallback", model=model.name, from_model=chain[0].name)
                return res, model
            except ProviderError as e:
                log("executor_error", model=model.name, error=str(e)[:300], attempt=attempt)
                last = e
        return None

    # ---------- one supervised unit of work ----------

    async def _supervised_unit(
        self,
        session: str,
        task_id: str,
        messages: list[dict],
        task_text: str,
        constraints: list[str],
        budget: Budget,
        log,
    ) -> UnitResult:
        sup = self.cfg.supervision
        chain = self.cfg.executor_chain(
            self.control.forced_executor or self.cfg.default_executor
        )
        attempts = 0
        fm_seen: list[str] = []
        best_text = ""
        best_evidence = ""
        best_report: VerifyReport | None = None
        feedback = ""
        escalated = ""

        while attempts <= sup.max_repairs:
            if self.control.paused:
                escalated = "supervisor is paused (!resume to continue)"
                break
            if budget.exhausted:
                escalated = f"budget exhausted (${budget.spent:.3f} of ${budget.cap:.2f})"
                log("budget_stop", spent=budget.spent, budget=budget.cap)
                break

            attempts += 1
            msgs = list(messages)
            if feedback:
                msgs.append({
                    "role": "user",
                    "content": (
                        "Your previous answer was reviewed and found insufficient. "
                        f"{feedback}\nProduce a corrected, complete answer."
                    ),
                })

            executed = await self._execute(chain, msgs, log, attempts)
            if executed is None:
                escalated = "all executors failed (provider outage?)"
                break
            res, executor = executed
            budget.add(res.cost_usd)
            log("execute", model=executor.name, cost_usd=res.cost_usd,
                tokens_in=res.tokens_in, tokens_out=res.tokens_out, attempt=attempts)

            # heuristic monitors
            events = run_monitors(res.text, task_text)
            for ev in events:
                fm_seen.append(ev.fm_id)
                log("fm_event", model=executor.name, fm_id=ev.fm_id,
                    confidence=ev.confidence, evidence=ev.evidence)

            # execution power: run produced code; transcript = verifier evidence
            evidence = None
            backend = self.control.sandbox_backend or self.cfg.execution.backend
            code = sandbox.extract_python(res.text)
            if code and backend != "off":
                exec_res = await sandbox.run(
                    code, backend,
                    **({"zone": self.cfg.execution.gcloud_zone,
                        "machine_type": self.cfg.execution.gcloud_machine_type}
                       if backend == "gcloud" else {}),
                )
                log("execute_code", backend=exec_res.backend, ok=exec_res.ok,
                    exit_code=exec_res.exit_code, duration_s=round(exec_res.duration_s, 1),
                    stderr=exec_res.stderr[:400])
                if exec_res.ran:
                    evidence = exec_res.transcript()
                    if not exec_res.ok:
                        fm_seen.append("FM-X.3")
                        events.append(FMEvent(
                            "FM-X.3", 0.9, exec_res.stderr[:120],
                            "The code was executed and FAILED. Fix it so it runs "
                            f"cleanly. Execution output:\n{exec_res.transcript(800)}",
                        ))

            # independent cross-family verification (fails over internally;
            # total failure must not kill the turn — that's our own FM-3.2)
            try:
                report = await self.verifier.verify(
                    task=task_text, output=res.text,
                    contract=constraints, executor_family=executor.family,
                    evidence=evidence,
                )
            except Exception as e:
                log("verify_error", error=str(e)[:300])
                if best_report is None:
                    best_text = res.text
                escalated = "verification unavailable (provider errors); response is UNVERIFIED"
                break
            budget.add(report.cost_usd)
            log("verify", model=report.verifier, cost_usd=report.cost_usd,
                score=report.score, passed=report.passed,
                criteria={c.criterion: round(c.expected, 2) for c in report.criteria},
                continuous=all(c.continuous for c in report.criteria))

            if best_report is None or report.score > best_report.score:
                best_text, best_report = res.text, report
                best_evidence = evidence or ""

            if report.passed and not events:
                break

            parts = [ev.feedback for ev in events]
            if not report.passed:
                parts.append(report.feedback)
            feedback = " ".join(p for p in parts if p)

        if attempts > sup.max_repairs and best_report and not best_report.passed:
            escalated = (
                f"{attempts} attempts did not reach the quality bar "
                f"(best score {best_report.score:.2f}); returning best attempt"
            )

        return UnitResult(
            text=best_text, attempts=attempts, verify=best_report,
            fm_events=sorted(set(fm_seen)), escalated=escalated,
            evidence=best_evidence,
        )

    # ---------- full turn ----------

    async def run_turn(self, session: str, messages: list[dict]) -> TurnReport:
        task_id = uuid.uuid4().hex[:8]
        sup = self.cfg.supervision
        budget = Budget(cap=self.control.budget_usd or sup.budget_usd_per_task)
        task_text = _last_user_text(messages)
        executor_name = self.control.forced_executor or self.cfg.default_executor

        def log(kind: str, **kw):
            self.trace.record(session, task_id, kind, **kw)

        log("turn_start", model=executor_name, prompt_chars=len(task_text))

        # 1. Contract extraction (user-toggleable: !checklist on|off|skip)
        constraints: list[str] = []
        if self.control.consume_contract_enabled():
            constraints, cres = await contract_mod.extract(self.client, self.cfg, task_text)
            if cres:
                budget.add(cres.cost_usd)
                log("contract", model=self.cfg.utility, cost_usd=cres.cost_usd,
                    tokens_in=cres.tokens_in, tokens_out=cres.tokens_out,
                    constraints=constraints)
            else:
                # non-fatal (turn proceeds without a checklist) but never silent
                log("contract_failed", model=self.cfg.utility)
        else:
            log("contract_skipped")

        # 2. Planning decision (intense prompts → supervised units).
        # Trigger on size OR visible multi-deliverable structure — a short
        # prompt with "three separate deliverables" is still an intense task.
        # A checkpoint from a crashed/stopped identical turn restores the
        # plan and the units already paid for.
        ckpt_key = turn_key(session, task_text)
        units: list[planner.Unit] = []
        completed: dict[int, UnitResult] = {}
        prior_spent = 0.0
        ckpt = self.checkpoints.load(ckpt_key)
        if ckpt:
            units = [planner.Unit(**u) for u in ckpt["units"]]
            for k, v in ckpt.get("completed", {}).items():
                completed[int(k)] = UnitResult(
                    text=v["text"], attempts=v.get("attempts", 0), verify=None,
                    fm_events=v.get("fm_events", []), evidence=v.get("evidence", ""),
                )
            prior_spent = float(ckpt.get("spent", 0.0))
            log("resume", units=len(units), completed=sorted(completed),
                prior_spent=prior_spent)
        else:
            mode = self.control.plan_mode
            structured = _looks_multipart(task_text)
            if mode != "off" and (
                mode == "on"
                or len(task_text) >= sup.plan_threshold_chars
                or structured
            ):
                units, pres = await planner.plan(self.client, self.cfg, task_text)
                if pres:
                    budget.add(pres.cost_usd)
                log("plan", model=self.cfg.utility,
                    units=[u.description for u in units],
                    deps=[u.depends_on for u in units],
                    cost_usd=pres.cost_usd if pres else 0)

        if not units:
            unit = await self._supervised_unit(
                session, task_id, messages, task_text, constraints, budget, log)
            log("turn_end", spent=budget.spent, attempts=unit.attempts,
                score=unit.verify.score if unit.verify else None,
                escalated=unit.escalated)
            return TurnReport(
                text=unit.text, task_id=task_id, executor=executor_name,
                attempts=unit.attempts, verify=unit.verify,
                fm_events=unit.fm_events, cost_usd=budget.spent,
                escalated=unit.escalated,
            )

        # 3. Wave-parallel supervised unit execution. Independent units run
        # concurrently (bounded); dependent units wait for their inputs.
        # Every completed unit is checkpointed immediately.
        self.checkpoints.save(ckpt_key, _ckpt_state(units, completed, budget, prior_spent))
        weak_units: list[str] = []
        all_fm: list[str] = []
        escalated = ""
        sem = asyncio.Semaphore(self.UNIT_CONCURRENCY)

        async def run_unit(i: int) -> None:
            unit = units[i]
            prior = "\n\n".join(
                f"[completed unit {d+1}: {units[d].description}]\n{completed[d].text}"
                for d in unit.depends_on if d in completed
            )
            unit_msgs = list(messages)
            unit_msgs.append({
                "role": "user",
                "content": (
                    f"This large task is being done in units. Complete ONLY this "
                    f"unit now (unit {i+1} of {len(units)}): {unit.description}\n"
                    + (f"\nOutput of units this one depends on:\n{prior[:8000]}"
                       if prior else "")
                ),
            })
            # Verify against the UNIT's scope, not the full-task contract —
            # a module-only unit must not fail for lacking the README that
            # belongs to a later unit.
            unit_task = (
                f"One unit of a larger task. Judge ONLY this unit's scope: "
                f"{unit.description}"
            )
            async with sem:
                r = await self._supervised_unit(
                    session, task_id, unit_msgs, unit_task, [], budget, log)
            log("unit_done", unit=i + 1, attempts=r.attempts,
                score=r.verify.score if r.verify else None, escalated=r.escalated)
            completed[i] = r
            self.checkpoints.save(
                ckpt_key, _ckpt_state(units, completed, budget, prior_spent))

        for wave_no, wave in enumerate(planner.waves(units), 1):
            pending = [i for i in wave if i not in completed]
            if not pending:
                continue
            if self.control.paused or budget.exhausted:
                escalated = (f"stopped before wave {wave_no}: "
                             + ("paused" if self.control.paused else "budget exhausted")
                             + " — resend the same request to resume from checkpoint")
                break
            log("wave_start", wave=wave_no, units=[i + 1 for i in pending])
            await asyncio.gather(*(run_unit(i) for i in pending))
            hard_stops = [
                f"unit {i+1}/{len(units)}: {completed[i].escalated}"
                for i in pending
                if completed[i].escalated
                and ("paused" in completed[i].escalated
                     or "budget" in completed[i].escalated
                     or "executors failed" in completed[i].escalated
                     or "UNVERIFIED" in completed[i].escalated)
            ]
            weak_units += [
                f"unit {i+1}/{len(units)}: {completed[i].escalated}"
                for i in pending if completed[i].escalated
            ]
            if hard_stops:
                escalated = hard_stops[0] + " — resend the same request to resume"
                break

        results = [completed[i] for i in sorted(completed)]
        for r in results:
            all_fm += r.fm_events
        total_attempts = sum(r.attempts for r in results)

        # 4. Synthesis: assemble unit outputs into one coherent, VERIFIED
        # answer. Unit-level sandbox evidence rides along so the synthesizer
        # (and the final verifier) see observed behavior, not just text.
        assembled = "\n\n".join(r.text for r in results if r.text)
        evidence_appendix = "\n\n".join(
            f"[unit {i+1} execution evidence]\n{completed[i].evidence}"
            for i in sorted(completed) if completed[i].evidence
        )
        final_text = assembled
        final_report = None
        if len(results) > 1 and not escalated:
            chain = self.cfg.executor_chain(executor_name)
            synth_prompt = (
                "All units of the task are complete. Assemble them into one "
                "coherent final answer to the ORIGINAL request. Do not drop "
                "content; fix seams and duplication only.\n\n" + assembled[:24000]
                + (f"\n\nSandbox execution evidence for the units (for your "
                   f"reference; do not include verbatim unless asked):\n"
                   f"{evidence_appendix[:6000]}" if evidence_appendix else "")
            )
            synth_msgs = list(messages) + [{"role": "user", "content": synth_prompt}]
            feedback = ""
            for attempt in range(2):  # synthesis + one verified repair
                msgs = synth_msgs if not feedback else synth_msgs + [{
                    "role": "user",
                    "content": ("The assembled answer was reviewed and found "
                                f"insufficient. {feedback}\nProduce a corrected "
                                "complete assembly."),
                }]
                executed = await self._execute(chain, msgs, log, attempt + 1)
                if not executed:
                    break
                res, m = executed
                budget.add(res.cost_usd)
                log("synthesis", model=m.name, cost_usd=res.cost_usd,
                    tokens_in=res.tokens_in, tokens_out=res.tokens_out,
                    attempt=attempt + 1)
                try:
                    report = await self.verifier.verify(
                        task=task_text, output=res.text, contract=constraints,
                        executor_family=m.family,
                        evidence=evidence_appendix or None)
                except Exception as e:
                    log("verify_error", error=str(e)[:300])
                    final_text = res.text
                    break
                budget.add(report.cost_usd)
                log("verify", model=report.verifier, cost_usd=report.cost_usd,
                    score=report.score, passed=report.passed, stage="synthesis")
                if final_report is None or report.score > final_report.score:
                    final_text, final_report = res.text, report
                if report.passed:
                    break
                feedback = report.feedback

        if weak_units and not escalated:
            escalated = "; ".join(weak_units)
        if not escalated:
            self.checkpoints.delete(ckpt_key)
        best = final_report or max(
            (r.verify for r in results if r.verify),
            key=lambda v: v.score, default=None)
        log("turn_end", spent=budget.spent, attempts=total_attempts,
            units=len(results), escalated=escalated, prior_spent=prior_spent)
        return TurnReport(
            text=final_text, task_id=task_id, executor=executor_name,
            attempts=total_attempts, verify=best,
            fm_events=sorted(set(all_fm)), cost_usd=budget.spent + prior_spent,
            escalated=escalated, units=len(results),
        )


def _ckpt_state(units, completed, budget, prior_spent) -> dict:
    return {
        "units": [{"description": u.description, "depends_on": u.depends_on}
                  for u in units],
        "completed": {
            str(i): {"text": r.text, "attempts": r.attempts,
                     "fm_events": r.fm_events, "evidence": r.evidence,
                     "score": r.verify.score if r.verify else None}
            for i, r in completed.items() if not r.escalated and r.text
        },
        "spent": budget.spent + prior_spent,
    }


def _looks_multipart(task: str) -> bool:
    """Cheap structural signal that a task has several separable deliverables."""
    import re

    enumerated = re.findall(r"(?m)^\s*(?:\d+[\.\)]\s|[-*]\s|DELIVERABLE|PART\s+\d)", task)
    return len(enumerated) >= 3


def _last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):  # OpenAI content-parts form
                return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
            return str(c or "")
    return ""
