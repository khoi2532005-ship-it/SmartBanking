"""Checks for the budget-versus-actual calculations.

Plain assertions with a __main__ runner, so CI needs no test framework
(pytest arrives in Release 2). Run from services/budgeting/backend:

    python -m tests.test_budget_logic
"""

from pathlib import Path
import importlib.util
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services.budget_logic import (  # noqa: E402
    NEAR_LIMIT_THRESHOLD,
    build_summary,
    evaluate_budget,
)
from services import transactions_client  # noqa: E402


def _budget(budget_id, category, limit, customer_id=1, month=9, year=2026):
    return {
        "budget_id": budget_id,
        "customer_id": customer_id,
        "category": category,
        "monthly_limit": limit,
        "month": month,
        "year": year,
    }


def test_under_budget_is_on_track():
    line = evaluate_budget(_budget(1, "Groceries", 800.0), 400.0)
    assert line["status"] == "ON_TRACK", line
    assert line["over_budget"] is False
    assert line["spent"] == 400.0
    assert line["remaining"] == 400.0
    assert line["percent_used"] == 50.0
    assert line["over_by"] == 0.0


def test_over_budget_is_flagged():
    line = evaluate_budget(_budget(2, "Dining Out", 300.0), 412.0)
    assert line["status"] == "OVER_BUDGET", line
    assert line["over_budget"] is True
    assert line["remaining"] == -112.0
    assert line["over_by"] == 112.0
    assert line["percent_used"] == 137.3


def test_near_limit_threshold():
    line = evaluate_budget(_budget(3, "Utilities", 100.0), NEAR_LIMIT_THRESHOLD)
    assert line["status"] == "NEAR_LIMIT", line
    assert line["over_budget"] is False


def _seed():
    """The real seed: services/budgeting/database/init_db.py, whose rows are constants
    (importing it writes nothing), loaded by path under a name of its own."""
    path = BASE_DIR.parent / "database" / "init_db.py"
    spec = importlib.util.spec_from_file_location("budgeting_seed_for_logic_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seeded_september():
    """Customer 1's seeded budgets for September 2026, as budget dicts."""
    return [_budget(budget_id, category, limit) for budget_id, customer, category, limit, month, year, _created
            in _seed().BUDGETS if (customer, month, year) == (1, 9, 2026)]


def test_seed_holds_the_known_september_budgets():
    """Pinned by value: a changed seeded limit or an added or removed budget fails here."""
    got = [(b["budget_id"], b["category"], b["monthly_limit"]) for b in _seeded_september()]
    assert got == [(1, "Groceries", 800.0), (2, "Dining Out", 300.0), (3, "Transport", 200.0), (4, "Entertainment", 150.0),
                   (5, "Utilities", 250.0), (6, "Shopping", 400.0), (7, "Subscriptions", 60.0)], got


def test_near_limit_threshold_is_80_percent():
    """Pinned by value: changing the threshold in budget_logic.py must fail here."""
    assert NEAR_LIMIT_THRESHOLD == 80.0, NEAR_LIMIT_THRESHOLD
    for spent, status in ((79.9, "ON_TRACK"), (80.0, "NEAR_LIMIT"), (100.0, "NEAR_LIMIT"), (100.01, "OVER_BUDGET")):
        assert evaluate_budget(_budget(9, "Health", 100.0), spent)["status"] == status, (spent, status)


def test_seeded_period_with_mock_spending_gives_the_known_figures():
    """The real seed against the mock spending: the figures the demo and the
    post-commit endpoint tests rest on, pinned here by value."""
    totals, source, _ = transactions_client.spend_by_category(1, 9, 2026)
    assert source == "mock", source
    summary = build_summary(_seeded_september(), totals)
    got = {line["category"]: (line["spent"], line["status"]) for line in summary["budgets"]}
    assert got == {
        "Groceries": (645.0, "NEAR_LIMIT"), "Dining Out": (412.0, "OVER_BUDGET"), "Transport": (218.0, "OVER_BUDGET"),
        "Entertainment": (90.0, "ON_TRACK"), "Utilities": (240.0, "NEAR_LIMIT"), "Shopping": (505.0, "OVER_BUDGET"),
        "Subscriptions": (59.97, "NEAR_LIMIT"),
    }, got
    assert summary["totals"] == {
        "total_limit": 2160.0, "total_spent": 2169.97, "total_remaining": -9.97, "percent_used": 100.5,
        "budget_count": 7, "over_budget_count": 3,
    }, summary["totals"]
    assert summary["over_budget_categories"] == ["Dining Out", "Transport", "Shopping"], summary["over_budget_categories"]
    assert summary["unbudgeted_spending"] == [], summary["unbudgeted_spending"]


def test_exactly_on_limit_is_not_over():
    line = evaluate_budget(_budget(4, "Transport", 200.0), 200.0)
    assert line["over_budget"] is False, line
    assert line["status"] == "NEAR_LIMIT"
    assert line["remaining"] == 0.0


def test_no_spending_is_on_track():
    line = evaluate_budget(_budget(5, "Health", 150.0), 0.0)
    assert line["status"] == "ON_TRACK", line
    assert line["spent"] == 0.0
    assert line["percent_used"] == 0.0


def test_zero_limit_does_not_divide_by_zero():
    line = evaluate_budget(_budget(6, "Odd", 0.0), 50.0)
    assert line["percent_used"] == 0.0, line
    assert line["over_budget"] is False


def test_summary_totals_and_over_budget_list():
    budgets = [
        _budget(1, "Groceries", 800.0),
        _budget(2, "Dining Out", 300.0),
        _budget(3, "Transport", 200.0),
    ]
    spend = {"Groceries": 645.0, "Dining Out": 412.0, "Transport": 218.0}

    summary = build_summary(budgets, spend)
    totals = summary["totals"]

    assert totals["total_limit"] == 1300.0, totals
    assert totals["total_spent"] == 1275.0, totals
    assert totals["total_remaining"] == 25.0, totals
    assert totals["budget_count"] == 3
    assert totals["over_budget_count"] == 2, totals
    assert summary["over_budget_categories"] == ["Dining Out", "Transport"], summary


def test_summary_reports_unbudgeted_spending():
    budgets = [_budget(1, "Groceries", 800.0)]
    spend = {"Groceries": 100.0, "Gambling": 250.0, "Empty": 0.0}

    summary = build_summary(budgets, spend)

    assert summary["unbudgeted_spending"] == [{"category": "Gambling", "spent": 250.0}], (
        summary["unbudgeted_spending"]
    )


def test_summary_handles_no_budgets():
    summary = build_summary([], {"Groceries": 100.0})

    assert summary["budgets"] == []
    assert summary["totals"]["total_limit"] == 0.0
    assert summary["totals"]["percent_used"] == 0.0
    assert summary["totals"]["over_budget_count"] == 0


def test_budget_with_no_matching_spend_shows_zero():
    budgets = [_budget(1, "Groceries", 800.0)]
    summary = build_summary(budgets, {})
    assert summary["budgets"][0]["spent"] == 0.0
    assert summary["totals"]["total_spent"] == 0.0


def test_mock_transactions_are_filtered_by_period_and_customer():
    """The mock fallback must behave like a real per-customer, per-month API."""
    totals, source, transactions = transactions_client.spend_by_category(1, 9, 2026)

    assert source == "mock", source
    assert transactions, "mock returned no transactions"
    assert all(int(t["customer_id"]) == 1 for t in transactions)
    assert all(t["transaction_date"].startswith("2026-09") for t in transactions)

    # Matches the figures the seeded insights refer to.
    assert totals["Dining Out"] == 412.00, totals
    assert totals["Groceries"] == 645.00, totals
    assert totals["Transport"] == 218.00, totals
    assert totals["Shopping"] == 505.00, totals


def test_mock_transactions_differ_by_customer():
    totals_one, _, _ = transactions_client.spend_by_category(1, 9, 2026)
    totals_two, _, _ = transactions_client.spend_by_category(2, 9, 2026)
    assert totals_one != totals_two
    assert "Education" in totals_two, totals_two


def test_mock_transactions_empty_for_unknown_period():
    totals, _, transactions = transactions_client.spend_by_category(1, 1, 2020)
    assert totals == {}, totals
    assert transactions == []


def _run():
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]

    failures = []
    for name, test in tests:
        try:
            test()
            print(f"PASS {name}")
        except AssertionError as exc:
            failures.append((name, exc))
            print(f"FAIL {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures.append((name, exc))
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")

    print(f"\n{len(tests) - len(failures)}/{len(tests)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    # Force the mock path so the checks never depend on a live Transactions API.
    transactions_client.USE_MOCK_TRANSACTIONS = "true"
    sys.exit(_run())
