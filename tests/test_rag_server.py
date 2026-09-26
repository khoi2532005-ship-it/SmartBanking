"""Unit tests for the shared RAG server's pure functions.

No running server, no ChromaDB, no LLM call: the retriever is built from
in-memory chunks with the vector index disabled, which is exactly the
lexical-fallback path that has to work on its own.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag_server import config  # noqa: E402
from rag_server.embedding import DIM, embed, tokenize  # noqa: E402
from rag_server.grounding import confidence, extract_citations  # noqa: E402
from rag_server.ingest import Chunk, _pack, chunk_document  # noqa: E402
from rag_server.retriever import EvidenceRecord, Retriever  # noqa: E402


def _chunk(chunk_id: str, tier: int, text: str, heading: str = "") -> Chunk:
    source_id = chunk_id.split("#")[0]
    return Chunk(
        chunk_id=chunk_id, source_id=source_id, title=source_id.replace("-", " "),
        authority_tier=tier, heading=heading, text=text,
        word_count=len(text.split()), origin="test", indexed_at="2026-09-23T00:00:00Z",
    )


def _record(chunk_id: str, tier: int, relevance: float) -> EvidenceRecord:
    return EvidenceRecord(
        rank=0, chunk_id=chunk_id, source_id=chunk_id.split("#")[0], title="t",
        authority_tier=tier, heading="", distance=None, relevance=relevance, text="x",
    )


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def test_embed_is_deterministic_and_unit_length():
    a = embed("The NEAR_LIMIT status means 80 to 100 percent of the limit is used.")
    b = embed("The NEAR_LIMIT status means 80 to 100 percent of the limit is used.")
    assert a == b
    assert len(a) == DIM == config.EMBEDDING_DIM
    assert abs(sum(v * v for v in a) - 1.0) < 1e-9


def test_embed_of_empty_text_is_the_zero_vector():
    assert embed("the and of") == [0.0] * DIM          # stopwords only


def test_tokenize_keeps_identifiers_whole_and_drops_stopwords():
    tokens = tokenize("GET /api/budgets/summary is served by budgeting_summary in the API")
    assert "api/budgets/summary" in tokens
    assert "budgeting_summary" in tokens
    assert "the" not in tokens and "is" not in tokens


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def test_pack_never_exceeds_the_word_limit_even_for_one_long_sentence():
    one_long_sentence = " ".join(f"word{i}" for i in range(200)) + "."
    pieces = _pack("h", one_long_sentence, limit=80)
    assert pieces and all(len(p.split()) <= 80 for p in pieces)
    assert sum(len(p.split()) for p in pieces) == 200


def test_pack_groups_whole_sentences_up_to_the_limit():
    sentences = [f"Sentence number {i} has exactly six words." for i in range(1, 11)]  # 7 words each
    pieces = _pack("h", " ".join(sentences), limit=20)
    assert all(len(p.split()) <= 20 for p in pieces)
    assert all(p.endswith(".") for p in pieces)        # never cut mid-sentence
    assert " ".join(pieces) == " ".join(sentences)


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------

def test_extract_citations_keeps_retrieved_ids_and_drops_hallucinated_ones():
    allowed = {"budgeting-feature#003": _record("budgeting-feature#003", 1, 0.7)}
    answer = ("NEAR_LIMIT means 80 to 100 percent used [budgeting-feature#003]. "
              "It was invented in 1998 [made-up-source#999]. "
              "Exactly on the limit is also NEAR_LIMIT [budgeting-feature#003].")
    cleaned, cited = extract_citations(answer, allowed)
    assert [c.chunk_id for c in cited] == ["budgeting-feature#003"]   # de-duplicated, in order
    assert "made-up-source#999" not in cleaned
    assert cleaned.count("[budgeting-feature#003]") == 2


def test_confidence_is_derived_from_evidence_not_the_model():
    assert confidence([]) == "Unknown"
    high = [_record("a#001", 1, 0.7), _record("a#002", 1, 0.5), _record("b#001", 2, 0.4)]
    assert confidence(high) == "High"
    assert confidence([_record("a#001", 2, 0.5), _record("a#002", 2, 0.4)]) == "Medium"
    assert confidence([_record("a#001", 1, 0.65)]) == "Medium"
    assert confidence([_record("a#001", 3, 0.4)]) == "Low"
    assert confidence([_record("a#001", 1, 0.4)]) == "Low"


# ---------------------------------------------------------------------------
# Retrieval - lexical fallback must stand on its own (review finding)
# ---------------------------------------------------------------------------

@pytest.fixture
def corpus() -> list[Chunk]:
    # Five tier-1 chunks that merely mention the topic word ...
    noise = [
        _chunk(f"mcp-server#00{i}", 1,
               f"Tool number {i} is read-only. The MCP server can also be called from the agentic loop.")
        for i in range(1, 6)
    ]
    # ... and three tier-2 chunks that actually answer the question.
    answers = [
        _chunk("agentic-loop#001", 2, "The shared agentic loop has four stages: Plan, Act, Observe and Adapt."),
        _chunk("agentic-loop#002", 2, "PLAN states the goal, ACT collects evidence, OBSERVE validates, ADAPT retries the shared agentic loop."),
        _chunk("agentic-loop#003", 2, "Each stage of the shared agentic loop is logged so a marker can watch the stages happen."),
    ]
    return noise + answers


def test_lexical_fallback_surfaces_relevant_lower_tier_chunks(corpus):
    retriever = Retriever(chunks=corpus, use_vector=False)
    result = retriever.retrieve("What are the stages of the shared agentic loop?", k=5)

    assert result.mode == "lexical_fallback"
    served = [e.chunk_id for e in result.evidence]
    assert {"agentic-loop#001", "agentic-loop#002", "agentic-loop#003"} <= set(served), served
    # And they are ranked above the tier-1 chunks that merely mention the topic.
    assert served[0].startswith("agentic-loop")


def test_retriever_reports_index_stale_when_vector_is_disabled(corpus):
    assert Retriever(chunks=corpus, use_vector=False).index_stale() is True


def test_off_topic_query_retrieves_nothing_relevant(corpus):
    retriever = Retriever(chunks=corpus, use_vector=False)
    result = retriever.retrieve("What is the capital of France?", k=5)
    assert all(e.relevance < config.RELEVANCE_THRESHOLD for e in result.evidence)


def test_loan_eligibility_query_retrieves_the_approved_checks():
    chunks = chunk_document(config.CORPUS_DIR / "loans-feature.md")
    retriever = Retriever(chunks=chunks, use_vector=False)

    result = retriever.retrieve("what are the loan eligibility checks?", k=5)
    evidence = "\n".join(record.text for record in result.evidence)

    assert any(record.source_id == "loans-feature" for record in result.evidence)
    assert all(check in evidence for check in (
        "loan_type_supported",
        "amount_within_limits",
        "purpose_provided",
        "affordability",
    ))
    assert "40%" in evidence
    assert "monthly income" in evidence
