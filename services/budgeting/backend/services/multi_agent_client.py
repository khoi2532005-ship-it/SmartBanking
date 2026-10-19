"""Typed client for the shared Multi-Agent Server (Release 2).

The server is a host process (python -m multi_agent_server.server) reached at
MULTI_AGENT_SERVER_URL (http://host.docker.internal:8300 in Compose). A
request becomes a workflow that runs Planner -> Worker -> Reviewer and then
waits for a person; nothing is released until that decision is posted.

    start()            POST /workflow                      -> 202 summary {workflow_id, state, stages}
    workflow_status()  GET  /workflow/<id>/status          -> summary, for polling
    workflow()         GET  /workflow/<id>                 -> plan, result and review (operator only)
    decide()           POST /workflow/<id>/decision        -> accept | partially_accept | reject (+ note)
    response()         GET  /workflow/<id>/response        -> the final response; 409 until decided
    pending()          GET  /workflows/pending

Who may see what: `customer_view(response())` is the only payload that may
reach a customer: the approved answer and its findings, nothing the Reviewer
or the operator wrote. `workflow()` carries the Worker's unreleased answer
and the Reviewer's verdict and exists for the person doing the human review;
it belongs on the operator's review desk and nowhere else. Every call that
names a workflow checks the id's shape first, so nothing but a workflow id is
ever placed in a server URL.

- MULTI_AGENT_ENABLED=false raises MultiAgentDisabled before any network call (CI).
- A server that is down raises MultiAgentUnreachable with a readable message
  and a 2s connect timeout. Every call here answers quickly (the server runs
  the stages in the background), so the read timeout is short
  (MULTI_AGENT_CLIENT_TIMEOUT, default 10s).
- A non-2xx reply raises MultiAgentError carrying the status and the server's
  own error message; a 409 from response() means the workflow is still
  waiting for its decision, which the UI shows as such.
- MULTI_AGENT_API_TOKEN, when set, is sent as a bearer token on every call.
"""

from __future__ import annotations

import os
import re
from typing import Any

import requests

DEFAULT_URL = "http://localhost:8300"
CONNECT_TIMEOUT = 2
START_HINT = "start it on the host with: python -m multi_agent_server.server"

FEATURE = "budgeting"
MAX_REQUEST_CHARS = 1000                # the server's limit; enforced here before any call
MAX_NOTE_CHARS = 1000
DECISIONS = ("accept", "partially_accept", "reject")
STATE_AWAITING = "awaiting_human_review"
TERMINAL_STATES = ("accepted", "partially_accepted", "rejected", "failed")
_SUMMARY_KEYS = ("workflow_id", "state", "stages")
_RESPONSE_KEYS = ("workflow_id", "decision", "released")
WORKFLOW_ID = re.compile(r"^wf_[0-9a-f]{8}$")


class MultiAgentDisabled(RuntimeError):
    """MULTI_AGENT_ENABLED is off in this environment (for example CI)."""


class MultiAgentUnreachable(RuntimeError):
    """The Multi-Agent Server did not answer. Message is written for a person."""


class MultiAgentError(RuntimeError):
    """The server answered with an error status (or an unusable body)."""

    def __init__(self, status: int, message: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


# ---------------------------------------------------------------------------
# Settings - read at call time so tests and CI can flip them with the environment
# ---------------------------------------------------------------------------

def server_url() -> str:
    return (os.getenv("MULTI_AGENT_SERVER_URL", DEFAULT_URL).strip() or DEFAULT_URL).rstrip("/")


def enabled() -> bool:
    return os.getenv("MULTI_AGENT_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def api_token() -> str:
    return os.getenv("MULTI_AGENT_API_TOKEN", "").strip()


def _read_timeout() -> float:
    try:
        return float(os.getenv("MULTI_AGENT_CLIENT_TIMEOUT", "10"))
    except ValueError:
        return 10.0


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def _request(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    if not enabled():
        raise MultiAgentDisabled("Multi-Agent integration is disabled in this environment (MULTI_AGENT_ENABLED=false)")

    url = f"{server_url()}{path}"
    headers = {"Authorization": f"Bearer {api_token()}"} if api_token() else {}
    try:
        response = requests.request(method, url, json=body, headers=headers,
                                    timeout=(CONNECT_TIMEOUT, _read_timeout()))
    except requests.ConnectionError:
        raise MultiAgentUnreachable(f"Multi-Agent Server at {url} refused the connection - {START_HINT}") from None
    except requests.Timeout:
        raise MultiAgentUnreachable(f"Multi-Agent Server at {url} did not answer within {_read_timeout():.0f}s") from None
    except requests.RequestException as exc:
        raise MultiAgentUnreachable(f"request to Multi-Agent Server at {url} failed: {type(exc).__name__}") from None

    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"error": response.text[:200] or "non-JSON response"}


def check_workflow_id(workflow_id: Any) -> str:
    """Only a workflow id goes into a server URL; anything else is refused here."""
    text = str(workflow_id or "").strip()
    if not WORKFLOW_ID.match(text):
        raise MultiAgentError(400, "workflow id must look like wf_1a2b3c4d")
    return text


def _expect(status_code: int, payload: Any, ok: tuple[int, ...] = (200,)) -> dict[str, Any]:
    """The payload when the status is one we accept, otherwise a MultiAgentError."""
    if status_code == 401:
        raise MultiAgentError(401, "the Multi-Agent Server requires a bearer token: set MULTI_AGENT_API_TOKEN "
                                   "to the same value the server uses", payload if isinstance(payload, dict) else {})
    if status_code >= 500:
        # The server's own failure text stays in its logs; the caller learns only that it failed.
        raise MultiAgentError(502, f"the Multi-Agent Server failed (HTTP {status_code})")
    if status_code not in ok:
        message = payload.get("error") if isinstance(payload, dict) else None
        raise MultiAgentError(status_code, message or f"Multi-Agent Server returned HTTP {status_code}",
                              payload if isinstance(payload, dict) else {})
    if not isinstance(payload, dict):
        raise MultiAgentError(502, "Multi-Agent Server returned a non-object response")
    return payload


def _validate_summary(payload: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in _SUMMARY_KEYS if k not in payload]
    if missing:
        raise MultiAgentError(502, f"workflow summary is missing required fields: {', '.join(missing)}", payload)
    if not isinstance(payload["stages"], list):
        raise MultiAgentError(502, "workflow summary stages must be a list", payload)
    return payload


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start(request_text: str, customer_id: int, month: int, year: int, feature: str = FEATURE) -> dict[str, Any]:
    """Start a workflow for one customer and period. Returns the 202 summary."""
    text = (request_text or "").strip()
    if not text:
        raise MultiAgentError(400, "request is required")
    if len(text) > MAX_REQUEST_CHARS:
        raise MultiAgentError(400, f"request must be {MAX_REQUEST_CHARS} characters or fewer")
    body = {"feature": feature, "request": text,
            "context": {"customer_id": int(customer_id), "month": int(month), "year": int(year)}}
    status_code, payload = _request("POST", "/workflow", body)
    return _validate_summary(_expect(status_code, payload, ok=(202,)))


def workflow_status(workflow_id: str) -> dict[str, Any]:
    workflow_id = check_workflow_id(workflow_id)
    status_code, payload = _request("GET", f"/workflow/{workflow_id}/status")
    return _validate_summary(_expect(status_code, payload))


def workflow(workflow_id: str) -> dict[str, Any]:
    """The full record: plan, result (unreleased answer) and review. Operator only."""
    workflow_id = check_workflow_id(workflow_id)
    status_code, payload = _request("GET", f"/workflow/{workflow_id}")
    return _validate_summary(_expect(status_code, payload))


def is_budgeting(record: dict[str, Any]) -> bool:
    """This feature acts only on its own workflows; the shared server holds every feature's."""
    return record.get("feature") == FEATURE


def decide(workflow_id: str, decision: str, note: str = "", by: str = "budgeting-ui") -> dict[str, Any]:
    workflow_id = check_workflow_id(workflow_id)
    decision = (decision or "").strip().lower().replace(" ", "_").replace("-", "_")
    if decision not in DECISIONS:
        raise MultiAgentError(400, f"decision must be one of {', '.join(DECISIONS)}")
    note = (note or "").strip()
    if len(note) > MAX_NOTE_CHARS:
        raise MultiAgentError(400, f"note must be {MAX_NOTE_CHARS} characters or fewer")
    if decision == "partially_accept" and not note:
        raise MultiAgentError(400, "partially_accept needs a note saying what to correct")
    status_code, payload = _request("POST", f"/workflow/{workflow_id}/decision",
                                    {"decision": decision, "note": note, "by": by})
    return _validate_summary(_expect(status_code, payload))


def response(workflow_id: str) -> dict[str, Any]:
    """The final response as the server holds it (operator view).
    Raises MultiAgentError(409) while the decision is pending."""
    workflow_id = check_workflow_id(workflow_id)
    status_code, payload = _request("GET", f"/workflow/{workflow_id}/response")
    payload = _expect(status_code, payload)
    missing = [k for k in _RESPONSE_KEYS if k not in payload]
    if missing:
        raise MultiAgentError(502, f"final response is missing required fields: {', '.join(missing)}", payload)
    return payload


def customer_view(final: dict[str, Any]) -> dict[str, Any]:
    """What a customer may receive: the approved answer, nothing about the review.

    Accept and partially accept release the answer, its findings, the gaps the
    Worker named, the endpoints the evidence came from (paths only, no internal
    URLs) and, for a partial accept, the correction the person attached.
    Reject releases nothing beyond the fact of the decision. The Reviewer's
    verdict, summary and risks, the operator's name and the rejection note
    stay on the operator's side.
    """
    if not final.get("released"):
        return {"workflow_id": final.get("workflow_id"), "decision": final.get("decision"), "released": False}
    view = {
        "workflow_id": final.get("workflow_id"),
        "decision": final.get("decision"),
        "released": True,
        "released_at": final.get("released_at"),
        "answer": final.get("answer") or "",
        "findings": [{"statement": f.get("statement", "")} for f in final.get("findings") or [] if isinstance(f, dict)],
        "gaps": [str(g) for g in final.get("gaps") or []],
        "evidence_endpoints": sorted({str(e.get("endpoint")) for e in final.get("evidence_sources") or []
                                      if isinstance(e, dict) and e.get("endpoint")}),
    }
    if final.get("decision") == "partially_accept" and final.get("correction_note"):
        view["correction_note"] = final["correction_note"]
    return view


def pending() -> dict[str, Any]:
    status_code, payload = _request("GET", "/workflows/pending")
    return _expect(status_code, payload)


def health() -> dict[str, Any]:
    status_code, payload = _request("GET", "/health")
    if status_code != 200:
        raise MultiAgentError(status_code, f"Multi-Agent Server health returned HTTP {status_code}", payload)
    return payload


def status() -> dict[str, Any]:
    """Cheap summary for /api/agents/status."""
    info: dict[str, Any] = {"enabled": enabled(), "url": server_url(), "reachable": None}
    if not info["enabled"]:
        info["note"] = "disabled (MULTI_AGENT_ENABLED=false)"
        return info
    try:
        h = health()
        info["reachable"] = True
        info["pipeline"] = h.get("pipeline")
        info["pending"] = h.get("pending")
        info["auth"] = h.get("auth")
        info["models"] = h.get("models")
    except (MultiAgentUnreachable, MultiAgentError) as exc:
        info["reachable"] = False
        info["error"] = str(exc)
    return info
