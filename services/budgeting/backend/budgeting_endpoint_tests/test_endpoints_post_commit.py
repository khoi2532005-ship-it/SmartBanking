"""Post-commit endpoint tests for two budgeting API functions (Release 2, student 4).

    GET  /api/budgets/summary   the seeded period, its totals and statuses, and its 400s
    POST /api/budgets           create, the created line in the summary, then 409 and 400

They run against a live budgeting API (BUDGET_API_URL, default http://localhost:5004)
with the seeded database, which is what student-4.yml starts on every pull request into
main and every push to main. With no API answering and BUDGET_API_URL unset or empty they
skip, so a local pytest run without the stack is not red; with BUDGET_API_URL set (CI) an
API that does not answer is a failure.

Nothing about the data is copied into this file. The expected summary is built from what
the API itself serves (the period's stored budgets from GET /api/budgets and its spending
from GET /api/transactions/spending) run through the backend's own budget logic, loaded
from services/budget_logic.py. The logic's rules (the statuses, the near-limit threshold)
are pinned with their own expected values by tests/test_budget_logic.py; this test checks
that the endpoint applies them to the right budgets and spend. No AI service is involved;
the health answer's MCP, RAG and Multi-Agent flags are recorded and must all be off in CI.

Every check is recorded on the test itself through pytest's record_property, so it lands
in the JUnit XML and in the report conftest.py writes (ENDPOINT_REPORT_DIR).

    BUDGET_API_URL=http://localhost:5004 ENDPOINT_REPORT_DIR=reports \
        python -m pytest services/budgeting/backend/budgeting_endpoint_tests -q
"""

from __future__ import annotations

import importlib.util
import json
import os
import uuid
from pathlib import Path

import pytest
import requests

DEFAULT_API = "http://localhost:5004"
API = (os.getenv("BUDGET_API_URL") or DEFAULT_API).rstrip("/")   # an empty value means the default
TIMEOUT = 10
PERIOD = {"customer_id": 1, "month": 9, "year": 2026}                 # the seeded demo period
BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_CATEGORY_PREFIX = "CI check "                                    # the create test's own budgets


def load_budget_logic():
    """The backend's budget logic (a pure module with no imports), loaded by path under
    a name of its own so it never collides with another feature's `services` package."""
    spec = importlib.util.spec_from_file_location("budgeting_budget_logic_under_test",
                                                  BACKEND_DIR / "services" / "budget_logic.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def ids(rows) -> list:
    return sorted(r.get("budget_id") for r in rows if isinstance(r, dict))


def snapshot():
    """The period's stored budgets, spending and summary, read until the stored budgets are
    the same before and after the summary: another run on the same stack may be adding or
    removing its own test budget in between. Returns the responses and whether they agree."""
    for _ in range(5):
        before = get("/api/budgets", **PERIOD)
        summary = get("/api/budgets/summary", **PERIOD)
        spending = get("/api/transactions/spending", **PERIOD)
        after = get("/api/budgets", **PERIOD)
        try:
            stored_before, stored_after = before.json(), after.json()
        except ValueError:
            return before, summary, spending, False
        lines = body(summary).get("budgets")
        if (isinstance(stored_before, list) and isinstance(lines, list)
                and ids(stored_before) == ids(stored_after) == ids(lines)):
            return before, summary, spending, True
    return before, summary, spending, False


def remove_test_budgets(created_ids: set, category: str) -> tuple[bool, str]:
    """Delete every budget the test created: the ids its creates answered with, and
    every budget carrying its unique category in any period, which also catches a
    create whose answer was lost or a bad body the API wrongly accepted. Fails when
    the lookup itself fails, rather than reporting that nothing was there."""
    try:
        r = get("/api/budgets", category=category)
        rows = r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError) as exc:
        return False, f"could not look up the test budgets: {type(exc).__name__}: {exc}"
    if not isinstance(rows, list):
        return False, f"could not look up the test budgets: {describe(r)}"
    ids = set(created_ids) | {b.get("budget_id") for b in rows if isinstance(b, dict) and b.get("category") == category}
    ids.discard(None)
    if not ids:
        return True, "no test budget was created"
    statuses = {}
    for i in sorted(ids):
        try:
            statuses[i] = requests.delete(f"{API}/api/budgets/{i}", timeout=TIMEOUT).status_code
        except requests.RequestException as exc:
            statuses[i] = type(exc).__name__
    return all(code in (200, 204, 404) for code in statuses.values()), f"deleted {statuses}"


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
    logic = load_budget_logic()
    before, r, spending, agreed = snapshot()
    checks.check("answers 200 for the seeded period", r.status_code == 200, describe(r))
    s = body(r)
    sp = body(spending)
    checks.observe(spending_source=str(s.get("spending_source")))
    try:
        stored = before.json()
    except ValueError:
        stored = None
    checks.check("the period's stored budgets and its spending can be read",
                 isinstance(stored, list) and spending.status_code == 200 and isinstance(sp.get("totals_by_category"), dict),
                 f"GET /api/budgets {describe(before)}; GET /api/transactions/spending {describe(spending)}")
    checks.check("the seeded period has stored budgets", len(stored) > 0, f"{len(stored)} stored")

    expected = logic.build_summary(stored, sp["totals_by_category"])
    line_keys = sorted(expected["budgets"][0])
    checks.check("the answer carries a budgets list and a totals object with every total",
                 isinstance(s.get("budgets"), list) and isinstance(s.get("totals"), dict)
                 and set(expected["totals"]) <= set(s["totals"]), f"keys {sorted(s)}")
    checks.check("echoes customer_id, month and year", (s.get("customer_id"), s.get("month"), s.get("year")) == (1, 9, 2026),
                 str({k: s.get(k) for k in ("customer_id", "month", "year")}))
    malformed = [l for l in s["budgets"] if not (isinstance(l, dict) and set(line_keys) <= set(l))]
    checks.check("every budget line carries its limit, spend, remaining, percent and status", not malformed, str(malformed[:1]))
    checks.check("the summary and the spending endpoint name the same spending source",
                 s.get("spending_source") == sp.get("spending_source"), f"{s.get('spending_source')} vs {sp.get('spending_source')}")

    lines = {l["budget_id"]: l for l in s["budgets"]}
    if agreed:
        checks.check("the summary lists exactly the period's stored budgets", ids(stored) == sorted(lines),
                     f"stored {ids(stored)}, listed {sorted(lines)}")
    else:
        checks.note("another run changed the period's budgets during the reads: lines are checked one by one, totals are not")
    for want in expected["budgets"]:
        got = lines.get(want["budget_id"])
        if got is None and not agreed:
            continue
        checks.check(f"{want['category']}: the line is the budget logic's answer for its stored limit and its spend",
                     got is not None and {k: got.get(k) for k in line_keys} == want,
                     f"got {None if got is None else {k: got.get(k) for k in line_keys}}, expected {want}")
    if agreed:
        checks.check("totals, over-budget categories and unbudgeted spending are the budget logic's answer",
                     {k: s["totals"].get(k) for k in expected["totals"]} == expected["totals"]
                     and s.get("over_budget_categories") == expected["over_budget_categories"]
                     and s.get("unbudgeted_spending") == expected["unbudgeted_spending"],
                     f"totals {s['totals']}, expected {expected['totals']}")
    for query, word in (({"customer_id": 1, "month": 13, "year": 2026}, "month"),
                        ({"customer_id": "abc"}, "customer_id"),
                        ({"customer_id": 1, "year": 1999}, "year")):
        r = get("/api/budgets/summary", **query)
        checks.check(f"400 for {query}", r.status_code == 400 and word in str(body(r).get("error", "")), describe(r))


# ---------------------------------------------------------------- 2. POST /api/budgets

@pytest.mark.endpoint("POST", "/api/budgets")
def test_create_budget_then_duplicate_and_invalid_bodies(checks):
    category = f"{TEST_CATEGORY_PREFIX}{uuid.uuid4().hex[:8]}"
    payload = {**PERIOD, "category": category, "monthly_limit": 123.45}
    created: set = set()              # every id a create answered with, even one that should have been refused
    budget_id = None
    cleaned = None

    def create(body_to_send):
        r = post("/api/budgets", body_to_send)
        data = body(r)
        if r.status_code == 201 and isinstance(data.get("budget_id"), int):
            created.add(data["budget_id"])
        return r, data

    try:
        r, data = create(payload)
        checks.check("creating a new budget answers 201 with its id",
                     r.status_code == 201 and isinstance(data.get("budget_id"), int), describe(r))
        budget_id = data["budget_id"]

        s = body(get("/api/budgets/summary", **PERIOD))
        line = next((l for l in s.get("budgets", []) if isinstance(l, dict) and l.get("budget_id") == budget_id), None)
        checks.check("the new budget appears in the period summary with no spend, on track",
                     line is not None and line.get("category") == category and line.get("monthly_limit") == 123.45
                     and line.get("spent") == 0.0 and line.get("remaining") == 123.45 and line.get("status") == "ON_TRACK",
                     str(line))

        r, data = create(payload)
        checks.check("the same customer, category and period again answers 409",
                     r.status_code == 409 and "already exists" in str(data.get("error", "")), describe(r))

        for bad, word in (({**payload, "monthly_limit": 0}, "greater than zero"),
                          ({**payload, "monthly_limit": "lots"}, "Invalid input"),
                          ({k: v for k, v in payload.items() if k != "category"}, "category required"),
                          ({**payload, "month": 13}, "month must be between 1 and 12")):
            r, data = create(bad)
            checks.check(f"400 for {word}", r.status_code == 400 and word in str(data.get("error", "")), describe(r))
        r = requests.post(f"{API}/api/budgets", data="[1, 2]", headers={"Content-Type": "application/json"}, timeout=TIMEOUT)
        checks.check("400 for a JSON body that is not an object", r.status_code == 400, describe(r))
    finally:
        # Runs whatever happened above, including a create whose answer was lost.
        cleaned = remove_test_budgets(created, category)
        checks.record("cleanup: every budget the test created is deleted", cleaned[0], cleaned[1])
    assert cleaned[0], f"cleanup failed, a '{category}' budget may remain: {cleaned[1]}"
    if budget_id is not None:
        gone = requests.get(f"{API}/api/budgets/{budget_id}", timeout=TIMEOUT)
        s = body(get("/api/budgets/summary", **PERIOD))
        still_listed = any(isinstance(l, dict) and l.get("budget_id") == budget_id for l in s.get("budgets", []))
        checks.check("the created budget is gone again: 404 by id and no longer in the summary",
                     gone.status_code == 404 and not still_listed, f"GET by id {gone.status_code}, listed {still_listed}")
