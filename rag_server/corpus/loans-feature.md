---
source_id: loans-feature
title: Loans and Credit feature
authority_tier: 1
origin: docs/features.md and services/loans (extract, 2026-09-22)
---

# Purpose

Loans and Credit, owned by David Lee, lets users create, view, update and delete loan applications and repayment schedules. An AI explains why a loan eligibility or approval decision was made and suggests repayment options.

# Ports

Frontend 3002, backend/API 5002, database service 5012. The feature ships as three Docker images built from its own Dockerfiles.

# API endpoints

GET /api/loans lists loan applications and accepts customer_id, status, loan_type, min_amount, max_amount, date_from, date_to and q filters. POST /api/loans submits a loan application. GET /api/loans/{id} returns one loan. GET /api/loans/{id}/eligibility returns eligibility information. POST /api/loans/{id}/decision records an approval or rejection decision. GET /api/repayments lists repayments, GET /api/repayments/upcoming lists upcoming payments, and GET /api/repayments/{id} returns one repayment.

# AI functions

Explain loan eligibility in plain language. Explain the reasons behind a loan approval or rejection. Explain repayment schedules and payment requirements. Compare repayment options and suggest a suitable one. Prompts live in prompts/loans as eligibility_task, decision_task, repayment_task, comparison_task and explanation_system text files.

# Database tables

LoanApplications: loan_id, customer_id, loan_type, requested_amount, loan_purpose, application_date, status, interest_rate, approved_amount. Repayments: repayment_id, loan_id, due_date, payment_amount, principal_amount, interest_amount, amount_paid, payment_date, payment_status.

# Loan eligibility checks

SmartBank evaluates four loan eligibility checks: `loan_type_supported`, `amount_within_limits`, `purpose_provided`, and `affordability`. An application is eligible only when all four checks pass.

- `loan_type_supported`: the requested type is PERSONAL, AUTO, EDUCATION, HOME, or BUSINESS.
- `amount_within_limits`: the requested amount is within the selected loan type's allowed minimum and maximum.
- `purpose_provided`: the application includes a loan purpose.
- `affordability`: the estimated monthly payment is at most 40% of monthly income. When monthly income is unavailable, this check is skipped and treated as passed.

# Cross-feature rule

Loans stores only the customer_id and should validate it against the Accounts API when a loan is created. Seeded loans belong to customers 1, 2 and 3, which exist in Accounts.
