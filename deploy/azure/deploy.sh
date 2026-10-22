#!/usr/bin/env bash
# Deploys the Container Apps environment and every app in apps.json from the
# images build-images.sh pushed (Lecture 11, slide 14 "deploy.sh"), then writes
# the frontend addresses for deploy/azure/checks.py to reports/cloud/outputs.json.
#   ACR_NAME=<registry> [IMAGE_TAG=<sha>] bash deploy/azure/deploy.sh
set -euo pipefail

AZ_RG="${AZ_RG:-rg-smartbank}"
: "${ACR_NAME:?set ACR_NAME to the registry deploy/azure/setup.sh created}"
cd "$(git rev-parse --show-toplevel)"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse HEAD)}"
mkdir -p reports/cloud

az deployment group create \
  --resource-group "$AZ_RG" \
  --name "smartbank-${IMAGE_TAG:0:12}" \
  --template-file deploy/azure/main.bicep \
  --parameters acrName="$ACR_NAME" imageTag="$IMAGE_TAG" \
  --query properties.outputs --output json > reports/cloud/deployment-outputs.json

az containerapp list --resource-group "$AZ_RG" \
  --query "[].{name: name, type: 'container-app', status: properties.runningStatus}" \
  --output json > reports/cloud/resources.json

# {"frontends": {...}, "homeUrl": "...", "resources": [...]} for checks.py.
python3 - <<'PY'
import json
outputs = json.load(open("reports/cloud/deployment-outputs.json"))
flat = {name: value["value"] for name, value in outputs.items()}
flat["resources"] = json.load(open("reports/cloud/resources.json"))
json.dump(flat, open("reports/cloud/outputs.json", "w"), indent=2)
print("home:", flat["homeUrl"])
for feature, url in flat["frontends"].items():
    print(f"{feature}: {url}")
PY
