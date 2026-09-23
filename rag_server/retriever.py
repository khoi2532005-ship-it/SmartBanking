"""Retrieval (Lecture 8): top-k vector search, authority-first ranking, and a
lexical fallback when the vector index is unavailable.

Every retrieved chunk also gets a `relevance` score in 0..1: the IDF-weighted
share of the question's distinctive tokens that appear in the chunk. Vector
distance says "nearby in hash space"; relevance says "actually talks about
what was asked". The grounding layer uses relevance to decide whether there
is enough evidence to answer at all.

Retrieval is hybrid: the candidate set is the vector index's nearest chunks
plus the lexically most relevant chunks, de-duplicated. Chunks that pass the
relevance threshold are ranked first, by authority tier then relevance
(distance breaks ties); the remainder follow. Two variables were changed, one
per evaluation run, with before/after evidence in docs/evidence/rag-validation-*.json:
run 1 -> hybrid candidates, because pure vector retrieval missed the MCP tool
list (a short question against a long list chunk dilutes a hashed cosine
match); run 2 -> relevance band before tier, because strict tier-first
ordering let irrelevant tier-1 chunks crowd out the tier-2 chunk that answered.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from rag_server import config, ingest
from rag_server.embedding import tokenize
from rag_server.index import ChromaIndex, VectorIndexUnavailable
from rag_server.ingest import Chunk


@dataclass
class EvidenceRecord:
    rank: int
    chunk_id: str
    source_id: str
    title: str
    authority_tier: int
    heading: str
    distance: float | None       # None in lexical fallback
    relevance: float             # IDF-weighted overlap, 0..1
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Retrieval:
    query: str
    k: int
    mode: str                    # "hybrid" | "lexical_fallback"
    evidence: list[EvidenceRecord]
    note: str = ""               # why fallback fired, if it did


class Retriever:
    def __init__(self, chunks: list[Chunk] | None = None, use_vector: bool = True) -> None:
        """Load the corpus (or use `chunks` directly, for tests) and open the index.

        `use_vector=False` skips ChromaDB entirely, which is how the lexical
        fallback path is exercised deterministically in tests.
        """
        self.chunks: list[Chunk] = []
        self._by_id: dict[str, Chunk] = {}
        self._idf: dict[str, float] = {}
        self._max_idf = 1.0
        self._vector: ChromaIndex | None = None
        self.vector_error = ""
        if chunks is not None:
            self.chunks = list(chunks)
            self._index_chunks()
        else:
            self._load_corpus()
        if use_vector:
            self._open_vector()
        else:
            self.vector_error = "vector index disabled"

    # ---- corpus ------------------------------------------------------------

    def _load_corpus(self) -> None:
        try:
            self.chunks = ingest.load()
        except FileNotFoundError:
            self.chunks = ingest.build()
        self._index_chunks()

    def index_stale(self) -> bool:
        """True when the vector index is missing or does not match the corpus."""
        if self._vector is None:
            return True
        try:
            return self._vector.count() != len(self.chunks)
        except VectorIndexUnavailable:
            return True

    def _index_chunks(self) -> None:
        self._by_id = {c.chunk_id: c for c in self.chunks}
        n = len(self.chunks) or 1
        df: dict[str, int] = {}
        for chunk in self.chunks:
            for token in set(tokenize(chunk.embed_text)):
                df[token] = df.get(token, 0) + 1
        self._idf = {t: math.log((n + 1) / (d + 1)) + 1.0 for t, d in df.items()}
        self._max_idf = math.log((n + 1) / 1.0) + 1.0    # a token seen in no chunk

    def _open_vector(self) -> None:
        try:
            self._vector = ChromaIndex()
            self._vector.count()
            self.vector_error = ""
        except VectorIndexUnavailable as exc:
            self._vector = None
            self.vector_error = str(exc)

    def refresh(self) -> dict[str, Any]:
        """Controlled refresh: rebuild corpus and index, validate before use."""
        chunks = ingest.build()
        stats: dict[str, Any] = {"chunks": len(chunks), "sources": len({c.source_id for c in chunks})}
        try:
            index = ChromaIndex()
            indexed = index.rebuild(chunks)
            if indexed != len(chunks):
                raise VectorIndexUnavailable(
                    f"index holds {indexed} chunks but corpus has {len(chunks)} - not activated"
                )
            self._vector = index
            self.vector_error = ""
            stats["vector_indexed"] = indexed
        except VectorIndexUnavailable as exc:
            self._vector = None
            self.vector_error = str(exc)
            stats["vector_indexed"] = 0
            stats["vector_error"] = str(exc)
        # Activate the new corpus only after the index step is decided.
        self.chunks = chunks
        self._index_chunks()
        stats["mode"] = self.mode
        return stats

    @property
    def mode(self) -> str:
        return "hybrid" if self._vector is not None else "lexical_fallback"

    def get(self, chunk_id: str) -> Chunk | None:
        return self._by_id.get(chunk_id)

    def sources(self) -> list[dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for c in self.chunks:
            entry = out.setdefault(c.source_id, {
                "source_id": c.source_id, "title": c.title,
                "authority_tier": c.authority_tier, "origin": c.origin, "chunks": 0,
            })
            entry["chunks"] += 1
        return sorted(out.values(), key=lambda s: (s["authority_tier"], s["source_id"]))

    # ---- relevance ----------------------------------------------------------

    def relevance(self, query_tokens: list[str], chunk_text: str) -> float:
        """Share of the query's IDF weight found in the chunk, 0..1.

        A query token that appears in no chunk at all carries the maximum
        weight, so "capital of France" scores near zero against every chunk
        even though "of" is dropped and nothing matches.
        """
        if not query_tokens:
            return 0.0
        chunk_tokens = set(tokenize(chunk_text))
        total = sum(self._idf.get(t, self._max_idf) for t in query_tokens)
        hit = sum(self._idf.get(t, self._max_idf) for t in query_tokens if t in chunk_tokens)
        return round(hit / total, 4) if total else 0.0

    # ---- retrieval ----------------------------------------------------------

    def _lexical_rows(self, q_tokens: list[str], k: int) -> list[dict[str, Any]]:
        scored = [(self.relevance(q_tokens, c.embed_text), c) for c in self.chunks]
        # Relevance first, tier second. Candidate *selection* must not be
        # tier-first: with no vector half to supply them, a tier-2 chunk that
        # answers the question would never enter the candidate set (review
        # finding on the first version of this code).
        scored.sort(key=lambda pair: (-pair[0], pair[1].authority_tier))
        return [{
            "chunk_id": c.chunk_id, "text": c.text, "distance": None,
            "source_id": c.source_id, "title": c.title,
            "authority_tier": c.authority_tier, "heading": c.heading,
        } for score, c in scored[:k] if score > 0]

    def retrieve(self, query: str, k: int = config.TOP_K) -> Retrieval:
        k = max(1, min(int(k), 20))
        q_tokens = list(dict.fromkeys(tokenize(query)))   # unique, ordered
        note = ""
        mode = "hybrid"

        # Candidates: vector neighbours plus lexical matches, de-duplicated.
        rows: list[dict[str, Any]] = []
        if self._vector is not None:
            try:
                rows = self._vector.query(query, k)
            except VectorIndexUnavailable as exc:
                note = f"vector retrieval failed, using lexical fallback: {exc}"
        else:
            note = f"vector index unavailable, using lexical fallback: {self.vector_error}"

        if not rows:
            mode = "lexical_fallback"
        seen = {row["chunk_id"] for row in rows}
        for row in self._lexical_rows(q_tokens, k):
            if row["chunk_id"] not in seen:
                rows.append(row)
                seen.add(row["chunk_id"])

        records: list[EvidenceRecord] = []
        for row in rows:
            chunk = self._by_id.get(row["chunk_id"])
            text_for_score = chunk.embed_text if chunk else row["text"]
            records.append(EvidenceRecord(
                rank=0,
                chunk_id=row["chunk_id"],
                source_id=row["source_id"],
                title=row["title"],
                authority_tier=int(row["authority_tier"]),
                heading=row.get("heading", ""),
                distance=row["distance"],
                relevance=self.relevance(q_tokens, text_for_score),
                text=row["text"],
            ))

        # Ranking policy: authority orders evidence, it does not manufacture
        # it. Chunks that pass the relevance threshold are ranked first, by
        # authority tier then relevance then vector distance; everything below
        # the threshold follows in the same order. Without the split, five
        # tier-1 chunks that merely mention a word can push the one tier-2
        # chunk that actually answers out of the top k (second evaluation run).
        def order(r: EvidenceRecord):
            return (r.authority_tier, -r.relevance, r.distance if r.distance is not None else 9.0)

        strong = sorted((r for r in records if r.relevance >= config.RELEVANCE_THRESHOLD), key=order)
        weak = sorted((r for r in records if r.relevance < config.RELEVANCE_THRESHOLD), key=order)
        records = (strong + weak)[:k]
        for i, record in enumerate(records, start=1):
            record.rank = i

        return Retrieval(query=query, k=k, mode=mode, evidence=records, note=note)
