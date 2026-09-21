"""One HTTP helper for every tool.

Mirrors `agentic/net.py`: the raw `requests` exception for a service that is
not running is several lines of connection-pool noise, so this turns every
failure into one short sentence that can be shown to a person as the tool's
error content.
"""

from __future__ import annotations

from typing import Any

import requests

from mcp_server import config


class UpstreamError(Exception):
    """The feature API did not answer, or answered with something unusable."""


def get_json(base_url: str, path: str, params: dict[str, Any] | None = None) -> Any:
    """GET `<base_url><path>` and return parsed JSON, or raise UpstreamError."""
    clean = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    url = f"{base_url.rstrip('/')}{path}"
    try:
        response = requests.get(
            url, params=clean, timeout=(config.CONNECT_TIMEOUT, config.READ_TIMEOUT)
        )
    except requests.ConnectionError:
        raise UpstreamError(f"connection refused at {url} - is the service running?") from None
    except requests.Timeout:
        raise UpstreamError(f"no response from {url} within {config.READ_TIMEOUT}s") from None
    except requests.RequestException as exc:
        raise UpstreamError(f"request to {url} failed: {type(exc).__name__}") from None

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
        return response.json()
    except ValueError:
        raise UpstreamError(f"response from {url} was not JSON") from None
