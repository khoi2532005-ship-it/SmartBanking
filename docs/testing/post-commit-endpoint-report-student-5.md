# Post-commit endpoint test report - Student 5 (Transactions)

Workflow `student-5-transactions-ci`, job `endpoint-tests`, a local run, commit `ddd6881`, 2026-10-26T12:40:41Z.
Target `http://localhost:5005`; MCP, RAG and Multi-Agent were disabled.
Result: **passed**, 5/5 endpoint tests passed, 14 checks.

| Endpoint | Test | Outcome | Checks | Seconds |
|---|---|---|---:|---:|
| `GET /api/health` | `test_service_health` | passed | 3 | 0.026 |
| `GET /api/transactions` | `test_transactions_list` | passed | 3 | 0.018 |
| `POST /api/transactions` | `test_create_transaction` | passed | 3 | 0.062 |
| `GET /api/transactions/{transaction_id}` | `test_transaction_by_id` | passed | 3 | 0.024 |
| `DELETE /api/transactions/{transaction_id}` | `test_delete_transaction` | passed | 2 | 0.021 |

Total test duration: 0.151 seconds. Pytest exit status: 0.

## GET /api/health

- pass: the health endpoint answers 200
- pass: the service identifies itself as transactions-service
- pass: the service status is running

## GET /api/transactions

- pass: the transactions endpoint answers 200
- pass: the response contains at least one transaction
- pass: every transaction has transaction_id, account_id, amount, and date

## POST /api/transactions

- pass: the create transaction endpoint answers 201
- pass: the response contains a positive transaction_id
- pass: the response confirms transaction creation

## GET /api/transactions/{transaction_id}

- pass: the transaction-by-id endpoint answers 200
- pass: the response transaction_id matches the requested id
- pass: the response contains account_id and amount

## DELETE /api/transactions/{transaction_id}

- pass: the delete transaction endpoint answers 200
- pass: the response contains deleted id matching the transaction
