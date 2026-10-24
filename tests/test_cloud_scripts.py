"""The deployment scripts, run against stand-in `az` and `docker` commands that
record every call: no Azure, no registry, no images built."""

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = {"Microsoft.App", "Microsoft.OperationalInsights", "Microsoft.ContainerRegistry", "Microsoft.ManagedIdentity"}


def stub(directory, name, body):
    path = directory / name
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(0o755)


@pytest.fixture
def run_script(tmp_path):
    """Runs a deploy/azure script with stand-ins for az and docker; returns their calls."""
    log = tmp_path / "calls.log"
    # The docker stand-in reads stdin, as some CLIs do: a build loop that feeds
    # its list on stdin would lose the rest of the list after the first image.
    stub(tmp_path, "docker", f'echo "docker $*" >> "{log}"\ncat > /dev/null\n')
    stub(tmp_path, "az", f'echo "az $*" >> "{log}"\n'
                         'case "$*" in\n'
                         '  "provider show"*) echo NotRegistered ;;\n'
                         '  "group show"*|"acr show"*) exit 1 ;;\n'
                         '  "identity show"*clientId*) echo client-1 ;;\n'
                         '  "identity show"*principalId*) echo principal-1 ;;\n'
                         '  "deployment group create"*) echo \'{"frontends": {"value": {}}, "homeUrl": {"value": "https://home.example"}}\' ;;\n'
                         '  "containerapp list"*"[].name"*) printf "fraud-service\\nmcp-server\\nrag-server\\nmulti-agent-server\\n" ;;\n'
                         '  "containerapp list"*) echo "[]" ;;\n'
                         'esac\n')
    # oidc-setup.sh writes repository secrets: never let it reach the real gh.
    stub(tmp_path, "gh", f'echo "gh $*" >> "{log}"\n'
                         'case "$*" in\n'
                         '  "repo view"*) echo owner/repo ;;\n'
                         '  "api repos/"*) echo 7 ;;\n'
                         'esac\n')
    inherited = {k: v for k, v in os.environ.items()
                 if k not in ("AI_MODE_ENABLED", "MCP_ENABLED", "MULTI_AGENT_ENABLED", "GEMINI_API_KEY")}
    env = {**inherited, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}", "ACR_NAME": "smartbanktest",
           "IMAGE_TAG": "abc123", "REPORT_DIR": str(tmp_path / "reports")}

    def run(script, *, fails=False, **extra_env):
        result = subprocess.run(["bash", str(ROOT / "deploy/azure" / script)], env={**env, **extra_env}, cwd=ROOT,  # noqa: S603, S607  # a script from this repo
                                capture_output=True, text=True)
        if fails:
            assert result.returncode != 0
            return result.stderr
        assert result.returncode == 0, result.stderr
        return log.read_text().splitlines()
    return run


def test_images_are_built_here_for_linux_amd64_and_pushed(run_script):
    # ACR Tasks (az acr build) are paused on free-credit subscriptions such as
    # Azure for Students, so the images are built where the script runs.
    calls = run_script("build-images.sh")
    builds = [c for c in calls if c.startswith("docker build")]
    pushes = [c.split()[-1] for c in calls if c.startswith("docker push")]
    assert "az acr login --name smartbanktest" in calls
    assert not [c for c in calls if c.startswith("az acr build")]
    assert len(builds) == 17
    tags = [re.search(r"--tag (\S+)", b).group(1) for b in builds]
    assert all("--platform linux/amd64" in b and b.endswith(" .") for b in builds)
    assert all(re.fullmatch(r"smartbanktest\.azurecr\.io/smartbank-[a-z-]+:abc123", t) for t in tags)
    assert sorted(pushes) == sorted(tags)


def test_setup_registers_every_provider_the_deployment_uses(run_script):
    calls = run_script("setup.sh")
    registered = {re.search(r"--namespace (\S+)", c).group(1) for c in calls if c.startswith("az provider register")}
    assert registered == PROVIDERS
    assert any(c.startswith("az group create") for c in calls) and any(c.startswith("az acr create") for c in calls)


def test_oidc_setup_needs_no_directory_permission(run_script):
    # University tenants stop students registering applications ("Directory
    # permission is needed for the current user to register the application"),
    # so GitHub logs in as a managed identity, an ordinary resource in the group.
    calls = run_script("oidc-setup.sh")
    assert not [c for c in calls if c.startswith("az ad ")]
    assert any(c.startswith("az identity create") and "--resource-group rg-smartbank" in c for c in calls)
    subjects = {re.search(r"--subject (\S+)", c).group(1) for c in calls
                if c.startswith("az identity federated-credential create")}
    assert subjects == {"repo:owner@7/repo@7:environment:azure", "repo:owner/repo:environment:azure"}
    grants = [c for c in calls if c.startswith("az role assignment create")]
    assert len(grants) == 2
    assert all("--assignee-object-id principal-1 --assignee-principal-type ServicePrincipal" in g for g in grants)
    assert "gh secret set AZURE_CLIENT_ID --body client-1" in calls


def test_oidc_setup_tells_the_workflow_which_resource_group(run_script):
    calls = run_script("oidc-setup.sh", AZ_RG="smartbankacr")
    assert "gh variable set AZ_RG --body smartbankacr" in calls
    assert any(c.startswith("az identity create") and "--resource-group smartbankacr" in c for c in calls)


def test_oidc_setup_registers_the_same_providers():
    # The CI identity cannot register providers (it holds rights on the
    # resource group only), so the owner's one-time setup must register them all.
    line = re.search(r"for namespace in (.+); do", (ROOT / "deploy/azure/oidc-setup.sh").read_text()).group(1)
    assert set(line.split()) == PROVIDERS


def test_deploy_keeps_ai_mode_off_by_default(run_script):
    # The brief's cloud baseline: AI-Mode off, and no model key anywhere near the apps.
    create = next(c for c in run_script("deploy.sh") if c.startswith("az deployment group create"))
    assert "aiModeEnabled=false" in create and "geminiApiKey" not in create
    assert "mcpEnabled=false" in create and "multiAgentEnabled=false" in create


def test_deploy_passes_the_key_only_when_ai_mode_is_on(run_script):
    create = next(c for c in run_script("deploy.sh", AI_MODE_ENABLED="true", GEMINI_API_KEY="key-1")
                  if c.startswith("az deployment group create"))
    assert "aiModeEnabled=true" in create and "geminiApiKey=key-1" in create


def test_deploy_refuses_ai_mode_without_a_key(run_script):
    assert "GEMINI_API_KEY" in run_script("deploy.sh", fails=True, AI_MODE_ENABLED="true")


def test_deploy_passes_the_mcp_and_multi_agent_switches(run_script):
    create = next(c for c in run_script("deploy.sh", MCP_ENABLED="true", MULTI_AGENT_ENABLED="true", GEMINI_API_KEY="key-1")
                  if c.startswith("az deployment group create"))
    assert "mcpEnabled=true" in create and "multiAgentEnabled=true" in create and "aiModeEnabled=false" in create
    # The Planner, Worker and Reviewer call Gemini.
    assert "geminiApiKey=key-1" in create


def test_multi_agent_needs_the_key_and_mcp_does_not(run_script):
    assert "GEMINI_API_KEY" in run_script("deploy.sh", fails=True, MULTI_AGENT_ENABLED="true")
    create = next(c for c in run_script("deploy.sh", MCP_ENABLED="true") if c.startswith("az deployment group create"))
    assert "mcpEnabled=true" in create and "geminiApiKey" not in create and "ragEnabled=false" in create


def test_rag_is_a_switch_that_needs_the_key(run_script):
    # The RAG server's generator writes the grounded answer with Gemini.
    assert "GEMINI_API_KEY" in run_script("deploy.sh", fails=True, RAG_ENABLED="true")
    create = next(c for c in run_script("deploy.sh", RAG_ENABLED="true", GEMINI_API_KEY="key-1")
                  if c.startswith("az deployment group create"))
    assert "ragEnabled=true" in create and "geminiApiKey=key-1" in create
    assert "aiModeEnabled=false" in create and "mcpEnabled=false" in create and "multiAgentEnabled=false" in create


def test_deploy_removes_an_ai_server_whose_switch_is_off(run_script):
    # Bicep adds and updates but never removes: a server left by a bonus run
    # would otherwise keep running in the baseline.
    calls = run_script("deploy.sh", MCP_ENABLED="true")
    deletes = [c for c in calls if c.startswith("az containerapp delete")]
    assert sorted(d.split("--name ")[1].split()[0] for d in deletes) == ["multi-agent-server", "rag-server"]
    # Removed before the resource list is written, so the report does not list it.
    lists = [i for i, c in enumerate(calls) if c.startswith("az containerapp list") and "runningStatus" in c]
    assert calls.index(deletes[0]) < lists[0]
