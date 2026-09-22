---
source_id: budgeting-feature
title: Budgeting and Spending Insights feature
authority_tier: 1
origin: services/budgeting/README.md and docs/features.md (extract, 2026-09-22)
---

# Purpose

Budgeting and Spending Insights, owned by Cong Bao Nguyen, lets a customer set one monthly limit per spending category, tracks actual spending against each limit using real transaction data, and generates AI advice on what to adjust.

# Microservices and ports

budgets-frontend on port 3004 is an HTMX user interface served by nginx in Docker or serve.py in development. budgets-api on port 5004 holds the business logic, cross-feature calls and AI-Mode. budgets-db-api on port 5014 is the exclusive owner of the budgeting_and_insights.db SQLite file. The request flow is browser to budgets-frontend to budgets-api to budgets-db-api to SQLite. Nothing outside the database service opens the database file.

# Budget status rule

ON_TRACK means under 80 percent of the limit is used. NEAR_LIMIT means between 80 and 100 percent of the limit is used. OVER_BUDGET means spending has exceeded the limit; the response includes the over_by amount. Spending exactly equal to the limit is NEAR_LIMIT, not over. The 80 percent threshold is the constant NEAR_LIMIT_THRESHOLD in budget_logic.py.

# Budget API endpoints

GET /api/budgets lists budgets with customer_id, category, month and year filters. GET /api/budgets/summary returns budgets plus actual spend, percent used, status, over-budget flags, totals and unbudgeted spending for one customer and period. GET /api/budgets/{id} returns one budget with its spend and transactions. POST /api/budgets creates a budget and requires customer_id, category and monthly_limit greater than zero. PUT /api/budgets/{id} updates the limit, category or period. DELETE /api/budgets/{id} deletes a budget. GET /api/categories lists spending categories. GET /api/transactions/spending shows what the feature read from the Transactions API.

# AI-Mode endpoints

POST /api/budgets/insight generates a spending insight across all budgets for a month. POST /api/budgets/{id}/explain explains one category. GET /api/budgets/insights lists stored insight history. DELETE /api/budgets/insights/{id} deletes a stored insight. When the LLM provider is unreachable or no API key is set the AI endpoints return HTTP 503 with an explanatory message and CRUD is unaffected. Python computes every figure and the model only writes the prose around them.

# Cross-feature data

Actual spending is read only over HTTP from the Transactions API. USE_MOCK_TRANSACTIONS controls the fallback: auto tries the Transactions API and falls back to mock data on failure, true always uses mock data, false always uses the live API. Every response reports the source used in spending_source as transactions-api or mock, and the UI states it under the table.

# Database tables

budgets: budget_id, customer_id, category, monthly_limit, month, year, created_at, with a UNIQUE constraint on customer_id, category, month and year. budget_insights: insight_id, budget_id, insight_text, generated_at, model_used, with ON DELETE CASCADE to budgets. categories: category_id, name, description. Seeded with 14 budgets for customers 1 and 2, 10 insights and 10 categories.

# Tests

Thirteen checks in tests/test_budget_logic.py cover the budget maths and the mock transactions client. They run in CI in .github/workflows/student-4.yml.
