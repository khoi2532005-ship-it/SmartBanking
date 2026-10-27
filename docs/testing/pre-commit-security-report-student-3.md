# Pre-commit security report - Student 3 (Fraud Alerts)

Run at commit `12a2cb1` on `main`, 2026-10-27T02:40:46Z, from the repository root with

```bash
pre-commit run --files $(git ls-files services/fraud-alerts .github/workflows/student-3.yml)
```

Every configured hook passed. The report scope is the student-3 Fraud Alerts
feature and its workflow: `services/fraud-alerts` and
`.github/workflows/student-3.yml`. The report files are not part of the scanned
commit; the hooks run again when they are committed.

| Scan | Result | Findings | Fixed | Accepted |
|---|---|---|---|---|
| ruff-security (`S`, `S101` ignored in test files only) | passed | 2 | 0 | 2 |
| detect-secrets (`.secrets.baseline`) | passed | 0 | 0 | 0 |
| pip-audit (fraud backend and database requirements) | passed | 0 | 0 | 0 |

## Ruff security rules

The pinned Ruff version is 0.6.9. Run with `--ignore-noqa`, it reports exactly
two findings in `services/fraud-alerts`, both accepted with an inline
`# noqa: S104` and its reason:

| Rule | Where | Why it is accepted |
|---|---|---|
| S104 bind to all interfaces | services/fraud-alerts/backend/app.py:122 | the backend binds 0.0.0.0 so the frontend and the other services can reach it on the Docker network |
| S104 bind to all interfaces | services/fraud-alerts/database/app.py:418 | the database service binds 0.0.0.0 so the fraud backend can reach it on the Docker network |

Inside a container, binding to `127.0.0.1` would make the service unreachable
from every other container. Only the frontends are exposed outside Docker
locally, and in Azure the backend and database are internal apps.

## detect-secrets

No secrets were found in the fraud files. `.secrets.baseline` is empty, so no
finding is allowlisted; the Gemini key lives in `.env` (git-ignored) locally
and in the `GEMINI_API_KEY` repository secret in the cloud.

## pip-audit

The fraud backend and database requirements hooks both passed with no reported
advisories. The run also passed the root, accounts, budgeting, loans and
transactions pip-audit hooks.
