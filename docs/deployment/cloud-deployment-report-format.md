# Cloud deployment report format

The agentic loop's `cloud_deployment_review` mode reads one JSON file and
writes the Cloud Deployment Review entry that supports the final human release
decision. The cloud owner produces the file from the `cloud-deployment.yml`
run (or by hand from its logs) and commits it here as
`docs/deployment/cloud-deployment-report.json`. Until it exists the mode
reviews `cloud-deployment-report.sample.json` and marks the run degraded, so
the mode itself can be demonstrated before the deployment lands.

```
python agentic_loop.py --mode cloud_deployment_review
CLOUD_DEPLOYMENT_REPORT=path/to/report.json python agentic_loop.py --mode cloud_deployment_review
```

## Fields

| Field | Meaning |
|---|---|
| `provider`, `region`, `environment` | `azure` or `aws`, the region, and a name for the deployment (the required one is the baseline with the AI services disabled) |
| `deployed_at`, `commit`, `deployed_by` | when, which commit (short id), who |
| `workflow` | `name`, `run_id`, `run_url`, `conclusion` of the `cloud-deployment.yml` run |
| `scripts` | the reusable deployment scripts or infrastructure-as-code files used |
| `resources` | one `{name, type, status}` per cloud resource |
| `endpoints` | one `{name, method, url, expected_status, status}` per endpoint check against the deployed frontend and APIs |
| `crud_checks` | the same shape, for the create, read, update and delete calls that prove the core functions work |
| `ai_services` | `ai_mode`, `mcp`, `rag`, `multi_agent`: `disabled` or `enabled`; the required deployment keeps all four disabled, the bonus profile may enable some |
| `issues` | open problems, as sentences; an empty list means none |
| `release_decision` | `decision` (`approved` or `held`), `by`, `note`, `decided_at`: filled in by the person who makes the final release decision after reading the review |

The mode recommends `approve` only when every endpoint and CRUD check returned
its expected status, the workflow run succeeded and no issue is open;
otherwise `hold`. It records the human decision from `release_decision` when
one is present, and reports `pending` until then.
