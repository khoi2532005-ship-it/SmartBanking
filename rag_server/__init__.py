"""SmartBank shared RAG server (Release 1).

One non-containerised Retrieval-Augmented Generation service, run locally on
the host and used by every student feature. Lecture 8's controlled evidence
pipeline:

    approved corpus -> chunking -> deterministic embeddings -> vector index
    -> top-k retrieval ranked by source authority -> grounded answer with
    citations and an evidence-derived confidence category

The generator reuses the team's provider-agnostic LLM client in
`agentic/llm.py`; nothing here talks to a model directly.

Run it from the repo root:  python -m rag_server.server
Validate it:                python -m rag_server.validate
"""

__all__ = ["config", "embedding", "generator", "grounding", "index", "ingest", "retriever", "server"]
