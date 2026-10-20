"""Post-commit endpoint tests for two budgeting API functions (Release 2, student 4).

    GET  /api/budgets/summary   the seeded period, its totals and statuses, and its 400s
    POST /api/budgets           create, the created line in the summary, then 409 and 400

They run against a live budgeting API (BUDGET_API_URL, default http://localhost:5004)
with the seeded database, which is what student-4.yml starts after each push. In CI
there is no transactions service, so spending comes from the deterministic mock and
the exact figures are asserted; against a live transactions service the seeded
limits and the arithmetic are still asserted, the exact figures only for the mock.
No AI service is involved: MCP, RAG and the Multi-Agent Server stay disabled.

    BUDGET_API_URL=http://localhost:5004 ENDPOINT_REPORT_DIR=reports \
        python -m pytest services/budgeting/backend/tests/test_endpoints_post_commit.py -q

conftest.py writes post-commit-endpoint-report-student-4.{json,md} into
ENDPOINT_REPORT_DIR from the checks recorded here.
"""

from __future__ import annotations

import os
import uuid

import pytest
import requests

API = os.getenv("BUDGET_API_URL", "http://localhost:5004").rstrip("/")
TIMEOUT = 10
PERIOD = {"customer_id": 1, "month": 9, "year": 2026}                 # the seeded demo period

SEEDED_LIMITS = {"Groceries": 800.0, "Dining Out": 300.0, "Transport": 200.0, "Entertainment": 150.0,
                 "Utilities": 250.0, "Shopping": 400.0, "Subscriptions": 60.0}
# What the mock spending source yields for the seeded budgets (the CI stack has no transactions service).
MOCK_EXPECTED = {
    "Groceries": (645.0, "NEAR_LIMIT"), "Dining Out": (412.0, "OVER_BUDGET"), "Transport": (218.0, "OVER_BUDGET"),
    "Entertainment": (90.0, "ON_TRACK"), "Utilities": (240.0, "NEAR_LIMIT"), "Shopping": (505.0, "OVER_BUDGET"),
    "Subscriptions": (59.97, "NEAR_LIMIT"),
}
MOCK_TOTALS = {"total_limit": 2160.0, "total_spent": 2169.97, "total_remaining": -9.97, "percent_used": 100.5,
               "budget_count": 7, "over_budget_count": 3}
MOCK_OVER = ["Dining Out", "Transport", "Shopping"]

CHECKS: dict[str, list[dict]] = {}       # test name -> the checks it made; conftest reads this for the report
OBSERVED: dict[str, str] = {}            # facts worth reporting (api url, spending source)


def check(test: str, label: str, ok: bool, detail: str = "") -> None:
    CHECKS.setdefault(test, []).append({"check": label, "ok": bool(ok), "detail": detail})
    assert ok, f"{label}: {detail}"


def get(path: str, **params):
    return requests.get(f"{API}{path}", params=params, timeout=TIMEOUT)


def post(path: str, body):
    return requests.post(f"{API}{path}", json=body, timeout=TIMEOUT)


@pytest.fixture(scope="session", autouse=True)
def api_is_up():
    OBSERVED["api_url"] = API
    r = requests.get(f"{API}/api/health", timeout=TIMEOUT)
    assert r.status_code == 200, f"{API}/api/health answered {r.status_code}"
    health = r.json()
    OBSERVED["health"] = health.get("status", "")
    assert health.get("mcp", {}).get("enabled") is not True or os.getenv("CI") is None, "MCP must stay disabled in CI"
    return health


# ---------------------------------------------------------------- 1. GET /api/budgets/summary

def test_budget_summary_reports_the_seeded_period():
    t = "GET /api/budgets/summary"
    r = get("/api/budgets/summary", **PERIOD)
    check(t, "answers 200 for the seeded period", r.status_code == 200, f"HTTP {r.status_code}")
    s = r.json()
    OBSERVED["spending_source"] = str(s.get("spending_source"))
    check(t, "echoes customer_id, month and year", (s["customer_id"], s["month"], s["year"]) == (1, 9, 2026))
    lines = {line["category"]: line for line in s["budgets"]}
    check(t, "the seven seeded budgets are present with their limits",
          {c: line["monthly_limit"] for c, line in lines.items()} == SEEDED_LIMITS and s["totals"]["budget_count"] == 7,
          str(sorted(lines)))
    for category, line in lines.items():
        limit, spent = line["monthly_limit"], line["spent"]
        expected_status = ("OVER_BUDGET" if spent > limit else "NEAR_LIMIT" if round(spent / limit * 100, 1) >= 80.0 else "ON_TRACK")
        check(t, f"{category}: remaining, percent and status follow the limit and the spend",
              line["remaining"] == round(limit - spent, 2) and line["percent_used"] == round(spent / limit * 100, 1)
              and line["status"] == expected_status and line["over_budget"] == (spent > limit)
              and line["over_by"] == (round(spent - limit, 2) if spent > limit else 0.0),
              f"limit {limit} spent {spent} -> {line['status']} remaining {line['remaining']} {line['percent_used']}%")
    totals = s["totals"]
    over = [line["category"] for line in s["budgets"] if line["over_budget"]]
    check(t, "totals add up across the seven lines",
          totals["total_limit"] == 2160.0 and totals["total_spent"] == round(sum(l["spent"] for l in s["budgets"]), 2)
          and totals["total_remaining"] == round(totals["total_limit"] - totals["total_spent"], 2)
          and totals["percent_used"] == round(totals["total_spent"] / totals["total_limit"] * 100, 1)
          and totals["over_budget_count"] == len(over) and s["over_budget_categories"] == over,
          str(totals))
    if s.get("spending_source") == "mock":
        check(t, "mock spending source: the exact seeded figures and statuses",
              {c: (l["spent"], l["status"]) for c, l in lines.items()} == MOCK_EXPECTED
              and totals == MOCK_TOTALS and sorted(s["over_budget_categories"]) == sorted(MOCK_OVER),
              f"spent/status per category {[(c, l['spent'], l['status']) for c, l in lines.items()]}")
    else:
        CHECKS[t].append({"check": f"spending source is {s.get('spending_source')}: exact mock figures not asserted",
                          "ok": True, "detail": str(totals)})
    for query, word in (({"customer_id": 1, "month": 13, "year": 2026}, "month"),
                        ({"customer_id": "abc"}, "customer_id"),
                        ({"customer_id": 1, "year": 1999}, "year")):
        r = get("/api/budgets/summary", **query)
        check(t, f"400 for {query}", r.status_code == 400 and word in r.json().get("error", ""),
              f"HTTP {r.status_code} {r.text[:80]}")


# ---------------------------------------------------------------- 2. POST /api/budgets

def test_create_budget_then_duplicate_and_invalid_bodies():
    t = "POST /api/budgets"
    category = f"CI check {uuid.uuid4().hex[:8]}"
    body = {**PERIOD, "category": category, "monthly_limit": 123.45}
    budget_id = None
    try:
        r = post("/api/budgets", body)
        check(t, "creating a new budget answers 201 with its id",
              r.status_code == 201 and isinstance(r.json().get("budget_id"), int), f"HTTP {r.status_code} {r.text[:120]}")
        budget_id = r.json()["budget_id"]

        s = get("/api/budgets/summary", **PERIOD).json()
        line = next((l for l in s["budgets"] if l["budget_id"] == budget_id), None)
        check(t, "the new budget appears in the period summary with no spend, on track",
              line is not None and line["category"] == category and line["monthly_limit"] == 123.45
              and line["spent"] == 0.0 and line["remaining"] == 123.45 and line["status"] == "ON_TRACK"
              and s["totals"]["budget_count"] == 8, str(line))

        r = post("/api/budgets", body)
        check(t, "the same customer, category and period again answers 409",
              r.status_code == 409 and "already exists" in r.json().get("error", ""), f"HTTP {r.status_code} {r.text[:120]}")

        for bad, word in (({**body, "monthly_limit": 0}, "greater than zero"),
                          ({**body, "monthly_limit": "lots"}, "Invalid input"),
                          ({k: v for k, v in body.items() if k != "category"}, "category required"),
                          ({**body, "month": 13}, "month must be between 1 and 12")):
            r = post("/api/budgets", bad)
            check(t, f"400 for {word}", r.status_code == 400 and word in r.json().get("error", ""),
                  f"HTTP {r.status_code} {r.text[:120]}")
        r = requests.post(f"{API}/api/budgets", data="[1, 2]", headers={"Content-Type": "application/json"}, timeout=TIMEOUT)
        check(t, "400 for a JSON body that is not an object", r.status_code == 400, f"HTTP {r.status_code}")
    finally:
        if budget_id is not None:                                       # leave the stack as it was found
            d = requests.delete(f"{API}/api/budgets/{budget_id}", timeout=TIMEOUT)
            CHECKS.setdefault(t, []).append({"check": "cleanup: the test budget is deleted again",
                                             "ok": d.status_code in (200, 204), "detail": f"HTTP {d.status_code}"})
    s = get("/api/budgets/summary", **PERIOD).json()
    check(t, "the period is back to the seven seeded budgets", s["totals"]["budget_count"] == 7)
