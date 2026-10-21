#!/usr/bin/env bash
# One-time, run by the subscription owner on their own machine: lets GitHub
# Actions log in to Azure with OIDC, so no Azure password or key is stored
# anywhere (adapted from Lab 11's gh-secrets-setup.sh). It:
#   1. registers the Container Apps resource providers and creates the
#      resource group (subscription-level steps the CI identity cannot do);
#   2. creates the app registration "smartbank-github-oidc" if missing;
#   3. trusts tokens from this repository's `azure` GitHub environment, the
#      environment cloud-deployment.yml's deploy job runs in;
#   4. grants Contributor and User Access Administrator (the latter so
#      main.bicep can give the apps AcrPull) on the resource group only;
#   5. stores AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID as
#      GitHub secrets and ACR_NAME, AZ_LOCATION, AZURE_DEPLOY_ENABLED=false as variables,
#      and creates the `azure` environment.
#   ACR_NAME=<globally unique, lower-case> bash deploy/azure/oidc-setup.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: keep "/subscriptions/..." intact

AZ_RG="${AZ_RG:-rg-smartbank}"
AZ_LOCATION="${AZ_LOCATION:-australiaeast}"
: "${ACR_NAME:?set ACR_NAME to a globally unique, lower-case registry name}"
APP_NAME="smartbank-github-oidc"
ENVIRONMENT="azure"

az account show --output none 2>/dev/null || az login --output none
gh auth status >/dev/null 2>&1 || gh auth login

SUBSCRIPTION_ID=$(az account show --query id --output tsv)
TENANT_ID=$(az account show --query tenantId --output tsv)
REPO_SLUG=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
OWNER=${REPO_SLUG%%/*}
REPO=${REPO_SLUG##*/}
OWNER_ID=$(gh api "repos/${REPO_SLUG}" --jq .owner.id)
REPO_ID=$(gh api "repos/${REPO_SLUG}" --jq .id)

for namespace in Microsoft.App Microsoft.OperationalInsights Microsoft.ContainerRegistry Microsoft.ManagedIdentity; do
  az provider register --namespace "$namespace" --wait
done
az group create --name "$AZ_RG" --location "$AZ_LOCATION" --output none
RG_SCOPE="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${AZ_RG}"

CLIENT_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" --output tsv)
if [ -z "$CLIENT_ID" ]; then
  CLIENT_ID=$(az ad app create --display-name "$APP_NAME" --query appId --output tsv)
  az ad sp create --id "$CLIENT_ID" --output none
  echo "Created app registration $APP_NAME."
fi

# GitHub names a job that uses an environment by that environment. Repositories
# created or renamed after 2026-07-15 use the immutable form with owner and
# repository ids; older ones the plain names. Trust both: each is narrow.
trust() {   # trust <credential name> <subject>
  local params="{\"name\":\"$1\",\"issuer\":\"https://token.actions.githubusercontent.com\",\"subject\":\"$2\",\"audiences\":[\"api://AzureADTokenExchange\"]}"
  if az ad app federated-credential list --id "$CLIENT_ID" --query "[?name=='$1'].id" --output tsv | grep -q .; then
    az ad app federated-credential update --id "$CLIENT_ID" --federated-credential-id "$1" --parameters "$params" --output none
  else
    az ad app federated-credential create --id "$CLIENT_ID" --parameters "$params" --output none
  fi
  echo "Trusted $2"
}
trust "github-env-azure-ids" "repo:${OWNER}@${OWNER_ID}/${REPO}@${REPO_ID}:environment:${ENVIRONMENT}"
trust "github-env-azure-names" "repo:${OWNER}/${REPO}:environment:${ENVIRONMENT}"

for role in "Contributor" "User Access Administrator"; do
  if [ -z "$(az role assignment list --assignee "$CLIENT_ID" --role "$role" --scope "$RG_SCOPE" --query "[0].id" --output tsv)" ]; then
    az role assignment create --assignee "$CLIENT_ID" --role "$role" --scope "$RG_SCOPE" --output none
  fi
  echo "$role on $AZ_RG"
done

gh api --method PUT "repos/${REPO_SLUG}/environments/${ENVIRONMENT}" --silent
gh secret set AZURE_CLIENT_ID --body "$CLIENT_ID"
gh secret set AZURE_TENANT_ID --body "$TENANT_ID"
gh secret set AZURE_SUBSCRIPTION_ID --body "$SUBSCRIPTION_ID"
gh variable set ACR_NAME --body "$ACR_NAME"
gh variable set AZ_LOCATION --body "$AZ_LOCATION"
gh variable list --json name --jq '.[].name' | grep -qx AZURE_DEPLOY_ENABLED || gh variable set AZURE_DEPLOY_ENABLED --body false
echo "Done. Run the deployment from GitHub: Actions -> cloud-deployment -> Run workflow."
