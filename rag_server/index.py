"""Vector index setup (Lecture 8): a persistent ChromaDB collection.

Stores each chunk's id, text, deterministic vector and source metadata.
Rebuild deletes and recreates the collection, so a corpus or embedding change
is never half-applied. ChromaDB is imported lazily: if it is not installed or
fails to open, `VectorIndexUnavailable` is raised and the retriever falls back
to lexical retrieval, as the lecture's fallback flow requires.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rag_server import config
from rag_server.embedding import embed, embed_many
from rag_server.ingest import Chunk


class VectorIndexUnavailable(Exception):
    """ChromaDB missing or unusable. Message says what to do about it."""


class ChromaIndex:
    def __init__(self, persist_dir: Path = config.CHROMA_DIR,
                 collection: str = config.COLLECTION_NAME) -> None:
        try:
            import chromadb  # heavy import, only when the index is actually used
        except ImportError as exc:
            raise VectorIndexUnavailable(
                "chromadb is not installed - pip install -r requirements-rag.txt"
            ) from exc
        try:
            persist_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(persist_dir))
        except Exception as exc:
            raise VectorIndexUnavailable(f"could not open ChromaDB at {persist_dir}: {exc}") from exc
        self._name = collection
        self._collection = None

    # ---- lifecycle -------------------------------------------------------

    def _get(self):
        if self._collection is None:
            try:
                self._collection = self._client.get_collection(self._name)
            except Exception as exc:
                raise VectorIndexUnavailable(
                    f"collection '{self._name}' does not exist yet - POST /refresh to build it"
                ) from exc
        return self._collection

    def rebuild(self, chunks: list[Chunk]) -> int:
        """Delete and recreate the collection from the current corpus."""
        try:
            self._client.delete_collection(self._name)
        except Exception:
            pass                                  # first build: nothing to delete
        self._collection = self._client.create_collection(
            self._name, metadata={"hnsw:space": "cosine"}
        )
        if chunks:
            self._collection.add(
                ids=[c.chunk_id for c in chunks],
                documents=[c.text for c in chunks],
                embeddings=embed_many([c.embed_text for c in chunks]),
                metadatas=[{
                    "source_id": c.source_id,
                    "title": c.title,
                    "authority_tier": c.authority_tier,
                    "heading": c.heading,
                    "word_count": c.word_count,
                } for c in chunks],
            )
        return self.count()

    def count(self) -> int:
        return int(self._get().count())

    # ---- query -------------------------------------------------------------

    def query(self, text: str, k: int) -> list[dict[str, Any]]:
        """Nearest chunks by cosine distance. Smaller distance = closer."""
        collection = self._get()
        n = max(1, min(k, collection.count() or 1))
        try:
            result = collection.query(
                query_embeddings=[embed(text)],
                n_results=n,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            raise VectorIndexUnavailable(f"vector query failed: {exc}") from exc

        rows: list[dict[str, Any]] = []
        for chunk_id, doc, meta, dist in zip(
            result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
        ):
            rows.append({
                "chunk_id": chunk_id,
                "text": doc,
                "distance": round(float(dist), 4),
                **meta,
            })
        return rows
