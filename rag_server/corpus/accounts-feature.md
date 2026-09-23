---
source_id: accounts-feature
title: Accounts and Customers feature
authority_tier: 1
origin: docs/features.md and services/accounts (extract, 2026-09-22)
---

# Purpose

Accounts and Customers, owned by William Por, manages customer profiles and their bank accounts. Users can create, view, update and delete customers and accounts. The feature also produces an AI-generated plain-English summary of a customer's accounts and a basic customer risk profile.

# Source of truth for IDs

Accounts owns the customers and accounts tables. Every other feature stores only customer and account IDs and reads the rest through the Accounts API. The seed data defines customers 1 to 8 and accounts 1 to 11. Customer 1 is Amelia Turner with accounts 1 and 2. Customer 2 is Noah Whitfield with accounts 3 and 4. Other features must use these IDs and must not renumber them.

# Ports

Frontend 3001, backend/API 5001, database service 5011. In Release 0 the three tiers run as processes inside one container started by run.py.

# API endpoints

GET /api/customers lists customers. POST /api/customers creates one. GET, PUT and DELETE /api/customers/{id} read, update and delete one customer. GET /api/accounts lists accounts and accepts customer_id, status, account_type, min_balance, max_balance and q filters. POST /api/accounts creates an account. GET and PUT /api/accounts/{id} read and update one account. POST /api/accounts/{id}/close closes an account (soft delete, status becomes CLOSED). DELETE /api/accounts/{id} deletes it. GET /api/health reports the service status.

# AI endpoints

GET /customers/{id}/summary returns a plain-English account summary. GET /customers/{id}/risk-profile returns a basic risk profile with the AI explanation. GET /customers/{id}/history lists stored AI summaries.

# Database tables

Customers: customer_id, first_name, last_name, email, phone, date_of_birth, address, created_at, updated_at. Accounts: account_id, customer_id, account_number, account_type, balance, currency, status, created_at, updated_at. Account status is ACTIVE, INACTIVE or CLOSED. AI_Summaries: summary_id, customer_id, summary_type, summary_text, risk_level, created_at.

# Recommended delete behaviour

Prefer closing an account over deleting it, so the ID stays valid for features that reference it. Other features treat a 404 from Accounts as "unknown customer" rather than failing.
