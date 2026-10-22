"""The Container Apps deployment, checked in the source: deploy/azure/apps.json
is the one list of apps that main.bicep deploys."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APPS = {a["name"]: a for a in json.loads((ROOT / "deploy/azure/apps.json").read_text())["apps"]}
FEATURES = ("accounts", "loans", "fraud", "budgeting", "transactions")
AI_FLAGS = ("AI_MODE_ENABLED", "MCP_ENABLED", "RAG_ENABLED", "MULTI_AGENT_ENABLED")


def test_only_frontends_are_public():
    assert {n for n, a in APPS.items() if a["external"]} == {"home", *(f"{f}-frontend-service" for f in FEATURES)}


def test_databases_run_exactly_one_replica():
    dbs = [a for a in APPS.values() if a["role"] == "database"]
    assert len(dbs) == 5 and all((a["minReplicas"], a["maxReplicas"]) == (1, 1) for a in dbs)


def test_every_backend_starts_with_the_ai_services_off():
    for a in APPS.values():
        if a["role"] == "backend":
            assert {k: a["env"][k] for k in AI_FLAGS} == dict.fromkeys(AI_FLAGS, "false"), a["name"]


def test_internal_urls_name_an_app_and_carry_no_port():
    for a in APPS.values():
        for key, value in a["env"].items():
            m = re.fullmatch(r"http://([a-z-]+)(:\d+)?/?", value)
            if m:
                assert m.group(1) in APPS and m.group(2) is None, (a["name"], key, value)


@pytest.mark.parametrize("api, var, web", [("fraud-service", "FRAUD_FRONTEND_ORIGINS", "fraud"),
    ("budgeting-service", "BUDGET_FRONTEND_ORIGINS", "budgeting"), ("transactions", "TRANSACTIONS_FRONTEND_ORIGINS", "transactions")])
def test_origin_checking_backends_allow_their_own_frontend(api, var, web):
    assert APPS[api]["env"][var] == f"https://{web}-frontend-service.{{defaultDomain}}"


@pytest.mark.parametrize("feature, api", [("accounts", "accounts"), ("loans", "loans-service"), ("fraud", "fraud-service"),
    ("budgeting", "budgeting-service"), ("transactions", "transactions")])
def test_frontends_proxy_to_their_api_by_internal_address(feature, api):
    env = APPS[f"{feature}-frontend-service"]["env"]
    assert (env["API_UPSTREAM"], env["SMARTBANK_SAME_ORIGIN_API"]) == (f"https://{api}.internal.{{defaultDomain}}", "true")


def test_bicep_compiles():
    # az (CI runners have it) or the standalone bicep CLI.
    az, bicep = shutil.which("az"), shutil.which("bicep")
    assert az or bicep, "install the Azure CLI (brew install azure-cli) to compile deploy/azure/main.bicep"
    template = str(ROOT / "deploy/azure/main.bicep")
    command = [az, "bicep", "build", "--file", template, "--stdout"] if az else [bicep, "build", template, "--stdout"]
    result = subprocess.run(command, capture_output=True, text=True)  # noqa: S603  # the az/bicep CLI on PATH compiling a file in this repo
    assert result.returncode == 0, result.stderr


def test_every_app_image_is_built():
    # build-images.sh lists "<image> <Dockerfile>" pairs between its LIST markers.
    script = (ROOT / "deploy/azure/build-images.sh").read_text()
    pairs = dict(line.split() for line in script.split("<<'LIST'\n", 1)[1].split("\nLIST", 1)[0].splitlines())
    used = {a["image"].split("/", 1)[1].split(":")[0] for a in APPS.values()}
    assert set(pairs) == used
    assert [d for d in pairs.values() if not (ROOT / d).is_file()] == []


def test_bicep_takes_the_region_from_the_resource_group():
    # A subscription may only allow some regions; the resource group is created
    # where AZ_LOCATION says, and every resource must follow it.
    az, bicep = shutil.which("az"), shutil.which("bicep")
    template = str(ROOT / "deploy/azure/main.bicep")
    command = [az, "bicep", "build", "--file", template, "--stdout"] if az else [bicep, "build", template, "--stdout"]
    compiled = json.loads(subprocess.run(command, capture_output=True, text=True, check=True).stdout)  # noqa: S603  # the az/bicep CLI on PATH compiling a file in this repo
    assert compiled["parameters"]["location"]["defaultValue"] == "[resourceGroup().location]"


def test_the_environment_is_a_workload_profiles_environment():
    # Left unset, Azure made the environment "Express" (seen 2026-10-22), which
    # refuses allowInsecure and has no internal service discovery: the apps
    # could not reach each other. Ask for the standard mode explicitly.
    az, bicep = shutil.which("az"), shutil.which("bicep")
    template = str(ROOT / "deploy/azure/main.bicep")
    command = [az, "bicep", "build", "--file", template, "--stdout"] if az else [bicep, "build", template, "--stdout"]
    compiled = json.loads(subprocess.run(command, capture_output=True, text=True, check=True).stdout)  # noqa: S603  # the az/bicep CLI on PATH compiling a file in this repo
    resources = compiled["resources"].values() if isinstance(compiled["resources"], dict) else compiled["resources"]
    env = next(r for r in resources if r["type"] == "Microsoft.App/managedEnvironments")
    assert env["apiVersion"] >= "2026-07-01"
    assert env["properties"]["environmentMode"] == "WorkloadProfiles"
    assert env["properties"]["workloadProfiles"] == [{"name": "Consumption", "workloadProfileType": "Consumption"}]
    apps = next(r for r in resources if r["type"] == "Microsoft.App/containerApps")
    assert apps["properties"]["workloadProfileName"] == "Consumption"


def test_every_app_replaces_the_compose_addresses_baked_into_its_image():
    # Images bake in Compose addresses such as http://accounts:5001. Container
    # Apps reach an app by name on port 80, so each app must override them: the
    # transactions database app kept the image's address and timed out (503).
    script = (ROOT / "deploy/azure/build-images.sh").read_text()
    dockerfiles = dict(line.split() for line in script.split("<<'LIST'\n", 1)[1].split("\nLIST", 1)[0].splitlines())
    for a in APPS.values():
        dockerfile = (ROOT / dockerfiles[a["image"].split("/", 1)[1].split(":")[0]]).read_text()
        baked = dict(re.findall(r"([A-Z_]+)=(\S+)", " ".join(re.findall(r"^ENV (?:.*\\\n)*.*$", dockerfile, re.M))))
        compose = {k for k, v in baked.items() if re.fullmatch(r"http://[a-z-]+:\d+/?", v)}
        assert compose <= set(a["env"]), (a["name"], sorted(compose - set(a["env"])))


def compiled_template():
    az, bicep = shutil.which("az"), shutil.which("bicep")
    template = str(ROOT / "deploy/azure/main.bicep")
    command = [az, "bicep", "build", "--file", template, "--stdout"] if az else [bicep, "build", template, "--stdout"]
    return json.loads(subprocess.run(command, capture_output=True, text=True, check=True).stdout)  # noqa: S603  # the az/bicep CLI on PATH compiling a file in this repo


def test_ai_mode_is_a_switch_that_starts_off():
    params = compiled_template()["parameters"]
    assert (params["aiModeEnabled"]["type"], params["aiModeEnabled"]["defaultValue"]) == ("bool", False)
    assert (params["geminiApiKey"]["type"], params["geminiApiKey"]["defaultValue"]) == ("securestring", "")


def test_the_gemini_key_reaches_the_apps_only_as_a_container_apps_secret():
    resources = compiled_template()["resources"]
    resources = resources.values() if isinstance(resources, dict) else resources
    apps = next(r for r in resources if r["type"] == "Microsoft.App/containerApps")
    assert "geminiApiKey" in json.dumps(apps["properties"]["configuration"]["secrets"])
    assert "geminiApiKey" not in json.dumps(apps["properties"]["template"])
    assert "gemini-api-key" in json.dumps(apps["properties"]["template"])


def test_no_model_key_is_written_into_apps_json():
    text = (ROOT / "deploy/azure/apps.json").read_text()
    assert "API_KEY" not in text and "AIza" not in text
