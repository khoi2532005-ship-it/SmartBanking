# Post-commit endpoint test report - Student 3 (Fraud Alerts)

Workflow `student-3-fraud-ci`, job `endpoint-tests`, run
[40203858561](https://github.com/khoi2532005-ship-it/SmartBanking/actions/runs/40203858561) on `main`, commit `6c97f6d`, 2026-10-25T14:48:05Z.
Target `http://localhost:5003` (the fraud backend and database started in the
runner); AI-Mode, MCP, RAG and Multi-Agent were disabled.
Result: **passed**, 26/26 tests passed, 46 checks,
over the two endpoint functions `GET /api/alerts` and `POST /api/rules`.

The tests call the live API, never the app in-process. They plant their own
disabled `release-check` rule and alerts on a test customer, remove them
afterwards, and first sweep away anything an interrupted run left behind.

| Endpoint | Test | Outcome | Checks | Seconds |
|---|---|---|---:|---:|
| `GET /api/alerts` | `test_list_returns_alerts_newest_first` | passed | 2 | 0.046 |
| `GET /api/alerts` | `test_each_filter_returns_exactly_the_matching_alerts[params0-expected0]` | passed | 1 | 0.007 |
| `GET /api/alerts` | `test_each_filter_returns_exactly_the_matching_alerts[params1-expected1]` | passed | 1 | 0.007 |
| `GET /api/alerts` | `test_each_filter_returns_exactly_the_matching_alerts[params2-expected2]` | passed | 1 | 0.006 |
| `GET /api/alerts` | `test_each_filter_returns_exactly_the_matching_alerts[params3-expected3]` | passed | 1 | 0.007 |
| `GET /api/alerts` | `test_each_filter_returns_exactly_the_matching_alerts[params4-expected4]` | passed | 1 | 0.009 |
| `GET /api/alerts` | `test_each_filter_returns_exactly_the_matching_alerts[params5-expected5]` | passed | 1 | 0.010 |
| `GET /api/alerts` | `test_each_filter_returns_exactly_the_matching_alerts[params6-expected6]` | passed | 1 | 0.009 |
| `GET /api/alerts` | `test_each_filter_returns_exactly_the_matching_alerts[params7-expected7]` | passed | 1 | 0.007 |
| `GET /api/alerts` | `test_each_filter_returns_exactly_the_matching_alerts[params8-expected8]` | passed | 1 | 0.006 |
| `GET /api/alerts` | `test_each_filter_returns_exactly_the_matching_alerts[params9-expected9]` | passed | 1 | 0.006 |
| `GET /api/alerts` | `test_each_filter_returns_exactly_the_matching_alerts[params10-expected10]` | passed | 1 | 0.006 |
| `GET /api/alerts` | `test_a_filter_on_its_own_returns_only_matching_alerts` | passed | 1 | 0.006 |
| `GET /api/alerts` | `test_unusable_filters_are_400[params0-status must be one of new, reviewed, dismissed, confirmed]` | passed | 2 | 0.003 |
| `GET /api/alerts` | `test_unusable_filters_are_400[params1-min_amount must be a number]` | passed | 2 | 0.003 |
| `GET /api/alerts` | `test_unusable_filters_are_400[params2-customer_id must be a positive integer]` | passed | 2 | 0.003 |
| `GET /api/alerts` | `test_unusable_filters_are_400[params3-date_from must be an ISO date]` | passed | 2 | 0.061 |
| `POST /api/rules` | `test_rule_crud_cycle` | passed | 5 | 0.062 |
| `POST /api/rules` | `test_invalid_rules_are_400_and_store_nothing[body0-rule_name is required]` | passed | 3 | 0.009 |
| `POST /api/rules` | `test_invalid_rules_are_400_and_store_nothing[body1-rule_type must be one of]` | passed | 3 | 0.009 |
| `POST /api/rules` | `test_invalid_rules_are_400_and_store_nothing[body2-velocity needs threshold_secondary]` | passed | 3 | 0.009 |
| `POST /api/rules` | `test_invalid_rules_are_400_and_store_nothing[body3-start and end hours must differ]` | passed | 3 | 0.008 |
| `POST /api/rules` | `test_invalid_rules_are_400_and_store_nothing[body4-threshold_value must be a finite number]` | passed | 3 | 0.008 |
| `POST /api/rules` | `test_form_posts_are_400` | passed | 1 | 0.004 |
| `POST /api/rules` | `test_sweep_removes_what_an_interrupted_run_left` | passed | 1 | 0.073 |
| `POST /api/rules` | `test_a_test_rule_with_other_customers_alerts_is_left_for_a_person` | passed | 2 | 0.041 |

Total test duration: 0.492 seconds. Pytest exit status: 0.
The JUnit XML and pytest log from this run's `student-3-endpoint-tests`
artifact are in `docs/release-2/ci/student-3/`.

## GET /api/alerts

- pass: answers 200
- pass: lists the planted alerts newest first
- pass: no filter returns exactly the matching alerts, newest first
- pass: status=reviewed returns exactly the matching alerts, newest first
- pass: customer_id=<test customer> returns exactly the matching alerts, newest first
- pass: customer_id=<another customer> returns exactly the matching alerts, newest first
- pass: min_amount=5000 returns exactly the matching alerts, newest first
- pass: max_amount=5000 returns exactly the matching alerts, newest first
- pass: date_from=2026-02-15 returns exactly the matching alerts, newest first
- pass: date_to=2026-02-15 returns exactly the matching alerts, newest first
- pass: q=Gamma (recipient) returns exactly the matching alerts, newest first
- pass: q=transfer (category) returns exactly the matching alerts, newest first
- pass: status=new and max_amount=100 returns exactly the matching alerts, newest first
- pass: a single filter returns only alerts that match it
- pass: answers 400
- pass: error says: status must be one of new, reviewed, dismissed, confirmed
- pass: answers 400
- pass: error says: min_amount must be a number
- pass: answers 400
- pass: error says: customer_id must be a positive integer
- pass: answers 400
- pass: error says: date_from must be an ISO date

## POST /api/rules

- pass: create answers 201 and stores the rule disabled
- pass: read returns the stored fields
- pass: update answers 200 and the rule stays disabled
- pass: delete answers 200
- pass: a deleted rule reads as 404
- pass: answers 400
- pass: error says: rule_name is required
- pass: nothing is stored
- pass: answers 400
- pass: error says: rule_type must be one of
- pass: nothing is stored
- pass: answers 400
- pass: error says: velocity needs threshold_secondary
- pass: nothing is stored
- pass: answers 400
- pass: error says: start and end hours must differ
- pass: nothing is stored
- pass: answers 400
- pass: error says: threshold_value must be a finite number
- pass: nothing is stored
- pass: a form-encoded body answers 400 "JSON body required"
- pass: the sweep removes a test rule and its test alert left by an interrupted run
- pass: cleanup refuses a test rule whose alerts belong to another customer
- pass: that customer's alert is kept
