---
source_id: mcp-server
title: Shared MCP server
authority_tier: 1
origin: mcp_server/ and README.md (extract, 2026-09-22)
---

# What it is

The shared MCP server is one local Model Context Protocol server used by all five SmartBank features. It is built on FastMCP from the official mcp Python SDK and served over streamable HTTP at http://localhost:8100/mcp. Containerised backends reach it at http://host.docker.internal:8100/mcp. It runs on the host with python -m mcp_server.server and is not a docker-compose service.

# Registered tools

budgeting_summary(customer_id, month, year) is owned by Bao and calls GET /api/budgets/summary; it returns totals, per-category limit, spent and status, the over-budget list, unbudgeted spending and the spending source. accounts_count(customer_id optional) is owned by William and calls GET /api/accounts; it returns the account count by status and by type with no account numbers or balances. loans_list(customer_id, status optional) is owned by David and calls GET /api/loans; it returns loan id, type, requested amount and status. fraud_alerts_count(customer_id optional, status optional) is owned by Khoi and calls GET /api/alerts; it returns the alert count by severity and by status. transactions_spending(customer_id, month, year) is owned by Aidan and calls GET /api/transactions; it returns total spent, totals by category and a transaction count with deposits excluded.

# Tool boundaries

Every tool is read-only and calls only GET endpoints. Each tool is bound to one endpoint of one feature and cannot be pointed elsewhere by its arguments. Tools return aggregates or listed fields only; balances, account numbers, merchant names and raw transactions do not cross the boundary. Argument types are enforced by the schema. Ranges are checked before the backend is called: month must be 1 to 12, year 2000 to 2100, customer_id at least 1. Arguments the schema does not declare are rejected, not ignored. No tool opens a SQLite file.

# Result semantics

On success the client receives isError false with structuredContent JSON and the same JSON as text, and every result carries a source block naming the feature, service URL and endpoint. A bad argument type, range or an undeclared argument gives isError true with a message naming the argument, and the backend is never called. A feature API being down gives isError true with the message "<feature> service unavailable" and a reason. An unknown tool name gives isError true with "Unknown tool".

# Validation

python -m mcp_server.validate runs eight checks: server reachable, tools/list publishes every tool, valid invocation, domain-invalid input rejected, type-invalid input rejected, undeclared argument rejected, unknown tool rejected, and dependency unavailable returns an explicit error. The --evidence flag saves docs/evidence/mcp-validation-<timestamp>.json. Configuration comes from .env: MCP_HOST, MCP_PORT and the *_SERVICE_URL variables.
