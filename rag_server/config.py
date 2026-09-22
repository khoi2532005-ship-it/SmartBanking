"""Settings for the shared RAG server, read from the environment.

Same `.env` as everything else (LLM provider settings are read by
`agentic/llm.py`; nothing LLM-related is duplicated here).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

# ChromaDB phones home on first use unless told not to; on a machine without
# outbound access that call can block start-up with no output. Opt out here,
# before chromadb is ever imported.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

# ---- where this server listens -------------------------------------------
RAG_HOST = os.getenv("RAG_HOST", "0.0.0.0")
RAG_PORT = int(os.getenv("RAG_PORT", "8200"))

# ---- corpus and index locations -----------------------------------------
CORPUS_DIR = REPO_ROOT / "rag_server" / "corpus"        # versioned sources
DATA_DIR = REPO_ROOT / "rag_server" / "data"            # generated, gitignored
CORPUS_JSONL = DATA_DIR / "corpus.jsonl"
CHROMA_DIR = DATA_DIR / "chroma"
COLLECTION_NAME = "smartbank_docs"

# ---- pipeline parameters (Lecture 8 defaults) ---------------------------
EMBEDDING_DIM = 256          # deterministic hashed vectors
CHUNK_WORDS = 80             # max words per chunk
TOP_K = 5                    # retrieval depth

# A chunk counts as relevant evidence only if it shares enough distinctive
# vocabulary with the question (IDF-weighted overlap, 0..1). Below this the
# server answers "insufficient context" and spends no tokens.
RELEVANCE_THRESHOLD = float(os.getenv("RAG_RELEVANCE_THRESHOLD", "0.35"))

# Generation
MAX_ANSWER_TOKENS = int(os.getenv("RAG_MAX_ANSWER_TOKENS", "700"))
ANSWER_TEMPERATURE = 0.1


def local_url() -> str:
    host = "localhost" if RAG_HOST in ("0.0.0.0", "") else RAG_HOST
    return f"http://{host}:{RAG_PORT}"
