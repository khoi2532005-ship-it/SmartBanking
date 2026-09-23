"""Tool registry - the one file the whole team edits.

One module per feature under `mcp_server/tools/`, each exposing
`register(mcp)`. Add yours here and it appears in `tools/list`.

    Feature        Module            Tool                      Owner
    Budgeting      budgeting.py      budgeting_summary         Bao
    Accounts       accounts.py       accounts_count            William
    Loans          loans.py          loans_list                David
    Fraud Alerts   fraud.py          fraud_alerts_count        Khoi
    Transactions   transactions.py   transactions_spending     Aidan

Every tool is read-only and calls its feature's existing HTTP API. No tool
opens a SQLite file, and no tool writes anything.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_server.tools import accounts, budgeting, fraud, loans, transactions

TOOL_MODULES = (budgeting, accounts, loans, fraud, transactions)


def register_all(mcp: FastMCP) -> None:
    for module in TOOL_MODULES:
        module.register(mcp)


def tool_names() -> list[str]:
    return [module.TOOL_NAME for module in TOOL_MODULES]
