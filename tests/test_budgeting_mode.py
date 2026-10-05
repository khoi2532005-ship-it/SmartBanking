"""Tests for the budgeting loop mode's period handling.

The seeded demo data is September 2026, so from October the current month is
empty. The mode must use the customer's most recent budget period and say so,
unless a period is pinned through the environment. HTTP is stubbed, so no
service is needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentic import net  # noqa: E402
from agentic.modes import budgeting  # noqa: E402

SEPTEMBER = {
    "customer_id": 1, "month": 9, "year": 2026, "spending_source": "transactions-api",
    "totals": {"total_spent": 1486.78, "total_limit": 2160.0, "percent_used": 68.8, "over_budget_count": 1},
    "budgets": [
        {"category": "Dining Out", "spent": 325.2, "monthly_limit": 300.0, "percent_used": 108.4,
         "status": "OVER_BUDGET", "over_budget": True, "over_by": 25.2},
        {"category": "Groceries", "spent": 184.8, "monthly_limit": 800.0, "percent_used": 23.1,
         "status": "ON_TRACK", "over_budget": False, "over_by": 0.0},
    ],
    "over_budget_categories": ["Dining Out"], "unbudgeted_spending": [],
}
EMPTY = {"customer_id": 1, "budgets": [], "totals": {}, "over_budget_categories": [], "spending_source": "transactions-api"}
ALL_BUDGETS = [{"budget_id": 1, "month": 8, "year": 2026}, {"budget_id": 2, "month": 9, "year": 2026}]


@pytest.fixture
def october(monkeypatch):
    """Run as if today were October 2026 with nothing pinned; stub the budgets API."""
    monkeypatch.setattr(budgeting, "MONTH", 10)
    monkeypatch.setattr(budgeting, "YEAR", 2026)
    monkeypatch.setattr(budgeting, "PERIOD_PINNED", False)
    calls: list[str] = []

    def fake_get_json(url, **kwargs):
        calls.append(url)
        if url.endswith("/api/budgets?customer_id=1"):
            return ALL_BUDGETS
        if "month=10&year=2026" in url:
            return dict(EMPTY, month=10, year=2026)
        if "month=9&year=2026" in url:
            return SEPTEMBER
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(net, "get_json", fake_get_json)
    return calls


def test_empty_current_month_falls_back_to_the_latest_budget_period(october):
    evidence = budgeting.BudgetingMode().collect()
    assert evidence.ok
    assert (evidence.facts["month"], evidence.facts["year"]) == (9, 2026)
    assert evidence.facts["period_fallback"] == {"requested": "10/2026", "used": "09/2026"}
    assert "10/2026 has no budgets" in evidence.summary and "09/2026" in evidence.summary
    assert not evidence.degraded                       # real data, different month: not a fallback source


def test_a_pinned_period_is_respected_even_when_empty(october, monkeypatch):
    monkeypatch.setattr(budgeting, "PERIOD_PINNED", True)
    evidence = budgeting.BudgetingMode().collect()
    assert not evidence.ok
    assert "No budgets for customer 1 in 10/2026" in evidence.summary
    assert not any(u.endswith("/api/budgets?customer_id=1") for u in october)


def test_a_populated_current_month_is_used_as_is(october, monkeypatch):
    monkeypatch.setattr(budgeting, "MONTH", 9)
    evidence = budgeting.BudgetingMode().collect()
    assert evidence.ok and evidence.facts["period_fallback"] is None
    assert (evidence.facts["month"], evidence.facts["year"]) == (9, 2026)
    assert not any(u.endswith("/api/budgets?customer_id=1") for u in october)


def test_plan_states_the_fallback_rule_unless_pinned(october, monkeypatch):
    assert any("most recent budget period" in c for c in budgeting.BudgetingMode().plan().checks)
    monkeypatch.setattr(budgeting, "PERIOD_PINNED", True)
    assert not any("most recent budget period" in c for c in budgeting.BudgetingMode().plan().checks)
