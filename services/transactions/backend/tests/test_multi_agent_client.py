from pathlib import Path
import os
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services import multi_agent_client as ma  # noqa: E402

WID = "wf_0a1b2c3d"


class _env:
    def __init__(self, **values):
        self.values, self.saved = values, {}

    def __enter__(self):
        for k, v in self.values.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, old in self.saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


class FakeServer:
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/health":
            return 200, {"service": "multi-agent-server", "pipeline": ["planner", "worker", "reviewer", "human"]}
        if (method, path) == ("POST", "/workflow"):
            return 202, {"workflow_id": WID, "feature": "transactions", "state": "created", "stages": []}
        if path == f"/workflow/{WID}/status":
            return 200, {"workflow_id": WID, "feature": "transactions", "state": "awaiting_human_review", "stages": []}
        if path == f"/workflow/{WID}":
            return 200, {"workflow_id": WID, "feature": "transactions", "state": "awaiting_human_review", "plan": {"tasks": []}, "result": {"answer": "ok"}, "review": {"verdict": "accept"}}
        if (method, path) == ("POST", f"/workflow/{WID}/decision"):
            return 200, {"workflow_id": WID, "feature": "transactions", "state": "accepted", "stages": [], "decision": {"decision": body["decision"]}}
        if path == f"/workflow/{WID}/response":
            return 200, {"workflow_id": WID, "feature": "transactions", "decision": "accept", "released": True, "answer": "ok"}
        if path == "/workflows/pending":
            return 200, {"count": 1, "workflows": [{"workflow_id": WID, "feature": "transactions"}]}
        return 404, {"error": "unknown"}


class _stub:
    def __init__(self, fake):
        self.fake = fake

    def __enter__(self):
        self.saved = ma._request
        ma._request = self.fake
        return self.fake

    def __exit__(self, *exc):
        ma._request = self.saved


def test_feature_client_uses_transactions_and_posts_context():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()) as fake:
        summary = ma.start("Which spending categories are highest?", "1", "9", "2026")
        assert ma.FEATURE == "transactions"
        assert summary["workflow_id"] == WID
        assert fake.calls[-1] == (
            "POST",
            "/workflow",
            {"feature": "transactions", "request": "Which spending categories are highest?",
             "context": {"customer_id": 1, "month": 9, "year": 2026}},
        )


def test_response_and_pending_are_feature_scoped():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()) as fake:
        assert ma.is_transactions({"feature": "transactions"}) is True
        assert ma.is_transactions({"feature": "budgeting"}) is False
        final = ma.response(WID)
        assert final["released"] is True and final["decision"] == "accept"
        pending = ma.pending()
        assert pending["count"] == 1 and pending["workflows"][0]["feature"] == "transactions"
