"""cloud-deployment.yml: deploys only after every student's CI passes
(rubric 6: "automated deployment through GitHub Actions after required CI/CD
validation"), logging in to Azure with OIDC."""

from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[1] / ".github/workflows"


def triggers(path):
    doc = yaml.safe_load(path.read_text())
    return doc.get("on", doc.get(True))      # PyYAML reads the key `on` as True


def test_every_student_workflow_can_be_called():
    for n in range(1, 6):
        assert "workflow_call" in triggers(WF / f"student-{n}.yml"), n


def test_deploy_waits_for_every_student_ci():
    jobs = yaml.safe_load((WF / "cloud-deployment.yml").read_text())["jobs"]
    assert set(jobs["deploy"]["needs"]) == {f"student-{n}" for n in range(1, 6)}
    for n in range(1, 6):
        assert jobs[f"student-{n}"] == {"uses": f"./.github/workflows/student-{n}.yml", "secrets": "inherit"}  # pragma: allowlist secret


def test_deploy_logs_in_with_oidc_and_reports():
    deploy = yaml.safe_load((WF / "cloud-deployment.yml").read_text())["jobs"]["deploy"]
    assert deploy["permissions"]["id-token"] == "write"
    runs = " ".join(str(s.get("run", "")) + str(s.get("uses", "")) for s in deploy["steps"])
    for needle in ("azure/login@v2", "deploy/azure/setup.sh", "deploy/azure/build-images.sh", "deploy/azure/deploy.sh",
                   "deploy/azure/checks.py", "actions/upload-artifact"):
        assert needle in runs, needle


def test_the_first_deploy_can_run_from_the_conversion_branch():
    # workflow_dispatch only finds workflows that are on the default branch,
    # so until this is merged the branch's own pushes must be able to deploy.
    push = triggers(WF / "cloud-deployment.yml")["push"]
    assert set(push["branches"]) == {"main", "acr-conversion"}


def test_the_region_comes_from_a_repository_variable():
    deploy = yaml.safe_load((WF / "cloud-deployment.yml").read_text())["jobs"]["deploy"]
    assert deploy["env"]["AZ_LOCATION"] == "${{ vars.AZ_LOCATION || 'australiaeast' }}"


def test_the_resource_group_comes_from_a_repository_variable():
    # The registry may be made in the portal, in a group with another name.
    deploy = yaml.safe_load((WF / "cloud-deployment.yml").read_text())["jobs"]["deploy"]
    assert deploy["env"]["AZ_RG"] == "${{ vars.AZ_RG || 'rg-smartbank' }}"


def test_ai_mode_follows_a_repository_variable_and_the_key_a_secret():
    deploy = yaml.safe_load((WF / "cloud-deployment.yml").read_text())["jobs"]["deploy"]
    assert deploy["env"]["AI_MODE_ENABLED"] == "${{ vars.AI_MODE_ENABLED || 'false' }}"
    holders = [s["name"] for s in deploy["steps"] if "GEMINI_API_KEY" in (s.get("env") or {})]
    assert holders == ["Deploy the Container Apps environment and apps"]
    step = next(s for s in deploy["steps"] if s.get("name") == holders[0])
    assert step["env"]["GEMINI_API_KEY"] == "${{ secrets.GEMINI_API_KEY }}"  # pragma: allowlist secret


def test_the_multi_agent_token_is_a_secret_only_the_deploy_step_holds():
    deploy = yaml.safe_load((WF / "cloud-deployment.yml").read_text())["jobs"]["deploy"]
    holders = [s["name"] for s in deploy["steps"] if "MULTI_AGENT_TOKEN" in (s.get("env") or {})]
    assert holders == ["Deploy the Container Apps environment and apps"]
    step = next(s for s in deploy["steps"] if s.get("name") == holders[0])
    assert step["env"]["MULTI_AGENT_TOKEN"] == "${{ secrets.MULTI_AGENT_TOKEN }}"  # noqa: S105  # pragma: allowlist secret (the expression, not a value)


def test_mcp_and_multi_agent_follow_repository_variables():
    env = yaml.safe_load((WF / "cloud-deployment.yml").read_text())["jobs"]["deploy"]["env"]
    assert env["MCP_ENABLED"] == "${{ vars.MCP_ENABLED || 'false' }}"
    assert env["RAG_ENABLED"] == "${{ vars.RAG_ENABLED || 'false' }}"
    assert env["MULTI_AGENT_ENABLED"] == "${{ vars.MULTI_AGENT_ENABLED || 'false' }}"
