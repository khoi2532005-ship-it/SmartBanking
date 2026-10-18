"""Stand-ins shared by the unit tests: no service, no network, no API key."""

import requests

# Rows shaped exactly as fraud-database-service and the seed fixture return them.
RULE = {"rule_id": 1, "rule_name": "Large Transaction Alert", "rule_type": "amount_over", "threshold_value": 5000.0,
        "threshold_secondary": None, "severity": "high", "enabled": 1, "created_at": "2026-08-01T09:00:00"}
TXN = {"transaction_id": 501, "customer_id": 1, "account_id": 1, "type": "withdrawal", "description": "Unknown Pty Ltd",
       "amount": 7500.0, "date": "2026-09-01T10:00:00", "category": "transfer"}
ALERT = {"alert_id": 1, "rule_id": 1, "customer_id": 1, "transaction_id": 101, "transaction_amount": 7500.0,
         "transaction_recipient": "Unknown Pty Ltd", "transaction_datetime": "2026-08-20T14:32:00",
         "transaction_category": "transfer", "severity": "high", "status": "new", "ai_explanation": None,
         "explanation_generated_at": None, "created_at": "2026-08-20T14:32:05"}


class FakeResponse:
    """Enough of requests.Response for the clients and the database_api callers."""

    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body
        self.text = body if isinstance(body, str) else ""

    def json(self):
        if self._body is None or isinstance(self._body, str):
            raise ValueError("not JSON")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")
