"""Client for the shared RAG server (Release 1).

POST /query on the host-side RAG server (python -m rag_server.server) returns
a grounded answer: text with [chunk-id] citation markers, the cited chunks,
and a confidence category derived from the evidence. When no approved
document is relevant it returns insufficient_context=true and cites nothing.
The reply is checked against that contract here, so the page never shows a
malformed reply as if it were a grounded answer.
"""

import requests

from services.local_servers import BadServerResponse, ServerDisabled, flag_enabled, setting, unavailable

DEFAULT_URL = "http://localhost:8200"
START_COMMAND = "python -m rag_server.server"
CONNECT_TIMEOUT = 2
# Generation takes seconds, and the server may retry the model once or twice.
READ_TIMEOUT = 90
MAX_QUESTION_LENGTH = 1000  # the RAG server's own limit

CONFIDENCE_CATEGORIES = ("High", "Medium", "Low", "Unknown")
REQUIRED_FIELDS = ("answer", "citations", "confidence_category", "retrieval_summary", "insufficient_context")


class RAGRefused(RuntimeError):
    """The RAG server answered with an error status, e.g. 503 when its LLM is unavailable."""

    def __init__(self, status, message, payload):
        super().__init__(message)
        self.status = status
        self.payload = payload


def enabled():
    return flag_enabled("RAG_ENABLED")


def server_url():
    return setting("RAG_SERVER_URL", DEFAULT_URL).rstrip("/")


def ask(question):
    """The grounded answer (or insufficient-context answer) for one question."""
    if not enabled():
        raise ServerDisabled("RAG is switched off in this environment (RAG_ENABLED=false)")

    base = server_url()
    try:
        response = requests.post(f"{base}/query", json={"query": question},
                                 timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
    except requests.RequestException as exc:
        raise unavailable("RAG server", base, START_COMMAND, exc) from None

    try:
        body = response.json()
    except ValueError:
        body = None
    if response.status_code != 200:
        payload = body if isinstance(body, dict) else {}
        raise RAGRefused(response.status_code,
                         payload.get("error") or f"RAG server answered HTTP {response.status_code}",
                         payload)
    return _checked(body)


def _checked(answer):
    if not isinstance(answer, dict):
        raise BadServerResponse("RAG server's reply is not a JSON object")
    missing = [field for field in REQUIRED_FIELDS if field not in answer]
    if missing:
        raise BadServerResponse(f"RAG reply is missing {', '.join(missing)}")
    if answer["confidence_category"] not in CONFIDENCE_CATEGORIES:
        raise BadServerResponse(f"RAG reply has an unknown confidence category: {answer['confidence_category']!r}")
    if not isinstance(answer["citations"], list):
        raise BadServerResponse("RAG reply's citations are not a list")
    if answer["insufficient_context"] and answer["citations"]:
        raise BadServerResponse("RAG reply says insufficient context but still cites sources")
    if not answer["insufficient_context"] and not answer["citations"]:
        raise BadServerResponse("RAG reply claims a grounded answer but cites nothing")
    return answer
