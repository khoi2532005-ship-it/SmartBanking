---
source_id: fraud-alerts-feature
title: Fraud Alerts feature
authority_tier: 1
origin: docs/features.md and services/fraud-alerts (extract, 2026-09-22)
---

# Purpose

Fraud Alerts, owned by Duc Minh Khoi Tran, monitors account activity and raises alerts when transactions look suspicious. Users view an alert dashboard, filter and sort alerts by status, date and amount, open an alert to see full details and an AI explanation, update alert status and delete alerts. Users also manage detection rules and can run detection across transactions.

# Ports

Frontend 3003, backend/API 5003, database service 5013. Three Docker images.

# API endpoints

GET /api/alerts lists alerts and accepts status, rule_id, customer_id, min_amount, max_amount, date_from, date_to and q filters. GET /api/alerts/{id} returns one alert. POST /api/alerts creates an alert. Alert status is updated to reviewed, dismissed or confirmed. GET /api/rules lists detection rules, GET /api/rules/{id} returns one, POST /api/rules creates one. POST /api/detection/run evaluates transactions against the enabled rules and creates alert records for breaches.

# How detection gets its data

Fraud Alerts reads transactions over HTTP from the Transactions API at GET /api/transactions and never opens the Transactions database file. TRANSACTIONS_SOURCE=http uses the live API; TRANSACTIONS_SOURCE=seed uses a local sample fixture. Account context for AI explanations comes from the Accounts API at GET /api/customers/{id} and is optional: if Accounts is unreachable the explanation is generated without it.

# AI explanation

The backend builds a prompt from the flagged transaction, the triggered rule and the account context, sends it to the LLM and returns a plain-English explanation of why the transaction was flagged. The explanation is stored on the alert.

# Database tables

AlertRules: rule_id, rule_name, rule_type, threshold values, severity, enabled, created_date. Alerts: alert_id, rule_id, customer_id, transaction_id, transaction_amount, transaction_recipient, transaction_datetime, transaction_category, severity, status, ai_explanation, explanation_generated_date, created_date. Severity is low, medium or high.
