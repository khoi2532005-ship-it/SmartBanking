#!/usr/bin/env bash
# Deploys the Container Apps environment and every app in apps.json from the
# images build-images.sh pushed (Lecture 11, slide 14 "deploy.sh"), then writes
# the frontend addresses for deploy/azure/checks.py to reports/cloud/outputs.json.
#   ACR_NAME=<registry> [IMAGE_TAG=<sha>] bash deploy/azure/deploy.sh
# AI-Mode, MCP, RAG and Multi-Agent stay off, the brief's cloud baseline, unless
# AI_MODE_ENABLED, MCP_ENABLED, RAG_ENABLED or MULTI_AGENT_ENABLED is true (the
# bonus profile). AI-Mode, RAG and Multi-Agent call Gemini, so any of them needs
# GEMINI_API_KEY, and only then is it passed, as a secure parameter that becomes
# a Container Apps secret. An AI server whose switch is off is removed after the
# deployment.
set -euo pipefail

AZ_RG="${AZ_RG:-rg-smartbank}"
: "${ACR_NAME:?set ACR_NAME to the registry deploy/azure/setup.sh created}"
cd "$(git rev-parse --show-toplevel)"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse HEAD)}"
REPORT_DIR="${REPORT_DIR:-reports/cloud}"
mkdir -p "$REPORT_DIR"

# True, TRUE and true all count, as in checks.py; anything else is off.
on() { [ "$(printf '%s' "${!1:-false}" | tr '[:upper:]' '[:lower:]')" = true ] && echo true || echo false; }

ai_params=(aiModeEnabled="$(on AI_MODE_ENABLED)" mcpEnabled="$(on MCP_ENABLED)" ragEnabled="$(on RAG_ENABLED)"
           multiAgentEnabled="$(on MULTI_AGENT_ENABLED)")
if [ "$(on AI_MODE_ENABLED)" = true ] || [ "$(on RAG_ENABLED)" = true ] || [ "$(on MULTI_AGENT_ENABLED)" = true ]; then
  : "${GEMINI_API_KEY:?AI_MODE_ENABLED, RAG_ENABLED or MULTI_AGENT_ENABLED needs GEMINI_API_KEY (the repository secret of that name)}"
  ai_params+=("geminiApiKey=$GEMINI_API_KEY")
fi

az deployment group create \
  --resource-group "$AZ_RG" \
  --name "smartbank-${IMAGE_TAG:0:12}" \
  --template-file deploy/azure/main.bicep \
  --parameters acrName="$ACR_NAME" imageTag="$IMAGE_TAG" "${ai_params[@]}" \
  --query properties.outputs --output json > "$REPORT_DIR/deployment-outputs.json"

# Bicep adds and updates apps but never removes one, so an AI server left by an
# earlier bonus deployment is removed here when its switch is now off.
# The list is read into an array first, so no command in the loop can read
# (and swallow) the rest of it from stdin.
deployed=$(az containerapp list --resource-group "$AZ_RG" --query "[].name" --output tsv)
servers=()
while read -r entry; do servers+=("$entry"); done < <(python3 -c \
  'import json; [print(a["name"], a["switch"]) for a in json.load(open("deploy/azure/apps.json"))["apps"] if "switch" in a]')
for entry in "${servers[@]}"; do
  read -r app switch <<< "$entry"
  if [ "$(on "$switch")" = false ] && grep -qx "$app" <<< "$deployed"; then
    echo "removing $app ($switch is off)"
    az containerapp delete --resource-group "$AZ_RG" --name "$app" --yes --output none
  fi
done

az containerapp list --resource-group "$AZ_RG" \
  --query "[].{name: name, type: 'container-app', status: properties.runningStatus}" \
  --output json > "$REPORT_DIR/resources.json"

# {"frontends": {...}, "homeUrl": "...", "resources": [...]} for checks.py.
REPORT_DIR="$REPORT_DIR" python3 - <<'PY'
import json, os
d = os.environ["REPORT_DIR"]
outputs = json.load(open(f"{d}/deployment-outputs.json"))
flat = {name: value["value"] for name, value in outputs.items()}
flat["resources"] = json.load(open(f"{d}/resources.json"))
json.dump(flat, open(f"{d}/outputs.json", "w"), indent=2)
print("home:", flat["homeUrl"])
for feature, url in flat["frontends"].items():
    print(f"{feature}: {url}")
PY
