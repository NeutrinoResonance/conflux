"""The supervised turn: contract → execute → monitor → verify → repair loop.

Implements the SPEC §4 lifecycle for a single conversational turn, with the
anti-loop rule (max_repairs, then escalate to the user) and per-task budget
gates. Every step is traced.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from . import contract as contract_mod
from . import sandbox
from .config import Config
from .control import ControlState
from .monitors import FMEvent, run_monitors
from .providers import Client, ProviderError
from .trace import Trace
from .verifier import Verifier, VerifyReport


@dataclass
class TurnReport:
    text: str
    task_id: str
    executor: str
    attempts: int
    verify: VerifyReport | None
    fm_events: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    escalated: str = ""        # non-empty → we're asking the user to intervene

    def trailer(self) -> str:
        if self.verify is None:
            return ""
        lines = [
            "",
            "---",
            f"[llm-super] executor={self.executor} attempts={self.attempts} "
            f"verifier={self.verify.verifier} score={self.verify.score:.2f} "
            f"cost=${self.cost_usd:.4f}",
        ]
        if self.fm_events:
            lines.append(f"[llm-super] failure modes detected: {', '.join(self.fm_events)}")
        if self.escalated:
            lines.append(f"[llm-super] NEEDS YOUR INPUT: {self.escalated}")
        return "\n".join(lines)


class Orchestrator:
    def __init__(self, cfg: Config, client: Client, trace: Trace, control: ControlState):
        self.cfg = cfg
        self.client = client
        self.trace = trace
        self.control = control
        self.verifier = Verifier(client, cfg)

    async def run_turn(self, session: str, messages: list[dict]) -> TurnReport:
        task_id = uuid.uuid4().hex[:8]
        sup = self.cfg.supervision
        budget = self.control.budget_usd or sup.budget_usd_per_task
        executor = self.cfg.model(self.control.forced_executor or self.cfg.default_executor)
        task_text = _last_user_text(messages)
        spent = 0.0

        def log(kind: str, **kw):
            self.trace.record(session, task_id, kind, **kw)

        log("turn_start", model=executor.name, prompt_chars=len(task_text))

        # 1. Contract extraction (cheap; failure is non-fatal; user-toggleable
        #    via !checklist on|off|skip)
        constraints: list[str] = []
        if self.control.consume_contract_enabled():
            constraints, cres = await contract_mod.extract(self.client, self.cfg, task_text)
            if cres:
                spent += cres.cost_usd
                log("contract", model=self.cfg.utility, cost_usd=cres.cost_usd,
                    tokens_in=cres.tokens_in, tokens_out=cres.tokens_out,
                    constraints=constraints)
        else:
            log("contract_skipped")

        # 2. Execute / monitor / verify / repair loop
        attempts = 0
        fm_seen: list[str] = []
        best_text = ""
        best_report: VerifyReport | None = None
        feedback = ""
        escalated = ""

        while attempts <= sup.max_repairs:
            if self.control.paused:
                escalated = "supervisor is paused (!resume to continue)"
                break
            if spent >= budget:
                escalated = f"budget exhausted (${spent:.3f} of ${budget:.2f})"
                log("budget_stop", cost_usd=0, spent=spent, budget=budget)
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
            try:
                res = await self.client.chat(executor, msgs, max_tokens=8192)
            except ProviderError as e:
                log("executor_error", model=executor.name, error=str(e))
                escalated = f"executor {executor.name} failed: HTTP {e.status}"
                break
            spent += res.cost_usd
            log("execute", model=executor.name, cost_usd=res.cost_usd,
                tokens_in=res.tokens_in, tokens_out=res.tokens_out, attempt=attempts)

            # heuristic monitors
            events = run_monitors(res.text, task_text)
            for ev in events:
                fm_seen.append(ev.fm_id)
                log("fm_event", model=executor.name, fm_id=ev.fm_id,
                    confidence=ev.confidence, evidence=ev.evidence)

            # execution power: run produced code in the sandbox; the transcript
            # becomes verifier evidence and (on failure) repair feedback
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

            # independent cross-family verification — its failure must never
            # kill the turn (that would be our own FM-3.2)
            try:
                report = await self.verifier.verify(
                    task=task_text, output=res.text,
                    contract=constraints, executor_family=executor.family,
                    evidence=evidence,
                )
            except Exception as e:
                log("verify_error", error=str(e))
                if best_report is None:
                    best_text = res.text
                escalated = "verification unavailable (provider errors); response is UNVERIFIED"
                break
            spent += report.cost_usd
            log("verify", model=report.verifier, cost_usd=report.cost_usd,
                score=report.score, passed=report.passed,
                criteria={c.criterion: round(c.expected, 2) for c in report.criteria},
                continuous=all(c.continuous for c in report.criteria))

            if best_report is None or report.score > best_report.score:
                best_text, best_report = res.text, report

            if report.passed and not events:
                break

            # build targeted feedback for the next attempt
            parts = [ev.feedback for ev in events]
            if not report.passed:
                parts.append(report.feedback)
            feedback = " ".join(p for p in parts if p)
            if attempts > sup.max_repairs:
                break
        else:
            pass

        if attempts > sup.max_repairs and best_report and not best_report.passed:
            escalated = (
                f"{attempts} attempts did not reach the quality bar "
                f"(best score {best_report.score:.2f}); returning best attempt"
            )

        log("turn_end", cost_usd=0, spent=spent, attempts=attempts,
            score=best_report.score if best_report else None, escalated=escalated)

        return TurnReport(
            text=best_text,
            task_id=task_id,
            executor=executor.name,
            attempts=attempts,
            verify=best_report,
            fm_events=sorted(set(fm_seen)),
            cost_usd=spent,
            escalated=escalated,
        )


def _last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):  # OpenAI content-parts form
                return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
            return str(c or "")
    return ""
