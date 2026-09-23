"""The shared SmartBank RAG server.  Run from the repo root:

    python -m rag_server.server

Flask on localhost:8200. Every feature's backend sends questions here and
displays the grounded answer, its citations and confidence category, or the
insufficient-context response. Not containerised; not a Compose service.

    GET  /health     index size, retrieval mode, model
    GET  /sources    the approved documents in the corpus
    POST /refresh    rebuild corpus + index (controlled refresh)
    POST /retrieve   {"query", "k"?}  -> ranked evidence, no LLM call
    POST /query      {"query", "k"?}  -> grounded answer contract
"""

from __future__ import annotations

import threading

from flask import Flask, jsonify, request

from rag_server import config, generator, grounding
from rag_server.retriever import Retriever

app = Flask(__name__)

_retriever: Retriever | None = None
_lock = threading.Lock()


def get_retriever() -> Retriever:
    global _retriever
    with _lock:
        if _retriever is None:
            _retriever = Retriever()
        return _retriever


@app.errorhandler(Exception)
def handle_exception(exc):
    app.logger.exception(exc)
    return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


def _query_arg() -> tuple[str, int] | tuple[None, tuple]:
    data = request.get_json(silent=True) or {}
    query = str(data.get("query") or "").strip()
    if not query:
        return None, (jsonify({"error": "query is required"}), 400)
    if len(query) > 1000:
        return None, (jsonify({"error": "query must be 1000 characters or fewer"}), 400)
    try:
        k = int(data.get("k") or config.TOP_K)
    except (TypeError, ValueError):
        return None, (jsonify({"error": "k must be an integer"}), 400)
    return query, k


# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    r = get_retriever()
    return jsonify({
        "service": "rag-server",
        "status": "running",
        "index": {
            "chunks": len(r.chunks),
            "sources": len(r.sources()),
            "retrieval_mode": r.mode,
            "vector_error": r.vector_error or None,
            "embedding_dim": config.EMBEDDING_DIM,
            "k": config.TOP_K,
            "relevance_threshold": config.RELEVANCE_THRESHOLD,
        },
        "model": generator.model_description(),
    })


@app.get("/sources")
def sources():
    return jsonify(get_retriever().sources())


@app.post("/refresh")
def refresh():
    retriever = get_retriever()          # takes and releases _lock itself
    with _lock:                          # then hold it for the rebuild only
        stats = retriever.refresh()
    return jsonify({"message": "corpus and index rebuilt", **stats})


@app.post("/retrieve")
def retrieve():
    query, k = _query_arg()
    if query is None:
        return k
    retrieval = get_retriever().retrieve(query, k)
    relevant = grounding.relevant(retrieval.evidence)
    return jsonify({
        "query": query,
        "retrieval_mode": retrieval.mode,
        "note": retrieval.note,
        "k": retrieval.k,
        "retrieved_count": len(retrieval.evidence),
        "relevant_count": len(relevant),
        "evidence": [e.to_dict() for e in retrieval.evidence],
    })


@app.post("/query")
def query():
    query_text, k = _query_arg()
    if query_text is None:
        return k

    retrieval = get_retriever().retrieve(query_text, k)
    relevant = grounding.relevant(retrieval.evidence)

    # Failure boundary: nothing relevant -> say so, spend no tokens.
    if not relevant:
        return jsonify(grounding.insufficient_response(
            retrieval, relevant,
            reason="no retrieved chunk passed the relevance threshold",
        ))

    allowed = {e.chunk_id: e for e in relevant}
    try:
        text, model = generator.answer(query_text, relevant)
        if generator.INSUFFICIENT_TOKEN in text.upper():
            # The model may refuse even when the evidence plainly covers the
            # topic (observed on list-style questions). If the best chunk is
            # strongly relevant, ask once more with that fact stated; if it
            # still declines, believe it. One bounded retry, like the loop.
            if relevant[0].relevance >= grounding.STRONG_RELEVANCE:
                text, model = generator.answer(
                    query_text, relevant,
                    feedback=("it replied INSUFFICIENT_CONTEXT although the context chunks "
                              "directly discuss the subject of the question - answer from "
                              "them, citing chunk ids, or reply INSUFFICIENT_CONTEXT only if "
                              "the specific fact asked for is genuinely absent"),
                )
            if generator.INSUFFICIENT_TOKEN in text.upper():
                return jsonify(grounding.insufficient_response(
                    retrieval, relevant, model=model, llm_called=True,
                    reason="the model reported the retrieved context does not answer the question",
                ))

        cleaned, cited = grounding.extract_citations(text, allowed)
        note = ""
        if not cited:
            # One bounded correction, the same Adapt step the loop uses.
            text, model = generator.answer(
                query_text, relevant,
                feedback="it cited no chunk ids - put the supporting chunk id in square "
                         "brackets after every factual sentence",
            )
            if generator.INSUFFICIENT_TOKEN in text.upper():
                return jsonify(grounding.insufficient_response(
                    retrieval, relevant, model=model, llm_called=True,
                    reason="the model reported the retrieved context does not answer the question",
                ))
            cleaned, cited = grounding.extract_citations(text, allowed)
            if not cited:
                cited = relevant[:3]
                note = ("model did not cite chunk ids; citations list the retrieved "
                        "context the answer was generated from")
    except generator.GenerationUnavailable as exc:
        return jsonify({
            "error": f"AI provider unavailable: {exc}",
            "query": query_text,
            "retrieval_summary": {
                "k": retrieval.k, "retrieved_count": len(retrieval.evidence),
                "relevant_count": len(relevant), "retrieval_mode": retrieval.mode,
                "top_chunk": retrieval.evidence[0].chunk_id if retrieval.evidence else None,
            },
            "evidence": [e.to_dict() for e in retrieval.evidence],
        }), 503

    return jsonify(grounding.grounded_response(retrieval, relevant, cleaned, cited, model, note))


# ---------------------------------------------------------------------------

def _banner(r: Retriever) -> None:
    rule = "=" * 72
    print(rule)
    print("  SmartBank - shared RAG server (not containerised)")
    print(f"  listening:  http://{config.RAG_HOST}:{config.RAG_PORT}")
    print(f"  local url:  {config.local_url()}")
    print(f"  containers: http://host.docker.internal:{config.RAG_PORT}")
    print(f"  corpus:     {len(r.chunks)} chunks from {len(r.sources())} sources "
          f"({config.CHUNK_WORDS}-word max, {config.EMBEDDING_DIM}-d embeddings, k={config.TOP_K})")
    print(f"  retrieval:  {r.mode}" + (f"  ({r.vector_error})" if r.vector_error else ""))
    print(f"  generator:  {generator.model_description()}")
    print("  validate:   python -m rag_server.validate")
    print(rule, flush=True)


if __name__ == "__main__":
    retriever = get_retriever()
    if retriever.index_stale():
        # No vector index yet, or its chunk count differs from the corpus:
        # rebuild before serving. Otherwise the persistent collection is reused.
        stats = retriever.refresh()
        print(f"  index built: {stats}")
    _banner(retriever)
    app.run(host=config.RAG_HOST, port=config.RAG_PORT, debug=False, threaded=True)
