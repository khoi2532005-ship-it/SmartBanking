"""Terminal validation of the shared RAG server - Lecture 8's evaluation.

    python -m rag_server.validate                # print the record
    python -m rag_server.validate --evidence     # also save docs/evidence/rag-validation-<ts>.json
    python -m rag_server.validate --url http://localhost:8200

    1  reachable            /health answers and the index has chunks
    2  retrieval quality    Precision@5 and Recall@5 over benchmark queries
    3  grounded answer      /query returns an answer with >= 1 citation and a
                            valid confidence category
    4  claims supported     every citation is a retrieved chunk, and the
                            expected fact appears in a cited chunk
    5  insufficient context off-topic questions return the insufficient
                            response with no citations and no LLM call
    6  controlled refresh   /refresh rebuilds and reports the same chunk count
                            /health then serves

Relevance for P@5 / R@5: a chunk is relevant to a benchmark query when it
comes from one of the expected sources AND contains the expected keyword.
Total relevant is counted over the whole corpus, so recall is honest. Most
benchmark questions have only one or two relevant chunks in a 63-chunk
corpus, so Precision@5 is capped near 0.2-0.4 by construction; it is reported
for the record and the gate is on recall and on every query hitting.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from rag_server import config

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"
TIMEOUT = (2, 120)

# Benchmark: question, expected sources, a keyword a relevant chunk must contain.
BENCHMARK: list[dict[str, Any]] = [
    {"query": "What does the NEAR_LIMIT budget status mean?",
     "sources": ["budgeting-feature"], "keyword": "NEAR_LIMIT"},
    {"query": "Which port does the budgeting backend API run on?",
     "sources": ["budgeting-feature", "smartbank-overview"], "keyword": "5004"},
    {"query": "What tools does the shared MCP server expose?",
     "sources": ["mcp-server"], "keyword": "budgeting_summary"},
    {"query": "What are the stages of the shared agentic loop?",
     "sources": ["agentic-loop"], "keyword": "Adapt"},
    {"query": "How does the Fraud Alerts feature get transaction data?",
     "sources": ["fraud-alerts-feature"], "keyword": "Transactions API"},
    {"query": "Which customer IDs does the Accounts seed data define?",
     "sources": ["accounts-feature"], "keyword": "customers 1 to 8"},
]

OFF_TOPIC = [
    "What is the capital of France?",
    "Who won the 2022 FIFA World Cup?",
]

CONFIDENCE = {"High", "Medium", "Low", "Unknown"}


@dataclass
class Record:
    n: int
    check: str
    expected: str
    observed: str = ""
    passed: bool = False
    detail: dict[str, Any] = field(default_factory=dict)


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       cwd=REPO_ROOT, text=True).strip()
    except Exception:
        return "unknown"


def _post(url: str, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    r = requests.post(f"{url}{path}", json=body, timeout=TIMEOUT)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"error": r.text[:200]}


def _is_relevant(chunk: dict[str, Any], case: dict[str, Any]) -> bool:
    return chunk["source_id"] in case["sources"] and case["keyword"].lower() in chunk["text"].lower()


def run_checks(url: str) -> list[Record]:
    records: list[Record] = []

    # 1 - reachable ---------------------------------------------------------
    rec = Record(1, "server reachable, index populated", "/health 200 with chunks > 0")
    try:
        health = requests.get(f"{url}/health", timeout=(2, 10)).json()
        chunks = health.get("index", {}).get("chunks", 0)
        rec.observed = (f"{chunks} chunks, {health['index'].get('sources')} sources, "
                        f"mode={health['index'].get('retrieval_mode')}, model={health.get('model')}")
        rec.passed = chunks > 0
        rec.detail = health.get("index", {})
    except Exception as exc:
        rec.observed = f"unreachable: {exc}. Start it with: python -m rag_server.server"
        records.append(rec)
        return records
    records.append(rec)

    # corpus for recall denominators
    from rag_server import ingest
    try:
        corpus = [asdict(c) for c in ingest.load()]
    except FileNotFoundError:
        corpus = [asdict(c) for c in ingest.build()]

    # 2 - retrieval quality --------------------------------------------------
    rec = Record(2, "retrieval quality (Precision@5, Recall@5)",
                 "every benchmark query has >= 1 relevant chunk in its top 5; mean R@5 >= 0.6 "
                 "(P@5 is reported, not gated: most queries have only 1-2 relevant chunks in the corpus)")
    per_query = []
    for case in BENCHMARK:
        status, body = _post(url, "/retrieve", {"query": case["query"], "k": 5})
        top = body.get("evidence", [])[:5]
        relevant_top = [c for c in top if _is_relevant(c, case)]
        total_relevant = [c for c in corpus if _is_relevant(c, case)]
        p = len(relevant_top) / 5
        r = (len(relevant_top) / len(total_relevant)) if total_relevant else 0.0
        per_query.append({
            "query": case["query"], "precision_at_5": round(p, 2), "recall_at_5": round(r, 2),
            "relevant_in_top5": len(relevant_top), "total_relevant": len(total_relevant),
            "top_chunk": top[0]["chunk_id"] if top else None,
            "top_relevance": top[0]["relevance"] if top else None,
            "mode": body.get("retrieval_mode"),
        })
    mean_p = sum(q["precision_at_5"] for q in per_query) / len(per_query)
    mean_r = sum(q["recall_at_5"] for q in per_query) / len(per_query)
    misses = [q["query"] for q in per_query if q["relevant_in_top5"] == 0]
    rec.observed = f"mean P@5={mean_p:.2f}, mean R@5={mean_r:.2f}" + (
        f"; no relevant chunk for: {misses}" if misses else "; every query hit")
    rec.passed = not misses and mean_r >= 0.6
    rec.detail = {"mean_precision_at_5": round(mean_p, 3), "mean_recall_at_5": round(mean_r, 3),
                  "per_query": per_query}
    records.append(rec)

    # 3 - grounded answer -----------------------------------------------------
    case = BENCHMARK[0]
    rec = Record(3, "grounded answer with citations and confidence",
                 "200; non-empty answer; >= 1 citation; confidence in High/Medium/Low; insufficient_context false")
    status, body = _post(url, "/query", {"query": case["query"]})
    if status != 200:
        rec.observed = f"HTTP {status}: {body.get('error', '')[:160]}"
        answer_body = None
    else:
        answer_body = body
        rec.observed = (f"confidence={body.get('confidence_category')}, "
                        f"citations={[c['chunk_id'] for c in body.get('citations', [])]}, "
                        f"insufficient={body.get('insufficient_context')}, "
                        f"answer={body.get('answer', '')[:110]!r}")
        rec.passed = (bool(body.get("answer")) and len(body.get("citations", [])) >= 1
                      and body.get("confidence_category") in CONFIDENCE - {"Unknown"}
                      and body.get("insufficient_context") is False)
        rec.detail = {"answer": body.get("answer"), "citations": body.get("citations"),
                      "confidence_category": body.get("confidence_category"),
                      "retrieval_summary": body.get("retrieval_summary"),
                      "generation": body.get("generation")}
    records.append(rec)

    # 4 - claims supported ----------------------------------------------------
    rec = Record(4, "claims supported by cited chunks",
                 "each citation is a retrieved chunk; the expected fact appears in a cited chunk")
    if not answer_body:
        rec.observed = "skipped - no grounded answer to check"
    else:
        retrieved = {e["chunk_id"]: e for e in answer_body.get("evidence", [])}
        cited = [c["chunk_id"] for c in answer_body.get("citations", [])]
        unknown = [c for c in cited if c not in retrieved]
        supported = any(case["keyword"].lower() in retrieved[c]["text"].lower()
                        for c in cited if c in retrieved)
        rec.observed = (f"{len(cited)} citations, {len(unknown)} not in retrieved set, "
                        f"expected fact '{case['keyword']}' in cited chunk: {supported}")
        rec.passed = not unknown and supported
        rec.detail = {"cited": cited, "unknown": unknown, "keyword": case["keyword"]}
    records.append(rec)

    # 5 - insufficient context --------------------------------------------------
    rec = Record(5, "off-topic query -> insufficient context",
                 "insufficient_context true; no citations; confidence Unknown; llm_called false")
    results = []
    for q in OFF_TOPIC:
        status, body = _post(url, "/query", {"query": q})
        results.append({
            "query": q, "status": status,
            "insufficient_context": body.get("insufficient_context"),
            "citations": len(body.get("citations", [])),
            "confidence_category": body.get("confidence_category"),
            "llm_called": body.get("generation", {}).get("llm_called"),
            "relevant_count": body.get("retrieval_summary", {}).get("relevant_count"),
        })
    ok = all(r["status"] == 200 and r["insufficient_context"] is True and r["citations"] == 0
             and r["confidence_category"] == "Unknown" and r["llm_called"] is False for r in results)
    rec.observed = "; ".join(
        f"{r['query'][:32]!r}: insufficient={r['insufficient_context']}, llm_called={r['llm_called']}"
        for r in results)
    rec.passed = ok
    rec.detail = {"results": results}
    records.append(rec)

    # 6 - controlled refresh --------------------------------------------------------
    rec = Record(6, "controlled refresh", "/refresh 200; chunk count equals /health afterwards")
    status, body = _post(url, "/refresh", {})
    after = requests.get(f"{url}/health", timeout=(2, 10)).json()["index"]
    rec.observed = (f"HTTP {status}: chunks={body.get('chunks')}, vector_indexed={body.get('vector_indexed')}, "
                    f"mode={body.get('mode')}; health chunks={after.get('chunks')}")
    rec.passed = status == 200 and body.get("chunks") == after.get("chunks") and after.get("chunks", 0) > 0
    rec.detail = body
    records.append(rec)

    return records


def print_report(url: str, records: list[Record]) -> None:
    rule = "=" * 72
    print(rule)
    print("  SmartBank RAG server - terminal validation")
    print(f"  server: {url}   commit: {_git_sha()}   k={config.TOP_K}   threshold={config.RELEVANCE_THRESHOLD}")
    print(rule)
    for r in records:
        print(f"  {'PASS' if r.passed else 'FAIL'}  {r.n}. {r.check}")
        print(f"        expected:  {r.expected}")
        print(f"        observed:  {r.observed}")
        if r.n == 2 and "per_query" in r.detail:
            for q in r.detail["per_query"]:
                print(f"          P@5={q['precision_at_5']:.2f} R@5={q['recall_at_5']:.2f}  "
                      f"top={q['top_chunk']} rel={q['top_relevance']}  {q['query']}")
    passed = sum(1 for r in records if r.passed)
    print(rule)
    print(f"  {passed}/{len(records)} checks passed")
    print(rule)


def write_evidence(url: str, records: list[Record]) -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "kind": "rag-terminal-validation",
        "timestamp": stamp,
        "server_url": url,
        "implementation_version": _git_sha(),
        "parameters": {"k": config.TOP_K, "chunk_words": config.CHUNK_WORDS,
                       "embedding_dim": config.EMBEDDING_DIM,
                       "relevance_threshold": config.RELEVANCE_THRESHOLD},
        "benchmark": BENCHMARK,
        "off_topic": OFF_TOPIC,
        "records": [asdict(r) for r in records],
        "passed": all(r.passed for r in records),
    }
    path = EVIDENCE_DIR / f"rag-validation-{stamp}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the shared RAG server.")
    parser.add_argument("--url", default=f"http://localhost:{config.RAG_PORT}")
    parser.add_argument("--evidence", action="store_true")
    args = parser.parse_args(argv)

    records = run_checks(args.url)
    print_report(args.url, records)
    if args.evidence:
        path = write_evidence(args.url, records)
        print(f"  evidence: {path.relative_to(REPO_ROOT)}")
    return 0 if all(r.passed for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
