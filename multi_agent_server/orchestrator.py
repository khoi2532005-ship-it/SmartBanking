"""Runs a workflow through its stages, one bounded step at a time.

The orchestrator owns the state machine; the agents own their reasoning.
Every transition and stage outcome goes to workflow_history.jsonl and every
coordination decision (contract checks, retries, fallbacks, handoffs) to
coordination_audit.jsonl, so a run can be reconstructed from the two files
alone. Stages arrive one per commit: planner and worker now; reviewer and the
human gate follow.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from multi_agent_server import config, evidence
from multi_agent_server.agents import base, planner, worker
from multi_agent_server.audit import AuditLog
from multi_agent_server.models import StageRecord, State, Workflow, now_iso
from multi_agent_server.store import WorkflowStore

Stage = Callable[[Workflow], None]


class InlineExecutor:
    """Runs submitted work at once on the caller's thread (tests, validate script)."""

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        fn(*args, **kwargs)


class Orchestrator:
    def __init__(self, store: WorkflowStore, audit: AuditLog, *, executor: Any | None = None,
                 ask: base.AskFn | None = None, stage_timeout: float | None = None) -> None:
        self.store = store
        self.audit = audit
        self.executor = executor or ThreadPoolExecutor(max_workers=2, thread_name_prefix="workflow")
        self.ask = ask
        self.stage_timeout = config.STAGE_TIMEOUT if stage_timeout is None else stage_timeout
        self.stages: list[tuple[str, Stage]] = [("planner", self.run_planner), ("worker", self.run_worker)]

    @property
    def stage_names(self) -> list[str]:
        return [name for name, _ in self.stages]

    # ---- running ------------------------------------------------------------

    def start(self, workflow: Workflow) -> None:
        self.executor.submit(self._run_safely, workflow.workflow_id)

    def _run_safely(self, workflow_id: str) -> None:
        workflow = self.store.get(workflow_id)
        if workflow is None:
            return
        try:
            self.run(workflow)
        except Exception as exc:  # a bug in a stage must not leave a workflow hanging
            self.fail(workflow, f"{type(exc).__name__}: {exc}")

    def run(self, workflow: Workflow) -> None:
        for _name, stage in self.stages:
            if workflow.state in State.TERMINAL:
                return
            stage(workflow)

    # ---- stage: planner -----------------------------------------------------

    def run_planner(self, workflow: Workflow) -> None:
        self.transition(workflow, State.PLANNING)
        record = self.begin_stage(workflow, planner.ROLE, model=base.model_for(planner.ROLE))
        started = time.monotonic()
        status = "completed"
        try:
            result = base.bounded(lambda: planner.plan(workflow, ask=self.ask),
                                  self.stage_timeout, label=planner.ROLE)
        except base.StageTimeout as exc:
            status = "timed_out"
            result = planner.fallback_result(workflow, str(exc), model=record.model)

        for attempt, errors in enumerate(result.rejections, start=1):
            self.audit.coordination(workflow, "plan_rejected", detail={
                "attempt": attempt, "errors": errors,
                "action": "retry" if attempt < planner.MAX_ATTEMPTS else "fallback",
            })
        if result.source == "fallback":
            self.audit.coordination(workflow, "fallback_applied", detail={
                "stage": planner.ROLE, "reason": result.fallback_reason,
                "fallback": "deterministic plan from the catalogue defaults",
            })
        else:
            self.audit.coordination(workflow, "plan_accepted", detail={
                "attempts": result.attempts, "task_count": len(result.plan["tasks"]),
                "accepted_first_try": result.accepted_first_try,
            })

        workflow.plan = result.plan
        self.end_stage(workflow, record, status=status, duration=time.monotonic() - started,
                       output={"task_count": len(result.plan["tasks"]), "source": result.source,
                               "attempts": result.attempts, "objective": result.plan["objective"]},
                       fallback=result.source == "fallback", fallback_reason=result.fallback_reason)
        self.transition(workflow, State.PLANNED)

    # ---- stage: worker ------------------------------------------------------

    def run_worker(self, workflow: Workflow) -> None:
        attempt = workflow.revisions + 1
        plan = workflow.plan or {}
        self.transition(workflow, State.WORKING)
        self.audit.coordination(workflow, "handoff", detail={
            "from": planner.ROLE, "to": worker.ROLE, "contract": "plan",
            "task_count": len(plan.get("tasks", [])), "attempt": attempt,
        })
        record = self.begin_stage(workflow, worker.ROLE, model=base.model_for(worker.ROLE), attempt=attempt)
        started = time.monotonic()

        # Step 1: evidence over the feature APIs. No evidence at all is a
        # structured failure, not something to reason about.
        try:
            collected = base.bounded(lambda: evidence.collect(plan, workflow.feature, workflow.context),
                                     self.stage_timeout, label="worker evidence")
        except base.StageTimeout as exc:
            self.end_stage(workflow, record, status="timed_out", duration=time.monotonic() - started,
                           output={"step": "evidence"}, error=str(exc))
            self.fail(workflow, f"worker: {exc}")
            return
        failed = [r for r in collected if r["status"] != "ok"]
        if collected and len(failed) == len(collected):
            reason = "no feature API answered"
            workflow.result = worker.blocked_result(collected, reason, attempt)
            self.audit.coordination(workflow, "worker_blocked", detail={
                "reason": reason, "errors": [r["error"] for r in failed],
                "urls": [r["url"] for r in failed],
            })
            self.end_stage(workflow, record, status="failed", duration=time.monotonic() - started,
                           output={"step": "evidence", "tasks_total": len(collected), "tasks_ok": 0,
                                   "tasks_failed": len(failed)},
                           error="; ".join(r["error"] for r in failed))
            self.fail(workflow, f"worker: {reason}: {failed[0]['error']}")
            return

        # Step 2: the analysis tasks, one bounded model call with a correction.
        status = "completed"
        try:
            result = base.bounded(
                lambda: worker.analyse(workflow, collected, feedback=self._revision_feedback(workflow),
                                       attempt=attempt, ask=self.ask),
                self.stage_timeout, label="worker analysis")
        except base.StageTimeout as exc:
            status = "timed_out"
            result = worker.fallback_result(workflow, collected, str(exc), model=record.model, attempt=attempt)

        for call, errors in enumerate(result.rejections, start=1):
            self.audit.coordination(workflow, "result_rejected", detail={
                "attempt": attempt, "call": call, "errors": errors,
                "action": "retry" if call < worker.MAX_ATTEMPTS else "fallback",
            })
        if result.source == "fallback":
            self.audit.coordination(workflow, "fallback_applied", detail={
                "stage": worker.ROLE, "reason": result.fallback_reason,
                "fallback": "findings written from the evidence summaries",
            })
        else:
            self.audit.coordination(workflow, "result_accepted", detail={
                "attempt": attempt, "calls": result.attempts, "finding_count": len(result.result["findings"]),
                "accepted_first_try": result.accepted_first_try,
            })

        workflow.result = result.result
        self.end_stage(workflow, record, status=status, duration=time.monotonic() - started,
                       output={"tasks_total": len(collected), "tasks_ok": len(collected) - len(failed),
                               "tasks_failed": len(failed), "finding_count": len(result.result["findings"]),
                               "source": result.source, "calls": result.attempts},
                       fallback=result.source == "fallback", fallback_reason=result.fallback_reason)
        self.transition(workflow, State.EXECUTED)

    @staticmethod
    def _revision_feedback(workflow: Workflow) -> str:
        """The Reviewer's notes for a second Worker attempt (set by the review stage)."""
        review = workflow.review or {}
        notes = review.get("revision_notes") or []
        if isinstance(notes, str):
            notes = [notes]
        return "\n".join(f"- {note}" for note in notes if note)

    # ---- shared bookkeeping -------------------------------------------------

    def transition(self, workflow: Workflow, state: str) -> None:
        previous = workflow.state
        workflow.state = state
        self.store.save(workflow)
        self.audit.history(workflow, "state_changed", detail={"from": previous, "to": state})

    def begin_stage(self, workflow: Workflow, role: str, *, model: str, attempt: int = 1) -> StageRecord:
        record = StageRecord(role=role, attempt=attempt, started_at=now_iso(), model=model)
        workflow.stages.append(record)
        self.store.save(workflow)
        self.audit.history(workflow, "stage_started", role=role, model=model,
                           detail={"attempt": attempt, "timeout_seconds": self.stage_timeout})
        return record

    def end_stage(self, workflow: Workflow, record: StageRecord, *, status: str, duration: float,
                  output: dict[str, Any], error: str = "", fallback: bool = False,
                  fallback_reason: str = "") -> None:
        record.finished_at = now_iso()
        record.status = status
        record.output = output
        record.error = error
        record.fallback = fallback
        record.fallback_reason = fallback_reason
        record.duration_seconds = round(duration, 3)
        self.store.save(workflow)
        event = {"completed": "stage_completed", "failed": "stage_failed", "timed_out": "stage_timed_out"}[status]
        self.audit.history(workflow, event, role=record.role, model=record.model, detail={
            **output, "attempt": record.attempt, "duration_seconds": record.duration_seconds,
            "fallback": fallback, "fallback_reason": fallback_reason, "error": error,
        })

    def fail(self, workflow: Workflow, error: str) -> None:
        workflow.error = error
        self.transition(workflow, State.FAILED)
        self.audit.history(workflow, "workflow_failed", detail={"error": error})
        self.audit.coordination(workflow, "workflow_failed", detail={"error": error})
