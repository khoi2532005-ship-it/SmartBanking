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
# The shared servers that run as apps of their own in the bonus profile: name -> (switch, port).
AI_SERVERS = {"mcp-server": ("MCP_ENABLED", 8100), "rag-server": ("RAG_ENABLED", 8200),
              "multi-agent-server": ("MULTI_AGENT_ENABLED", 8300)}
FEATURE_APIS = {"ACCOUNTS_SERVICE_URL": "http://accounts", "LOANS_SERVICE_URL": "http://loans-service",
                "FRAUD_SERVICE_URL": "http://fraud-service", "BUDGET_SERVICE_URL": "http://budgeting-service",
                "TRANSACTIONS_SERVICE_URL": "http://transactions"}


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


def secrets_of(apps):
    """The apps' configuration.secrets, written as a list or compiled from a loop."""
    configuration = apps["properties"]["configuration"]
    return configuration.get("secrets") or next(c["input"] for c in configuration["copy"] if c["name"] == "secrets")


def test_the_gemini_key_reaches_the_apps_only_as_a_container_apps_secret():
    template = compiled_template()
    resources = template["resources"]
    resources = resources.values() if isinstance(resources, dict) else resources
    apps = next(r for r in resources if r["type"] == "Microsoft.App/containerApps")
    assert "geminiApiKey" in json.dumps(secrets_of(apps))
    assert "geminiApiKey" not in json.dumps(apps["properties"]["template"])
    assert "secretRef" in json.dumps(apps["properties"]["template"])
    assert template["variables"]["secretNames"]["GEMINI_API_KEY"] == "gemini-api-key"  # pragma: allowlist secret


def test_no_model_key_is_written_into_apps_json():
    text = (ROOT / "deploy/azure/apps.json").read_text()
    assert "API_KEY" not in text and "AIza" not in text and "TOKEN" not in text


def test_each_ai_server_is_an_internal_app_behind_its_switch():
    # Bonus B2 and B4: the shared servers run as apps of their own, only when
    # their switch is on, and only apps in the environment can reach them.
    assert {n for n, a in APPS.items() if "switch" in a} == set(AI_SERVERS)
    for name, (switch, port) in AI_SERVERS.items():
        a = APPS[name]
        assert (a["role"], a["switch"], a["external"], a["targetPort"]) == ("ai-server", switch, False, port)
        # Multi-Agent keeps its workflows and audit files on the replica's disk.
        assert (a["minReplicas"], a["maxReplicas"]) == (1, 1), name


def test_ai_servers_reach_every_feature_api_by_app_name():
    # The RAG server answers from the approved documents baked into its image
    # and calls no feature API.
    for name in AI_SERVERS:
        if name != "rag-server":
            assert {k: APPS[name]["env"].get(k) for k in FEATURE_APIS} == FEATURE_APIS, name
    assert not any(k.endswith("_SERVICE_URL") for k in APPS["rag-server"]["env"])


def test_the_rag_image_bakes_in_the_index_of_the_approved_documents():
    # rag_server/data is gitignored and dockerignored, so the image must build
    # the index itself; a server that starts with no index would spend its
    # first request building one.
    text = (ROOT / "deploy/azure/Dockerfile.rag-server").read_text()
    assert "requirements-rag.txt" in text and "COPY rag_server/" in text
    assert "COPY agentic/" in text and "COPY prompts/" in text   # the generator reuses agentic/llm.py and prompts/
    assert re.search(r"RUN python .*refresh\(\)", text), "the index is built at image build time"
    assert "RAG_PORT=8200" in text and 'CMD ["python", "-m", "rag_server.server"]' in text


def test_backends_call_the_ai_servers_in_the_environment_not_on_the_host():
    # The images bake in host.docker.internal, where the servers run beside
    # Compose; in the cloud each server is an app, reached by name on port 80.
    for a in APPS.values():
        if a["role"] == "backend":
            assert a["env"]["MCP_SERVER_URL"] == "http://mcp-server/mcp", a["name"]
            assert a["env"]["RAG_SERVER_URL"] == "http://rag-server", a["name"]
            assert a["env"]["MULTI_AGENT_SERVER_URL"] == "http://multi-agent-server", a["name"]


def container_apps(template):
    resources = template["resources"]
    resources = resources.values() if isinstance(resources, dict) else resources
    return next(r for r in resources if r["type"] == "Microsoft.App/containerApps")


def test_mcp_and_multi_agent_are_switches_that_start_off():
    params = compiled_template()["parameters"]
    for name in ("mcpEnabled", "ragEnabled", "multiAgentEnabled"):
        assert (params[name]["type"], params[name]["defaultValue"]) == ("bool", False), name
    # A new token on every deployment, given to the server and the backends
    # alike: nobody has to store it.
    assert (params["multiAgentToken"]["type"], params["multiAgentToken"]["defaultValue"]) == ("securestring", "[newGuid()]")


def test_an_ai_server_is_deployed_only_when_its_switch_is_on():
    apps = container_apps(compiled_template())
    assert "switch" in apps.get("condition", "")


def test_the_multi_agent_token_reaches_the_apps_only_as_a_container_apps_secret():
    template = compiled_template()
    apps = container_apps(template)
    assert "multiAgentToken" in json.dumps(secrets_of(apps))
    assert "multiAgentToken" not in json.dumps(apps["properties"]["template"])
    assert template["variables"]["secretNames"]["MULTI_AGENT_API_TOKEN"] == "multi-agent-token"  # noqa: S105  # pragma: allowlist secret (the secret's name, not its value)
