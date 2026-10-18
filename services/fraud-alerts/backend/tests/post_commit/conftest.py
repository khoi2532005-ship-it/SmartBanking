"""Post-commit endpoint tests run against a live fraud-service, never in-process.

    FRAUD_API_URL=http://localhost:5003 python -m pytest services/fraud-alerts/backend/tests/post_commit -v

CI points them at the Compose stack; after a cloud deploy the same suite is
fraud's CRUD check, pointed at the deployed backend.
"""

import os

import pytest
import requests

FRAUD_API_URL = os.getenv("FRAUD_API_URL", "http://localhost:5003").rstrip("/")
START = "docker compose up -d --build --no-deps fraud-database-service fraud-service"


@pytest.fixture(scope="session")
def api():
    """fraud-service's base URL. Every test fails at once, with the fix, if it is not up."""
    try:
        requests.get(f"{FRAUD_API_URL}/api/health", timeout=5).raise_for_status()
    except requests.RequestException as exc:
        pytest.fail(f"fraud-service is not answering at {FRAUD_API_URL} ({type(exc).__name__}). Start it with: {START}")
    return FRAUD_API_URL
