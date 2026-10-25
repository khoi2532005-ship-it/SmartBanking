# SmartBanking on Azure Container Apps - runbook

The required Release 2 cloud deployment: the integrated application on Azure
Container Apps, with images in Azure Container Registry. AI-Mode, MCP, RAG and
the Multi-Agent Server stay **off**, which is the brief's cloud baseline. It
follows the reference architecture in Lecture 11 (slides 12-14) and Lab 11 §5.

| What | Where |
|---|---|
| The 16 container apps: one public frontend per feature plus the home page; APIs and databases internal. Plus the MCP, RAG and Multi-Agent servers, internal, in the bonus profile only | `deploy/azure/apps.json` |
| Infrastructure as code (Bicep, compiled to ARM) | `deploy/azure/main.bicep` |
| Reusable scripts | `deploy/azure/{oidc-setup,setup,build-images,deploy,cleanup}.sh` |
| Endpoint and CRUD checks, and the deployment report | `deploy/azure/checks.py` |
| CI/CD: deploys only after all five `student-x.yml` workflows pass | `.github/workflows/cloud-deployment.yml` |
| Local rehearsal of the same layout | `docker-compose.cloud.yml` |

```
GitHub Actions --(student-1..5 pass)--> docker build (linux/amd64) + push to ACR (14 images, tag = commit)
      --> Bicep: Container Apps environment + 16 apps, pulling from ACR with a managed identity
Browser --HTTPS--> <feature>-frontend-service (nginx, public)
                     |- /config.js        cloud mode: the tabs call this same address
                     |- /api/*, /ui/*  -> <api>.internal.<domain>  (internal app)
                                            '-> http://<feature>-database-service  (internal app, SQLite, 1 replica)
Browser --HTTPS--> home (public): links each feature to its frontend address
```

## 1. Rehearse locally (no Azure)

```bash
docker compose -f docker-compose.yml -f docker-compose.cloud.yml up -d --build
.venv/bin/python -m pytest tests/test_cloud_frontends.py tests/test_cloud_rehearsal.py tests/test_cloud_infra.py tests/test_cloud_workflow.py -v
```

The rehearsal runs the cloud layout on this machine: the frontends run in cloud
mode, and no backend or database publishes a port. `docker compose up` without
the override is the normal local stack, unchanged.

## 2. One-time setup (the subscription owner)

Prerequisites: an Azure subscription, the Azure CLI (`brew install azure-cli`),
and the GitHub CLI logged in with admin rights on the repository. Azure for
Students is enough: the images are built on the GitHub runner and pushed, not
built with ACR Tasks (`az acr build`), which free-credit subscriptions cannot run.

```bash
az login
ACR_NAME=smartbank<something unique, lower-case> bash deploy/azure/oidc-setup.sh
```

If the subscription only allows some regions (Azure for Students often does),
prefix the command with `AZ_LOCATION=<allowed region>`. Everything follows the
resource group's region, and the workflow reads the `AZ_LOCATION` variable this
script sets. To use a resource group with another name, such as one you created
the registry in from the portal, prefix `AZ_RG=<name>` to this script and to
`setup.sh`; the script stores it as the `AZ_RG` variable, and the workflow uses that.

This registers the resource providers the deployment uses (Container Apps, Log
Analytics, Container Registry, Managed Identity) and creates `rg-smartbank`. It then
creates `smartbank-github-oidc` in that group: a user-assigned managed identity
that trusts this repository's `azure` GitHub environment, so no Azure password is
stored. It's a managed identity rather than an app registration because
university tenants usually stop students registering applications ("Directory
permission is needed"). The identity gets Contributor and User Access
Administrator on **that resource group only**. Finally, the script stores `AZURE_CLIENT_ID`, `AZURE_TENANT_ID` and
`AZURE_SUBSCRIPTION_ID` as secrets, and `ACR_NAME`, `AZ_RG`, `AZ_LOCATION` and
`AZURE_DEPLOY_ENABLED=false` as variables.

## 3. Deploy

**First deployment, from the `acr-conversion` branch.** GitHub only offers "Run
workflow" for workflows on the default branch, so until this branch is merged it
deploys on its own pushes:

```bash
gh variable set AZURE_DEPLOY_ENABLED --body true
git push -u origin acr-conversion
gh run watch
gh variable set AZURE_DEPLOY_ENABLED --body false   # afterwards, if pushes should not redeploy
```

**Once merged into `main`:** **Actions → cloud-deployment → Run workflow**, or
`gh workflow run cloud-deployment.yml`.

The workflow runs in this order:
1. The five student workflows, which are the CI gate.
2. `tests/test_cloud_infra.py`.
3. The OIDC login.
4. `setup.sh`, then `build-images.sh` (built on the runner, pushed to ACR), then `deploy.sh`.
5. `checks.py`.

It then uploads the `cloud-deployment-report` artifact. To deploy on every push
to `main` as well, set the repository variable `AZURE_DEPLOY_ENABLED` to `true`.

The same scripts run from a terminal after `az login`, with Docker running.
The images are built for linux/amd64, which is slow under emulation on Apple
Silicon, so prefer the workflow:
`ACR_NAME=… bash deploy/azure/setup.sh && ACR_NAME=… bash deploy/azure/build-images.sh && ACR_NAME=… bash deploy/azure/deploy.sh`.
Then run `python deploy/azure/checks.py --outputs reports/cloud/outputs.json --out reports/cloud/cloud-deployment-report.json`.

## 4. Evidence

1. Download the run's `cloud-deployment-report` artifact. Copy
   `cloud-deployment-report.json` and `deployment-results.md` into this folder.
2. Open the `homeUrl` from the report, then each feature through it, and
   screenshot each.
3. Run each student's post-commit suite against their frontend address. For
   fraud: `FRAUD_API_URL=https://fraud-frontend-service.<domain> python -m pytest services/fraud-alerts/backend/tests/post_commit -v`.
4. Run the agentic-loop review:
   `CLOUD_DEPLOYMENT_REPORT=docs/deployment/cloud-deployment-report.json python agentic_loop.py --mode cloud_deployment_review`.
   Then record the human release decision in the report's `release_decision`.

## 5. AI services in the cloud (bonus profile)

The required deployment is the baseline, with every AI service off. Each bonus
service has a repository variable that turns it on:

| Variable | Bonus | What turns on |
|---|---|---|
| `AI_MODE_ENABLED` | B1 | AI-Mode (Gemini) in every backend |
| `MCP_ENABLED` | B2 | the app `mcp-server` (the shared MCP server), and every backend calling it at `http://mcp-server/mcp` |
| `RAG_ENABLED` | B3 | the app `rag-server` (the shared RAG server, its index of the approved documents built into the image), and every backend calling it at `http://rag-server` |
| `MULTI_AGENT_ENABLED` | B4 | the app `multi-agent-server` (Planner → Worker → Reviewer → human), and the backends calling it at `http://multi-agent-server` |

```bash
gh secret set GEMINI_API_KEY                   # paste the key; it never enters the repository
gh variable set AI_MODE_ENABLED --body true
gh variable set MCP_ENABLED --body true
gh variable set RAG_ENABLED --body true
gh variable set MULTI_AGENT_ENABLED --body true
```

Then deploy as in section 3.

- **The three servers** are internal apps built from `deploy/azure/Dockerfile.mcp-server`,
  `deploy/azure/Dockerfile.rag-server` and `deploy/azure/Dockerfile.multi-agent-server`.
  Locally they still run on the host and never in Compose. MCP and Multi-Agent
  reach the feature APIs by app name; RAG answers from its documents only.
- **AI-Mode, RAG and Multi-Agent call Gemini**, so any of them needs the secret.
  `deploy.sh` passes the key to `main.bicep` as a secure parameter. Each app that
  needs it stores it as a Container Apps secret and reads it as `GEMINI_API_KEY`.
  With one of those variables on and no secret, `deploy.sh` stops before deploying.
- **The backends and the Multi-Agent Server share a bearer token**
  (`MULTI_AGENT_API_TOKEN`). `main.bicep` derives it from the resource group,
  so it is the same on every deployment and nobody stores it; a container that
  restarts later reads the same value as the others.
- **Checks wait for a cold start.** Each AI check retries for up to two minutes
  while its server is still starting (no reply, or a 5xx that is not "switched
  off"), and the RAG question may take up to 100 s, as long as fraud's backend
  waits for an answer.
- **The report** says `"profile": "bonus"` and expects exactly the services
  asked for to be on. For each server that is on, it does that server's real
  job through the fraud frontend and backend, which is what the bonus marks ask
  for: MCP lists its tools and fraud's backend calls its own tool
  (`POST /api/mcp/tool`); RAG answers a question about fraud alerts, and the
  answer must be grounded, with citations; the Multi-Agent Server runs a
  workflow started through fraud to the human gate, the check accepts it as
  `cloud-deployment.yml`, and the final response must be released. A reply
  that is a 200 but not that (an "insufficient context" answer, a workflow
  that failed) is recorded with `"ok": false` and an issue, so the report and
  the cloud review hold the release.

To go back to the baseline, set the variables to `false` and deploy again.
The keys leave the apps, and `deploy.sh` removes `mcp-server`, `rag-server`
and `multi-agent-server`, because Bicep never removes an app by itself. The
Multi-Agent Server keeps its workflows on its one replica, so a new revision
starts with none.

## Things to know

- **Data resets.** Each database is SQLite inside its container (one replica),
  seeded when the image is built. A restart or new revision brings back the
  seed. That's enough for the demonstration, but it isn't persistent storage.
- **Origin checks.** Fraud, Budgeting and Transactions only accept browser
  writes from their own frontend. The proxy forwards the page's `Origin`, so
  each of those backends gets `*_FRONTEND_ORIGINS=https://<feature>-frontend-service.<domain>`
  in `apps.json`. A 403 on every write means that value is wrong.
- **A 502 from a frontend** means its API app isn't running. Run
  `az containerapp logs show -g rg-smartbank -n <api app>`. Right after the
  first deployment, image pulls can fail for a minute until the AcrPull
  permission propagates; re-run the workflow.
- **Transactions calls the AI model on every create** to pick a category,
  whatever the AI flags say. In the baseline no model key is passed, so it
  falls back at once. With AI-Mode on, every create calls Gemini, so creates are
  slower and count against the key's quota.

## Cost and cleanup

Expect roughly USD 2–3 a day with all 16 apps running, plus about USD 0.17 a day
for ACR Basic; check the Azure pricing calculator for current rates. Set a
budget alert in Cost Management. When marking is done:

```bash
bash deploy/azure/cleanup.sh
```

This deletes `rg-smartbank`: the registry, the environment and every app. Run
`oidc-setup.sh` again before the next deployment, because the role assignments
went with the resource group.
