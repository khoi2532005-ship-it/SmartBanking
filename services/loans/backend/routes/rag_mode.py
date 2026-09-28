"""RAG Mode routes for Loans & Credit (Release 1 integration).

Thin proxies to the shared RAG server for retrieved evidence and grounded
answers with citations. Every route applies the same gate as the MCP routes:
RAG_ENABLED env var AND the X-RAG-Mode header.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
import requests

from services.rag_api import call_rag_service, rag_disabled_response, rag_mode_is_enabled

rag_bp = Blueprint("rag_mode", __name__)


@rag_bp.post("/api/rag/retrieve")
def rag_retrieve():
    if not rag_mode_is_enabled(request):
        return rag_disabled_response()

    data = request.get_json(silent=True) or request.form
    query = str((data.get("query") or "").strip())
    if not query:
        return jsonify({"status": "error", "error": "query is required"}), 400

    try:
        k = int(data.get("k") or 5)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "error": "k must be an integer"}), 400

    try:
        payload = call_rag_service("/retrieve", {"query": query, "k": k, "caller": "loans"})
        return jsonify({"status": "ok", "result": payload})
    except requests.RequestException as exc:
        return jsonify({"status": "error", "error": str(exc)}), 503


@rag_bp.post("/api/rag/answer")
def rag_answer():
    if not rag_mode_is_enabled(request):
        return rag_disabled_response()

    data = request.get_json(silent=True) or request.form
    query = str((data.get("query") or "").strip())
    if not query:
        return jsonify({"status": "error", "error": "query is required"}), 400

    try:
        k = int(data.get("k") or 5)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "error": "k must be an integer"}), 400

    try:
        payload = call_rag_service("/query", {"query": query, "k": k, "caller": "loans"})
        return jsonify({"status": "ok", "result": payload})
    except requests.RequestException as exc:
        return jsonify({"status": "error", "error": str(exc)}), 503