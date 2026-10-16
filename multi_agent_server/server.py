"""Shared Multi-Agent Server: Planner -> Worker -> Reviewer -> Human Review.

Runs on the host, never as a Compose service; containers reach it at
MULTI_AGENT_SERVER_URL. Starting a workflow answers at once; the orchestrator
then runs the stages in the background and the caller polls the status. The
Planner, Worker and Reviewer stages are in place; the human gate follows.

    python -m multi_agent_server.server

    GET  /health                       server, roles, models, audit paths
    POST /workflow                     start a workflow -> 202 {workflow_id, state}
    GET  /workflows[?state=...]        list workflows
    GET  /workflow/<id>                the full record
    GET  /workflow/<id>/status         the compact view the UI polls
    GET  /workflow/<id>/plan           the Planner's plan (null until planned)
    GET  /workflow/<id>/result         the Worker's evidence and result (null until executed)
    GET  /workflow/<id>/review         the Reviewer's verdict, defects and risks (null until reviewed)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from multi_agent_server import config
from multi_agent_server.audit import AuditLog
from multi_agent_server.models import State
from multi_agent_server.orchestrator import Orchestrator
from multi_agent_server.store import WorkflowStore, is_valid_state


def create_app(data_dir: Path | None = None, audit_dir: Path | None = None, *,
               executor: Any | None = None, ask: Any | None = None,
               stage_timeout: float | None = None, max_revisions: int | None = None) -> Flask:
    """`executor` and `ask` are injection points for tests and the validate
    script: an inline executor runs the stages before POST /workflow answers,
    and `ask` replaces the model call."""
    app = Flask(__name__)
    store = WorkflowStore(Path(data_dir or config.DATA_DIR))
    audit = AuditLog(Path(audit_dir or config.AUDIT_DIR))
    orchestrator = Orchestrator(store, audit, executor=executor, ask=ask, stage_timeout=stage_timeout,
                                max_revisions=max_revisions)
    app.extensions["multi_agent"] = {"store": store, "audit": audit, "orchestrator": orchestrator}

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
            "stage_timeout_seconds": config.STAGE_TIMEOUT,
            "max_revisions": orchestrator.max_revisions,
            "pipeline": orchestrator.stage_names,
            "workflows": store.count(),
            "audit": {
                "workflow_history": str(audit.history_path),
                "coordination_audit": str(audit.coordination_path),
            },
        })

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

    return app


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
    for key, low, high in (("customer_id", 1, None), ("month", 1, 12), ("year", 2000, 2100)):
        if key in context:
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
    print(f"  pipeline:   {' -> '.join(ext['orchestrator'].stage_names)} (human review follows)")
    print(f"  workflows:  {ext['store'].count()} loaded from {ext['store'].directory}")
    print(f"  audit:      {ext['audit'].history_path}")
    print(f"              {ext['audit'].coordination_path}")
    print(f"  containers: http://host.docker.internal:{config.PORT}")
    print(rule)


if __name__ == "__main__":
    application = create_app()
    _banner(application)
    application.run(host=config.HOST, port=config.PORT, debug=False, threaded=True)
