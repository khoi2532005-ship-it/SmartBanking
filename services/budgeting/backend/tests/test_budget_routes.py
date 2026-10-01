"""Checks for the budgets read routes: query-string validation and the period default.

Same plain-assert runner as the other budgeting checks, so CI needs no test
framework. The database and Transactions calls are stubbed, so these run
without any service. From services/budgeting/backend:

    python -m tests.test_budget_routes
"""

from datetime import date
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services import database_api, transactions_client  # noqa: E402


class _stubbed:
    """Answer the database and Transactions calls without a network."""

    def __enter__(self):
        self.saved = (database_api.search_budgets, transactions_client.spend_by_category)
        self.calls = []
        database_api.search_budgets = lambda filters: self.calls.append(("budgets", dict(filters))) or []
        transactions_client.spend_by_category = (
            lambda customer_id, month, year: self.calls.append(("spend", customer_id, month, year)) or ({}, "mock", [])
        )
        return self

    def __exit__(self, *exc):
        database_api.search_budgets, transactions_client.spend_by_category = self.saved


def _client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


READ_ROUTES = ("/api/budgets/summary", "/api/transactions/spending")


def test_non_integer_or_out_of_range_arguments_are_400_not_500():
    """customer_id=abc used to reach the database call and come back as a 500."""
    with _stubbed() as stub:
        c = _client()
        for route in READ_ROUTES:
            for query, word in (("customer_id=abc", "customer_id"), ("customer_id=0", "customer_id"),
                                ("customer_id=1&month=13", "month"), ("customer_id=1&month=abc", "month"),
                                ("customer_id=1&year=abc", "year"), ("customer_id=1&year=1999", "year")):
                r = c.get(f"{route}?{query}")
                assert r.status_code == 400, (route, query, r.status_code)
                assert word in r.get_json()["error"], (route, query, r.get_json())
        assert stub.calls == [], "nothing may be called before the arguments are valid"


def test_explicit_period_is_used_as_given():
    with _stubbed() as stub:
        c = _client()
        r = c.get("/api/budgets/summary?customer_id=2&month=9&year=2026")
        assert r.status_code == 200
        body = r.get_json()
        assert (body["customer_id"], body["month"], body["year"]) == (2, 9, 2026)
        assert ("budgets", {"customer_id": 2, "month": 9, "year": 2026}) in stub.calls


def test_period_defaults_to_the_current_month_and_an_empty_month_stays_empty():
    """No silent fallback to another month: an empty period is reported as empty."""
    today = date.today()
    with _stubbed():
        c = _client()
        r = c.get("/api/budgets/summary?customer_id=1")
        assert r.status_code == 200
        body = r.get_json()
        assert (body["month"], body["year"]) == (today.month, today.year)
        assert body["budgets"] == [] and body["totals"].get("budget_count", 0) == 0


def _run():
    tests = [(n, o) for n, o in sorted(globals().items()) if n.startswith("test_") and callable(o)]
    failures = []
    for name, test in tests:
        try:
            test()
            print(f"PASS {name}")
        except AssertionError as exc:
            failures.append(name)
            print(f"FAIL {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures.append(name)
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - len(failures)}/{len(tests)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run())
