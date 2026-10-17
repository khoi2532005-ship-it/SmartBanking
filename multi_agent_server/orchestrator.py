"""Runs a workflow through its stages, one bounded step at a time.

The orchestrator owns the state machine; the agents own their reasoning.
Every transition and stage outcome goes to workflow_history.jsonl and every
coordination decision (contract checks, retries, fallbacks, handoffs) to
coordination_audit.jsonl, so a run can be reconstructed from the two files
alone. The last stage is the human gate: the workflow waits in
awaiting_human_review and the final response is only built when a person
accepts, partially accepts or rejects it.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from multi_agent_server import config, evidence
from multi_agent_server.agents import base, planner, reviewer, worker
from multi_agent_server.audit import AuditLog
from multi_agent_server.models import (
    DECISIONS, MAX_BY_CHARS, MAX_NOTE_CHARS, StageRecord, State, Workflow, now_iso, seconds_between,
)
from multi_agent_server.store import WorkflowStore

Stage = Callable[[Workflow], None]
HUMAN = "human"


class InvalidDecision(ValueError):
    """The decision is malformed (status 400 at the API)."""


class WrongState(RuntimeError):
    """The workflow is not waiting for a decision (status 409 at the API)."""


class InlineExecutor:
    """Runs submitted work at once on the caller's thread (tests, validate script)."""

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        fn(*args, **kwargs)


class Orchestrator:
    def __init__(self, store: WorkflowStore, audit: AuditLog, *, executor: Any | None = None,
                 ask: base.AskFn | None = None, stage_timeout: float | None = None,
                 max_revisions: int | None = None, service_urls: dict[str, str] | None = None) -> None:
        self.store = store
        self.audit = audit
        self.executor = executor or ThreadPoolExecutor(max_workers=2, thread_name_prefix="workflow")
        self.ask = ask
        self.stage_timeout = config.STAGE_TIMEOUT if stage_timeout is None else stage_timeout
        self.max_revisions = config.MAX_REVISIONS if max_revisions is None else max_revisions
        self.service_urls = service_urls          # None: the configured feature URLs
        # One lock for the human gate: opening it and deciding are each atomic,
        # so two decisions cannot both succeed and a decision cannot slip in
        # before the human stage record exists.
        self._gate_lock = threading.Lock()
        self.stages: list[tuple[str, Stage]] = [
            ("planner", self.run_planner), ("worker", self.run_worker), ("reviewer", self.run_reviewer),
            (HUMAN, self.run_human_gate)]

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

    def run_worker(self, workflow: Workflow, *, keep_previous_on_failure: bool = False) -> bool:
        """Run the Worker. Returns True when a result was produced.

        On a revision (`keep_previous_on_failure`), a Worker that cannot run,
        because the feature API is down or evidence timed out, does not fail
        the workflow: the first result and review are kept and escalated to
        the human, who still sees everything that was produced.
        """
        attempt = workflow.revisions + 1
        plan = workflow.plan or {}
        previous_result = workflow.result
        self.transition(workflow, State.WORKING)
        self.audit.coordination(workflow, "handoff", detail={
            "from": reviewer.ROLE if workflow.revisions else planner.ROLE, "to": worker.ROLE,
            "contract": "plan" if not workflow.revisions else "plan + revision_notes",
            "task_count": len(plan.get("tasks", [])), "attempt": attempt,
        })
        record = self.begin_stage(workflow, worker.ROLE, model=base.model_for(worker.ROLE), attempt=attempt)
        started = time.monotonic()

        # Step 1: evidence over the feature APIs. No evidence at all is a
        # structured failure, not something to reason about.
        try:
            collected = base.bounded(lambda: evidence.collect(plan, workflow.feature, workflow.context,
                                                              self.service_urls),
                                     self.stage_timeout, label="worker evidence")
        except base.StageTimeout as exc:
            self.end_stage(workflow, record, status="timed_out", duration=time.monotonic() - started,
                           output={"step": "evidence"}, error=str(exc))
            return self._worker_unavailable(workflow, str(exc), previous_result, keep_previous_on_failure)
        failed = [r for r in collected if r["status"] != "ok"]
        if collected and len(failed) == len(collected):
            reason = "no feature API answered"
            self.audit.coordination(workflow, "worker_blocked", detail={
                "reason": reason, "errors": [r["error"] for r in failed],
                "urls": [r["url"] for r in failed],
            })
            self.end_stage(workflow, record, status="failed", duration=time.monotonic() - started,
                           output={"step": "evidence", "tasks_total": len(collected), "tasks_ok": 0,
                                   "tasks_failed": len(failed)},
                           error="; ".join(r["error"] for r in failed))
            if not keep_previous_on_failure:
                workflow.result = worker.blocked_result(collected, reason, attempt)
            return self._worker_unavailable(workflow, f"{reason}: {failed[0]['error']}", previous_result,
                                            keep_previous_on_failure)

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
        return True

    def _worker_unavailable(self, workflow: Workflow, error: str, previous_result: Any, keep_previous: bool) -> bool:
        if not keep_previous:
            self.fail(workflow, f"worker: {error}")
            return False
        workflow.result = previous_result
        review = dict(workflow.review or {})
        review["escalated"] = True
        review["escalation_reason"] = f"revision attempt failed ({error}); the first result is kept for the human"
        workflow.review = review
        self.audit.coordination(workflow, "revision_failed", detail={
            "error": error, "kept": "the first result and its review", "revision": workflow.revisions,
        })
        self.store.save(workflow)
        return False

    # ---- stage: reviewer, with the bounded revision cycle -------------------

    def run_reviewer(self, workflow: Workflow) -> None:
        while True:
            outcome = self._review_once(workflow)
            if workflow.state == State.FAILED:
                return
            verdict = outcome.review["verdict"]
            if verdict == "revise" and workflow.revisions < self.max_revisions:
                workflow.revisions += 1
                self.transition(workflow, State.REVISING)
                self.audit.coordination(workflow, "revision_requested", detail={
                    "revision": workflow.revisions, "max_revisions": self.max_revisions,
                    "notes": outcome.review["revision_notes"],
                    "defects": outcome.review["defects"],
                })
                if not self.run_worker(workflow, keep_previous_on_failure=True):
                    if workflow.state == State.FAILED:
                        return
                    break                       # the first result and review go to the human
                continue
            break

        review = workflow.review or {}
        if verdict == "revise":
            if not review.get("escalated"):
                review["escalated"] = True
                review["escalation_reason"] = f"revision limit reached ({self.max_revisions})"
            self.audit.coordination(workflow, "escalated_to_human", detail={
                "reason": review["escalation_reason"], "revisions": workflow.revisions,
                "open_defects": review["defects"], "notes": review["revision_notes"],
            })
        elif verdict == reviewer.ESCALATE:
            self.audit.coordination(workflow, "escalated_to_human", detail={
                "reason": review["escalation_reason"], "revisions": workflow.revisions,
                "risks": review["risks"],
            })
        else:
            self.audit.coordination(workflow, "review_accepted", detail={
                "completion_gate": "every criterion met, no high-severity defect",
                "revisions": workflow.revisions, "risks": review["risks"],
            })
        self.store.save(workflow)
        self.transition(workflow, State.REVIEWED)

    def _review_once(self, workflow: Workflow) -> reviewer.ReviewResult:
        attempt = workflow.revisions + 1
        self.transition(workflow, State.REVIEWING)
        self.audit.coordination(workflow, "handoff", detail={
            "from": worker.ROLE, "to": reviewer.ROLE, "contract": "result",
            "finding_count": len((workflow.result or {}).get("findings", [])), "attempt": attempt,
        })
        record = self.begin_stage(workflow, reviewer.ROLE, model=base.model_for(reviewer.ROLE), attempt=attempt)
        started = time.monotonic()
        status = "completed"
        try:
            outcome = base.bounded(lambda: reviewer.review(workflow, attempt=attempt, ask=self.ask,
                                                           max_revisions=self.max_revisions),
                                   self.stage_timeout, label=reviewer.ROLE)
        except base.StageTimeout as exc:
            status = "timed_out"
            outcome = reviewer.fallback_result(workflow, str(exc), model=record.model, attempt=attempt,
                                               max_revisions=self.max_revisions)

        for call, errors in enumerate(outcome.rejections, start=1):
            self.audit.coordination(workflow, "review_rejected", detail={
                "attempt": attempt, "call": call, "errors": errors,
                "action": "retry" if call < reviewer.MAX_ATTEMPTS else "fallback",
            })
        if outcome.source == "fallback":
            self.audit.coordination(workflow, "fallback_applied", detail={
                "stage": reviewer.ROLE, "reason": outcome.fallback_reason,
                "fallback": "no verdict invented; the review escalates to the human with the checks",
            })
        else:
            self.audit.coordination(workflow, "verdict_recorded", detail={
                "attempt": attempt, "verdict": outcome.review["verdict"], "calls": outcome.attempts,
                "criteria_met": sum(1 for c in outcome.review["criteria"] if c["met"]),
                "criteria_total": len(outcome.review["criteria"]),
                "defects": len(outcome.review["defects"]), "accepted_first_try": outcome.accepted_first_try,
            })

        workflow.review = outcome.review
        self.end_stage(workflow, record, status=status, duration=time.monotonic() - started,
                       output={"verdict": outcome.review["verdict"], "defects": len(outcome.review["defects"]),
                               "risks": len(outcome.review["risks"]), "source": outcome.source,
                               "calls": outcome.attempts},
                       fallback=outcome.source == "fallback", fallback_reason=outcome.fallback_reason)
        return outcome

    # ---- stage: human gate --------------------------------------------------

    def run_human_gate(self, workflow: Workflow) -> None:
        """Park the workflow for the person. Nothing is released until they decide.

        The human stage record is opened before the state becomes decidable,
        under the gate lock, so a decision can never arrive between the two.
        """
        review = workflow.review or {}
        with self._gate_lock:                      # no decision can be logged before these records
            self.begin_stage(workflow, HUMAN, model=HUMAN)
            self.transition(workflow, State.AWAITING_HUMAN_REVIEW)
            self.audit.coordination(workflow, "handoff", detail={
                "from": reviewer.ROLE, "to": HUMAN, "contract": "review",
                "verdict": review.get("verdict"), "escalated": bool(review.get("escalated")),
                "open_defects": len(review.get("defects", [])), "risks": len(review.get("risks", [])),
            })
            self.audit.coordination(workflow, "awaiting_decision", detail={
                "options": list(DECISIONS), "released": False,
            })

    def decide(self, workflow: Workflow, decision: str, note: str = "", by: str = "api") -> Workflow:
        """Apply the person's decision and build the final response."""
        decision = str(decision or "").strip().lower().replace(" ", "_").replace("-", "_")
        if decision not in DECISIONS:
            raise InvalidDecision(f"decision must be one of {list(DECISIONS)}")
        note = str(note or "").strip()
        if len(note) > MAX_NOTE_CHARS:
            raise InvalidDecision(f"note must be {MAX_NOTE_CHARS} characters or fewer")
        by = str(by or "api").strip()
        if len(by) > MAX_BY_CHARS:
            raise InvalidDecision(f"by must be {MAX_BY_CHARS} characters or fewer")
        if decision == "partially_accept" and not note:
            raise InvalidDecision("partially_accept needs a note saying what to correct")

        with self._gate_lock:                      # check and change the state as one step
            if workflow.state != State.AWAITING_HUMAN_REVIEW:
                raise WrongState(f"workflow {workflow.workflow_id} is {workflow.state}, not awaiting_human_review")
            decided_at = now_iso()
            record = next((s for s in reversed(workflow.stages) if s.role == HUMAN and s.status == "running"), None)
            snapshot = (workflow.decision, workflow.final_response, workflow.state,
                        None if record is None else (record.finished_at, record.status, dict(record.output),
                                                     record.duration_seconds))

            def restore() -> None:
                workflow.decision, workflow.final_response, workflow.state = snapshot[:3]
                if record is not None and snapshot[3] is not None:
                    record.finished_at, record.status, record.output, record.duration_seconds = snapshot[3]

            # Phase 1: memory and disk change together, or not at all (the store write is atomic).
            try:
                workflow.decision = {"decision": decision, "note": note, "by": by or "api", "decided_at": decided_at}
                workflow.final_response = self.build_final_response(workflow)
                if record is not None:
                    record.finished_at = decided_at
                    record.status = "completed"
                    record.output = {"decision": decision, "note": note, "by": workflow.decision["by"],
                                     "released": workflow.final_response["released"]}
                    record.duration_seconds = seconds_between(record.started_at, decided_at)
                workflow.state = DECISIONS[decision]
                self.store.save(workflow)
            except Exception:
                restore()
                raise
            # Phase 2: the audit lines. If one cannot be written, the decision is taken back on
            # disk as well, so a restart never serves a released response that no record explains.
            released = workflow.final_response["released"]
            try:
                self.audit.history(workflow, "state_changed", detail={"from": State.AWAITING_HUMAN_REVIEW,
                                                                      "to": workflow.state})
                if record is not None:
                    self.audit.history(workflow, "stage_completed", role=HUMAN, model=HUMAN, detail={
                        **record.output, "attempt": record.attempt, "duration_seconds": record.duration_seconds,
                        "fallback": False, "fallback_reason": "", "error": ""})
                self.audit.coordination(workflow, "human_decision", actor=HUMAN, detail={
                    "decision": decision, "note": note, "by": workflow.decision["by"],
                    "review_verdict": (workflow.review or {}).get("verdict"), "revisions": workflow.revisions,
                })
                self.audit.coordination(workflow, "response_released" if released else "response_withheld", detail={
                    "decision": decision, "with_correction": bool(note) and decision == "partially_accept",
                })
                self.audit.history(workflow, "workflow_completed", detail={
                    "decision": decision, "released": released, "revisions": workflow.revisions,
                    "stages": len(workflow.stages),
                })
            except Exception:
                restore()
                try:
                    self.store.save(workflow)
                except Exception:
                    pass                           # the disk is failing; memory is at least consistent
                raise
        return workflow

    @staticmethod
    def build_final_response(workflow: Workflow) -> dict[str, Any]:
        """What the caller receives after the decision; nothing before it.

        Accept releases the Worker's answer. Partially accept releases it with
        the person's correction attached. Reject releases nothing but the
        reason, and keeps the audit trail.
        """
        decision = workflow.decision or {}
        result = workflow.result or {}
        review = workflow.review or {}
        kind = decision.get("decision")
        released = kind in ("accept", "partially_accept")
        return {
            "workflow_id": workflow.workflow_id,
            "feature": workflow.feature,
            "request": workflow.request,
            "decision": kind,
            "released": released,
            "released_at": decision.get("decided_at") if released else None,
            "decided_by": decision.get("by"),
            "answer": result.get("answer") if released else None,
            "findings": result.get("findings", []) if released else [],
            "correction_note": decision.get("note") or "",
            "review_verdict": review.get("verdict"),
            "review_summary": review.get("summary"),
            "risks": review.get("risks", []),
            "gaps": result.get("gaps", []) if released else [],
            "request_only_numbers": result.get("request_only_numbers", []) if released else [],
            "evidence_sources": [
                {"task_id": r["task_id"], "endpoint": r["endpoint"], "url": r["url"], "status": r["status"]}
                for r in result.get("evidence", [])
            ],
            "revisions": workflow.revisions,
            "models": sorted({s.model for s in workflow.stages if s.model and s.role != HUMAN}),
        }

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
        self.close_running_stages(workflow, error)
        self.transition(workflow, State.FAILED)
        self.audit.history(workflow, "workflow_failed", detail={"error": error})
        self.audit.coordination(workflow, "workflow_failed", detail={"error": error})

    def close_running_stages(self, workflow: Workflow, error: str) -> int:
        """A crashed or interrupted stage is closed as failed, so no record stays 'running'."""
        closed = 0
        for record in workflow.stages:
            if record.status != "running":
                continue
            record.finished_at = now_iso()
            record.status = "failed"
            record.error = error
            record.duration_seconds = seconds_between(record.started_at, record.finished_at)
            self.audit.history(workflow, "stage_failed", role=record.role, model=record.model, detail={
                "attempt": record.attempt, "duration_seconds": record.duration_seconds,
                "fallback": False, "fallback_reason": "", "error": error})
            closed += 1
        if closed:
            self.store.save(workflow)
        return closed

    def recover_interrupted(self) -> list[str]:
        """At startup: a workflow that was mid-run when the server stopped cannot
        resume (its stage thread is gone), so it is closed as failed with the
        reason, instead of staying 'working' forever. Workflows waiting for a
        human decision are untouched: that gate survives a restart."""
        interrupted = []
        for workflow in self.store.list():
            if workflow.state in (State.CREATED, *State.RUNNING):
                reason = f"interrupted by a server restart while {workflow.state}"
                self.audit.coordination(workflow, "interrupted", detail={"state": workflow.state, "reason": reason})
                self.fail(workflow, reason)
                interrupted.append(workflow.workflow_id)
        return interrupted
