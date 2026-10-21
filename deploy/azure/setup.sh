#!/usr/bin/env bash
# Resource group and container registry for the SmartBanking cloud deployment
# (Lecture 11, slide 14 "setup.sh"). Safe to re-run: it only creates what is
# missing. Needs an Azure login: `az login` locally, azure/login in CI.
#   ACR_NAME=<globally unique, lower-case letters/digits> bash deploy/azure/setup.sh
set -euo pipefail

AZ_RG="${AZ_RG:-rg-smartbank}"
AZ_LOCATION="${AZ_LOCATION:-australiaeast}"
: "${ACR_NAME:?set ACR_NAME to a globally unique, lower-case registry name}"

# The deployment needs these providers (Container Apps, its logs, the registry,
# the pull identity) once per subscription. The CI identity
# may only hold rights on the resource group, so register only when missing
# (deploy/azure/oidc-setup.sh registers them with the owner's login).
for namespace in Microsoft.App Microsoft.OperationalInsights Microsoft.ContainerRegistry Microsoft.ManagedIdentity; do
  if [ "$(az provider show --namespace "$namespace" --query registrationState --output tsv)" != "Registered" ]; then
    az provider register --namespace "$namespace" --wait
  fi
done

if ! az group show --name "$AZ_RG" --output none 2>/dev/null; then
  az group create --name "$AZ_RG" --location "$AZ_LOCATION" --output none
fi

if ! az acr show --resource-group "$AZ_RG" --name "$ACR_NAME" --output none 2>/dev/null; then
  az acr create --resource-group "$AZ_RG" --name "$ACR_NAME" --sku Basic --admin-enabled false --output none
fi

echo "Resource group $AZ_RG and registry $ACR_NAME.azurecr.io are ready."
