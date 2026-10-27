# Post-commit endpoint report - Student 1 (Accounts & Customers)

The "Run the two Multi-Agent endpoint function checks (Release 2)" step in
student-1.yml's unit-checks job runs after every push to main or pull
request touching services/accounts. It runs `tests.test_agents_endpoints`
against a Flask test client with `services.multi_agent_client`
monkeypatched, so no running Multi-Agent Server, API key or network call
is required - no containers are started for this step at all, unlike the
live-stack endpoint tests in smoke-check. start_workflow (POST
/api/agents/workflow) is checked for a valid 202, a missing-task 400
before any call is made, and a disabled-server 503. get_workflow (GET
/api/agents/workflow/<id>) is checked for a known workflow's 200, a
malformed id's 400 before any call, and another feature's workflow
correctly returning 404. Run on commit `dc11f1f` (run `40550213747`):
6/6 passed. Report: docs/testing/post-commit-endpoint-report-student-1.md and .json.
