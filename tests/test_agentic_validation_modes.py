"""Tests for the Release 1 validation modes: mcp_validation and rag_validation.

The contract checks are stubbed with realistic records and the LLM is
scripted, so no server, no API key and no network are needed. The cases that
matter are the ADAPT ones: an entry that drops a tool name, invents a chunk id
or misreports the pass count is rejected with a reason the model can act on,
and the corrected retry passes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("mcp")  # mcp_server.validate drives the server through the SDK

from agentic import llm, loop, modes, prompts  # noqa: E402
from agentic.modes.mcp_validation import MCPValidationMode  # noqa: E402
from agentic.modes.rag_validation import RAGValidationMode  # noqa: E402
from mcp_server import validate as mcp_validate  # noqa: E402
from rag_server import validate as rag_validate  # noqa: E402

VALID_ARGS = {"customer_id": 1, "month": 9, "year": 2026}
TOOLS = ["budgeting_summary", "accounts_count", "loans_list", "fraud_alerts_count", "transactions_spending"]


def mcp_records() -> list:
    R = mcp_validate.Record
    specs = {
        "budgeting_summary": {"required": ["customer_id", "month", "year"], "properties": ["customer_id", "month", "year"]},
        "accounts_count": {"required": [], "properties": []},
        "loans_list": {"required": ["customer_id"], "properties": ["customer_id", "status"]},
        "fraud_alerts_count": {"required": [], "properties": ["customer_id", "status"]},
        "transactions_spending": {"required": ["customer_id", "month", "year"], "properties": ["customer_id", "month", "year"]},
    }
    return [
        R(1, "server reachable", "-", {}, "initialize succeeds", "initialize ok", True),
        R(2, "tools/list publishes every tool", "-", {}, "5 tools, each with an inputSchema",
          "5 tools: " + ", ".join(TOOLS), True, False, specs),
        R(3, "valid invocation", "budgeting_summary", dict(VALID_ARGS),
          "isError false; structured result with totals and budgets",
          "isError false; budget_count=7, total_spent=2169.97, spending_source=transactions-api", True, False,
          {"structured_keys": ["budget_count", "budgets", "totals"], "budget_count": 7, "total_spent": 2169.97,
           "total_limit": 2160.0, "spending_source": "transactions-api", "over_budget_categories": ["Dining Out"]}),
        R(4, "domain-invalid input rejected", "budgeting_summary", {**VALID_ARGS, "month": 13},
          "isError true mentioning month", "isError True: month must be between 1 and 12, got 13", True),
        R(5, "type-invalid input rejected", "budgeting_summary", {**VALID_ARGS, "customer_id": "abc"},
          "isError true from schema validation", "isError True: customer_id Input should be a valid integer", True),
        R(6, "undeclared argument rejected", "budgeting_summary", {**VALID_ARGS, "sql": "SELECT 1"},
          "isError true: extra inputs not permitted", "isError True: sql Extra inputs are not permitted", True),
        R(7, "unknown tool rejected", "no_such_tool", {}, "rejected, never served",
          "isError True: Unknown tool: no_such_tool", True),
        R(8, "dependency unavailable -> explicit error", "loans_list", {"customer_id": 1},
          "isError true saying the service is unavailable",
          "isError True: loans service unavailable: connection refused", True),
    ]


def rag_records() -> list:
    R = rag_validate.Record
    per_query = [
        {"query": "What does the NEAR_LIMIT budget status mean?", "precision_at_5": 0.4, "recall_at_5": 1.0,
         "relevant_in_top5": 2, "total_relevant": 2, "top_chunk": "budgeting-feature#003",
         "top_relevance": 0.61, "mode": "hybrid"},
        {"query": "What tools does the shared MCP server expose?", "precision_at_5": 0.2, "recall_at_5": 0.67,
         "relevant_in_top5": 1, "total_relevant": 3, "top_chunk": "mcp-server#002",
         "top_relevance": 0.67, "mode": "hybrid"},
    ]
    off_topic = [
        {"query": q, "status": 200, "insufficient_context": True, "citations": 0,
         "confidence_category": "Unknown", "llm_called": False, "relevant_count": 0}
        for q in ("What is the capital of France?", "Who won the 2022 FIFA World Cup?")
    ]
    return [
        R(1, "server reachable, index populated", "/health 200 with chunks > 0",
          "65 chunks, 9 sources, mode=hybrid, model=gemini / test", True,
          {"chunks": 65, "sources": 9, "retrieval_mode": "hybrid", "vector_error": None, "k": 5,
           "relevance_threshold": 0.35}),
        R(2, "retrieval quality (Precision@5, Recall@5)", "every query hits; mean R@5 >= 0.6",
          "mean P@5=0.30, mean R@5=0.83; every query hit", True,
          {"mean_precision_at_5": 0.3, "mean_recall_at_5": 0.833, "per_query": per_query}),
        R(3, "grounded answer with citations and confidence", "200; >= 1 citation; confidence set",
          "confidence=High, citations=['budgeting-feature#003']", True,
          {"answer": "A budget is NEAR_LIMIT at 80% of its limit [budgeting-feature#003].",
           "citations": [{"chunk_id": "budgeting-feature#003", "source_id": "budgeting-feature",
                          "title": "Budgeting", "authority_tier": 1}],
           "confidence_category": "High",
           "retrieval_summary": {"k": 5, "retrieved_count": 5, "relevant_count": 2,
                                 "retrieval_mode": "hybrid", "top_chunk": "budgeting-feature#003"},
           "generation": {"model": "gemini / test", "llm_called": True}}),
        R(4, "claims supported by cited chunks", "each citation retrieved; fact present",
          "1 citations, 0 not in retrieved set, expected fact 'NEAR_LIMIT' in cited chunk: True", True,
          {"cited": ["budgeting-feature#003"], "unknown": [], "keyword": "NEAR_LIMIT"}),
        R(5, "off-topic query -> insufficient context", "insufficient; no citations; llm_called false",
          "2 off-topic questions refused", True, {"results": off_topic}),
        R(6, "controlled refresh", "/refresh 200; chunk count equals /health afterwards",
          "HTTP 200: chunks=65, vector_indexed=65, mode=hybrid; health chunks=65", True,
          {"chunks": 65, "sources": 9, "vector_indexed": 65, "mode": "hybrid", "message": "corpus and index rebuilt"}),
    ]


GOOD_MCP = (
    "Tools: 5 registered - budgeting_summary, accounts_count, loans_list, fraud_alerts_count, transactions_spending\n"
    'Demo call: budgeting_summary with {"customer_id": 1, "month": 9, "year": 2026}\n'
    "Result: total spent $2,169.97 across 7 budgets; spending source transactions-api\n"
    'Rejected: month 13 was rejected as out of range, customer_id "abc" was rejected as a non-integer, '
    "the undeclared sql argument was rejected as an extra input, and the unknown tool no_such_tool "
    "was rejected with an explicit error.\n"
    "Verdict: 8/8 checks passed - PASS"
)

GOOD_RAG = (
    "Index: 65 chunks from 9 documents, retrieval mode hybrid\n"
    "Retrieval: mean P@5 0.30, mean R@5 0.83, 2 of 2 benchmark questions found a relevant chunk in the top 5\n"
    "Grounded answer: confidence High, citations budgeting-feature#003\n"
    "Off-topic: 2 questions returned insufficient context with no citations and no model call\n"
    "Verdict: 6/6 checks passed - PASS"
)


@pytest.fixture
def answers(monkeypatch):
    """Scripted llm.ask; the review call is answered separately."""
    scripted: list[str] = []

    def fake_ask(system_prompt, user_prompt, **kwargs):
        if kwargs.get("review"):
            return "Risk: none.\nCorrection: none.\nRetest: repeat."
        assert scripted, "llm.ask called more times than the script allows"
        return scripted.pop(0)

    monkeypatch.setattr(llm, "ask", fake_ask)
    monkeypatch.setattr(llm, "describe", lambda **kw: "stub/stub")
    return scripted


@pytest.fixture
def mcp_checks(monkeypatch):
    records = mcp_records()
    monkeypatch.setattr(mcp_validate, "run_checks", lambda url: records)
    return records


@pytest.fixture
def rag_checks(monkeypatch):
    records = rag_records()
    monkeypatch.setattr(rag_validate, "run_checks", lambda url: records)
    return records


# ---------------------------------------------------------------- registry

def test_both_modes_are_on_the_menu():
    for key in ("mcp_validation", "rag_validation"):
        assert key in modes.MODES, key
        assert modes.MODES[key].label and modes.MODES[key].owner == "Bao"


def test_prompt_files_exist_and_are_not_inline():
    assert len(prompts.load_all("_mcp", "validation_system.txt", "validation_task.txt")) == 2
    assert len(prompts.load_all("_rag", "validation_system.txt", "validation_task.txt")) == 2


# ---------------------------------------------------------------- MCP mode

def test_mcp_faithful_entry_passes_first_time(answers, mcp_checks):
    answers.append(GOOD_MCP)
    result = loop.run(MCPValidationMode())
    assert result.ok and not result.adapted
    assert result.evidence.facts["tool_count"] == 5
    assert result.evidence.facts["passed_count"] == 8
    assert not result.evidence.degraded


def test_mcp_entry_that_drops_a_tool_is_rejected_then_corrected(answers, mcp_checks):
    answers.extend([GOOD_MCP.replace("loans_list, ", ""), GOOD_MCP])
    result = loop.run(MCPValidationMode())
    assert result.ok and result.adapted
    assert "loans_list" in result.attempts[0].verdict.feedback
    assert "loans_list" in result.attempts[1].adapt_note      # the complaint reached the retry


def test_mcp_wrong_pass_count_is_rejected(answers, mcp_checks):
    answers.extend([GOOD_MCP.replace("8/8 checks passed - PASS", "7/8 checks passed - FAIL"), GOOD_MCP])
    result = loop.run(MCPValidationMode())
    assert result.ok and result.adapted
    assert "8/8" in result.attempts[0].verdict.feedback


def test_mcp_wrong_demo_arguments_are_rejected(answers, mcp_checks):
    answers.extend([GOOD_MCP.replace('"month": 9', '"month": 10'), GOOD_MCP])
    result = loop.run(MCPValidationMode())
    assert result.ok and result.adapted
    assert "month=9" in result.attempts[0].verdict.feedback


def test_mcp_unreachable_server_never_calls_the_model(answers, mcp_checks):
    mcp_checks[0].passed = False
    mcp_checks[0].observed = "connection refused"
    result = loop.run(MCPValidationMode())
    assert not result.ok and result.attempts == []
    assert "python -m mcp_server.server" in result.evidence.summary


def test_mcp_failed_contract_check_stops_before_the_model(answers, mcp_checks):
    mcp_checks[3].passed = False
    mcp_checks[3].observed = "isError False: month 13 was served"
    result = loop.run(MCPValidationMode())
    assert not result.ok and result.attempts == []
    assert "domain-invalid" in result.evidence.summary


def test_mcp_mock_spending_marks_the_run_degraded(answers, mcp_checks):
    mcp_checks[2].detail["spending_source"] = "mock"
    answers.append(GOOD_MCP.replace("transactions-api", "mock"))
    result = loop.run(MCPValidationMode())
    assert result.ok and result.evidence.degraded
    assert "mock" in result.evidence.note


# ---------------------------------------------------------------- RAG mode

def test_rag_faithful_entry_passes_first_time(answers, rag_checks):
    answers.append(GOOD_RAG)
    result = loop.run(RAGValidationMode())
    assert result.ok and not result.adapted
    assert result.evidence.facts["metrics"]["mean_recall_at_5"] == "0.83"
    assert not result.evidence.degraded


def test_rag_invented_chunk_id_is_rejected_then_corrected(answers, rag_checks):
    answers.extend([GOOD_RAG.replace("citations budgeting-feature#003",
                                     "citations budgeting-feature#003, loans-feature#009"), GOOD_RAG])
    result = loop.run(RAGValidationMode())
    assert result.ok and result.adapted
    assert "loans-feature#009" in result.attempts[0].verdict.feedback


def test_rag_misquoted_metric_is_rejected(answers, rag_checks):
    answers.extend([GOOD_RAG.replace("mean P@5 0.30", "mean P@5 0.50"), GOOD_RAG])
    result = loop.run(RAGValidationMode())
    assert result.ok and result.adapted
    assert "P@5 as 0.30" in result.attempts[0].verdict.feedback


def test_rag_wrong_confidence_is_rejected(answers, rag_checks):
    answers.extend([GOOD_RAG.replace("confidence High", "confidence Medium"), GOOD_RAG])
    result = loop.run(RAGValidationMode())
    assert result.ok and result.adapted
    assert "High" in result.attempts[0].verdict.feedback


def test_rag_unreachable_server_never_calls_the_model(answers, rag_checks):
    rag_checks[0].passed = False
    rag_checks[0].observed = "unreachable: connection refused. Start it with: python -m rag_server.server"
    result = loop.run(RAGValidationMode())
    assert not result.ok and result.attempts == []
    assert "python -m rag_server.server" in result.evidence.summary


def test_rag_lexical_fallback_is_degraded_not_hidden(answers, rag_checks):
    rag_checks[0].detail["retrieval_mode"] = "lexical_fallback"
    answers.append(GOOD_RAG.replace("hybrid", "lexical_fallback"))
    result = loop.run(RAGValidationMode())
    assert result.ok and result.evidence.degraded
    assert "lexical_fallback" in result.evidence.note
