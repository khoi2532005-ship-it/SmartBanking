# Pre-commit security report - Student 4 (Budgeting & Spending Insights)

Run on commit 524bac2 (main, after PR #62 merged the shared hooks) with
`pre-commit run --all-files` from the repo root, 2026-10-20T11:56:09Z.
Hooks: Ruff 0.6.9 (security rules `S`), detect-secrets 1.5.0, pip-audit 2.7.3.
Scope for this report: `services/budgeting`, `requirements-multi-agent.txt`
and the shared `multi_agent_server` I own. The same hooks run on every
commit through the installed git hook; the commit that adds this report went
through them.

| Scan | Result | Findings | Fixed | Accepted |
|---|---|---|---|---|
| ruff-security (`S`, `S101` ignored in tests only) | passed | 4 | 0 | 4 |
| detect-secrets (`.secrets.baseline`) | passed | 0 | 0 | 0 |
| pip-audit (backend, database, multi-agent requirements) | passed | 7 | 7 | 0 |

## Ruff security rules

Four findings, all accepted with a reason on the line (`# noqa`):

| Rule | Where | Why it is accepted |
|---|---|---|
| S104 bind to all interfaces | backend/app.py:91 | the API binds 0.0.0.0 so the Docker-published port and the frontend container can reach it |
| S104 | database/app.py:428 | same; the database service is reachable only on the compose network |
| S104 | frontend/serve.py:52 | the dev frontend binds 0.0.0.0 so the tabs open from another device on the LAN |
| S106 hard-coded password | backend/tests/test_multi_agent_client.py:210 | a made-up bearer token in a test fixture |

The 304 `assert` statements (S101) in the budgeting test modules are the
tests themselves; the shared config ignores S101 in test files only.

## detect-secrets

No secret in any budgeting file. The Gemini key is read from `.env`, which is
gitignored; the multi-agent bearer token and the frontend origins come from
the environment. The baseline is empty for this feature.

## pip-audit

Before PR #62 the budgeting pins carried seven known vulnerabilities; the
bumps fixed all of them and the current pins audit clean.

| Package | Was | Now | Advisories closed |
|---|---|---|---|
| flask (backend and database) | 3.0.3 | 3.1.3 | PYSEC-2026-2151 |
| flask-cors (backend) | 5.0.0 | 6.0.0 | PYSEC-2026-1383, PYSEC-2026-1384, PYSEC-2026-1385 |
| requests (backend) | 2.32.3 | 2.33.0 | PYSEC-2026-1872, PYSEC-2026-2275 |

`requirements-multi-agent.txt` had no findings. The four chromadb advisories
ignored in the shared config belong to the RAG server's requirements and have
no fixed release yet; they are tracked in `.pre-commit-config.yaml`.

The budgeting checks (`python -m tests.test_multi_agent_client`,
`test_multi_agent_contract`, `test_agent_clients`, `test_budget_routes`,
`test_budget_logic`) pass on the bumped pins; student-4.yml ran them on PR #62.
