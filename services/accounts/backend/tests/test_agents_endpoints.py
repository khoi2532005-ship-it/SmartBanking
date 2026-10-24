"""Endpoint tests for the Multi-Agent routes (Release 2).

CI runs exactly two endpoint functions of this backend's own API, per the
Release 2 brief: start_workflow (POST /api/agents/workflow) and get_workflow
(GET /api/agents/workflow/<id>), both in routes/agents.py. Both run against a
Flask test client with services.multi_agent_client monkeypatched, so no
running Multi-Agent Server, API key or network call is needed - the same
"no server, no key, no network" guarantee the shared engine tests give.

Run with:  python -m tests.test_agents_endpoints   (from services/accounts/backend/)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402
from services import multi_agent_client  # noqa: E402

SUMMARY = {"workflow_id": "wf_0a1b2c3d", "feature": "accounts", "state": "planning", "stages": []}
FULL_RECORD = {**SUMMARY, "request": "Summarise accounts", "context": {"customer_id": 1},
                "created_at": "2026-10-21T00:00:00+00:00", "updated_at": "2026-10-21T00:00:00+00:00",
                "revisions": 0, "plan": None, "result": None, "review": None, "decision": None,
                "final_response": None, "error": ""}


class TestStartWorkflow(unittest.TestCase):
    """POST /api/agents/workflow -> routes.agents.start_workflow"""

    def setUp(self):
        self.client = create_app().test_client()

    def test_valid_request_starts_a_workflow_and_returns_202(self):
        with patch.object(multi_agent_client, "start", return_value=SUMMARY) as start:
            response = self.client.post(
                "/api/agents/workflow",
                json={"task": "Summarise this customer's accounts.", "customer_id": 1},
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["workflow_id"], "wf_0a1b2c3d")
        start.assert_called_once_with("Summarise this customer's accounts.", 1)

    def test_missing_task_is_a_400_before_any_call(self):
        with patch.object(multi_agent_client, "start") as start:
            response = self.client.post("/api/agents/workflow", json={"customer_id": 1})
        self.assertEqual(response.status_code, 400)
        self.assertIn("task", response.get_json()["error"])
        start.assert_not_called()

    def test_disabled_server_is_reported_as_503(self):
        with patch.object(multi_agent_client, "start",
                           side_effect=multi_agent_client.ServerDisabled("Multi-Agent is switched off")):
            response = self.client.post(
                "/api/agents/workflow", json={"task": "Summarise accounts.", "customer_id": 1}
            )
        self.assertEqual(response.status_code, 503)
        self.assertTrue(response.get_json()["disabled"])


class TestGetWorkflow(unittest.TestCase):
    """GET /api/agents/workflow/<id> -> routes.agents.get_workflow"""

    def setUp(self):
        self.client = create_app().test_client()

    def test_known_accounts_workflow_returns_the_record(self):
        with patch.object(multi_agent_client, "workflow", return_value=FULL_RECORD):
            response = self.client.get("/api/agents/workflow/wf_0a1b2c3d")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["workflow_id"], "wf_0a1b2c3d")
        self.assertEqual(body["feature"], "accounts")

    def test_malformed_id_is_a_400_before_any_call(self):
        with patch.object(multi_agent_client, "workflow") as workflow:
            response = self.client.get("/api/agents/workflow/not-a-workflow-id")
        self.assertEqual(response.status_code, 400)
        workflow.assert_not_called()

    def test_another_features_workflow_is_404(self):
        with patch.object(
            multi_agent_client, "workflow",
            side_effect=multi_agent_client.WorkflowRefused(404, "unknown accounts workflow wf_0a1b2c3d", {}),
        ):
            response = self.client.get("/api/agents/workflow/wf_0a1b2c3d")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
