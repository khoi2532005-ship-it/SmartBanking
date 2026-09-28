"""Route blueprints for the budgeting backend, plus one request helper.

`json_object()` is the one way a route reads a JSON body. Flask's
`request.get_json(silent=True)` returns whatever the body parses to - a list
for `[1]`, a string for `"hi"` - and the usual `data.get(...)` then raises
inside the route, turning a caller's mistake into a 500. Every POST and PUT
route calls this helper so a non-object body is a 400 with a readable reason.
"""

from flask import jsonify, request


def json_object():
    """Return (body, None) for a JSON object body, or (None, error_response).

    A missing, empty or `null` body is treated as {} so routes can fall back
    to their defaults and report which fields are required.

        data, error = json_object()
        if error:
            return error
    """
    data = request.get_json(silent=True)
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, (jsonify({"error": "JSON object body required"}), 400)
    return data, None
