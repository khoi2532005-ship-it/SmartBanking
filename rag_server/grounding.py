"""Grounded answer contract (Lecture 8): evidence boundaries, citations,
evidence-derived confidence, and the insufficient-context response.

Confidence is computed from what was retrieved - how many chunks passed the
relevance threshold, how relevant the best one is, and its authority tier.
It is never the model's opinion of itself.
"""

from __future__ import annotations

import re
from typing import Any

from rag_server import config
from rag_server.retriever import EvidenceRecord, Retrieval

# A top chunk at or above this relevance plainly discusses the question's
# subject; used to decide whether a model "insufficient" reply earns a retry.
STRONG_RELEVANCE = 0.6

INSUFFICIENT_MESSAGE = (
    "Insufficient context: the approved SmartBank documents do not contain "
    "enough information to answer this question."
)

_CITATION_RE = re.compile(r"\[([a-z0-9-]+#\d{3})\]")


# ---------------------------------------------------------------------------
# Evidence boundary
# ---------------------------------------------------------------------------

def relevant(evidence: list[EvidenceRecord],
             threshold: float = config.RELEVANCE_THRESHOLD) -> list[EvidenceRecord]:
    """Only chunks that actually share the question's vocabulary may ground an answer."""
    return [e for e in evidence if e.relevance >= threshold]


# ---------------------------------------------------------------------------
# Confidence category - from evidence quantity and authority, not the model
# ---------------------------------------------------------------------------

def confidence(relevant_chunks: list[EvidenceRecord]) -> str:
    if not relevant_chunks:
        return "Unknown"
    n = len(relevant_chunks)
    top = max(relevant_chunks, key=lambda e: e.relevance)
    best_tier = min(e.authority_tier for e in relevant_chunks)

    if n >= 3 and best_tier == 1 and top.relevance >= 0.6:
        return "High"
    if n >= 2 and top.relevance >= 0.45:
        return "Medium"
    if n >= 1 and best_tier <= 2 and top.relevance >= 0.6:
        return "Medium"
    return "Low"


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------

def extract_citations(answer: str, allowed: dict[str, EvidenceRecord]) -> tuple[str, list[EvidenceRecord]]:
    """Keep citation markers that point at retrieved chunks; drop any others.

    Returns the cleaned answer and the cited records in first-use order.
    """
    cited: list[EvidenceRecord] = []
    seen: set[str] = set()

    def keep(match: re.Match) -> str:
        chunk_id = match.group(1)
        record = allowed.get(chunk_id)
        if record is None:
            return ""                          # hallucinated id: remove it
        if chunk_id not in seen:
            seen.add(chunk_id)
            cited.append(record)
        return match.group(0)

    cleaned = _CITATION_RE.sub(keep, answer)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).replace(" .", ".").strip()
    return cleaned, cited


def _citation_dicts(records: list[EvidenceRecord]) -> list[dict[str, Any]]:
    return [{
        "chunk_id": r.chunk_id,
        "source_id": r.source_id,
        "title": r.title,
        "authority_tier": r.authority_tier,
        "heading": r.heading,
    } for r in records]


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------

def _summary(retrieval: Retrieval, relevant_chunks: list[EvidenceRecord]) -> dict[str, Any]:
    return {
        "k": retrieval.k,
        "retrieved_count": len(retrieval.evidence),
        "relevant_count": len(relevant_chunks),
        "top_chunk": retrieval.evidence[0].chunk_id if retrieval.evidence else None,
        "retrieval_mode": retrieval.mode,
        "relevance_threshold": config.RELEVANCE_THRESHOLD,
    }


def grounded_response(retrieval: Retrieval, relevant_chunks: list[EvidenceRecord],
                      answer: str, cited: list[EvidenceRecord], model: str,
                      note: str = "") -> dict[str, Any]:
    return {
        "query": retrieval.query,
        "answer": answer,
        "citations": _citation_dicts(cited),
        "confidence_category": confidence(relevant_chunks),
        "retrieval_summary": _summary(retrieval, relevant_chunks),
        "insufficient_context": False,
        "generation": {"model": model, "llm_called": True, "note": note},
        "evidence": [e.to_dict() for e in retrieval.evidence],
    }


def insufficient_response(retrieval: Retrieval, relevant_chunks: list[EvidenceRecord],
                          reason: str, model: str = "", llm_called: bool = False) -> dict[str, Any]:
    return {
        "query": retrieval.query,
        "answer": INSUFFICIENT_MESSAGE,
        "citations": [],
        "confidence_category": "Unknown",
        "retrieval_summary": _summary(retrieval, relevant_chunks),
        "insufficient_context": True,
        "generation": {"model": model, "llm_called": llm_called, "note": reason},
        "evidence": [e.to_dict() for e in retrieval.evidence],
    }
