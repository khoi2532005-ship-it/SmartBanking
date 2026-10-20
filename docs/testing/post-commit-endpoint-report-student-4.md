# Post-commit endpoint test report - Student 4 (Budgeting & Spending Insights)

Workflow `student-4-budgets-ci`, job `endpoint-tests`, a local run, commit `32546bf`, 2026-10-20T12:20:05Z.
Target `http://localhost:5004` with the seeded database; spending source `mock`;
MCP, RAG and the Multi-Agent Server disabled. Result: **passed**,
2/2 endpoint tests, 25 checks.

| Endpoint | Test | Outcome | Checks | Seconds |
|---|---|---|---|---|
| `GET /api/budgets/summary` | test_budget_summary_reports_the_seeded_period | passed | 15 | 0.01 |
| `POST /api/budgets` | test_create_budget_then_duplicate_and_invalid_bodies | passed | 10 | 0.02 |

## GET /api/budgets/summary

- pass: answers 200 for the seeded period (HTTP 200)
- pass: echoes customer_id, month and year
- pass: the seven seeded budgets are present with their limits (['Dining Out', 'Entertainment', 'Groceries', 'Shopping', 'Subscriptions', 'Transport', 'Utilities'])
- pass: Dining Out: remaining, percent and status follow the limit and the spend (limit 300.0 spent 412.0 -> OVER_BUDGET remaining -112.0 137.3%)
- pass: Entertainment: remaining, percent and status follow the limit and the spend (limit 150.0 spent 90.0 -> ON_TRACK remaining 60.0 60.0%)
- pass: Groceries: remaining, percent and status follow the limit and the spend (limit 800.0 spent 645.0 -> NEAR_LIMIT remaining 155.0 80.6%)
- pass: Shopping: remaining, percent and status follow the limit and the spend (limit 400.0 spent 505.0 -> OVER_BUDGET remaining -105.0 126.2%)
- pass: Subscriptions: remaining, percent and status follow the limit and the spend (limit 60.0 spent 59.97 -> NEAR_LIMIT remaining 0.03 99.9%)
- pass: Transport: remaining, percent and status follow the limit and the spend (limit 200.0 spent 218.0 -> OVER_BUDGET remaining -18.0 109.0%)
- pass: Utilities: remaining, percent and status follow the limit and the spend (limit 250.0 spent 240.0 -> NEAR_LIMIT remaining 10.0 96.0%)
- pass: totals add up across the seven lines ({'budget_count': 7, 'over_budget_count': 3, 'percent_used': 100.5, 'total_limit': 2160.0, 'total_remaining': -9.97, 'total_spent': 2169.97})
- pass: mock spending source: the exact seeded figures and statuses (spent/status per category [('Dining Out', 412.0, 'OVER_BUDGET'), ('Entertainment', 90.0, 'ON_TRACK'), ('Groceries', 645.0, 'NEAR_LIMIT'), ('Shopping', 505.0, 'OVER_BUDGET'), ('Subscriptions', 59.97, 'NEAR_LIMIT'), ('Transport', 218.0, 'OVER_BUDGET'), ('Utilities', 240.0, 'NEAR_LIMIT')])
- pass: 400 for {'customer_id': 1, 'month': 13, 'year': 2026} (HTTP 400 {"error":"month must be between 1 and 12"}
)
- pass: 400 for {'customer_id': 'abc'} (HTTP 400 {"error":"customer_id must be an integer"}
)
- pass: 400 for {'customer_id': 1, 'year': 1999} (HTTP 400 {"error":"year must be between 2000 and 2100"}
)

## POST /api/budgets

- pass: creating a new budget answers 201 with its id (HTTP 201 {"budget_id":18,"message":"Budget created"}
)
- pass: the new budget appears in the period summary with no spend, on track ({'budget_id': 18, 'category': 'CI check 6cf7a4b5', 'customer_id': 1, 'month': 9, 'monthly_limit': 123.45, 'over_budget': False, 'over_by': 0.0, 'percent_used': 0.0, 'remaining': 123.45, 'spent': 0.0, 'status': 'ON_TRACK', 'year': 2026})
- pass: the same customer, category and period again answers 409 (HTTP 409 {"error":"A budget for that customer, category, month and year already exists"}
)
- pass: 400 for greater than zero (HTTP 400 {"error":"monthly_limit must be greater than zero"}
)
- pass: 400 for Invalid input (HTTP 400 {"error":"Invalid input: could not convert string to float: 'lots'"}
)
- pass: 400 for category required (HTTP 400 {"error":"category required"}
)
- pass: 400 for month must be between 1 and 12 (HTTP 400 {"error":"month must be between 1 and 12"}
)
- pass: 400 for a JSON body that is not an object (HTTP 400)
- pass: cleanup: the test budget is deleted again (HTTP 200)
- pass: the period is back to the seven seeded budgets
