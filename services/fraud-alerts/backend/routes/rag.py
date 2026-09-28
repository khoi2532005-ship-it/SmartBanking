"""Release 1: the AI Mode tab asks the shared RAG server questions through here.

    POST /api/rag/query   {"query": "..."} -> grounded answer or insufficient context

A grounded answer carries source citations and a confidence category. When no
approved document is relevant the reply has insufficient_context=true and no
citations; that is a valid answer (HTTP 200), not an error.
"""

from flask import Blueprint, jsonify, request

from services import rag_client
from services.llm_client import describe_error
from services.local_servers import BadServerResponse, ServerDisabled, ServerUnavailable, failure

rag_bp = Blueprint("rag", __name__, url_prefix="/api/rag")


@rag_bp.post("/query")
def query():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    question = data.get("query")
    if not isinstance(question, str) or not question.strip():
        return jsonify({"error": "query is required"}), 400
    question = question.strip()
    if len(question) > rag_client.MAX_QUESTION_LENGTH:
        return jsonify({"error": f"query must be {rag_client.MAX_QUESTION_LENGTH} characters or fewer"}), 400

    try:
        answer = rag_client.ask(question)
    except rag_client.RAGRefused as exc:
        # 503 means the RAG server's LLM was unavailable (often the shared
        # rate limit); it still reports what it retrieved, which is passed on.
        body = {"error": f"RAG server: {describe_error(exc)}"}
        if "retrieval_summary" in exc.payload:
            body["retrieval_summary"] = exc.payload["retrieval_summary"]
        return jsonify(body), 503 if exc.status == 503 else 502
    except (ServerDisabled, ServerUnavailable, BadServerResponse) as exc:
        body, status = failure(exc)
        return jsonify(body), status

    return jsonify({**answer, "server": rag_client.server_url()})
