# Post-commit endpoint test report - Student 5 (Transactions)

Workflow `student-5-transactions-ci`, job `endpoint-tests`, a local run, commit `b64a6a8`, 2026-10-27T12:51:10Z.
Target `http://localhost:5005`; MCP, RAG and Multi-Agent were disabled.
Result: **failed**, 0/5 endpoint tests passed, 0 checks.

| Endpoint | Test | Outcome | Checks | Seconds |
|---|---|---|---:|---:|
| `GET /api/health` | `test_service_health` | failed | 0 | 0.002 |
| `GET /api/transactions` | `test_transactions_list` | failed | 0 | 0.001 |
| `POST /api/transactions` | `test_create_transaction` | failed | 0 | 0.001 |
| `GET /api/transactions/{transaction_id}` | `test_transaction_by_id` | failed | 0 | 0.001 |
| `DELETE /api/transactions/{transaction_id}` | `test_delete_transaction` | failed | 0 | 0.001 |

Total test duration: 0.006 seconds. Pytest exit status: 1.

## GET /api/health


## GET /api/transactions


## POST /api/transactions


## GET /api/transactions/{transaction_id}


## DELETE /api/transactions/{transaction_id}

