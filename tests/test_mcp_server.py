"""Unit tests for the shared MCP server's pure functions and contract helpers.

No running server, no feature APIs, no network. The whole module is skipped
where the `mcp` SDK is not installed, so workflows that only install the
agentic-loop requirements still run `pytest tests/` cleanly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("mcp")

from mcp.server.fastmcp import FastMCP  # noqa: E402

from mcp_server.tools._contract import (  # noqa: E402
    ToolError,
    enforce_strict_arguments,
    require_customer_id,
    require_month,
    require_year,
)
from mcp_server.tools.transactions import _aggregate, _month_bounds  # noqa: E402


# ---------------------------------------------------------------------------
# transactions_spending: month window and spending aggregation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "month, year, expected",
    [
        (9, 2026, ("2026-09-01", "2026-09-30")),
        (2, 2026, ("2026-02-01", "2026-02-28")),
        (2, 2024, ("2026-02-01".replace("2026", "2024"), "2024-02-29")),   # leap year
        (12, 2026, ("2026-12-01", "2026-12-31")),                          # no rollover
    ],
)
def test_month_bounds_are_inclusive_and_end_on_the_last_day(month, year, expected):
    """The Transactions API filters with `date <= date_to`, so the window must
    end on the month's own last day - never the 1st of the next month."""
    assert _month_bounds(month, year) == expected


def test_aggregate_counts_only_money_leaving_the_account():
    rows = [
        {"amount": -50.00, "category": "Groceries", "type": "Withdrawal"},
        {"amount": 250.00, "category": "Salary", "type": "Deposit"},        # deposit: not spending
        {"amount": 120.00, "category": "Transfer", "type": "Transfer"},     # incoming transfer: not spending
        {"amount": -20.50, "category": "Groceries", "type": "Withdrawal"},
        {"amount": -75.00, "category": "Rent", "type": "Transfer"},         # outgoing transfer: spending
        {"amount": "not-a-number", "category": "Odd"},                      # unparseable: skipped
        {"amount": -9.99},                                                  # no category
    ]
    totals, counted = _aggregate(rows)
    assert totals == {"Groceries": 70.50, "Rent": 75.00, "Uncategorised": 9.99}
    assert counted == 4
    assert list(totals) == sorted(totals)          # stable, sorted output


# ---------------------------------------------------------------------------
# Input rules
# ---------------------------------------------------------------------------

def test_range_validators_accept_in_range_values():
    assert require_month(1) == 1 and require_month(12) == 12
    assert require_year(2000) == 2000 and require_year(2100) == 2100
    assert require_customer_id(1) == 1


@pytest.mark.parametrize("bad", [0, 13, -1])
def test_month_out_of_range_is_a_tool_error(bad):
    with pytest.raises(ToolError, match="month"):
        require_month(bad)


@pytest.mark.parametrize("bad", [1999, 2101])
def test_year_out_of_range_is_a_tool_error(bad):
    with pytest.raises(ToolError, match="year"):
        require_year(bad)


@pytest.mark.parametrize("bad", [0, -5])
def test_customer_id_must_be_positive(bad):
    with pytest.raises(ToolError, match="customer_id"):
        require_customer_id(bad)


# ---------------------------------------------------------------------------
# Access boundary: undeclared arguments are rejected, not ignored
# ---------------------------------------------------------------------------

def test_enforce_strict_arguments_rejects_undeclared_arguments():
    server = FastMCP("test")

    @server.tool()
    def echo(customer_id: int) -> dict:
        """Echo."""
        return {"customer_id": customer_id}

    tool = server._tool_manager.get_tool("echo")          # noqa: SLF001 - same access the helper uses
    model = tool.fn_metadata.arg_model
    model.model_validate({"customer_id": 1, "sql": "SELECT *"})   # FastMCP default: silently accepted

    enforce_strict_arguments(server)

    model = tool.fn_metadata.arg_model
    model.model_validate({"customer_id": 1})                       # declared arguments still fine
    with pytest.raises(Exception, match="[Ee]xtra"):
        model.model_validate({"customer_id": 1, "sql": "SELECT *"})
