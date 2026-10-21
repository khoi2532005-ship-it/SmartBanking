"""The cloud topology, rehearsed locally: every frontend in cloud mode, and no
backend or database port published.

    docker compose -f docker-compose.yml -f docker-compose.cloud.yml up -d --build
    .venv/bin/python -m pytest tests/test_cloud_rehearsal.py -v

The same checks run against the deployed Container Apps from
cloud-deployment.yml (deploy/azure/checks.py).
"""

import pytest
import requests

from deploy.azure import checks

START = "docker compose -f docker-compose.yml -f docker-compose.cloud.yml up -d --build"


@pytest.fixture(scope="session", autouse=True)
def rehearsal_stack():
    """Fails every test at once, with the start command, if the stack is not up."""
    try:
        requests.get("http://localhost:3003/", timeout=5)
    except requests.RequestException as exc:
        pytest.fail(f"the rehearsal stack is not answering on http://localhost:3003 ({type(exc).__name__}). Start it with: {START}")


def web(feature):
    return f"http://localhost:{checks.FEATURES[feature]['web_port']}"


@pytest.mark.parametrize("feature", checks.FEATURES)
def test_frontend_serves_cloud_config(feature):
    r = requests.get(f"{web(feature)}/config.js", timeout=5)
    assert r.status_code == 200 and "SMARTBANK_SAME_ORIGIN_API = true" in r.text


@pytest.mark.parametrize("feature", checks.FEATURES)
def test_api_is_reached_through_the_frontend(feature):
    assert all(c["status"] == c["expected_status"] for c in checks.endpoint_checks(feature, web(feature)))


@pytest.mark.parametrize("feature", checks.FEATURES)
def test_browser_writes_through_the_frontend_are_accepted(feature):
    # Browsers send Origin on same-origin writes, and the proxy forwards it with
    # the backend's Host: origin-checking backends must list their frontend.
    r = requests.get(f"{web(feature)}/api/health", headers={"Origin": web(feature)}, timeout=5)
    assert r.status_code == 200 and r.headers.get("Access-Control-Allow-Origin") in (web(feature), "*")


@pytest.mark.parametrize("feature", checks.FEATURES)
def test_backend_port_is_not_published(feature):
    with pytest.raises(requests.ConnectionError):
        requests.get(f"http://localhost:{checks.FEATURES[feature]['api_port']}/api/health", timeout=3)


@pytest.mark.parametrize("feature", checks.FEATURES)
def test_crud_cycle_through_the_frontend(feature):
    results = checks.crud_checks(feature, web(feature))
    assert [(c["name"], c["status"]) for c in results] == [(c["name"], c["expected_status"]) for c in results]


def test_home_serves_the_frontend_map():
    # In the cloud each feature has its own address, not a port on the home
    # page's host: the home page reads the map from /config.js.
    r = requests.get("http://localhost:3000/config.js", timeout=5)
    assert r.status_code == 200 and '"3003": "http://127.0.0.1:3003"' in r.text


def test_crud_checks_write_with_the_browser_origin():
    # A browser sends Origin on writes, so the checks must too: otherwise a wrong
    # *_FRONTEND_ORIGINS passes the report while every write from the UI is
    # refused. 127.0.0.1:3003 is the fraud frontend under a host fraud-service
    # does not allow.
    results = checks.crud_checks("fraud", "http://127.0.0.1:3003")
    assert (results[0]["name"], results[0]["status"]) == ("fraud create", 403)


def test_checks_wait_for_the_frontends_to_answer():
    assert checks.wait_until_ready({"fraud": "http://localhost:3003"}, timeout=10) == []
    assert checks.wait_until_ready({"nowhere": "http://localhost:3999"}, timeout=3) == ["nowhere"]
