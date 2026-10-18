import types

import pytest

from tests.unit.helpers import RULE, TXN, FakeResponse


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def detection_world(monkeypatch):
    """One enabled rule, one transaction that trips it, and an alert store
    that accepts the alert as id 99. .updates records every update_alert call."""
    from routes import detection
    from services import database_api

    world = types.SimpleNamespace(updates=[])
    monkeypatch.setattr(database_api, "search_rules", lambda filters=None: [RULE])
    monkeypatch.setattr(detection, "fetch_transactions", lambda: ([TXN], "seed", 0))
    monkeypatch.setattr(database_api, "create_alert_response", lambda payload: FakeResponse(201, {"alert_id": 99}))
    monkeypatch.setattr(database_api, "update_alert",
                        lambda alert_id, payload: world.updates.append((alert_id, payload)) or {})
    return world
