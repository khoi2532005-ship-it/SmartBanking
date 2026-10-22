# Post-commit endpoint test report - Student 4 (Budgeting & Spending Insights)

Workflow `student-4-budgets-ci`, job `smoke-check`, run 39725293520 on `main`, commit `fa227e0`, 2026-10-22T05:20:21Z.
Target `http://localhost:5004` with the seeded database; spending source `mock`;
AI services as the API reported them: ai_mode disabled, mcp disabled, rag disabled, multi_agent disabled. Result: **passed**,
2/2 endpoint tests passed, 31 checks.

| Endpoint | Test | Outcome | Checks | Seconds |
|---|---|---|---|---|
| `GET /api/budgets/summary` | test_budget_summary_reports_the_seeded_period | passed | 21 | 0.111 |
| `POST /api/budgets` | test_create_budget_then_duplicate_and_invalid_bodies | passed | 10 | 0.132 |

## GET /api/budgets/summary

- pass: budgets left by an interrupted run were removed before the period was read (found [], removed [], failed {})
- pass: answers 200 for the seeded period (HTTP 200 '{"budgets":[{"budget_id":2,"category":"Dining Out","customer_id":1,"month":9,"monthly_limit":300.0,"over_budget":true,"o')
- pass: the period's stored budgets and its spending can be read (GET /api/budgets HTTP 200 '[{"budget_id":2,"category":"Dining Out","created_at":"2026-09-01 08:16:00","customer_id":1,"month":9,"monthly_limit":300'; GET /api/transactions/spending HTTP 200 '{"customer_id":1,"month":9,"spending_source":"mock","totals_by_category":{"Dining Out":412.0,"Entertainment":90.0,"Groce')
- pass: the seeded period has stored budgets, each with an id (7 stored; first [{'budget_id': 2, 'category': 'Dining Out', 'created_at': '2026-09-01 08:16:00', 'customer_id': 1, 'month': 9, 'monthly_limit': 300.0, 'year': 2026}])
- pass: the answer carries a budgets list and a totals object with every total (keys ['budgets', 'customer_id', 'month', 'over_budget_categories', 'spending_source', 'totals', 'unbudgeted_spending', 'year'])
- pass: echoes customer_id, month and year ({'customer_id': 1, 'month': 9, 'year': 2026})
- pass: every budget line carries its id, limit, spend, remaining, percent and status ([])
- pass: the summary and the spending endpoint name the same spending source (mock vs mock)
- pass: the period's stored budgets are exactly the seeded ones (init_db.py) (stored [(2, 'Dining Out', 300.0), (4, 'Entertainment', 150.0), (1, 'Groceries', 800.0), (6, 'Shopping', 400.0), (7, 'Subscriptions', 60.0), (3, 'Transport', 200.0), (5, 'Utilities', 250.0)], seeded [(1, 'Groceries', 800.0), (2, 'Dining Out', 300.0), (3, 'Transport', 200.0), (4, 'Entertainment', 150.0), (5, 'Utilities', 250.0), (6, 'Shopping', 400.0), (7, 'Subscriptions', 60.0)])
- pass: the summary lists exactly the period's stored budgets (stored [1, 2, 3, 4, 5, 6, 7], listed [1, 2, 3, 4, 5, 6, 7])
- pass: Dining Out: the line is the budget logic's answer for its stored limit and its spend (got {'budget_id': 2, 'category': 'Dining Out', 'customer_id': 1, 'month': 9, 'monthly_limit': 300.0, 'over_budget': True, 'over_by': 112.0, 'percent_used': 137.3, 'remaining': -112.0, 'spent': 412.0, 'status': 'OVER_BUDGET', 'year': 2026}, expected {'budget_id': 2, 'customer_id': 1, 'category': 'Dining Out', 'month': 9, 'year': 2026, 'monthly_limit': 300.0, 'spent': 412.0, 'remaining': -112.0, 'percent_used': 137.3, 'status': 'OVER_BUDGET', 'over_budget': True, 'over_by': 112.0})
- pass: Entertainment: the line is the budget logic's answer for its stored limit and its spend (got {'budget_id': 4, 'category': 'Entertainment', 'customer_id': 1, 'month': 9, 'monthly_limit': 150.0, 'over_budget': False, 'over_by': 0.0, 'percent_used': 60.0, 'remaining': 60.0, 'spent': 90.0, 'status': 'ON_TRACK', 'year': 2026}, expected {'budget_id': 4, 'customer_id': 1, 'category': 'Entertainment', 'month': 9, 'year': 2026, 'monthly_limit': 150.0, 'spent': 90.0, 'remaining': 60.0, 'percent_used': 60.0, 'status': 'ON_TRACK', 'over_budget': False, 'over_by': 0.0})
- pass: Groceries: the line is the budget logic's answer for its stored limit and its spend (got {'budget_id': 1, 'category': 'Groceries', 'customer_id': 1, 'month': 9, 'monthly_limit': 800.0, 'over_budget': False, 'over_by': 0.0, 'percent_used': 80.6, 'remaining': 155.0, 'spent': 645.0, 'status': 'NEAR_LIMIT', 'year': 2026}, expected {'budget_id': 1, 'customer_id': 1, 'category': 'Groceries', 'month': 9, 'year': 2026, 'monthly_limit': 800.0, 'spent': 645.0, 'remaining': 155.0, 'percent_used': 80.6, 'status': 'NEAR_LIMIT', 'over_budget': False, 'over_by': 0.0})
- pass: Shopping: the line is the budget logic's answer for its stored limit and its spend (got {'budget_id': 6, 'category': 'Shopping', 'customer_id': 1, 'month': 9, 'monthly_limit': 400.0, 'over_budget': True, 'over_by': 105.0, 'percent_used': 126.2, 'remaining': -105.0, 'spent': 505.0, 'status': 'OVER_BUDGET', 'year': 2026}, expected {'budget_id': 6, 'customer_id': 1, 'category': 'Shopping', 'month': 9, 'year': 2026, 'monthly_limit': 400.0, 'spent': 505.0, 'remaining': -105.0, 'percent_used': 126.2, 'status': 'OVER_BUDGET', 'over_budget': True, 'over_by': 105.0})
- pass: Subscriptions: the line is the budget logic's answer for its stored limit and its spend (got {'budget_id': 7, 'category': 'Subscriptions', 'customer_id': 1, 'month': 9, 'monthly_limit': 60.0, 'over_budget': False, 'over_by': 0.0, 'percent_used': 99.9, 'remaining': 0.03, 'spent': 59.97, 'status': 'NEAR_LIMIT', 'year': 2026}, expected {'budget_id': 7, 'customer_id': 1, 'category': 'Subscriptions', 'month': 9, 'year': 2026, 'monthly_limit': 60.0, 'spent': 59.97, 'remaining': 0.03, 'percent_used': 99.9, 'status': 'NEAR_LIMIT', 'over_budget': False, 'over_by': 0.0})
- pass: Transport: the line is the budget logic's answer for its stored limit and its spend (got {'budget_id': 3, 'category': 'Transport', 'customer_id': 1, 'month': 9, 'monthly_limit': 200.0, 'over_budget': True, 'over_by': 18.0, 'percent_used': 109.0, 'remaining': -18.0, 'spent': 218.0, 'status': 'OVER_BUDGET', 'year': 2026}, expected {'budget_id': 3, 'customer_id': 1, 'category': 'Transport', 'month': 9, 'year': 2026, 'monthly_limit': 200.0, 'spent': 218.0, 'remaining': -18.0, 'percent_used': 109.0, 'status': 'OVER_BUDGET', 'over_budget': True, 'over_by': 18.0})
- pass: Utilities: the line is the budget logic's answer for its stored limit and its spend (got {'budget_id': 5, 'category': 'Utilities', 'customer_id': 1, 'month': 9, 'monthly_limit': 250.0, 'over_budget': False, 'over_by': 0.0, 'percent_used': 96.0, 'remaining': 10.0, 'spent': 240.0, 'status': 'NEAR_LIMIT', 'year': 2026}, expected {'budget_id': 5, 'customer_id': 1, 'category': 'Utilities', 'month': 9, 'year': 2026, 'monthly_limit': 250.0, 'spent': 240.0, 'remaining': 10.0, 'percent_used': 96.0, 'status': 'NEAR_LIMIT', 'over_budget': False, 'over_by': 0.0})
- pass: totals, over-budget categories and unbudgeted spending are the budget logic's answer (totals {'budget_count': 7, 'over_budget_count': 3, 'percent_used': 100.5, 'total_limit': 2160.0, 'total_remaining': -9.97, 'total_spent': 2169.97}, expected {'total_limit': 2160.0, 'total_spent': 2169.97, 'total_remaining': -9.97, 'percent_used': 100.5, 'budget_count': 7, 'over_budget_count': 3})
- pass: 400 for {'customer_id': 1, 'month': 13, 'year': 2026} (HTTP 400 '{"error":"month must be between 1 and 12"}\n')
- pass: 400 for {'customer_id': 'abc'} (HTTP 400 '{"error":"customer_id must be an integer"}\n')
- pass: 400 for {'customer_id': 1, 'year': 1999} (HTTP 400 '{"error":"year must be between 2000 and 2100"}\n')

## POST /api/budgets

- pass: creating a new budget answers 201 with its id (HTTP 201 '{"budget_id":15,"message":"Budget created"}\n')
- pass: the new budget appears in the period summary with no spend, on track ({'budget_id': 15, 'category': 'CI check b293d54f', 'customer_id': 1, 'month': 9, 'monthly_limit': 123.45, 'over_budget': False, 'over_by': 0.0, 'percent_used': 0.0, 'remaining': 123.45, 'spent': 0.0, 'status': 'ON_TRACK', 'year': 2026})
- pass: the same customer, category and period again answers 409 (HTTP 409 '{"error":"A budget for that customer, category, month and year already exists"}\n')
- pass: 400 for greater than zero (HTTP 400 '{"error":"monthly_limit must be greater than zero"}\n')
- pass: 400 for Invalid input (HTTP 400 '{"error":"Invalid input: could not convert string to float: \'lots\'"}\n')
- pass: 400 for category required (HTTP 400 '{"error":"category required"}\n')
- pass: 400 for month must be between 1 and 12 (HTTP 400 '{"error":"month must be between 1 and 12"}\n')
- pass: 400 for a JSON body that is not an object (HTTP 400 '{"error":"JSON object body required"}\n')
- pass: cleanup: every budget the test created is deleted (deleted {15: 200})
- pass: the created budget is gone again: 404 by id and no longer in the summary (GET by id 404, listed False)
