"""One HTTP helper for the Worker, in the MCP tools' client pattern.

Mirrors mcp_server/http.py: every failure becomes one short sentence that can
be shown to a person and written to the audit, instead of connection-pool
noise. The Worker only ever reads feature APIs over HTTP; it never opens a
database file.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

from multi_agent_server import config


class UpstreamError(Exception):
    """The feature API did not answer, or answered with something unusable."""


@dataclass
class FetchResult:
    url: str
    status_code: int
    payload: Any
    duration_seconds: float


def build_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def fetch(base_url: str, path: str, params: dict[str, Any] | None = None) -> FetchResult:
    """GET `<base_url><path>` and return the parsed JSON, or raise UpstreamError."""
    clean = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    url = build_url(base_url, path)
    started = time.monotonic()
    try:
        response = requests.get(url, params=clean, timeout=(config.CONNECT_TIMEOUT, config.READ_TIMEOUT))
    except requests.ConnectionError:
        raise UpstreamError(f"connection refused at {url} - is the service running?") from None
    except requests.Timeout:
        raise UpstreamError(f"no response from {url} within {config.READ_TIMEOUT}s") from None
    except requests.RequestException as exc:
        raise UpstreamError(f"request to {url} failed: {type(exc).__name__}") from None
    duration = round(time.monotonic() - started, 3)

    if response.status_code >= 400:
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict) and body.get("error"):
                detail = f" - {body['error']}"
        except ValueError:
            pass
        raise UpstreamError(f"HTTP {response.status_code} from {url}{detail}")

    try:
        payload = response.json()
    except ValueError:
        raise UpstreamError(f"response from {url} was not JSON") from None
    return FetchResult(url=url, status_code=response.status_code, payload=payload, duration_seconds=duration)
