"""Settings and failure types shared by the MCP and RAG clients (Release 1).

Both shared servers run on the host, never in Compose, so this backend reaches
them over HTTP: http://host.docker.internal:<port> from inside Docker,
localhost when run directly. Each integration has an on/off flag
(MCP_ENABLED, RAG_ENABLED) so CI can run the image with both switched off
while the integration code stays in place.
"""

import os
from urllib.parse import urlparse

import requests


class ServerDisabled(RuntimeError):
    """The integration is switched off in this environment (e.g. CI)."""


class ServerUnavailable(RuntimeError):
    """The server did not answer. The message says why and what to do."""


class BadServerResponse(RuntimeError):
    """The server answered, but not with what its protocol promises."""


def flag_enabled(name):
    return os.getenv(name, "true").strip().lower() in ("1", "true", "yes", "on")


def setting(name, default):
    return os.getenv(name, "").strip() or default


# requests raises the same ConnectionError whether a host name did not resolve
# or nothing was listening, but the fixes differ, so the text is checked.
_NAME_NOT_RESOLVED = (
    "NameResolutionError",
    "getaddrinfo failed",
    "Name or service not known",
    "Temporary failure in name resolution",
    "nodename nor servname",
)


def unavailable(label, url, start_command, exc):
    """A ServerUnavailable a person can act on, from a requests exception."""
    if any(marker in repr(exc) for marker in _NAME_NOT_RESOLVED):
        host = urlparse(url).hostname
        return ServerUnavailable(
            f"{label} host {host} could not be resolved. On Linux Docker, give this "
            'service extra_hosts: ["host.docker.internal:host-gateway"].'
        )
    # A connect timeout is still "nothing listening" (Windows is slow to refuse
    # a closed port); only a read timeout means the server is up but slow.
    if isinstance(exc, requests.ReadTimeout):
        return ServerUnavailable(f"{label} at {url} accepted the request but did not answer in time")
    return ServerUnavailable(
        f"{label} at {url} is not reachable. Start it on the host with: {start_command}"
    )


def failure(exc):
    """(JSON body, HTTP status) for a failed MCP or RAG call, same shape for both routes."""
    if isinstance(exc, ServerDisabled):
        return {"error": str(exc), "disabled": True}, 503
    if isinstance(exc, ServerUnavailable):
        return {"error": str(exc), "unreachable": True}, 503
    return {"error": str(exc)}, 502
