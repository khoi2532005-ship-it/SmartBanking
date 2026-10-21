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
                         'esac\n')
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}", "ACR_NAME": "smartbanktest",
           "IMAGE_TAG": "abc123"}

    def run(script):
        result = subprocess.run(["bash", str(ROOT / "deploy/azure" / script)], env=env, cwd=ROOT,  # noqa: S603, S607  # a script from this repo
                                capture_output=True, text=True)
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
    assert len(builds) == 14
    tags = [re.search(r"--tag (\S+)", b).group(1) for b in builds]
    assert all("--platform linux/amd64" in b and b.endswith(" .") for b in builds)
    assert all(re.fullmatch(r"smartbanktest\.azurecr\.io/smartbank-[a-z-]+:abc123", t) for t in tags)
    assert sorted(pushes) == sorted(tags)


def test_setup_registers_every_provider_the_deployment_uses(run_script):
    calls = run_script("setup.sh")
    registered = {re.search(r"--namespace (\S+)", c).group(1) for c in calls if c.startswith("az provider register")}
    assert registered == PROVIDERS
    assert any(c.startswith("az group create") for c in calls) and any(c.startswith("az acr create") for c in calls)


def test_oidc_setup_registers_the_same_providers():
    # The CI identity cannot register providers (it holds rights on the
    # resource group only), so the owner's one-time setup must register them all.
    line = re.search(r"for namespace in (.+); do", (ROOT / "deploy/azure/oidc-setup.sh").read_text()).group(1)
    assert set(line.split()) == PROVIDERS
