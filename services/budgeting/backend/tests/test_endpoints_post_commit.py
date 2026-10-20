"""Post-commit endpoint tests for two budgeting API functions (Release 2, student 4).

    GET  /api/budgets/summary   the seeded period, its totals and statuses, and its 400s
    POST /api/budgets           create, the created line in the summary, then 409 and 400

They run against a live budgeting API (BUDGET_API_URL, default http://localhost:5004)
with the seeded database, which is what student-4.yml starts after each push. In CI
there is no transactions service, so spending comes from the deterministic mock and
the exact figures are asserted; against a live transactions service the seeded
limits and the arithmetic are still asserted, the exact figures only for the mock.
Budgets added beyond the seed (a used local volume) are tolerated: counts and totals
are then checked arithmetically rather than against the seed figures. No AI service
is involved; the health answer's MCP, RAG and Multi-Agent flags are recorded in the
report and must all be off in CI.

    BUDGET_API_URL=http://localhost:5004 ENDPOINT_REPORT_DIR=reports \
        python -m pytest services/budgeting/backend/tests/test_endpoints_post_commit.py -q

conftest.py writes post-commit-endpoint-report-student-4.{json,md} into
ENDPOINT_REPORT_DIR from the checks recorded here, also when a run fails.
"""

from __future__ import annotations

import os
import sys
import uuid

import pytest
import requests

API = os.getenv("BUDGET_API_URL", "http://localhost:5004").rstrip("/")
TIMEOUT = 10
PERIOD = {"customer_id": 1, "month": 9, "year": 2026}                 # the seeded demo period

SEEDED_LIMITS = {"Groceries": 800.0, "Dining Out": 300.0, "Transport": 200.0, "Entertainment": 150.0,
                 "Utilities": 250.0, "Shopping": 400.0, "Subscriptions": 60.0}
SEEDED_TOTAL_LIMIT = round(sum(SEEDED_LIMITS.values()), 2)
# What the mock spending source yields for the seeded budgets (the CI stack has no transactions service).
MOCK_EXPECTED = {
    "Groceries": (645.0, "NEAR_LIMIT"), "Dining Out": (412.0, "OVER_BUDGET"), "Transport": (218.0, "OVER_BUDGET"),
    "Entertainment": (90.0, "ON_TRACK"), "Utilities": (240.0, "NEAR_LIMIT"), "Shopping": (505.0, "OVER_BUDGET"),
    "Subscriptions": (59.97, "NEAR_LIMIT"),
}
MOCK_TOTAL_SPENT = round(sum(spent for spent, _ in MOCK_EXPECTED.values()), 2)
MOCK_TOTALS = {"total_limit": SEEDED_TOTAL_LIMIT, "total_spent": MOCK_TOTAL_SPENT,
               "total_remaining": round(SEEDED_TOTAL_LIMIT - MOCK_TOTAL_SPENT, 2),
               "percent_used": round(MOCK_TOTAL_SPENT / SEEDED_TOTAL_LIMIT * 100, 1),
               "budget_count": len(SEEDED_LIMITS),
               "over_budget_count": sum(1 for _, status in MOCK_EXPECTED.values() if status == "OVER_BUDGET")}
MOCK_OVER = sorted(c for c, (_, status) in MOCK_EXPECTED.items() if status == "OVER_BUDGET")

CHECKS: dict[str, list[dict]] = {}            # test function name -> the checks it made (conftest reads this)
ENDPOINTS: dict[str, tuple[str, str]] = {}    # test function name -> (method, path), set by @endpoint
OBSERVED: dict[str, object] = {}              # facts worth reporting: api url, AI flags, spending source


def endpoint(method: str, path: str):
    """Names the endpoint function a test covers, for the report."""
    def mark(fn):
        ENDPOINTS[fn.__name__] = (method, path)
        return fn
    return mark


def _calling_test() -> str:
    return sys._getframe(2).f_code.co_name


def check(label: str, ok: bool, detail: str = "") -> None:
    """Record a check for the report, then assert it."""
    CHECKS.setdefault(_calling_test(), []).append({"check": label, "ok": bool(ok), "detail": detail})
    assert ok, f"{label}: {detail}"


def note(label: str, detail: str = "") -> None:
    """Record a fact for the report without asserting anything."""
    CHECKS.setdefault(_calling_test(), []).append({"check": label, "ok": True, "detail": detail, "info": True})


def body(r: requests.Response) -> dict:
    """The JSON object a response carries, or a marker when it is not JSON, so a
    broken answer fails the check that reads it instead of the test's plumbing."""
    try:
        data = r.json() if r.content else {}
    except ValueError:
        return {"_not_json": r.text[:200]}
    return data if isinstance(data, dict) else {"_not_object": data}


def describe(r: requests.Response) -> str:
    return f"HTTP {r.status_code} {r.text[:120]!r}"


def get(path: str, **params):
    return requests.get(f"{API}{path}", params=params, timeout=TIMEOUT)


def post(path: str, payload):
    return requests.post(f"{API}{path}", json=payload, timeout=TIMEOUT)


@pytest.fixture(scope="session", autouse=True)
def api_is_up():
    OBSERVED["api_url"] = API
    r = requests.get(f"{API}/api/health", timeout=TIMEOUT)
    assert r.status_code == 200, f"{API}/api/health answered {r.status_code}"
    health = body(r)
    flags = {name: bool((health.get(name) or {}).get("enabled")) for name in ("mcp", "rag", "multi_agent")}
    OBSERVED["ai_services"] = {name: ("enabled" if on else "disabled") for name, on in flags.items()}
    if os.getenv("CI"):
        assert not any(flags.values()), f"MCP, RAG and the Multi-Agent Server must stay disabled in CI: {flags}"
    return health


# ---------------------------------------------------------------- 1. GET /api/budgets/summary

@endpoint("GET", "/api/budgets/summary")
def test_budget_summary_reports_the_seeded_period():
    r = get("/api/budgets/summary", **PERIOD)
    check("answers 200 for the seeded period", r.status_code == 200, describe(r))
    s = body(r)
    OBSERVED["spending_source"] = str(s.get("spending_source"))
    check("echoes customer_id, month and year", (s.get("customer_id"), s.get("month"), s.get("year")) == (1, 9, 2026), str(s)[:120])
    lines = {line["category"]: line for line in s.get("budgets", [])}
    check("the seven seeded budgets are present with their limits",
          all(c in lines and lines[c]["monthly_limit"] == limit for c, limit in SEEDED_LIMITS.items()), str(sorted(lines)))
    extra = sorted(set(lines) - set(SEEDED_LIMITS))
    if extra:
        note(f"budgets beyond the seed are present ({extra}): totals are checked arithmetically, not against the seed figures")
    for category, line in lines.items():
        limit, spent = line["monthly_limit"], line["spent"]
        expected_status = ("OVER_BUDGET" if spent > limit else "NEAR_LIMIT" if round(spent / limit * 100, 1) >= 80.0 else "ON_TRACK")
        check(f"{category}: remaining, percent and status follow the limit and the spend",
              line["remaining"] == round(limit - spent, 2) and line["percent_used"] == round(spent / limit * 100, 1)
              and line["status"] == expected_status and line["over_budget"] == (spent > limit)
              and line["over_by"] == (round(spent - limit, 2) if spent > limit else 0.0),
              f"limit {limit} spent {spent} -> {line['status']} remaining {line['remaining']} {line['percent_used']}%")
    totals = s["totals"]
    over = [line["category"] for line in s["budgets"] if line["over_budget"]]
    check("totals add up across the lines",
          totals["budget_count"] == len(lines)
          and totals["total_limit"] == round(sum(l["monthly_limit"] for l in lines.values()), 2)
          and totals["total_spent"] == round(sum(l["spent"] for l in lines.values()), 2)
          and totals["total_remaining"] == round(totals["total_limit"] - totals["total_spent"], 2)
          and totals["percent_used"] == round(totals["total_spent"] / totals["total_limit"] * 100, 1)
          and totals["over_budget_count"] == len(over) and s["over_budget_categories"] == over,
          str(totals))
    if s.get("spending_source") == "mock":
        check("mock spending source: the seeded categories carry the exact figures and statuses",
              all((lines[c]["spent"], lines[c]["status"]) == MOCK_EXPECTED[c] for c in MOCK_EXPECTED),
              str([(c, lines[c]["spent"], lines[c]["status"]) for c in MOCK_EXPECTED]))
        if not extra:
            check("mock spending source: the exact seeded totals and over-budget categories",
                  totals == MOCK_TOTALS and sorted(s["over_budget_categories"]) == MOCK_OVER, str(totals))
    else:
        note(f"spending source is {s.get('spending_source')}: exact mock figures not asserted", str(totals))
    for query, word in (({"customer_id": 1, "month": 13, "year": 2026}, "month"),
                        ({"customer_id": "abc"}, "customer_id"),
                        ({"customer_id": 1, "year": 1999}, "year")):
        r = get("/api/budgets/summary", **query)
        check(f"400 for {query}", r.status_code == 400 and word in str(body(r).get("error", "")), describe(r))


# ---------------------------------------------------------------- 2. POST /api/budgets

@endpoint("POST", "/api/budgets")
def test_create_budget_then_duplicate_and_invalid_bodies():
    count_before = body(get("/api/budgets/summary", **PERIOD)).get("totals", {}).get("budget_count")
    check("the period's budget count is known before the create", isinstance(count_before, int), str(count_before))
    category = f"CI check {uuid.uuid4().hex[:8]}"
    payload = {**PERIOD, "category": category, "monthly_limit": 123.45}
    budget_id = None
    cleanup = None
    try:
        r = post("/api/budgets", payload)
        check("creating a new budget answers 201 with its id",
              r.status_code == 201 and isinstance(body(r).get("budget_id"), int), describe(r))
        budget_id = body(r)["budget_id"]

        s = body(get("/api/budgets/summary", **PERIOD))
        line = next((l for l in s.get("budgets", []) if l.get("budget_id") == budget_id), None)
        check("the new budget appears in the period summary with no spend, on track",
              line is not None and line["category"] == category and line["monthly_limit"] == 123.45
              and line["spent"] == 0.0 and line["remaining"] == 123.45 and line["status"] == "ON_TRACK"
              and s["totals"]["budget_count"] == count_before + 1, str(line))

        r = post("/api/budgets", payload)
        check("the same customer, category and period again answers 409",
              r.status_code == 409 and "already exists" in str(body(r).get("error", "")), describe(r))

        for bad, word in (({**payload, "monthly_limit": 0}, "greater than zero"),
                          ({**payload, "monthly_limit": "lots"}, "Invalid input"),
                          ({k: v for k, v in payload.items() if k != "category"}, "category required"),
                          ({**payload, "month": 13}, "month must be between 1 and 12")):
            r = post("/api/budgets", bad)
            check(f"400 for {word}", r.status_code == 400 and word in str(body(r).get("error", "")), describe(r))
        r = requests.post(f"{API}/api/budgets", data="[1, 2]", headers={"Content-Type": "application/json"}, timeout=TIMEOUT)
        check("400 for a JSON body that is not an object", r.status_code == 400, describe(r))
    finally:
        if budget_id is not None:                                       # leave the stack as it was found
            try:
                d = requests.delete(f"{API}/api/budgets/{budget_id}", timeout=TIMEOUT)
                cleanup = (d.status_code, d.text[:80])
            except requests.RequestException as exc:                    # never hide the check that failed above
                cleanup = ("error", f"{type(exc).__name__}: {exc}")
            CHECKS.setdefault("test_create_budget_then_duplicate_and_invalid_bodies", []).append(
                {"check": "cleanup: the test budget is deleted again", "ok": cleanup[0] in (200, 204), "detail": str(cleanup)})
    assert cleanup is not None and cleanup[0] in (200, 204), f"cleanup failed, budget {budget_id} may remain: {cleanup}"
    s = body(get("/api/budgets/summary", **PERIOD))
    check("the period is back to its previous budget count", s.get("totals", {}).get("budget_count") == count_before,
          f"{s.get('totals', {}).get('budget_count')} vs {count_before}")
