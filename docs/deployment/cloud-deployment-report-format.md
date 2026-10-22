# Cloud deployment report format

The agentic loop's `cloud_deployment_review` mode reads one JSON file and
writes the Cloud Deployment Review entry that supports the final human release
decision. The cloud owner produces the file from the `cloud-deployment.yml`
run (or by hand from its logs) and commits it here as
`docs/deployment/cloud-deployment-report.json`. Until it exists the mode
reviews `cloud-deployment-report.sample.json`, marks the run degraded and
holds the release, so the mode can be demonstrated before the deployment
lands without ever approving one that did not happen.

```
python agentic_loop.py --mode cloud_deployment_review
CLOUD_DEPLOYMENT_REPORT=path/to/report.json python agentic_loop.py --mode cloud_deployment_review
```

## Fields

| Field | Meaning |
|---|---|
| `provider`, `region`, `environment` | `azure` or `aws`, the region, and a name for the deployment |
| `profile` | `baseline` (the required deployment, all four AI services disabled; the default when left out) or `bonus` (AI services may be enabled) |
| `deployed_at`, `commit`, `deployed_by` | when, which commit (short id), who |
| `workflow` | `name`, `run_id`, `run_url`, `conclusion` of the `cloud-deployment.yml` run |
| `scripts` | the reusable deployment scripts or infrastructure-as-code files used |
| `resources` | one `{name, type, status}` per cloud resource |
| `endpoints` | one `{name, method, url, expected_status, status}` per endpoint check against the deployed frontend and APIs; `status` is the HTTP code received, or `null` when nothing answered; an optional `ok: false` fails a check even when the code matches |
| `crud_checks` | the same shape, for the create, read, update and delete calls that prove the core functions work |
| `ai_services` | `ai_mode`, `mcp`, `rag`, `multi_agent`: `disabled` or `enabled`; a service left out counts as unknown, not disabled |
| `issues` | open problems, as sentences; an empty list means none |
| `release_decision` | `decision` (`approved` or `held`), `by`, `note`, `decided_at`: filled in by the person who makes the final release decision after reading the review |

The mode recommends `approve` only when all of these hold, and `hold` with
the reasons otherwise:

- the report is not the sample (`"sample": true` or the sample file)
- `workflow` names a `cloud-deployment.yml` run whose `conclusion` is `success`
- every endpoint and CRUD check returned its expected status code
- in the baseline profile all four AI services are `disabled`; in the bonus profile each is reported as `enabled` or `disabled`
- no issue is open

It records the human decision from `release_decision` when one is present,
and reports `pending` until then.
