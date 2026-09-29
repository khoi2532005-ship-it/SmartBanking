"""Shared RAG server validation mode - Bao (Release 1).

Runs Lecture 8's evaluation against the team's shared RAG server, has the
model write the evaluation entry, and checks that entry against the record.

ACT reuses `rag_server/validate.py`: the same checks the terminal script runs
(reachable with a populated index, Precision@5 / Recall@5 over the benchmark,
a grounded answer with citations and a confidence category, every claim
supported by a cited chunk, off-topic questions refused with no model call).
The refresh check stays skipped: a rebuild touches the shared index every
feature is querying, so it is an operator's explicit decision on the host,
never a side effect of a loop run. OBSERVE rejects an entry that misquotes the index
size or the metrics, names a confidence the record does not show, drops a
cited chunk id or invents one, or reports a pass count the record does not
support; ADAPT retries with that complaint. A server that is unreachable or
fails a check stops the run before any token is spent.

Env: RAG_SERVER_URL (default http://localhost:8200), the same name every
feature backend uses.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict

from agentic import prompts
from agentic.core import Evidence, Mode, Plan, Verdict

RAG_SERVER_URL = os.getenv("RAG_SERVER_URL", "http://localhost:8200")
PROMPT_FAMILY = "_rag"
START_HINT = "Start it with: python -m rag_server.server"

REQUIRED_LINES = ("index", "retrieval", "grounded answer", "off-topic", "verdict")

_CHUNK_ID_RE = re.compile(r"\b([a-z0-9-]+#\d{3})\b")
_CHECKS_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*checks")
_HITS_RE = re.compile(r"(\d+)\s+of\s+(\d+)")


def _tag(record: dict) -> str:
    if record.get("skipped"):
        return "SKIP"
    return "PASS" if record["passed"] else "FAIL"


def _line(output: str, label: str) -> str:
    for line in output.splitlines():
        if line.strip().lower().startswith(label):
            return line.strip()
    return ""


def _metric(value) -> str:
    return f"{float(value or 0):.2f}"


class RAGValidationMode(Mode):
    key = "rag_validation"
    label = "RAG Server Validation"
    owner = "Bao"

    def plan(self) -> Plan:
        return Plan(
            goal=(
                "Verify the shared RAG server retrieves the right evidence, answers only from it "
                "with citations and a confidence, refuses off-topic questions, and that the "
                "model's evaluation entry reports exactly what was observed"
            ),
            checks=[
                f"the RAG server answers /health at {RAG_SERVER_URL} with a populated index",
                "every benchmark question finds a relevant chunk in its top 5 (Precision@5 and Recall@5 recorded)",
                "a benchmark question returns a grounded answer with at least one citation and a confidence category",
                "every citation is a retrieved chunk and the expected fact appears in a cited chunk",
                "off-topic questions return insufficient context with no citations and no model call",
                "the shared index is left untouched: the refresh check is skipped unless an operator runs it on purpose",
                "the entry quotes the index size, metrics, confidence and chunk ids exactly and matches the pass count",
            ],
            stop_condition="An entry passes OBSERVE, or the retry budget is spent.",
        )

    def collect(self) -> Evidence:
        try:
            from rag_server import validate as rag_validate
        except ImportError as exc:
            return Evidence(
                ok=False,
                summary=f"the RAG validation module is not importable ({exc}). "
                        "Install its dependencies with: pip install -r requirements-agentic.txt",
            )

        records = [asdict(r) for r in rag_validate.run_checks(RAG_SERVER_URL)]
        facts: dict = {"server_url": RAG_SERVER_URL, "records": records}

        if not records or not records[0]["passed"]:
            observed = records[0]["observed"] if records else "no result"
            hint = "" if "Start it with" in observed else f". {START_HINT}"
            return Evidence(ok=False, facts=facts,
                            summary=f"RAG server at {RAG_SERVER_URL}: {observed}{hint}")

        failed = [r for r in records if not r["passed"]]
        if failed:
            return Evidence(
                ok=False, facts=facts,
                summary="RAG evaluation check(s) failed: "
                        + "; ".join(f"{r['n']} {r['check']} - {r['observed']}" for r in failed)
                        + ". Fix that before asking for a report entry.",
            )

        by_n = {r["n"]: r for r in records}
        index = by_n[1]["detail"]
        metrics = by_n[2]["detail"]
        grounded = by_n[3]["detail"]
        claims = by_n[4]["detail"]
        off_topic = by_n[5]["detail"].get("results") or []
        refresh_rec = by_n.get(6) or {}
        refresh = refresh_rec.get("detail") or {}
        refresh_skipped = bool(refresh_rec.get("skipped"))
        skipped = [r["n"] for r in records if r.get("skipped")]

        per_query = metrics.get("per_query") or []
        hits = sum(1 for q in per_query if q.get("relevant_in_top5", 0) > 0)
        citations = [c.get("chunk_id") for c in (grounded.get("citations") or []) if c.get("chunk_id")]
        confidence = grounded.get("confidence_category") or "Unknown"
        mode = index.get("retrieval_mode") or "unknown"
        passed_count = sum(1 for r in records if r["passed"])

        # A lexical fallback means the vector index could not be opened. The
        # checks still ran, but the metrics describe the fallback path, not the
        # hybrid ranker that is meant to be under test.
        degraded = mode != "hybrid"

        facts.update({
            "index": {
                "chunks": index.get("chunks"), "sources": index.get("sources"),
                "retrieval_mode": mode, "k": index.get("k"),
                "relevance_threshold": index.get("relevance_threshold"),
            },
            "metrics": {
                "mean_precision_at_5": _metric(metrics.get("mean_precision_at_5")),
                "mean_recall_at_5": _metric(metrics.get("mean_recall_at_5")),
                "hits": hits, "benchmark_total": len(per_query), "per_query": per_query,
            },
            "grounded_answer": {
                "query": (rag_validate.BENCHMARK[0]["query"] if rag_validate.BENCHMARK else ""),
                "answer": grounded.get("answer"), "confidence_category": confidence,
                "citations": citations,
                "model": (grounded.get("generation") or {}).get("model"),
            },
            "claims": claims,
            "off_topic": off_topic,
            "refresh": {"skipped": refresh_skipped, "chunks": refresh.get("chunks"), "mode": refresh.get("mode")},
            "passed_count": passed_count,
            "total": len(records),
            "skipped": skipped,
        })
        refresh_note = (
            "Refresh skipped: the shared index was not rebuilt by this run."
            if refresh_skipped else f"Refresh rebuilt {refresh.get('chunks')} chunks."
        )

        # The summary doubles as the evidence the REVIEW stage judges the entry
        # against, so it carries the ids and figures the entry must quote.
        return Evidence(
            ok=True,
            summary=(
                f"{index.get('chunks')} chunks from {index.get('sources')} documents, retrieval mode {mode}. "
                f"Mean P@5 {facts['metrics']['mean_precision_at_5']}, mean R@5 "
                f"{facts['metrics']['mean_recall_at_5']}, {hits} of {len(per_query)} benchmark questions "
                f"found a relevant chunk in the top 5. "
                f"Grounded answer to \"{facts['grounded_answer']['query']}\": confidence {confidence}, "
                f"citations {', '.join(citations) or 'none'}. "
                f"{len(off_topic)} off-topic questions returned insufficient context with no citations "
                f"and no model call. {refresh_note} "
                f"{passed_count}/{len(records)} checks passed"
                + (f" ({len(skipped)} skipped)" if skipped else "")
            ),
            facts=facts,
            degraded=degraded,
            note=(
                f"retrieval ran in {mode} (vector index unavailable): the metrics describe the "
                "fallback path, not the hybrid ranker"
                if degraded else ""
            ),
        )

    def build_prompt(self, plan: Plan, evidence: Evidence, feedback: str) -> tuple[str, str]:
        system_prompt, task_prompt = prompts.load_all(
            PROMPT_FAMILY, "validation_system.txt", "validation_task.txt",
        )
        f = evidence.facts
        idx, met, ans = f["index"], f["metrics"], f["grounded_answer"]

        per_query_lines = [
            f"- \"{q['query']}\": top chunk {q.get('top_chunk')} (relevance {q.get('top_relevance')}), "
            f"{q.get('relevant_in_top5')} of {q.get('total_relevant')} relevant chunks in the top 5"
            for q in met["per_query"]
        ]
        off_topic_lines = [
            f"- \"{r['query']}\": insufficient_context={r.get('insufficient_context')}, "
            f"citations={r.get('citations')}, confidence={r.get('confidence_category')}, "
            f"llm_called={r.get('llm_called')}"
            for r in f["off_topic"]
        ]
        check_lines = [f"{r['n']}. {r['check']}: {_tag(r)} - {r['observed']}" for r in f["records"]]
        answer_text = (ans.get("answer") or "").replace("\n", " ")

        evidence_block = "\n".join([
            f"Server: {f['server_url']}",
            f"Index: {idx['chunks']} chunks from {idx['sources']} documents, retrieval mode {idx['retrieval_mode']}",
            f"Retrieval quality over {met['benchmark_total']} benchmark questions: mean P@5 "
            f"{met['mean_precision_at_5']}, mean R@5 {met['mean_recall_at_5']}, {met['hits']} of "
            f"{met['benchmark_total']} questions found a relevant chunk in the top 5",
            *per_query_lines,
            f"Grounded answer to \"{ans['query']}\": confidence {ans['confidence_category']}; "
            f"citations {', '.join(ans['citations']) or 'none'}; model {ans.get('model')}",
            f"Answer text: {answer_text[:400]}",
            f"Claims: {len(f['claims'].get('cited') or [])} citations, "
            f"{len(f['claims'].get('unknown') or [])} not in the retrieved set, expected fact "
            f"'{f['claims'].get('keyword')}' present in a cited chunk",
            f"Off-topic questions ({len(f['off_topic'])}):",
            *off_topic_lines,
            ("Refresh: skipped - this run does not rebuild the shared index"
             if f["refresh"].get("skipped")
             else f"Refresh: {f['refresh'].get('chunks')} chunks rebuilt, mode {f['refresh'].get('mode')}"),
            "Checks:",
            *check_lines,
            f"Checks passed: {f['passed_count']}/{f['total']}"
            + (f" (check {', '.join(map(str, f['skipped']))} skipped and counted as passed - see its observed line)"
               if f.get("skipped") else ""),
        ])

        correction = ""
        if feedback:
            correction = (
                f"\n\nYour previous entry was rejected: {feedback}. Fix exactly that. Keep the "
                "five-line format and copy chunk ids, categories and figures from the evidence "
                "verbatim."
            )

        return system_prompt, f"{task_prompt}{correction}\n\nEvidence:\n{evidence_block}"

    def validate(self, output: str, evidence: Evidence) -> Verdict:
        f = evidence.facts
        idx, met, ans = f["index"], f["metrics"], f["grounded_answer"]
        reasons: list[str] = []

        if not output.strip():
            return Verdict(False, ["the entry was empty"])

        text = output.lower()

        for label in REQUIRED_LINES:
            if not _line(output, label):
                reasons.append(f"it did not include the '{label.capitalize()}:' line")

        # Index size and retrieval mode, as given.
        if str(idx["chunks"]) not in text or str(idx["sources"]) not in text:
            reasons.append(
                f"it did not state the index size ({idx['chunks']} chunks from {idx['sources']} documents)"
            )
        if str(idx["retrieval_mode"]).lower() not in text:
            reasons.append(f"it did not state the retrieval mode ({idx['retrieval_mode']})")

        # Metrics to two decimals, and the hit count.
        for name, value in (("P@5", met["mean_precision_at_5"]), ("R@5", met["mean_recall_at_5"])):
            if value not in text:
                reasons.append(f"it did not quote mean {name} as {value}")
        hits_match = _HITS_RE.search(_line(output, "retrieval").lower())
        expected_hits = (str(met["hits"]), str(met["benchmark_total"]))
        if not hits_match:
            reasons.append(
                f"the Retrieval line did not say '{expected_hits[0]} of {expected_hits[1]} benchmark questions'"
            )
        elif hits_match.groups() != expected_hits:
            reasons.append(
                f"it reported {hits_match.group(1)} of {hits_match.group(2)} benchmark questions but the "
                f"record shows {expected_hits[0]} of {expected_hits[1]}"
            )

        # Confidence category and citations: exactly the record's, nothing invented.
        if str(ans["confidence_category"]).lower() not in text:
            reasons.append(f"it did not state the confidence category ({ans['confidence_category']})")
        missing = [c for c in ans["citations"] if c.lower() not in text]
        if missing:
            reasons.append("it did not list these cited chunk ids: " + ", ".join(missing))
        known = {c.lower() for c in ans["citations"]} | {
            str(q.get("top_chunk")).lower() for q in met["per_query"]
        }
        invented = sorted({c for c in _CHUNK_ID_RE.findall(text) if c not in known})
        if invented:
            reasons.append("it cited chunk ids that are not in the evidence: " + ", ".join(invented))

        # Off-topic handling.
        off_line = _line(output, "off-topic").lower()
        if off_line and str(len(f["off_topic"])) not in off_line:
            reasons.append(f"the Off-topic line did not state that {len(f['off_topic'])} questions were refused")
        if "insufficient" not in text:
            reasons.append("it did not say the off-topic questions returned insufficient context")

        # Pass count and verdict word must match the record exactly.
        match = _CHECKS_RE.search(text)
        expected = f"{f['passed_count']}/{f['total']}"
        if not match:
            reasons.append(f"it did not state the pass count as '{expected} checks passed'")
        elif f"{match.group(1)}/{match.group(2)}" != expected:
            reasons.append(
                f"it reported {match.group(1)}/{match.group(2)} checks passed but the record shows {expected}"
            )
        all_passed = f["passed_count"] == f["total"]
        words = re.findall(r"\b(pass|fail)\b", _line(output, "verdict").lower())
        final = words[-1] if words else ""
        if all_passed and final != "pass":
            reasons.append("the Verdict line must end with PASS because every check passed")
        if not all_passed and final != "fail":
            reasons.append("the Verdict line must end with FAIL because a check failed")

        return Verdict(ok=not reasons, reasons=reasons)
