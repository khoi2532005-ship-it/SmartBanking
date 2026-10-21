#!/usr/bin/env bash
# Builds every SmartBanking image in Azure Container Registry, tagged with the
# git commit, so each deployment names exactly the code it runs. The builds
# run in ACR (`az acr build`), from the repository root as build context, the
# same as docker-compose.yml.
#   ACR_NAME=<registry> [IMAGE_TAG=<sha>] bash deploy/azure/build-images.sh
set -euo pipefail

: "${ACR_NAME:?set ACR_NAME to the registry deploy/azure/setup.sh created}"
cd "$(git rev-parse --show-toplevel)"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse HEAD)}"

# <image> <Dockerfile>: the names in docker-compose.yml plus the two nginx
# frontends Accounts and Transactions run as separate apps in the cloud.
# tests/test_cloud_infra.py checks this list against deploy/azure/apps.json.
while read -r image dockerfile; do
  echo "== ${image}:${IMAGE_TAG} (${dockerfile})"
  az acr build --registry "$ACR_NAME" --image "${image}:${IMAGE_TAG}" --file "$dockerfile" --output none .
done <<'LIST'
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
LIST
