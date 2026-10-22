from pathlib import Path
import os
import sys

from urllib.parse import urlparse

from flask import Flask, jsonify, request
from flask_cors import CORS


BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from routes.agents import agents_bp
from routes.budgets import budgets_bp
from routes.insights import insights_bp
from routes.ui import ui_bp
from services import llm_client, mcp_client, multi_agent_client, rag_client


# Browsers call this API from the budgeting tab (port 3004) and the shared home
# page (port 3000) on the same host as the API, as fraud-service does for its
# tab: a page on another host, even on those ports, is refused before any
# route runs, so it can neither drive the Multi-Agent panel nor read its
# answers. The CORS pattern alone cannot compare hosts, hence the request
# check. BUDGET_FRONTEND_ORIGINS adds exact origins (comma-separated), e.g. a
# proxied cloud frontend. Server-side callers send no Origin and are not affected.
TAB_PORTS = (3004, 3000)
DEFAULT_ORIGINS = r"^https?://[^/]+:(3004|3000)$"
HTMX_RESPONSE_HEADERS = ["HX-Trigger", "HX-Retarget", "HX-Reswap"]      # the panel reads these cross-origin


def extra_origins():
    return [o.strip() for o in os.getenv("BUDGET_FRONTEND_ORIGINS", "").split(",") if o.strip()]


def allowed_origins():
    return [DEFAULT_ORIGINS, *extra_origins()]


def origin_allowed(origin, host, extra):
    """The budgeting tab or the home page next to this API, or a configured origin."""
    if origin in extra:
        return True
    try:
        page = urlparse(origin)
        return (page.scheme in ("http", "https") and page.port in TAB_PORTS
                and page.hostname == urlparse(f"//{host}").hostname)
    except ValueError:  # a malformed port in either header
        return False


def create_app():
    app = Flask(__name__)
    CORS(app, origins=allowed_origins(), expose_headers=HTMX_RESPONSE_HEADERS)
    extra = extra_origins()

    @app.before_request
    def same_host_pages_only():
        origin = request.headers.get("Origin")
        if origin is not None and not origin_allowed(origin, request.host, extra):
            return jsonify({"error": "budgeting-service answers only its own tab and the home page from a browser"}), 403
        return None

    app.register_blueprint(budgets_bp)
    app.register_blueprint(insights_bp)
    app.register_blueprint(ui_bp)
    app.register_blueprint(agents_bp)

    @app.get("/api/health")
    def health():
        # Configuration only - no probes here, so health stays instant.
        # /api/agents/status does the reachability checks.
        return jsonify({
            "service": "budgets-service",
            "status": "running",
            "llm": llm_client.provider(),
            "ai_mode": {"enabled": llm_client.enabled(), "provider": llm_client.provider()},
            "mcp": {"enabled": mcp_client.enabled(), "url": mcp_client.server_url()},
            "rag": {"enabled": rag_client.enabled(), "url": rag_client.server_url()},
            "multi_agent": {"enabled": multi_agent_client.enabled(), "url": multi_agent_client.server_url()},
        })

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5004, debug=False, threaded=True)  # noqa: S104  # local service bind required for Docker host access
