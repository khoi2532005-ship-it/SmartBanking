"""Typed client for the shared RAG server (Release 1).

The RAG server is a host process (python -m rag_server.server) reached at
RAG_SERVER_URL (http://host.docker.internal:8200 in Compose). This client
sends a question to POST /query and returns the grounded answer contract:

    answer, citations[], confidence_category, retrieval_summary,
    insufficient_context, generation, evidence[]

It validates that shape before handing it to a route, so the UI never
renders a half-formed answer as if it were grounded.

- RAG_ENABLED=false raises RAGDisabled before any network call (CI).
- A server that is down raises RAGUnreachable with a readable message and
  a 2s connect timeout. Generation is slower than retrieval, so the read
  timeout is generous (RAG_CLIENT_TIMEOUT, default 90s).
- A non-200 reply raises RAGError carrying the status and the server's own
  error message; a 503 means the LLM provider was unavailable and the
  payload still lists the evidence that was retrieved.
"""

from __future__ import annotations

import os
from typing import Any

import requests

DEFAULT_URL = "http://localhost:8200"
CONNECT_TIMEOUT = 2
START_HINT = "start it on the host with: python -m rag_server.server"

CONFIDENCE_CATEGORIES = ("High", "Medium", "Low", "Unknown")
_REQUIRED_KEYS = ("answer", "citations", "confidence_category", "retrieval_summary", "insufficient_context")


class RAGDisabled(RuntimeError):
    """RAG_ENABLED is off in this environment (for example CI)."""


class RAGUnreachable(RuntimeError):
    """The RAG server did not answer. Message is written for a person."""


class RAGError(RuntimeError):
    """The RAG server answered with an error status."""

    def __init__(self, status: int, message: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


# ---------------------------------------------------------------------------
# Settings - read at call time so tests and CI can flip them with the environment
# ---------------------------------------------------------------------------

def server_url() -> str:
    return (os.getenv("RAG_SERVER_URL", DEFAULT_URL).strip() or DEFAULT_URL).rstrip("/")


def enabled() -> bool:
    return os.getenv("RAG_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def _read_timeout() -> float:
    try:
        return float(os.getenv("RAG_CLIENT_TIMEOUT", "90"))
    except ValueError:
        return 90.0


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def _request(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    if not enabled():
        raise RAGDisabled("RAG integration is disabled in this environment (RAG_ENABLED=false)")

    url = f"{server_url()}{path}"
    try:
        response = requests.request(
            method, url, json=body, timeout=(CONNECT_TIMEOUT, _read_timeout())
        )
    except requests.ConnectionError:
        raise RAGUnreachable(f"RAG server at {url} refused the connection - {START_HINT}") from None
    except requests.Timeout:
        raise RAGUnreachable(f"RAG server at {url} did not answer within {_read_timeout():.0f}s") from None
    except requests.RequestException as exc:
        raise RAGUnreachable(f"request to RAG server at {url} failed: {type(exc).__name__}") from None

    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"error": response.text[:200] or "non-JSON response"}


def _validate_contract(payload: Any) -> dict[str, Any]:
    """Refuse to pass on anything that is not the grounded answer contract."""
    if not isinstance(payload, dict):
        raise RAGError(502, "RAG server returned a non-object response")
    missing = [k for k in _REQUIRED_KEYS if k not in payload]
    if missing:
        raise RAGError(502, f"RAG response is missing required fields: {', '.join(missing)}", payload)
    if payload["confidence_category"] not in CONFIDENCE_CATEGORIES:
        raise RAGError(502, f"RAG response has an unknown confidence category: {payload['confidence_category']!r}", payload)
    if not isinstance(payload["citations"], list):
        raise RAGError(502, "RAG response citations must be a list", payload)
    if payload["insufficient_context"] and payload["citations"]:
        raise RAGError(502, "RAG response claims insufficient context but carries citations", payload)
    return payload


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def query(question: str, k: int | None = None) -> dict[str, Any]:
    """Ask the shared RAG server; returns the validated grounded-answer contract."""
    question = (question or "").strip()
    if not question:
        raise RAGError(400, "query is required")
    body: dict[str, Any] = {"query": question}
    if k is not None:
        body["k"] = int(k)

    status_code, payload = _request("POST", "/query", body)
    if status_code == 200:
        return _validate_contract(payload)
    message = payload.get("error") if isinstance(payload, dict) else None
    raise RAGError(status_code, message or f"RAG server returned HTTP {status_code}",
                   payload if isinstance(payload, dict) else {})


def health() -> dict[str, Any]:
    status_code, payload = _request("GET", "/health")
    if status_code != 200:
        raise RAGError(status_code, f"RAG server health returned HTTP {status_code}", payload)
    return payload


def status() -> dict[str, Any]:
    """Cheap summary for /api/agents/status."""
    info: dict[str, Any] = {"enabled": enabled(), "url": server_url(), "reachable": None}
    if not info["enabled"]:
        info["note"] = "disabled (RAG_ENABLED=false)"
        return info
    try:
        h = health()
        info["reachable"] = True
        info["index"] = h.get("index")
        info["model"] = h.get("model")
    except (RAGUnreachable, RAGError) as exc:
        info["reachable"] = False
        info["error"] = str(exc)
    return info
