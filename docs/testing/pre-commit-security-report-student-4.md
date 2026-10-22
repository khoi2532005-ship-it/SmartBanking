# Pre-commit security report - Student 4 (Budgeting & Spending Insights)

Run on commit fa227e0 (main, after PR #72) with `pre-commit run --all-files`
from the repo root, 2026-10-22T05:46:57Z; every hook passed on the whole
repository. Hooks: Ruff 0.6.9 (security rules `S`), detect-secrets 1.5.0,
pip-audit 2.7.3. Scope for this report: everything I own, that is
`services/budgeting`, `requirements-multi-agent.txt`, the shared
`multi_agent_server`, my agentic-loop modes (`budgeting`, `mcp_validation`,
`rag_validation`, `multi_agent_review`, `testing_review`,
`cloud_deployment_review`, `_review_common`) and their tests. The same hooks
run on every commit through the installed git hook; the commit that adds this
report went through them.

| Scan | Result | Findings | Fixed | Accepted |
|---|---|---|---|---|
| ruff-security (`S`, `S101` ignored in tests only) | passed | 21 | 0 | 21 |
| detect-secrets (`.secrets.baseline`) | passed | 0 | 0 | 0 |
| pip-audit (backend, database, multi-agent requirements) | passed | 7 | 7 | 0 |

## Ruff security rules

Twenty-one findings, each accepted with a reason on the line (`# noqa`).
`ruff check --select S --ignore-noqa` lists them; without `--ignore-noqa`
the hook passes.

| Rule | Where | Why it is accepted |
|---|---|---|
| S104 bind to all interfaces | services/budgeting/backend/app.py:92 | the API binds 0.0.0.0 so the Docker-published port and the frontend container can reach it |
| S104 | services/budgeting/database/app.py:428 | same; the database service is reachable only on the compose network |
| S104 | services/budgeting/frontend/serve.py:52 | the dev frontend binds 0.0.0.0 so it is reachable from a container and from another device on the LAN |
| S106 hard-coded password | services/budgeting/backend/tests/test_multi_agent_client.py:210 | a made-up bearer token in a test fixture |
| S603 subprocess call | services/budgeting/backend/budgeting_endpoint_tests/conftest.py:38 | `git rev-parse --short=7 HEAD` names the commit in the report: a constant command, no outside input |
| S607 partial executable path | services/budgeting/backend/budgeting_endpoint_tests/conftest.py:39 | the same `git` call, found on PATH |
| S104 | multi_agent_server/config.py:19 | the default bind lets the budgeting and fraud containers reach the host's Multi-Agent Server |
| S104 | multi_agent_server/config.py:74 | not a bind: `local_url()` compares the host with "0.0.0.0" to print a localhost address |
| S110 try-except-pass | multi_agent_server/orchestrator.py:406 | a failed disk write is already handled: the workflow state is rolled back and the audit line is marked |
| S110 | multi_agent_server/orchestrator.py:414 | undoing that audit line is best effort; the workflow state is already restored |
| S104 | multi_agent_server/server.py:348 | the start-up check tries a wildcard bind on purpose, to see whether the port is free |
| S603 | multi_agent_server/validate.py:86 | names the commit for the validation record (`git describe --dirty`): a constant command on the repo path |
| S607 | multi_agent_server/validate.py:87 | the same `git` call, found on PATH |
| S603 | multi_agent_server/validate.py:96 | `git status` on the repo's own working tree, to refuse evidence from a dirty tree |
| S607 | multi_agent_server/validate.py:97 | the same `git` call, found on PATH |
| S314 XML parsing | agentic/modes/testing_review.py:111 | parses the team's own JUnit files from CI, not untrusted input |
| S106 | tests/test_multi_agent_server.py:1016 | a made-up token in a test fixture |
| S104 | tests/test_multi_agent_server.py:1105 | a port probe in test setup only |
| S106 | tests/test_multi_agent_server.py:1154 | a made-up token in a test fixture |
| S106 | tests/test_multi_agent_server.py:1163 | a made-up token in a test fixture |
| S106 | tests/test_multi_agent_server.py:1184 | a made-up token in a test fixture |

The `assert` statements (S101) in the test modules are the tests themselves;
the shared config ignores S101 in test files only.

## detect-secrets

No secret in any of these paths. The Gemini key is read from `.env`, which is
gitignored; the multi-agent bearer token and the frontend origins come from
the environment. The baseline has no entry for any of these paths.

## pip-audit

Before PR #62 the budgeting pins carried seven known vulnerabilities; the
bumps fixed all of them, and the pins still audit clean on this commit.

| Package | Was | Now | Advisories closed |
|---|---|---|---|
| flask (backend and database) | 3.0.3 | 3.1.3 | PYSEC-2026-2151 |
| flask-cors (backend) | 5.0.0 | 6.0.0 | PYSEC-2026-1383, PYSEC-2026-1384, PYSEC-2026-1385 |
| requests (backend) | 2.32.3 | 2.33.0 | PYSEC-2026-1872, PYSEC-2026-2275 |

`requirements-multi-agent.txt` had no findings. The four chromadb advisories
ignored in the shared config belong to the RAG server's requirements and have
no fixed release yet; they are tracked in `.pre-commit-config.yaml`.

## Since the 20 October run

The run on `524bac2` (2026-10-20) listed only the four accepted findings in
`services/budgeting`. This run covers every path above, so it adds the
accepted findings in `multi_agent_server`, the endpoint-test `conftest.py`,
`testing_review.py` and the server tests. Line numbers are as on `fa227e0`
(the API's bind moved from line 91 to 92).
