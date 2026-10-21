"""Post-commit endpoint tests for two budgeting API functions (Release 2, student 4).

    GET  /api/budgets/summary   the seeded period, its totals and statuses, and its 400s
    POST /api/budgets           create, the created line in the summary, then 409 and 400

They run against a live budgeting API (BUDGET_API_URL, default http://localhost:5004)
with the seeded database, which is what student-4.yml starts on every pull request into
main and every push to main. With no API answering and BUDGET_API_URL unset they skip,
so a local pytest run without the stack is not red; with BUDGET_API_URL set (CI) an API
that does not answer is a failure. In CI there is no transactions service, so spending
comes from the deterministic mock and the exact figures are asserted; budgets added
beyond the seed are tolerated and the totals are then checked arithmetically. No AI
service is involved; the health answer's MCP, RAG and Multi-Agent flags are recorded and
must all be off in CI.

Every check is recorded on the test itself through pytest's record_property, so it lands
in the JUnit XML and in the report conftest.py writes (ENDPOINT_REPORT_DIR).

    BUDGET_API_URL=http://localhost:5004 ENDPOINT_REPORT_DIR=reports \
        python -m pytest services/budgeting/backend/tests/test_endpoints_post_commit.py -q
"""

from __future__ import annotations

import json
import os
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
LINE_KEYS = ("category", "monthly_limit", "spent", "remaining", "percent_used", "status", "over_budget", "over_by")
TOTAL_KEYS = ("total_limit", "total_spent", "total_remaining", "percent_used", "budget_count", "over_budget_count")
NEAR_LIMIT_PERCENT = 80.0


# ---------------------------------------------------------------- helpers

def body(r: requests.Response) -> dict:
    """The JSON object a response carries, or a marker when it is not one, so a broken
    answer fails the check that reads it instead of the test's plumbing."""
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


def expected_line(limit: float, spent: float) -> dict:
    """What services/budget_logic.evaluate_budget derives from a limit and a spend."""
    percent = round(spent / limit * 100, 1) if limit > 0 else 0.0
    status = "OVER_BUDGET" if limit > 0 and spent > limit else ("NEAR_LIMIT" if percent >= NEAR_LIMIT_PERCENT else "ON_TRACK")
    return {"remaining": round(limit - spent, 2), "percent_used": percent, "status": status,
            "over_budget": status == "OVER_BUDGET", "over_by": round(spent - limit, 2) if spent > limit else 0.0}


def remove_test_budgets(budget_id, category: str) -> tuple[bool, str]:
    """Delete the test's budget by id, or, when the create's answer was lost, every
    budget carrying the test's unique category, so nothing is left in the seeded period."""
    try:
        ids = [budget_id] if budget_id is not None else [
            b.get("budget_id") for b in get("/api/budgets", **PERIOD, category=category).json()
            if isinstance(b, dict) and b.get("category") == category]
        statuses = [requests.delete(f"{API}/api/budgets/{i}", timeout=TIMEOUT).status_code for i in ids]
    except (requests.RequestException, ValueError, AttributeError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if not ids:
        return True, "no test budget was created"
    return all(s in (200, 204) for s in statuses), f"deleted {ids}: HTTP {statuses}"


class Checks:
    """Records every check on the running test (pytest's record_property), then asserts it."""

    def __init__(self, record_property):
        self._record = record_property

    def record(self, label: str, ok: bool, detail: str = "", *, info: bool = False) -> None:
        self._record("check", json.dumps({"check": label, "ok": bool(ok), "detail": detail, "info": info}))

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        self.record(label, ok, detail)
        assert ok, f"{label}: {detail}"

    def note(self, label: str, detail: str = "") -> None:
        self.record(label, True, detail, info=True)

    def observe(self, **facts) -> None:
        self._record("observed", json.dumps(facts))


@pytest.fixture(scope="session")
def api_is_up():
    """The health answer. Skips the module when no API answers and BUDGET_API_URL is unset."""
    try:
        r = requests.get(f"{API}/api/health", timeout=TIMEOUT)
    except requests.RequestException as exc:
        if not os.getenv("BUDGET_API_URL"):
            pytest.skip(f"no budgeting API at {API} ({type(exc).__name__}); start the stack or set BUDGET_API_URL")
        pytest.fail(f"{API}/api/health did not answer: {type(exc).__name__}: {exc}")
    if r.status_code != 200:
        pytest.fail(f"{API}/api/health answered {describe(r)}")
    health = body(r)
    flags = {name: bool((health.get(name) or {}).get("enabled")) for name in ("mcp", "rag", "multi_agent")}
    if os.getenv("CI") and any(flags.values()):
        pytest.fail(f"MCP, RAG and the Multi-Agent Server must stay disabled in CI: {flags}")
    return {"ai_services": {name: ("enabled" if on else "disabled") for name, on in flags.items()}}


@pytest.fixture
def checks(api_is_up, record_property):
    recorder = Checks(record_property)
    recorder.observe(api_url=API, **api_is_up)
    return recorder


# ---------------------------------------------------------------- 1. GET /api/budgets/summary

@pytest.mark.endpoint("GET", "/api/budgets/summary")
def test_budget_summary_reports_the_seeded_period(checks):
    r = get("/api/budgets/summary", **PERIOD)
    checks.check("answers 200 for the seeded period", r.status_code == 200, describe(r))
    s = body(r)
    checks.observe(spending_source=str(s.get("spending_source")))
    checks.check("the answer carries a budgets list and a totals object with every total",
                 isinstance(s.get("budgets"), list) and isinstance(s.get("totals"), dict)
                 and all(k in s["totals"] for k in TOTAL_KEYS), f"keys {sorted(s)}")
    checks.check("echoes customer_id, month and year", (s.get("customer_id"), s.get("month"), s.get("year")) == (1, 9, 2026),
                 str({k: s.get(k) for k in ("customer_id", "month", "year")}))
    malformed = [l for l in s["budgets"] if not (isinstance(l, dict) and all(k in l for k in LINE_KEYS))]
    checks.check("every budget line carries its limit, spend, remaining, percent and status",
                 not malformed, str(malformed[:1]))
    lines = {line["category"]: line for line in s["budgets"]}
    checks.check("the seven seeded budgets are present with their limits",
                 all(c in lines and lines[c]["monthly_limit"] == limit for c, limit in SEEDED_LIMITS.items()), str(sorted(lines)))
    extra = sorted(set(lines) - set(SEEDED_LIMITS))
    if extra:
        checks.note(f"budgets beyond the seed are present ({extra}): totals are checked arithmetically, not against the seed figures")
    for category, line in lines.items():
        expected = expected_line(float(line["monthly_limit"]), float(line["spent"]))
        got = {k: line[k] for k in expected}
        checks.check(f"{category}: remaining, percent and status follow the limit and the spend", got == expected,
                     f"limit {line['monthly_limit']} spent {line['spent']} -> got {got}, expected {expected}")
    totals = s["totals"]
    total_limit = round(sum(float(l["monthly_limit"]) for l in lines.values()), 2)
    total_spent = round(sum(float(l["spent"]) for l in lines.values()), 2)
    over = [line["category"] for line in s["budgets"] if line["over_budget"]]
    checks.check("totals add up across the lines",
                 totals["budget_count"] == len(lines) and totals["total_limit"] == total_limit
                 and totals["total_spent"] == total_spent
                 and totals["total_remaining"] == round(total_limit - total_spent, 2)
                 and totals["percent_used"] == (round(total_spent / total_limit * 100, 1) if total_limit > 0 else 0.0)
                 and totals["over_budget_count"] == len(over) and s.get("over_budget_categories") == over,
                 str(totals))
    if s.get("spending_source") == "mock":
        checks.check("mock spending source: the seeded categories carry the exact figures and statuses",
                     all((lines[c]["spent"], lines[c]["status"]) == MOCK_EXPECTED[c] for c in MOCK_EXPECTED),
                     str([(c, lines[c]["spent"], lines[c]["status"]) for c in MOCK_EXPECTED]))
        if not extra:
            checks.check("mock spending source: the exact seeded totals and over-budget categories",
                         totals == MOCK_TOTALS and sorted(s.get("over_budget_categories", [])) == MOCK_OVER, str(totals))
    else:
        checks.note(f"spending source is {s.get('spending_source')}: exact mock figures not asserted", str(totals))
    for query, word in (({"customer_id": 1, "month": 13, "year": 2026}, "month"),
                        ({"customer_id": "abc"}, "customer_id"),
                        ({"customer_id": 1, "year": 1999}, "year")):
        r = get("/api/budgets/summary", **query)
        checks.check(f"400 for {query}", r.status_code == 400 and word in str(body(r).get("error", "")), describe(r))


# ---------------------------------------------------------------- 2. POST /api/budgets

@pytest.mark.endpoint("POST", "/api/budgets")
def test_create_budget_then_duplicate_and_invalid_bodies(checks):
    count_before = body(get("/api/budgets/summary", **PERIOD)).get("totals", {}).get("budget_count")
    checks.check("the period's budget count is known before the create", isinstance(count_before, int), str(count_before))
    category = f"CI check {uuid.uuid4().hex[:8]}"
    payload = {**PERIOD, "category": category, "monthly_limit": 123.45}
    budget_id = None
    cleaned = None
    try:
        r = post("/api/budgets", payload)
        checks.check("creating a new budget answers 201 with its id",
                     r.status_code == 201 and isinstance(body(r).get("budget_id"), int), describe(r))
        budget_id = body(r)["budget_id"]

        s = body(get("/api/budgets/summary", **PERIOD))
        line = next((l for l in s.get("budgets", []) if isinstance(l, dict) and l.get("budget_id") == budget_id), None)
        checks.check("the new budget appears in the period summary with no spend, on track",
                     line is not None and line.get("category") == category and line.get("monthly_limit") == 123.45
                     and line.get("spent") == 0.0 and line.get("remaining") == 123.45 and line.get("status") == "ON_TRACK"
                     and s.get("totals", {}).get("budget_count") == count_before + 1, str(line))

        r = post("/api/budgets", payload)
        checks.check("the same customer, category and period again answers 409",
                     r.status_code == 409 and "already exists" in str(body(r).get("error", "")), describe(r))

        for bad, word in (({**payload, "monthly_limit": 0}, "greater than zero"),
                          ({**payload, "monthly_limit": "lots"}, "Invalid input"),
                          ({k: v for k, v in payload.items() if k != "category"}, "category required"),
                          ({**payload, "month": 13}, "month must be between 1 and 12")):
            r = post("/api/budgets", bad)
            checks.check(f"400 for {word}", r.status_code == 400 and word in str(body(r).get("error", "")), describe(r))
        r = requests.post(f"{API}/api/budgets", data="[1, 2]", headers={"Content-Type": "application/json"}, timeout=TIMEOUT)
        checks.check("400 for a JSON body that is not an object", r.status_code == 400, describe(r))
    finally:
        # Runs whatever happened above, including a create whose answer was lost.
        cleaned = remove_test_budgets(budget_id, category)
        checks.record("cleanup: the test budget is deleted again", cleaned[0], cleaned[1])
    assert cleaned[0], f"cleanup failed, a '{category}' budget may remain: {cleaned[1]}"
    s = body(get("/api/budgets/summary", **PERIOD))
    checks.check("the period is back to its previous budget count", s.get("totals", {}).get("budget_count") == count_before,
                 f"{s.get('totals', {}).get('budget_count')} vs {count_before}")
