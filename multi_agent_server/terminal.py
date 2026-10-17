"""Shared pieces of the terminal runners: HTTP to the server, rendering, prompts.

The runners talk to a running server over HTTP exactly as the app does, so a
decision made at the terminal and one made in the UI go through the same
endpoint and leave the same audit records.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable

import requests

from multi_agent_server import config
from multi_agent_server.models import DECISIONS

DECISION_KEYS = {"a": "accept", "p": "partially_accept", "r": "reject", "s": None}
PROMPT = "Decision  [A]ccept / [P]artially accept / [R]eject / [S]kip: "
NOTE_PROMPT = "Correction note (optional, Enter to skip): "


class ServerUnavailable(RuntimeError):
    pass


class InputClosed(EOFError):
    """stdin is closed: no interactive decision can be made (use --decision)."""


def positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive number of seconds")
    return value


def configure_console() -> None:
    """UTF-8 output even when redirected on Windows (cp1252 would crash on an arrow or emoji)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def require_note_for_partial(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.decision == "partially_accept" and not args.note:
        parser.error("--decision partially_accept needs --note saying what to correct")


class HttpClient:
    """The few calls the runners need, with the project's fail-fast timeouts."""

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = (base_url or config.local_url()).rstrip("/")
        self.token = config.API_TOKEN if token is None else token

    def get(self, path: str) -> tuple[int, Any]:
        return self._call("GET", path)

    def post(self, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        return self._call("POST", path, body)

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            response = requests.request(method, url, json=body, headers=headers,
                                        timeout=(config.CONNECT_TIMEOUT, config.READ_TIMEOUT))
        except requests.ConnectionError:
            raise ServerUnavailable(f"cannot reach the Multi-Agent Server at {self.base_url} "
                                    "- start it with: python -m multi_agent_server.server") from None
        except requests.RequestException as exc:
            raise ServerUnavailable(f"request to {url} failed: {type(exc).__name__}") from None
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": f"non-JSON response from {url}"}
        if response.status_code == 401:
            raise ServerUnavailable("the server requires a bearer token: set MULTI_AGENT_API_TOKEN in .env "
                                    "to the same value the server uses")
        return response.status_code, payload


class FlaskClientAdapter:
    """Same interface over a Flask test client (tests and the validate script)."""

    def __init__(self, test_client: Any, token: str = "") -> None:
        self.client = test_client
        self.base_url = "flask://test"
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def get(self, path: str) -> tuple[int, Any]:
        response = self.client.get(path, headers=self.headers)
        return response.status_code, response.get_json()

    def post(self, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        response = self.client.post(path, json=body, headers=self.headers)
        return response.status_code, response.get_json()


# ---------------------------------------------------------------- rendering

def _wrap(label: str, text: str, width: int = 96) -> str:
    indent = " " * 12
    words, lines, line = str(text).split(), [], ""
    for word in words:
        if line and len(line) + 1 + len(word) > width - len(indent):
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    if not lines:
        lines = ["(none)"]
    return f"  {label:<9} {lines[0]}" + "".join(f"\n{indent}{more}" for more in lines[1:])


def render_workflow(full: dict[str, Any]) -> str:
    """One readable block per workflow: request, plan, evidence, result, review."""
    plan = full.get("plan") or {}
    result = full.get("result") or {}
    review = full.get("review") or {}
    out = [f"{full['workflow_id']}  {full['feature']}  state {full['state']}  created {full['created_at']}"]
    out.append(_wrap("Request:", full["request"]))
    out.append(_wrap("Context:", json.dumps(full.get("context") or {}, sort_keys=True)))
    if plan:
        meta = plan.get("meta") or {}
        out.append(_wrap("Plan:", f"{plan.get('objective', '')} ({len(plan.get('tasks', []))} tasks, "
                                  f"source {meta.get('source', '?')}, {meta.get('model', '?')})"))
        for task in plan.get("tasks", []):
            if task["kind"] == "api":
                out.append(f"            {task['id']} GET {task['endpoint']} {json.dumps(task['params'], sort_keys=True)}")
            else:
                out.append(f"            {task['id']} analysis (after {', '.join(task.get('depends_on', []))}): {task.get('instruction', '')}")
    for record in result.get("evidence", []):
        status = (f"ok HTTP {record['http_status']} {record['duration_seconds']}s" if record["status"] == "ok"
                  else f"ERROR {record['error']}")
        out.append(_wrap("Evidence:", f"{record['task_id']} {record['url']} -> {status}"))
    for finding in result.get("findings", []):
        out.append(_wrap("Finding:", f"{finding['task_id']} <- {', '.join(finding['evidence'])}: {finding['statement']}"))
    if result:
        meta = result.get("meta") or {}
        out.append(_wrap("Answer:", f"{result.get('answer') or '(none)'}  [source {meta.get('source', '?')}, "
                                    f"attempt {meta.get('attempt', '?')}]"))
        for gap in result.get("gaps", []):
            out.append(_wrap("Gap:", gap))
        if result.get("request_only_numbers"):
            out.append(_wrap("Unproven:", "figures " + ", ".join(result["request_only_numbers"])
                             + " come from the request, not from the evidence"))
    if review:
        meta = review.get("meta") or {}
        criteria = review.get("criteria", [])
        met = sum(1 for c in criteria if c.get("met") is True)
        verdict = review.get("verdict", "?") + (" (escalated: " + review.get("escalation_reason", "") + ")"
                                               if review.get("escalated") else "")
        out.append(_wrap("Review:", f"{verdict}  [source {meta.get('source', '?')}, attempt {meta.get('attempt', '?')}, "
                                    f"criteria met {met}/{len(criteria)}]"))
        out.append(_wrap("", review.get("summary", "")))
        for defect in review.get("defects", []):
            out.append(_wrap("Defect:", f"[{defect.get('severity')}] {defect.get('about', '')}: {defect.get('note', '')}"))
        for risk in review.get("risks", []):
            out.append(_wrap("Risk:", risk))
    if full.get("revisions"):
        out.append(_wrap("Revisions:", str(full["revisions"])))
    if full.get("error"):
        out.append(_wrap("Error:", full["error"]))
    return "\n".join(out)


def render_response(response: dict[str, Any]) -> str:
    if not response.get("released"):
        return (f"  Decision {response.get('decision')}: response withheld."
                + (f" Note: {response['correction_note']}" if response.get("correction_note") else ""))
    out = [f"  Decision {response['decision']}: response released at {response.get('released_at')} by {response.get('decided_by')}"]
    out.append(_wrap("Answer:", response.get("answer") or "(none)"))
    if response.get("correction_note"):
        out.append(_wrap("Correction:", response["correction_note"]))
    if response.get("request_only_numbers"):
        out.append(_wrap("Unproven:", "figures " + ", ".join(response["request_only_numbers"])
                         + " come from the request, not from the evidence"))
    for risk in response.get("risks", []):
        out.append(_wrap("Risk:", risk))
    return "\n".join(out)


# ---------------------------------------------------------------- prompting

def prompt_decision(input_fn: Callable[[str], str] = input, out: Callable[[str], None] = print
                    ) -> tuple[str | None, str]:
    """Ask until one of the four keys is given. Returns (decision or None for skip, note)."""
    while True:
        try:
            raw = input_fn(PROMPT)
        except EOFError:
            raise InputClosed("stdin is closed; use --decision, or run from an interactive terminal") from None
        key = (raw or "").strip().lower()[:1]
        if key in DECISION_KEYS:
            decision = DECISION_KEYS[key]
            break
        out(f"  Please answer A, P, R or S (one of {list(DECISIONS)} or skip).")
    if decision is None:
        return None, ""
    prompt = NOTE_PROMPT if decision != "partially_accept" else "Correction note (required for partially accept): "
    while True:
        try:
            note = input_fn(prompt).strip()
        except EOFError:
            raise InputClosed("stdin is closed before the note; use --decision and --note") from None
        if note or decision != "partially_accept":
            return decision, note
        out("  Partially accept needs a note saying what to correct.")


def send_decision(client: Any, workflow_id: str, decision: str, note: str, by: str) -> tuple[int, Any]:
    return client.post(f"/workflow/{workflow_id}/decision", {"decision": decision, "note": note, "by": by})


def fail(message: str, out: Callable[[str], None] = print) -> int:
    out(f"error: {message}")
    return 1


def stdout(line: str) -> None:
    print(line)
    sys.stdout.flush()
