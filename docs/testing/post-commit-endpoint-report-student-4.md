# Post-commit endpoint test report - Student 4 (Budgeting & Spending Insights)

Workflow `student-4-budgets-ci`, job `local`, a local run, commit `8a1fe42`, 2026-10-21T01:49:34Z.
Target `http://localhost:5004` with the seeded database; spending source `mock`;
AI services as the API reported them: mcp disabled, rag disabled, multi_agent disabled. Result: **passed**,
2/2 endpoint tests passed, 29 checks.

| Endpoint | Test | Outcome | Checks | Seconds |
|---|---|---|---|---|
| `GET /api/budgets/summary` | test_budget_summary_reports_the_seeded_period | passed | 18 | 0.011 |
| `POST /api/budgets` | test_create_budget_then_duplicate_and_invalid_bodies | passed | 11 | 0.024 |

## GET /api/budgets/summary

- pass: answers 200 for the seeded period (HTTP 200 '{"budgets":[{"budget_id":2,"category":"Dining Out","customer_id":1,"month":9,"monthly_limit":300.0,"over_budget":true,"o')
- pass: the answer carries a budgets list and a totals object with every total (keys ['budgets', 'customer_id', 'month', 'over_budget_categories', 'spending_source', 'totals', 'unbudgeted_spending', 'year'])
- pass: echoes customer_id, month and year ({'customer_id': 1, 'month': 9, 'year': 2026})
- pass: every budget line carries its limit, spend, remaining, percent and status ([])
- pass: the seven seeded budgets are present with their limits (['Dining Out', 'Entertainment', 'Groceries', 'Shopping', 'Subscriptions', 'Transport', 'Utilities'])
- pass: Dining Out: remaining, percent and status follow the limit and the spend (limit 300.0 spent 412.0 -> got {'remaining': -112.0, 'percent_used': 137.3, 'status': 'OVER_BUDGET', 'over_budget': True, 'over_by': 112.0}, expected {'remaining': -112.0, 'percent_used': 137.3, 'status': 'OVER_BUDGET', 'over_budget': True, 'over_by': 112.0})
- pass: Entertainment: remaining, percent and status follow the limit and the spend (limit 150.0 spent 90.0 -> got {'remaining': 60.0, 'percent_used': 60.0, 'status': 'ON_TRACK', 'over_budget': False, 'over_by': 0.0}, expected {'remaining': 60.0, 'percent_used': 60.0, 'status': 'ON_TRACK', 'over_budget': False, 'over_by': 0.0})
- pass: Groceries: remaining, percent and status follow the limit and the spend (limit 800.0 spent 645.0 -> got {'remaining': 155.0, 'percent_used': 80.6, 'status': 'NEAR_LIMIT', 'over_budget': False, 'over_by': 0.0}, expected {'remaining': 155.0, 'percent_used': 80.6, 'status': 'NEAR_LIMIT', 'over_budget': False, 'over_by': 0.0})
- pass: Shopping: remaining, percent and status follow the limit and the spend (limit 400.0 spent 505.0 -> got {'remaining': -105.0, 'percent_used': 126.2, 'status': 'OVER_BUDGET', 'over_budget': True, 'over_by': 105.0}, expected {'remaining': -105.0, 'percent_used': 126.2, 'status': 'OVER_BUDGET', 'over_budget': True, 'over_by': 105.0})
- pass: Subscriptions: remaining, percent and status follow the limit and the spend (limit 60.0 spent 59.97 -> got {'remaining': 0.03, 'percent_used': 99.9, 'status': 'NEAR_LIMIT', 'over_budget': False, 'over_by': 0.0}, expected {'remaining': 0.03, 'percent_used': 99.9, 'status': 'NEAR_LIMIT', 'over_budget': False, 'over_by': 0.0})
- pass: Transport: remaining, percent and status follow the limit and the spend (limit 200.0 spent 218.0 -> got {'remaining': -18.0, 'percent_used': 109.0, 'status': 'OVER_BUDGET', 'over_budget': True, 'over_by': 18.0}, expected {'remaining': -18.0, 'percent_used': 109.0, 'status': 'OVER_BUDGET', 'over_budget': True, 'over_by': 18.0})
- pass: Utilities: remaining, percent and status follow the limit and the spend (limit 250.0 spent 240.0 -> got {'remaining': 10.0, 'percent_used': 96.0, 'status': 'NEAR_LIMIT', 'over_budget': False, 'over_by': 0.0}, expected {'remaining': 10.0, 'percent_used': 96.0, 'status': 'NEAR_LIMIT', 'over_budget': False, 'over_by': 0.0})
- pass: totals add up across the lines ({'budget_count': 7, 'over_budget_count': 3, 'percent_used': 100.5, 'total_limit': 2160.0, 'total_remaining': -9.97, 'total_spent': 2169.97})
- pass: mock spending source: the seeded categories carry the exact figures and statuses ([('Groceries', 645.0, 'NEAR_LIMIT'), ('Dining Out', 412.0, 'OVER_BUDGET'), ('Transport', 218.0, 'OVER_BUDGET'), ('Entertainment', 90.0, 'ON_TRACK'), ('Utilities', 240.0, 'NEAR_LIMIT'), ('Shopping', 505.0, 'OVER_BUDGET'), ('Subscriptions', 59.97, 'NEAR_LIMIT')])
- pass: mock spending source: the exact seeded totals and over-budget categories ({'budget_count': 7, 'over_budget_count': 3, 'percent_used': 100.5, 'total_limit': 2160.0, 'total_remaining': -9.97, 'total_spent': 2169.97})
- pass: 400 for {'customer_id': 1, 'month': 13, 'year': 2026} (HTTP 400 '{"error":"month must be between 1 and 12"}\n')
- pass: 400 for {'customer_id': 'abc'} (HTTP 400 '{"error":"customer_id must be an integer"}\n')
- pass: 400 for {'customer_id': 1, 'year': 1999} (HTTP 400 '{"error":"year must be between 2000 and 2100"}\n')

## POST /api/budgets

- pass: the period's budget count is known before the create (7)
- pass: creating a new budget answers 201 with its id (HTTP 201 '{"budget_id":25,"message":"Budget created"}\n')
- pass: the new budget appears in the period summary with no spend, on track ({'budget_id': 25, 'category': 'CI check 24d064c8', 'customer_id': 1, 'month': 9, 'monthly_limit': 123.45, 'over_budget': False, 'over_by': 0.0, 'percent_used': 0.0, 'remaining': 123.45, 'spent': 0.0, 'status': 'ON_TRACK', 'year': 2026})
- pass: the same customer, category and period again answers 409 (HTTP 409 '{"error":"A budget for that customer, category, month and year already exists"}\n')
- pass: 400 for greater than zero (HTTP 400 '{"error":"monthly_limit must be greater than zero"}\n')
- pass: 400 for Invalid input (HTTP 400 '{"error":"Invalid input: could not convert string to float: \'lots\'"}\n')
- pass: 400 for category required (HTTP 400 '{"error":"category required"}\n')
- pass: 400 for month must be between 1 and 12 (HTTP 400 '{"error":"month must be between 1 and 12"}\n')
- pass: 400 for a JSON body that is not an object (HTTP 400 '{"error":"JSON object body required"}\n')
- pass: cleanup: the test budget is deleted again (deleted [25]: HTTP [200])
- pass: the period is back to its previous budget count (7 vs 7)
