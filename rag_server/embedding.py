"""Deterministic 256-dimensional embeddings (Lecture 8, Local Components).

No model download, no network, identical vectors on every machine and every
run: each token is hashed with SHA-1 into one of 256 slots with a sign, and
the vector is L2-normalised. Word bigrams are added at half weight so short
phrases ("over budget", "near limit") pull chunks closer than their words
alone would. The same function embeds documents and queries.

This is a hashing embedding, not a semantic one - two sentences with the same
meaning but different words are far apart. That is why the retriever also
scores IDF-weighted token overlap and why the corpus is written in the same
vocabulary the features use.
"""

from __future__ import annotations

import hashlib
import math
import re

from rag_server import config

DIM = config.EMBEDDING_DIM

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*")

STOPWORDS = frozenset("""
a an the and or but if then else of to in on at by for from with without into
onto over under is are was were be been being am do does did done have has had
having this that these those it its they them their there here what which who
whom whose when where why how i you he she we me him her us my your his our
can could may might must shall should will would not no nor so than too very
as also just only about above below between each every any some such more most
other own same up down out off again further once
""".split())


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens (dots, dashes, slashes and underscores kept
    inside tokens so `api/budgets`, `budget_id` and `2026-09` survive), stopwords
    removed."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


def _slot(token: str) -> tuple[int, float]:
    digest = hashlib.sha1(token.encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % DIM
    sign = 1.0 if digest[4] & 1 else -1.0
    return index, sign


def embed(text: str) -> list[float]:
    vector = [0.0] * DIM
    tokens = tokenize(text)
    if not tokens:
        return vector

    for token in tokens:
        index, sign = _slot(token)
        vector[index] += sign

    for left, right in zip(tokens, tokens[1:]):
        index, sign = _slot(f"{left} {right}")
        vector[index] += 0.5 * sign

    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return vector
    return [v / norm for v in vector]


def embed_many(texts: list[str]) -> list[list[float]]:
    return [embed(t) for t in texts]
