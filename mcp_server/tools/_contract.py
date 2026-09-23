"""Shared pieces of every tool contract.

Lecture 7 (Tool Contracts): a tool exposes one bounded operation, validates
its inputs before touching the backend, returns a structured result, and on
any validation, backend or domain failure returns a tool result with
`isError: true` and actionable error content - never an invented result.

FastMCP already turns a raised `ToolError` into exactly that error result and
rejects wrongly-typed arguments before the function runs. The helpers here add
the two things it does not do on its own: range checks on otherwise valid
integers, and rejecting arguments the schema never declared.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_server.http import UpstreamError

__all__ = [
    "ToolError",
    "enforce_strict_arguments",
    "require_customer_id",
    "require_month",
    "require_year",
    "source",
    "upstream",
]


# ---------------------------------------------------------------------------
# Input rules
# ---------------------------------------------------------------------------

def require_customer_id(customer_id: int) -> int:
    if customer_id < 1:
        raise ToolError(f"customer_id must be a positive integer, got {customer_id}")
    return customer_id


def require_month(month: int) -> int:
    if not 1 <= month <= 12:
        raise ToolError(f"month must be between 1 and 12, got {month}")
    return month


def require_year(year: int) -> int:
    if not 2000 <= year <= 2100:
        raise ToolError(f"year must be between 2000 and 2100, got {year}")
    return year


# ---------------------------------------------------------------------------
# Result semantics
# ---------------------------------------------------------------------------

def source(feature: str, base_url: str, path: str) -> dict[str, str]:
    """Every result names the system of record it came from, for traceability."""
    return {"feature": feature, "service_url": base_url, "endpoint": path}


@contextmanager
def upstream(feature: str) -> Iterator[None]:
    """Turn an unreachable or failing feature API into a clean tool error.

    The message names the feature and says what went wrong, so the caller
    (a backend, the agentic loop, a person at a terminal) can act on it.
    """
    try:
        yield
    except UpstreamError as exc:
        raise ToolError(f"{feature} service unavailable: {exc}") from None


# ---------------------------------------------------------------------------
# Access boundary: unknown arguments are rejected, not ignored
# ---------------------------------------------------------------------------

def enforce_strict_arguments(mcp: FastMCP) -> None:
    """Make every registered tool reject arguments its schema does not declare.

    Lecture 7's invalid-input test is `{"sql": "SELECT *"}` being refused
    before the backend is invoked. FastMCP validates declared arguments but
    silently drops extra ones, so this tightens the generated argument model
    of each tool to `extra = "forbid"`. It reaches into the tool manager,
    which is a private attribute of FastMCP 1.x; the validate script checks
    the behaviour so an SDK upgrade that breaks this is caught, not missed.
    """
    for tool in mcp._tool_manager.list_tools():  # noqa: SLF001 - see docstring
        model = tool.fn_metadata.arg_model
        model.model_config["extra"] = "forbid"
        model.model_rebuild(force=True)
