#!/usr/bin/env bash
# Deletes the whole SmartBanking resource group - registry, environment and
# every app - so nothing keeps billing after the assessment.
#   bash deploy/azure/cleanup.sh
set -euo pipefail

AZ_RG="${AZ_RG:-rg-smartbank}"
az group delete --name "$AZ_RG" --yes --no-wait
echo "Deleting resource group $AZ_RG in the background (az group show --name $AZ_RG to follow)."
