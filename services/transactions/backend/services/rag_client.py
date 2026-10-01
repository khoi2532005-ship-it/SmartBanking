"""Typed client for the shared RAG server (Release 1)."""

from __future__ import annotations

import os
from typing import Any

import requests

DEFAULT_URL = "http://localhost:8200"
CONNECT_TIMEOUT = 2
START_HINT = "start it on the host with: python -m rag_server.server"

CONFIDENCE_CATEGORIES = ("High", "Medium", "Low", "Unknown")
MAX_QUERY_CHARS = 1000
_REQUIRED_KEYS = ("answer", "citations", "confidence_category", "retrieval_summary", "insufficient_context")


class RAGDisabled(RuntimeError):
    """RAG_ENABLED is off in this environment."""


class RAGUnreachable(RuntimeError):
    """The RAG server did not answer."""


class RAGError(RuntimeError):
    """The RAG server answered with an error status."""

    def __init__(self, status: int, message: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


def server_url() -> str:
    return (os.getenv("RAG_SERVER_URL", DEFAULT_URL).strip() or DEFAULT_URL).rstrip("/")


def enabled() -> bool:
    return os.getenv("RAG_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def _read_timeout() -> float:
    try:
        return float(os.getenv("RAG_CLIENT_TIMEOUT", "90"))
    except ValueError:
        return 90.0


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    if not enabled():
        raise RAGDisabled("RAG integration is disabled in this environment (RAG_ENABLED=false)")

    url = f"{server_url()}{path}"
    try:
        response = requests.request(
            method, url, json=body, timeout=(CONNECT_TIMEOUT, _read_timeout())
        )
    except requests.ConnectionError:
        raise RAGUnreachable(f"shared RAG server at {url} refused the connection - {START_HINT}") from None
    except requests.Timeout:
        raise RAGUnreachable(f"shared RAG server at {url} did not answer within {_read_timeout():.0f}s") from None
    except requests.RequestException as exc:
        raise RAGUnreachable(f"request to shared RAG server at {url} failed: {type(exc).__name__}") from None

    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"error": response.text[:200] or "non-JSON response"}


def _validate_contract(payload: Any) -> dict[str, Any]:
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


def query(question: str, k: int | None = None) -> dict[str, Any]:
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
    raise RAGError(status_code, message or f"RAG server returned HTTP {status_code}", payload if isinstance(payload, dict) else {})


def health() -> dict[str, Any]:
    status_code, payload = _request("GET", "/health")
    if status_code != 200:
        raise RAGError(status_code, f"RAG server health returned HTTP {status_code}", payload)
    return payload


def status() -> dict[str, Any]:
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
