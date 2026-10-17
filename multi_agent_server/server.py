"""Shared Multi-Agent Server: Planner -> Worker -> Reviewer -> Human Review.

Runs on the host, never as a Compose service; containers reach it at
MULTI_AGENT_SERVER_URL. Starting a workflow answers at once; the orchestrator
then runs the stages in the background and the caller polls the status. After
the Reviewer the workflow waits in awaiting_human_review; the final response
exists only once a person has decided.

    python -m multi_agent_server.server

    GET  /health                       server, roles, models, audit paths
    POST /workflow                     start a workflow -> 202 {workflow_id, state}
    GET  /workflows[?state=...]        list workflows
    GET  /workflows/pending            workflows waiting for a human decision
    GET  /workflow/<id>                the full record
    GET  /workflow/<id>/status         the compact view the UI polls
    GET  /workflow/<id>/plan           the Planner's plan (null until planned)
    GET  /workflow/<id>/result         the Worker's evidence and result (null until executed)
    GET  /workflow/<id>/review         the Reviewer's verdict, defects and risks (null until reviewed)
    POST /workflow/<id>/decision       {"decision": accept | partially_accept | reject, "note"?: str}
    GET  /workflow/<id>/response       the final response; 409 until the decision is made
    GET  /metrics[?workflows=id,id]    coordination metrics computed from the two audit files
"""

from __future__ import annotations

import hmac
import socket
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from multi_agent_server import config, metrics
from multi_agent_server.audit import AuditLog
from multi_agent_server.models import CONTEXT_KEYS, DECISIONS, State
from multi_agent_server.orchestrator import InvalidDecision, Orchestrator, WrongState
from multi_agent_server.store import WorkflowStore, is_valid_state


def create_app(data_dir: Path | None = None, audit_dir: Path | None = None, *,
               executor: Any | None = None, ask: Any | None = None,
               stage_timeout: float | None = None, max_revisions: int | None = None,
               api_token: str | None = None) -> Flask:
    """`executor` and `ask` are injection points for tests and the validate
    script: an inline executor runs the stages before POST /workflow answers,
    and `ask` replaces the model call. `api_token` overrides MULTI_AGENT_API_TOKEN."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES     # a request is a sentence and three integers
    store = WorkflowStore(Path(data_dir or config.DATA_DIR))
    audit = AuditLog(Path(audit_dir or config.AUDIT_DIR))
    orchestrator = Orchestrator(store, audit, executor=executor, ask=ask, stage_timeout=stage_timeout,
                                max_revisions=max_revisions)
    token = config.API_TOKEN if api_token is None else api_token.strip()
    interrupted = orchestrator.recover_interrupted()
    app.extensions["multi_agent"] = {"store": store, "audit": audit, "orchestrator": orchestrator,
                                     "token": token, "interrupted": interrupted}

    @app.before_request
    def require_token():
        # /health stays open so a probe can tell "down" from "not authorised".
        if not token or request.path == "/health":
            return None
        if not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {token}"):
            return jsonify({"error": "missing or invalid bearer token",
                            "hint": "set MULTI_AGENT_API_TOKEN to the server's value for every client"}), 401
        return None

    @app.errorhandler(Exception)
    def handle_exception(exc):
        # Structured errors, never an HTML page: a caller's mistake keeps its
        # own status code, anything else is a 500 with the reason.
        if isinstance(exc, HTTPException):
            return jsonify({"error": exc.description, "status": exc.code}), exc.code
        app.logger.exception(exc)
        return jsonify({"error": f"{type(exc).__name__}: {exc}", "status": 500}), 500

    @app.get("/health")
    def health():
        return jsonify({
            "service": "multi-agent-server",
            "status": "running",
            "release": 2,
            "roles": list(config.ROLES),
            "models": {role: config.role_model(role) or "shared AI-Mode model" for role in config.ROLES},
            "features": list(config.FEATURES),
            "stage_timeout_seconds": orchestrator.stage_timeout,
            "max_revisions": orchestrator.max_revisions,
            "auth": "token" if token else "open",
            "interrupted_on_start": interrupted,
            "pipeline": orchestrator.stage_names,
            "decisions": list(DECISIONS),
            "workflows": store.count(),
            "pending": len(store.list(State.AWAITING_HUMAN_REVIEW)),
            "audit": {
                "workflow_history": str(audit.history_path),
                "coordination_audit": str(audit.coordination_path),
            },
        })

    @app.get("/metrics")
    def get_metrics():
        history, coordination = audit.read_history(), audit.read_coordination()
        selected = request.args.get("workflows")
        if selected:
            ids = {w.strip() for w in selected.split(",") if w.strip()}
            history = [r for r in history if r["workflow_id"] in ids]
            coordination = [r for r in coordination if r["workflow_id"] in ids]
        body = metrics.compute(history, coordination)
        body["scope"] = sorted(ids) if selected else "all"
        return jsonify(body)

    @app.post("/workflow")
    def start_workflow():
        payload, error = _validate_request(request.get_json(silent=True))
        if error:
            return jsonify(error), 400
        workflow = store.create(payload["feature"], payload["request"], payload["context"])
        audit.history(workflow, "workflow_created",
                      detail={"request": workflow.request, "context": workflow.context})
        audit.coordination(workflow, "request_accepted",
                           detail={"feature": workflow.feature, "stages": ["planner", "worker", "reviewer", "human"]})
        orchestrator.start(workflow)
        body = workflow.summary()
        body["links"] = {
            "self": f"/workflow/{workflow.workflow_id}",
            "status": f"/workflow/{workflow.workflow_id}/status",
        }
        return jsonify(body), 202

    @app.get("/workflows/pending")
    def list_pending():
        pending = []
        for workflow in store.list(State.AWAITING_HUMAN_REVIEW):
            review = workflow.review or {}
            pending.append({
                **workflow.summary(),
                "request": workflow.request,
                "context": workflow.context,
                "review_verdict": review.get("verdict"),
                "escalated": bool(review.get("escalated")),
                "links": {"self": f"/workflow/{workflow.workflow_id}",
                          "decision": f"/workflow/{workflow.workflow_id}/decision"},
            })
        return jsonify({"count": len(pending), "options": list(DECISIONS), "workflows": pending})

    @app.get("/workflows")
    def list_workflows():
        state = request.args.get("state")
        if state and not is_valid_state(state):
            return jsonify({"error": f"unknown state {state!r}", "states": list(State.ALL)}), 400
        return jsonify([w.summary() for w in store.list(state)])

    @app.get("/workflow/<workflow_id>")
    def get_workflow(workflow_id: str):
        workflow = store.get(workflow_id)
        if workflow is None:
            return jsonify({"error": f"unknown workflow {workflow_id!r}"}), 404
        return jsonify(workflow.to_dict())

    @app.get("/workflow/<workflow_id>/status")
    def get_status(workflow_id: str):
        workflow = store.get(workflow_id)
        if workflow is None:
            return jsonify({"error": f"unknown workflow {workflow_id!r}"}), 404
        return jsonify(workflow.summary())

    @app.get("/workflow/<workflow_id>/plan")
    def get_plan(workflow_id: str):
        workflow = store.get(workflow_id)
        if workflow is None:
            return jsonify({"error": f"unknown workflow {workflow_id!r}"}), 404
        return jsonify({"workflow_id": workflow.workflow_id, "state": workflow.state, "plan": workflow.plan})

    @app.get("/workflow/<workflow_id>/result")
    def get_result(workflow_id: str):
        workflow = store.get(workflow_id)
        if workflow is None:
            return jsonify({"error": f"unknown workflow {workflow_id!r}"}), 404
        return jsonify({"workflow_id": workflow.workflow_id, "state": workflow.state, "result": workflow.result})

    @app.get("/workflow/<workflow_id>/review")
    def get_review(workflow_id: str):
        workflow = store.get(workflow_id)
        if workflow is None:
            return jsonify({"error": f"unknown workflow {workflow_id!r}"}), 404
        return jsonify({"workflow_id": workflow.workflow_id, "state": workflow.state,
                        "revisions": workflow.revisions, "review": workflow.review})

    @app.post("/workflow/<workflow_id>/decision")
    def post_decision(workflow_id: str):
        workflow = store.get(workflow_id)
        if workflow is None:
            return jsonify({"error": f"unknown workflow {workflow_id!r}"}), 404
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "JSON object body required", "options": list(DECISIONS)}), 400
        try:
            orchestrator.decide(workflow, data.get("decision"), data.get("note") or "", str(data.get("by") or "api"))
        except InvalidDecision as exc:
            return jsonify({"error": str(exc), "options": list(DECISIONS)}), 400
        except WrongState as exc:
            return jsonify({"error": str(exc), "state": workflow.state}), 409
        body = workflow.summary()
        body["final_response"] = workflow.final_response
        return jsonify(body)

    @app.get("/workflow/<workflow_id>/response")
    def get_response(workflow_id: str):
        workflow = store.get(workflow_id)
        if workflow is None:
            return jsonify({"error": f"unknown workflow {workflow_id!r}"}), 404
        if workflow.final_response is None:
            # The completion gate in HTTP form: nothing to read until a person has decided.
            return jsonify({
                "error": "no response yet: the workflow has not been decided by a human",
                "workflow_id": workflow.workflow_id, "state": workflow.state,
                "awaiting_decision": workflow.state == State.AWAITING_HUMAN_REVIEW,
                "links": {"status": f"/workflow/{workflow.workflow_id}/status",
                          "decision": f"/workflow/{workflow.workflow_id}/decision"},
            }), 409
        return jsonify(workflow.final_response)

    return app


MAX_BODY_BYTES = 64 * 1024


def _validate_request(data: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Shape and bounds of POST /workflow; the structured error names what to fix."""
    if not isinstance(data, dict):
        return {}, {"error": "JSON object body required"}
    feature = str(data.get("feature") or "").strip().lower()
    if feature not in config.FEATURES:
        return {}, {"error": f"feature must be one of {list(config.FEATURES)}", "allowed_features": list(config.FEATURES)}
    text = str(data.get("request") or "").strip()
    if not text:
        return {}, {"error": "request is required"}
    if len(text) > config.MAX_REQUEST_CHARS:
        return {}, {"error": f"request must be {config.MAX_REQUEST_CHARS} characters or fewer"}
    context = data.get("context") or {}
    if not isinstance(context, dict):
        return {}, {"error": "context must be a JSON object"}
    unknown = sorted(str(k) for k in context if k not in CONTEXT_KEYS)
    if unknown:
        # Only these three reach the agents, the prompts and the audit; anything
        # else would become "evidence" the grounding check could not question.
        return {}, {"error": f"context accepts only {', '.join(CONTEXT_KEYS)}; unknown {unknown}"}
    for key, low, high in (("customer_id", 1, None), ("month", 1, 12), ("year", 2000, 2100)):
        if key in context:
            if isinstance(context[key], bool):
                return {}, {"error": f"context.{key} must be an integer"}
            try:
                value = int(context[key])
            except (TypeError, ValueError):
                return {}, {"error": f"context.{key} must be an integer"}
            if value < low or (high is not None and value > high):
                return {}, {"error": f"context.{key} must be between {low} and {high or 'any'}"}
            context[key] = value
    if "customer_id" not in context:
        return {}, {"error": "context.customer_id is required: every workflow is about one customer"}
    return {"feature": feature, "request": text, "context": context}, None


def _banner(app: Flask) -> None:
    rule = "=" * 72
    ext = app.extensions["multi_agent"]
    print(rule)
    print("  SmartBank Multi-Agent Server (Release 2) - host process, not a container")
    print(f"  listening:  {config.local_url()}")
    print(f"  pipeline:   {' -> '.join(ext['orchestrator'].stage_names)} (then the human decision)")
    print(f"  workflows:  {ext['store'].count()} loaded from {ext['store'].directory}")
    print(f"  audit:      {ext['audit'].history_path}")
    print(f"              {ext['audit'].coordination_path}")
    print(f"  containers: http://host.docker.internal:{config.PORT}")
    if ext["token"]:
        print("  auth:       bearer token required on every /workflow route (MULTI_AGENT_API_TOKEN)")
    else:
        print("  auth:       open - set MULTI_AGENT_API_TOKEN in .env to require a bearer token")
    if ext["interrupted"]:
        print(f"  recovered:  {len(ext['interrupted'])} interrupted workflow(s) closed as failed")
    print(rule)


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """True when something already listens on the port (a connect probe works on every OS).

    On localhost a refused connection is the only sign that nothing is there; a
    timeout means a listener with a full backlog, so it counts as in use. Any
    other error also counts as in use: refusing to start is safer than
    touching another server's data.
    """
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except ConnectionRefusedError:
        return False
    except OSError:
        return True


def main() -> int:
    # Claim the port before touching the data directory: a second start while a
    # server is already running must not mark that server's live workflows as
    # interrupted. create_app() runs the restart recovery, so it comes after.
    if port_in_use(config.PORT):
        print(f"error: {config.local_url()} is already in use - is another Multi-Agent Server running? "
              "Nothing was changed on disk.")
        return 1
    application = create_app()
    _banner(application)
    application.run(host=config.HOST, port=config.PORT, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
