---
source_id: rag-server
title: Shared RAG server
authority_tier: 1
origin: rag_server/ (2026-09-22)
---

# What it is

The shared RAG server is one local Retrieval-Augmented Generation service used by all five SmartBank features. It is a Flask service on http://localhost:8200, reached by containerised backends at http://host.docker.internal:8200. It runs on the host with python -m rag_server.server and is not a docker-compose service. The pipeline is approved corpus, chunking, deterministic embeddings, a ChromaDB vector index, top-k retrieval ranked by source authority, then a grounded answer generated through the team's shared LLM client in agentic/llm.py.

# Knowledge sources

The corpus is the set of approved project documents in rag_server/corpus, versioned in the repository. Each document declares a source_id and an authority_tier. Tier 1 is feature and API documentation, tier 2 is team documentation such as the README and the agentic loop guide, tier 3 is supporting notes. Documents are split into chunks of at most 80 words, each with a chunk_id of the form source_id#number.

# Retrieval

The query is embedded with the same deterministic 256-dimensional hashed embedding used for the chunks and compared in ChromaDB using cosine distance. Retrieval is hybrid: the nearest vector chunks and the chunks with the highest IDF-weighted token overlap form one candidate set. Candidates that pass the relevance threshold are ranked first by authority tier and then by relevance, the remaining candidates follow, and the top five are returned (k=5) with retrieval_mode hybrid. If vector retrieval raises an error the server falls back to lexical retrieval alone, sets retrieval_mode to lexical_fallback and distance to null.

# Grounded answer contract

POST /query with a JSON body containing query returns answer, citations, confidence_category, retrieval_summary and insufficient_context. The answer uses only the retrieved context. Each citation lists chunk_id, source_id, title and authority_tier. confidence_category is High, Medium, Low or Unknown and is derived from the number of relevant chunks, their relevance scores and the authority tier of the top chunk, never from the model's self-assessment. retrieval_summary reports k, retrieved_count, top_chunk and retrieval_mode.

# Insufficient context

When no retrieved chunk passes the relevance threshold, or the model reports that the context does not answer the question, the server returns insufficient_context true, an empty citations list, confidence Unknown and the message "Insufficient context: the approved SmartBank documents do not contain enough information to answer this question." No unsupported answer is ever generated.

# Endpoints and validation

GET /health reports the index size and mode. GET /sources lists the corpus documents. POST /retrieve returns ranked evidence without calling the model. POST /refresh rebuilds the corpus and index and validates the chunk count before activation. POST /query returns the grounded answer. python -m rag_server.validate measures Precision@5 and Recall@5 over benchmark queries, validates grounding and citations, and confirms the insufficient-context path; --evidence saves docs/evidence/rag-validation-<timestamp>.json.
