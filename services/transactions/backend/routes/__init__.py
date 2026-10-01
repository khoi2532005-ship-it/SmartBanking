"""Shared route helpers for the transactions backend."""

from flask import jsonify, request


def json_object():
    """Return a JSON object body, or a 400 error response when the body is invalid."""
    data = request.get_json(silent=True)
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, (jsonify({"error": "JSON object body required"}), 400)
    return data, None
