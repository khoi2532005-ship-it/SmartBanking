"""Typed client for the shared Multi-Agent Server (Release 2).

The server is a host process (python -m multi_agent_server.server) reached at
MULTI_AGENT_SERVER_URL (http://host.docker.internal:8300 in Compose). A
request becomes a workflow that runs Planner -> Worker -> Reviewer and then
waits for a person; the final response exists only after that decision.

    start()            POST /workflow                 -> 202 summary {workflow_id, state, stages}
    workflow_status()  GET  /workflow/<id>/status     -> summary: state, stages, decision, released
    workflow()         GET  /workflow/<id>            -> the whole record: plan, result, review, decision, final_response
    decide()           POST /workflow/<id>/decision   -> accept | partially_accept | reject (+ note, by)
    history()          GET  /workflows                -> every workflow the server holds, newest first

Every call that names a workflow checks the id's shape first, so nothing but
a workflow id is ever placed in a server URL. The routes keep this feature to
its own workflows with is_budgeting().

- MULTI_AGENT_ENABLED=false raises MultiAgentDisabled before any network call (CI).
- A server that is down raises MultiAgentUnreachable with a readable message
  and a 2 s connect timeout. Every call here answers quickly (the server runs
  the stages in the background), so the read timeout is short
  (MULTI_AGENT_CLIENT_TIMEOUT, default 10 s).
- A non-2xx reply raises MultiAgentError carrying the status and the server's
  own error message; a 409 from decide() means the workflow is not waiting.
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
    """The whole record: stages, plan, result, review, decision and final response."""
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


def history() -> list[dict[str, Any]]:
    """Every workflow the server holds, all features, newest first."""
    status_code, payload = _request("GET", "/workflows")
    if status_code != 200:
        _expect(status_code, payload)                      # raises with the server's reason
    if not isinstance(payload, list) or not all(isinstance(w, dict) for w in payload):
        raise MultiAgentError(502, "Multi-Agent Server returned a non-list workflow listing")
    return sorted(payload, key=lambda w: str(w.get("created_at") or ""), reverse=True)


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
