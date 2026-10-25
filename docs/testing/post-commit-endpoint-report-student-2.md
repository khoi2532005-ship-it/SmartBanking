# Post-commit endpoint test report - Student 2 (Loans & Credit)

Workflow `student-2-loans-ci`, job `smoke-check`, run
[39757287753](https://github.com/khoi2532005-ship-it/SmartBanking/actions/runs/39757287753)
on `loans-and-credit`, commit `f5125cc`, 2026-10-22T09:43:28Z.
Target `http://localhost:5002`; MCP, RAG and Multi-Agent were disabled.
Result: **passed**, 7/7 endpoint tests passed, 21 checks.

| Endpoint | Test | Outcome | Checks | Seconds |
|---|---|---|---:|---:|
| `GET /api/health` | `test_service_health` | passed | 3 | 0.004 |
| `GET /api/loans` | `test_loans_exist` | passed | 3 | 0.017 |
| `GET /api/loans/{loan_id}` | `test_loan_by_id` | passed | 3 | 0.010 |
| `GET /api/loans/{loan_id}/eligibility` | `test_loan_eligibility` | passed | 4 | 0.009 |
| `GET /api/repayments` | `test_repayments_exist` | passed | 3 | 0.004 |
| `GET /api/repayments/{repayment_id}` | `test_repayment_by_id` | passed | 3 | 0.009 |
| `GET /api/repayments/upcoming` | `test_upcoming_repayments` | passed | 2 | 0.007 |

Total test duration: 0.221 seconds. Pytest exit status: 0.

## GET /api/health

- pass: the health endpoint answers 200
- pass: the service identifies itself as `loan-service`
- pass: Multi-Agent is disabled

## GET /api/loans

- pass: the loans endpoint answers 200
- pass: the response contains at least one loan
- pass: every loan has `loan_id`, `customer_id`, `loan_type` and `status`

## GET /api/loans/{loan_id}

- pass: a loan is available to look up
- pass: the loan-by-id endpoint answers 200
- pass: the response `loan_id` matches the requested id

## GET /api/loans/{loan_id}/eligibility

- pass: a loan is available for the eligibility check
- pass: the eligibility endpoint answers 200
- pass: the response `loan_id` matches the requested id
- pass: eligibility contains `eligible` and `checks` fields

## GET /api/repayments

- pass: the repayments endpoint answers 200
- pass: the response contains at least one repayment
- pass: every repayment has `repayment_id`, `loan_id` and `due_date`

## GET /api/repayments/{repayment_id}

- pass: a repayment is available to look up
- pass: the repayment-by-id endpoint answers 200
- pass: the response `repayment_id` matches the requested id

## GET /api/repayments/upcoming

- pass: the upcoming-repayments endpoint answers 200
- pass: the response is a list
