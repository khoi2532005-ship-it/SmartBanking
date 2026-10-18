"""Stand-ins shared by the unit tests: no service, no network, no API key."""

import requests


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
