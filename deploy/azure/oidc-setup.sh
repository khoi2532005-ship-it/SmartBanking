#!/usr/bin/env bash
# One-time, run by the subscription owner on their own machine: lets GitHub
# Actions log in to Azure with OIDC, so no Azure password or key is stored
# anywhere (adapted from Lab 11's gh-secrets-setup.sh). It:
#   1. registers the Container Apps resource providers and creates the
#      resource group (subscription-level steps the CI identity cannot do);
#   2. creates the user-assigned managed identity "smartbank-github-oidc" in
#      the resource group. Not an app registration: university tenants
#      usually stop students registering applications ("Directory permission
#      is needed"), while an identity is an ordinary resource they may create;
#   3. trusts tokens from this repository's `azure` GitHub environment, the
#      environment cloud-deployment.yml's deploy job runs in;
#   4. grants Contributor and User Access Administrator (the latter so
#      main.bicep can give the apps AcrPull) on the resource group only;
#   5. stores AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID as
#      GitHub secrets and ACR_NAME, AZ_RG, AZ_LOCATION, AZURE_DEPLOY_ENABLED=false as variables,
#      and creates the `azure` environment.
#   ACR_NAME=<globally unique, lower-case> bash deploy/azure/oidc-setup.sh
# AZ_RG names another resource group (default rg-smartbank), e.g. one the
# registry was created in from the portal; the workflow reads it back.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: keep "/subscriptions/..." intact

AZ_RG="${AZ_RG:-rg-smartbank}"
AZ_LOCATION="${AZ_LOCATION:-australiaeast}"
: "${ACR_NAME:?set ACR_NAME to a globally unique, lower-case registry name}"
IDENTITY_NAME="smartbank-github-oidc"
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

# Creating an identity that exists updates it in place: same ids.
az identity create --resource-group "$AZ_RG" --name "$IDENTITY_NAME" --output none
CLIENT_ID=$(az identity show --resource-group "$AZ_RG" --name "$IDENTITY_NAME" --query clientId --output tsv)
PRINCIPAL_ID=$(az identity show --resource-group "$AZ_RG" --name "$IDENTITY_NAME" --query principalId --output tsv)
echo "Managed identity $IDENTITY_NAME is ready."

# GitHub names a job that uses an environment by that environment. Repositories
# created or renamed after 2026-07-15 use the immutable form with owner and
# repository ids; older ones the plain names. Trust both: each is narrow.
# Creating a credential that exists updates it.
trust() {   # trust <credential name> <subject>
  az identity federated-credential create --resource-group "$AZ_RG" --identity-name "$IDENTITY_NAME" --name "$1" \
    --issuer https://token.actions.githubusercontent.com --subject "$2" --audiences api://AzureADTokenExchange --output none
  echo "Trusted $2"
}
trust "github-env-azure-ids" "repo:${OWNER}@${OWNER_ID}/${REPO}@${REPO_ID}:environment:${ENVIRONMENT}"
trust "github-env-azure-names" "repo:${OWNER}/${REPO}:environment:${ENVIRONMENT}"

# By object id and principal type, so nothing is looked up in the directory.
for role in "Contributor" "User Access Administrator"; do
  if [ -z "$(az role assignment list --role "$role" --scope "$RG_SCOPE" --fill-principal-name false \
      --query "[?principalId=='$PRINCIPAL_ID'].id" --output tsv)" ]; then
    az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
      --role "$role" --scope "$RG_SCOPE" --output none
  fi
  echo "$role on $AZ_RG"
done

gh api --method PUT "repos/${REPO_SLUG}/environments/${ENVIRONMENT}" --silent
gh secret set AZURE_CLIENT_ID --body "$CLIENT_ID"
gh secret set AZURE_TENANT_ID --body "$TENANT_ID"
gh secret set AZURE_SUBSCRIPTION_ID --body "$SUBSCRIPTION_ID"
gh variable set ACR_NAME --body "$ACR_NAME"
gh variable set AZ_RG --body "$AZ_RG"
gh variable set AZ_LOCATION --body "$AZ_LOCATION"
gh variable list --json name --jq '.[].name' | grep -qx AZURE_DEPLOY_ENABLED || gh variable set AZURE_DEPLOY_ENABLED --body false
echo "Done. Run the deployment from GitHub: Actions -> cloud-deployment -> Run workflow."
