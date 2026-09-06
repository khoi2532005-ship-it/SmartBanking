"""HTTP helpers for collectors.

Collectors call services over HTTP, and the raw `requests` exception for a
service that simply is not running is four lines of connection-pool noise -
unreadable on a projector at a showcase. `get_json` turns that into one short
sentence, so every mode reports failures the same readable way without
repeating the try/except.
"""

from __future__ import annotations

from typing import Any

import requests

DEFAULT_TIMEOUT = 10


class ServiceUnreachable(Exception):
    """A service did not answer, or answered with something unusable."""


def get_json(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> Any:
    """GET `url` and return parsed JSON, or raise ServiceUnreachable.

    The message is written to be shown to a person, not logged: it says what
    failed in a few words and leaves the "how to fix it" to the caller, which
    knows which container to name.
    """
    try:
        response = requests.get(url, timeout=timeout)
    except requests.ConnectionError:
        raise ServiceUnreachable("connection refused - is the service running?") from None
    except requests.Timeout:
        raise ServiceUnreachable(f"no response within {timeout}s") from None
    except requests.RequestException as exc:
        raise ServiceUnreachable(f"request failed: {type(exc).__name__}") from None

    if response.status_code >= 400:
        # A 503 from our own services carries a useful JSON error body.
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict) and body.get("error"):
                detail = f" - {body['error']}"
        except ValueError:
            pass
        raise ServiceUnreachable(f"HTTP {response.status_code}{detail}")

    try:
        return response.json()
    except ValueError:
        raise ServiceUnreachable("response was not JSON") from None
