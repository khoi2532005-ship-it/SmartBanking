"""RAG client for the loans backend.

The shared RAG server (rag_server/) runs on the host at localhost:8200;
Compose containers reach it through RAG_SERVICE_URL (defaults to
http://host.docker.internal:8200). This module also owns the RAG mode gate,
mirroring mcp_mode.py: RAG_ENABLED in the environment AND the X-RAG-Mode
header both have to be on for a request to reach the shared server.
"""

from __future__ import annotations

import os

import requests

RAG_SERVICE_URL = os.getenv("RAG_SERVICE_URL", "http://localhost:8200")

try:
    RAG_SERVICE_TIMEOUT_SECONDS = int(os.getenv("RAG_SERVICE_TIMEOUT_SECONDS", "180"))
except ValueError:
    RAG_SERVICE_TIMEOUT_SECONDS = 180


def rag_mode_is_enabled(req) -> bool:
    enabled = os.getenv("RAG_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        return False
    mode_header = req.headers.get("X-RAG-Mode", "on").strip().lower()
    return mode_header in ("1", "true", "yes", "on")


def rag_disabled_response():
    return {"status": "error", "error": "RAG Mode is disabled."}, 403


def call_rag_service(path: str, payload: dict):
    """POST `<path>` to the shared RAG server and return its JSON body."""
    try:
        response = requests.post(
            f"{RAG_SERVICE_URL}{path}",
            json=payload,
            timeout=RAG_SERVICE_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise requests.RequestException(
            f"shared RAG server at {RAG_SERVICE_URL} did not answer: {type(exc).__name__}. "
            "Start it with 'python -m rag_server.server'."
        ) from exc

    try:
        data = response.json()
    except ValueError:
        response.raise_for_status()
        return {}

    if response.status_code >= 400:
        raise requests.HTTPError(
            f"RAG service {path} failed with status {response.status_code}: {data}"
        )

    return data