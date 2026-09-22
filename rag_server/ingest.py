"""Corpus preparation (Lecture 8): approved documents -> traceable chunks.

Reads every `rag_server/corpus/*.md`, takes its front-matter (source_id,
title, authority_tier, origin), splits the body into blocks of at most
CHUNK_WORDS words without cutting a sentence, and writes one chunk per line
to `rag_server/data/corpus.jsonl`.

Each chunk carries chunk_id (`<source_id>#<nnn>`), source_id, title,
authority_tier, the markdown heading it sits under, its text, word count,
origin and indexed_at, so every citation can be traced back to a versioned
source file.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from rag_server import config

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])")


class CorpusError(Exception):
    """A source document is malformed; the message names the file."""


@dataclass
class Chunk:
    chunk_id: str
    source_id: str
    title: str
    authority_tier: int
    heading: str
    text: str
    word_count: int
    origin: str
    indexed_at: str

    @property
    def embed_text(self) -> str:
        """What gets embedded: title and heading give the chunk its context."""
        return f"{self.title}. {self.heading}. {self.text}"


def _parse_front_matter(raw: str, path: Path) -> tuple[dict[str, str], str]:
    match = _FRONT_MATTER_RE.match(raw)
    if not match:
        raise CorpusError(f"{path.name}: missing front-matter block")
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    for required in ("source_id", "title", "authority_tier"):
        if required not in meta:
            raise CorpusError(f"{path.name}: front-matter is missing '{required}'")
    return meta, raw[match.end():]


def _blocks(body: str) -> list[tuple[str, str]]:
    """(heading, paragraph) pairs. Tables and lists stay with their paragraph."""
    heading = ""
    out: list[tuple[str, str]] = []
    for para in re.split(r"\n\s*\n", body.strip()):
        para = " ".join(line.strip() for line in para.strip().splitlines())
        if not para:
            continue
        if para.startswith("#"):
            heading = para.lstrip("#").strip()
            continue
        out.append((heading, para))
    return out


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _pack(heading: str, paragraph: str, limit: int) -> list[str]:
    """Split one paragraph into pieces of <= limit words on sentence boundaries."""
    pieces: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in _sentences(paragraph):
        words = sentence.split()
        if len(words) > limit:
            # One sentence longer than the limit (a long list): flush what we
            # have, then hard-split it into word windows so the limit holds.
            if current:
                pieces.append(" ".join(current))
                current, count = [], 0
            pieces.extend(" ".join(words[i:i + limit]) for i in range(0, len(words), limit))
            continue
        if current and count + len(words) > limit:
            pieces.append(" ".join(current))
            current, count = [], 0
        current.append(sentence)
        count += len(words)
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk_document(path: Path, limit: int = config.CHUNK_WORDS) -> list[Chunk]:
    meta, body = _parse_front_matter(path.read_text(encoding="utf-8"), path)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    chunks: list[Chunk] = []
    seen: set[str] = set()
    n = 0

    for heading, paragraph in _blocks(body):
        for piece in _pack(heading, paragraph, limit):
            key = re.sub(r"\s+", " ", piece.lower())
            if key in seen:
                continue                      # deduplicate identical text
            seen.add(key)
            n += 1
            chunks.append(Chunk(
                chunk_id=f"{meta['source_id']}#{n:03d}",
                source_id=meta["source_id"],
                title=meta["title"],
                authority_tier=int(meta["authority_tier"]),
                heading=heading,
                text=piece,
                word_count=len(piece.split()),
                origin=meta.get("origin", path.name),
                indexed_at=stamp,
            ))
    if not chunks:
        raise CorpusError(f"{path.name}: no text after front-matter")
    return chunks


def build(corpus_dir: Path = config.CORPUS_DIR, out: Path = config.CORPUS_JSONL) -> list[Chunk]:
    """Chunk every source document and write corpus.jsonl. Returns the chunks."""
    sources = sorted(corpus_dir.glob("*.md"))
    if not sources:
        raise CorpusError(f"no source documents in {corpus_dir}")

    chunks: list[Chunk] = []
    for path in sources:
        chunks.extend(chunk_document(path))

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
    return chunks


def load(path: Path = config.CORPUS_JSONL) -> list[Chunk]:
    """Read corpus.jsonl back. Raises FileNotFoundError if it was never built."""
    chunks: list[Chunk] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                chunks.append(Chunk(**json.loads(line)))
    return chunks


if __name__ == "__main__":
    built = build()
    by_source: dict[str, int] = {}
    for c in built:
        by_source[c.source_id] = by_source.get(c.source_id, 0) + 1
    print(f"{len(built)} chunks from {len(by_source)} sources -> {config.CORPUS_JSONL}")
    for source, count in by_source.items():
        print(f"  {source:<24} {count:>3} chunks")
