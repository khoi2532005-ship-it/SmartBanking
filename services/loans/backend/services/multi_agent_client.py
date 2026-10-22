"""Client for the shared Multi-Agent Server (Release 2).
    start(request, customer_id)         POST /workflow               -> 202 summary
    workflow(workflow_id)               GET  /workflow/<id>          -> the full record
    workflow_status(workflow_id)        GET  /workflow/<id>/status   -> the compact poll view
    decide(workflow_id, decision, ...)  POST /workflow/<id>/decision -> summary + final response
    response(workflow_id)               GET  /workflow/<id>/response -> 409 until decided
    history()                           GET  /workflows              -> this feature's workflows
    pending()                           GET  /workflows/pending      -> waiting for a person
"""

from __future__ import annotations

import os
import re
from typing import Any

import requests

DEFAULT_URL = "http://localhost:8300"
START_COMMAND = "python -m multi_agent_server.server"
CONNECT_TIMEOUT = 2
READ_TIMEOUT = 10

FEATURE = "loans"
MAX_REQUEST_CHARS = 1000                # the server's limit; enforced here before any call
MAX_NOTE_CHARS = 1000
MAX_DECIDED_BY_CHARS = 100
WORKFLOW_ID = re.compile(r"wf_[0-9a-f]{8}")   # fullmatch below: "$" would accept a trailing newline
DECISIONS = ("accept", "partially_accept", "reject")


class MultiAgentDisabled(RuntimeError):
    """MULTI_AGENT_ENABLED is off in this environment (for example CI)."""


class MultiAgentUnreachable(RuntimeError):
    """The Multi-Agent Server did not answer. Message is written for a person."""


class WorkflowRefused(RuntimeError):
    """The server answered 4xx: an unknown workflow, one already decided, a value it refused."""

    def __init__(self, status: int, message: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


class BadServerResponse(RuntimeError):
    """The server answered, but not with what its protocol promises."""


# ---------------------------------------------------------------------------
# Settings - read at call time so tests and CI can flip them with the environment
# ---------------------------------------------------------------------------

def enabled() -> bool:
    return os.getenv("MULTI_AGENT_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def server_url() -> str:
    return (os.getenv("MULTI_AGENT_SERVER_URL", "").strip() or DEFAULT_URL).rstrip("/")


def api_token() -> str:
    return os.getenv("MULTI_AGENT_API_TOKEN", "").strip()


def _call(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """The JSON body of a 2xx reply, or the failure that says why there is none."""
    if not enabled():
        raise MultiAgentDisabled(
            "Multi-Agent is switched off in this environment (MULTI_AGENT_ENABLED=false)")

    url = f"{server_url()}{path}"
    token = api_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = requests.request(method, url, json=body, headers=headers,
                                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
    except requests.ConnectionError:
        raise MultiAgentUnreachable(
            f"Multi-Agent Server at {url} refused the connection - start it with: {START_COMMAND}") from None
    except requests.Timeout:
        raise MultiAgentUnreachable(
            f"Multi-Agent Server at {url} did not answer within {READ_TIMEOUT}s") from None
    except requests.RequestException as exc:
        raise MultiAgentUnreachable(
            f"request to Multi-Agent Server at {url} failed: {type(exc).__name__}") from None

    if response.status_code == 401:
        # A configuration problem, not a refusal: the two sides hold different tokens.
        raise MultiAgentUnreachable(
            "the Multi-Agent Server requires a bearer token: set MULTI_AGENT_API_TOKEN "
            "to the value the server uses")
    try:
        payload = response.json()
    except ValueError:
        raise BadServerResponse(
            f"Multi-Agent Server answered HTTP {response.status_code} without JSON") from None
    if response.status_code >= 500:
        # The server's own error text stays in its log; the caller learns only that it failed.
        raise BadServerResponse(f"Multi-Agent Server failed (HTTP {response.status_code})")
    if response.status_code >= 400:
        payload = payload if isinstance(payload, dict) else {}
        raise WorkflowRefused(response.status_code,
                              payload.get("error") or f"Multi-Agent Server answered HTTP {response.status_code}",
                              payload)
    return payload


def check_workflow_id(workflow_id: Any) -> str:
    """Only a workflow id goes into a server URL; anything else is refused here."""
    text = workflow_id if isinstance(workflow_id, str) else ""
    if not WORKFLOW_ID.fullmatch(text):
        raise WorkflowRefused(400, "workflow id must look like wf_1a2b3c4d")
    return text


def _loans_only(record: Any, workflow_id: str) -> dict[str, Any]:
    """This feature acts only on its own workflows; the shared server holds every feature's."""
    if not isinstance(record, dict) or record.get("feature") != FEATURE:
        raise WorkflowRefused(404, f"unknown loans workflow {workflow_id}", {})
    return record


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start(request_text: str, customer_id: int) -> dict[str, Any]:
    """Start a workflow about one customer. Returns the server's 202 summary."""
    text = (request_text or "").strip()
    if not text:
        raise WorkflowRefused(400, "request is required")
    if len(text) > MAX_REQUEST_CHARS:
        raise WorkflowRefused(400, f"request must be {MAX_REQUEST_CHARS} characters or fewer")
    summary = _call("POST", "/workflow",
                    {"feature": FEATURE, "request": text, "context": {"customer_id": int(customer_id)}})
    if not isinstance(summary, dict) or "workflow_id" not in summary:
        raise BadServerResponse("Multi-Agent Server started a workflow without returning its id")
    return summary


def workflow_status(workflow_id: str) -> dict[str, Any]:
    """The compact view for polling: stages so far, state, released."""
    workflow_id = check_workflow_id(workflow_id)
    return _loans_only(_call("GET", f"/workflow/{workflow_id}/status"), workflow_id)


def workflow(workflow_id: str) -> dict[str, Any]:
    """The full record: plan, Worker result, review, decision, final response."""
    workflow_id = check_workflow_id(workflow_id)
    return _loans_only(_call("GET", f"/workflow/{workflow_id}"), workflow_id)


def decide(workflow_id: str, decision: str, note: str = "", reviewer: str = "") -> dict[str, Any]:
    """Post the decision. The feature is checked first, so another feature's
    workflow is never decided from here; the server itself refuses a workflow
    that is not awaiting a decision (409)."""
    workflow_id = check_workflow_id(workflow_id)
    decision = str(decision or "").strip().lower().replace(" ", "_").replace("-", "_")
    if decision not in DECISIONS:
        raise WorkflowRefused(400, f"decision must be one of {', '.join(DECISIONS)}")
    note = (note or "").strip()
    if len(note) > MAX_NOTE_CHARS:
        raise WorkflowRefused(400, f"note must be {MAX_NOTE_CHARS} characters or fewer")
    if decision == "partially_accept" and not note:
        raise WorkflowRefused(400, "partially_accept needs a note saying what to correct")
    reviewer = (reviewer or "").strip()
    _loans_only(_call("GET", f"/workflow/{workflow_id}/status"), workflow_id)
    by = f"loans-ui:{reviewer}" if reviewer else "loans-ui"
    return _call("POST", f"/workflow/{workflow_id}/decision",
                 {"decision": decision, "note": note, "by": by})


def response(workflow_id: str) -> dict[str, Any]:
    """The final response; raises WorkflowRefused(409) while the decision is pending."""
    workflow_id = check_workflow_id(workflow_id)
    return _loans_only(_call("GET", f"/workflow/{workflow_id}/response"), workflow_id)


def _listing(path: str, label: str) -> list[dict[str, Any]]:
    workflows = _call("GET", path)
    if not isinstance(workflows, list):
        raise BadServerResponse(f"Multi-Agent Server's {label} list is not a list")
    return [w for w in workflows if isinstance(w, dict) and w.get("feature") == FEATURE]


def history() -> list[dict[str, Any]]:
    """This feature's workflows, newest first (the server's order)."""
    return _listing("/workflows", "workflow")


def pending() -> list[dict[str, Any]]:
    """This feature's workflows waiting for a human decision."""
    return _listing("/workflows/pending", "pending")


def audit_metrics() -> dict[str, Any]:
    """Audit counts and workflow totals for this feature."""
    workflow_ids = []
    for workflow in history():
        workflow_id = workflow.get("workflow_id")
        if not isinstance(workflow_id, str) or not WORKFLOW_ID.fullmatch(workflow_id):
            raise BadServerResponse("Multi-Agent Server returned an invalid workflow id")
        workflow_ids.append(workflow_id)
    metrics = _call("GET", f"/metrics?workflows={','.join(workflow_ids)}")
    counts = metrics.get("counts") if isinstance(metrics, dict) else None
    workflows = metrics.get("workflows") if isinstance(metrics, dict) else None
    if (not isinstance(counts, dict)
            or not isinstance(counts.get("history_records"), int)
            or not isinstance(counts.get("coordination_records"), int)
            or not isinstance(workflows, dict)
            or not isinstance(workflows.get("total"), int)):
        raise BadServerResponse("Multi-Agent Server returned incomplete audit metrics")
    return metrics
