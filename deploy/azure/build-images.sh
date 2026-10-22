#!/usr/bin/env bash
# Builds every SmartBanking image for linux/amd64 (what Container Apps runs),
# tags it with the git commit, so each deployment names exactly the code it
# runs, and pushes it to Azure Container Registry. The images are built where
# this script runs - the GitHub runner, or a machine with Docker - because ACR
# Tasks (`az acr build`) are paused on free-credit subscriptions such as Azure
# for Students. Build context: the repository root, as in docker-compose.yml.
#   ACR_NAME=<registry> [IMAGE_TAG=<sha>] bash deploy/azure/build-images.sh
set -euo pipefail

: "${ACR_NAME:?set ACR_NAME to the registry deploy/azure/setup.sh created}"
cd "$(git rev-parse --show-toplevel)"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse HEAD)}"
REGISTRY="${ACR_NAME}.azurecr.io"

# <image> <Dockerfile>: the names in docker-compose.yml, the two nginx
# frontends Accounts and Transactions run as separate apps in the cloud, and
# the shared MCP and Multi-Agent servers (deployed only in the bonus profile).
# tests/test_cloud_infra.py checks this list against deploy/azure/apps.json.
# It is read into an array first, so no command in the build loop can read
# (and swallow) the rest of the list from stdin.
IMAGES=()
while read -r entry; do IMAGES+=("$entry"); done <<'LIST'
smartbank-home shared/frontend/Dockerfile
smartbank-accounts services/accounts/Dockerfile
smartbank-accounts-web services/accounts/frontend/Dockerfile.web
smartbank-loans-db services/loans/database/Dockerfile
smartbank-loans-api services/loans/backend/Dockerfile
smartbank-loans-web services/loans/frontend/Dockerfile
smartbank-fraud-db services/fraud-alerts/database/Dockerfile
smartbank-fraud-api services/fraud-alerts/backend/Dockerfile
smartbank-fraud-web services/fraud-alerts/frontend/Dockerfile
smartbank-budgeting-db services/budgeting/database/Dockerfile
smartbank-budgeting-api services/budgeting/backend/Dockerfile
smartbank-budgeting-web services/budgeting/frontend/Dockerfile
smartbank-transactions services/transactions/Dockerfile
smartbank-transactions-web services/transactions/frontend/Dockerfile.web
smartbank-mcp-server deploy/azure/Dockerfile.mcp-server
smartbank-multi-agent-server deploy/azure/Dockerfile.multi-agent-server
LIST

az acr login --name "$ACR_NAME"
for entry in "${IMAGES[@]}"; do
  read -r image dockerfile <<< "$entry"
  ref="${REGISTRY}/${image}:${IMAGE_TAG}"
  echo "== ${ref} (${dockerfile})"
  docker build --platform linux/amd64 --file "$dockerfile" --tag "$ref" .
  docker push "$ref"
done
