---
source_id: transactions-feature
title: Transactions feature
authority_tier: 1
origin: docs/features.md and services/transactions (extract, 2026-09-22)
---

# Purpose

Transactions, owned by Aidan Lei, lets users create, record and view deposits, withdrawals and transfers on their accounts. Transactions are categorised automatically by AI and unusual spending patterns can be flagged. Transaction data is exposed through the API for other features, particularly Fraud Alerts and Budgeting.

# Ports

Frontend 3005, backend/API 5005, database service 5015. In Release 0 the three tiers run as processes inside one container started by run.py.

# API endpoints

GET /api/transactions lists transactions and accepts account_id, customer_id, type, category, min_amount, max_amount, date_from, date_to and q filters. POST /api/transactions creates a transaction and requires account_id, amount, currency, type and date. GET /api/transactions/{id} returns one transaction. PUT /api/transactions/{id} updates account_id, amount, currency, type, category, description or date. DELETE /api/transactions/{id} deletes one. GET /api/accounts and GET /api/customers proxy account and customer data.

# Transaction record fields

transaction_id, account_id, customer_id, amount, currency, type, category, description and date. Type is Deposit, Withdrawal or Transfer. Withdrawal and transfer amounts are stored as negative numbers. Date is an ISO date string such as 2026-09-12.

# AI categorisation

When a transaction is created the description is sent to the LLM, which returns one category from groceries, rent, utilities, entertainment, transportation, healthcare, dining, shopping, income, transfer or other. If the model fails the category supplied in the request is kept.

# Cross-feature rule

Transactions owns the transactions table. Customer and account data belong to Accounts and are referenced by ID. Account existence is validated through the Accounts API. Budgeting reads spending from GET /api/transactions filtered by customer_id, date_from and date_to. Fraud Alerts reads the same endpoint to run detection.
