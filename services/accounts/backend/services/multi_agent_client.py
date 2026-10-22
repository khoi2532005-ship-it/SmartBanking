"""Client for the shared Multi-Agent Server (Release 2).

The server (python -m multi_agent_server.server on the host, port 8300) turns
a request into a workflow: it runs Planner -> Worker -> Reviewer in the
background, then waits for a person, and nothing is released until that
decision is posted. Every call here answers at once, so the read timeout is
short.

    start(task, customer_id)            POST /workflow               -> 202 summary
    workflow(workflow_id)               GET  /workflow/<id>          -> the full record
    review(workflow_id, decision, ...)  POST /workflow/<id>/decision -> summary + final response
    history()                           GET  /workflows              -> this feature's workflows

The server holds every feature's workflows. This client returns and decides
accounts ones only: another feature's workflow is "not found" here. The
routes (routes/agents.py) check every input before anything is sent.
"""

import requests

from services.local_servers import BadServerResponse, ServerDisabled, ServerUnavailable, flag_enabled, setting, unavailable

DEFAULT_URL = "http://localhost:8300"
START_COMMAND = "python -m multi_agent_server.server"
CONNECT_TIMEOUT = 2
READ_TIMEOUT = 10
FEATURE = "accounts"


class WorkflowRefused(RuntimeError):
    """The server answered 4xx: an unknown workflow, one already decided, a value it refused."""

    def __init__(self, status, message, payload):
        super().__init__(message)
        self.status = status
        self.payload = payload


def enabled():
    return flag_enabled("MULTI_AGENT_ENABLED")


def server_url():
    return setting("MULTI_AGENT_SERVER_URL", DEFAULT_URL).rstrip("/")


def _call(method, path, body=None):
    """The JSON body of a 2xx reply, or the failure that says why there is none."""
    if not enabled():
        raise ServerDisabled("Multi-Agent is switched off in this environment (MULTI_AGENT_ENABLED=false)")

    base = server_url()
    token = setting("MULTI_AGENT_API_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = requests.request(method, f"{base}{path}", json=body, headers=headers,
                                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
    except requests.RequestException as exc:
        raise unavailable("Multi-Agent Server", base, START_COMMAND, exc) from None

    status = response.status_code
    if status == 401:
        # A configuration problem, not a refusal: the two sides hold different tokens.
        raise ServerUnavailable("the Multi-Agent Server requires a bearer token: set MULTI_AGENT_API_TOKEN "
                                "to the value the server uses")
    try:
        payload = response.json()
    except ValueError:
        raise BadServerResponse(f"Multi-Agent Server answered HTTP {status} without JSON") from None
    if status >= 500:
        # The server's own error text stays in its log; the page learns only that it failed.
        raise BadServerResponse(f"Multi-Agent Server failed (HTTP {status})")
    if status >= 400:
        payload = payload if isinstance(payload, dict) else {}
        raise WorkflowRefused(status, payload.get("error") or f"Multi-Agent Server answered HTTP {status}", payload)
    return payload


def _accounts_only(record, workflow_id):
    if not isinstance(record, dict) or record.get("feature") != FEATURE:
        raise WorkflowRefused(404, f"unknown accounts workflow {workflow_id}", {})
    return record


def start(task, customer_id):
    """Start a workflow about one customer. Returns the server's 202 summary."""
    summary = _call("POST", "/workflow", {"feature": FEATURE, "request": task, "context": {"customer_id": customer_id}})
    if not isinstance(summary, dict) or "workflow_id" not in summary:
        raise BadServerResponse("Multi-Agent Server started a workflow without returning its id")
    return summary


def workflow(workflow_id):
    """The full record: plan, Worker result, review, decision, final response."""
    return _accounts_only(_call("GET", f"/workflow/{workflow_id}"), workflow_id)


def review(workflow_id, decision, note="", reviewer=""):
    """Post the reviewer's decision. The feature is checked first, so another
    feature's workflow is never decided from here; the server itself refuses a
    workflow that is not awaiting a decision (409)."""
    _accounts_only(_call("GET", f"/workflow/{workflow_id}/status"), workflow_id)
    by = f"accounts-ui:{reviewer}" if reviewer else "accounts-ui"
    return _call("POST", f"/workflow/{workflow_id}/decision", {"decision": decision, "note": note, "by": by})


def history():
    """This feature's workflows, newest first (the server's order)."""
    workflows = _call("GET", "/workflows")
    if not isinstance(workflows, list):
        raise BadServerResponse("Multi-Agent Server's workflow list is not a list")
    return [w for w in workflows if isinstance(w, dict) and w.get("feature") == FEATURE]
