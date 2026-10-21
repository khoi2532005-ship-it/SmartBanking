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
