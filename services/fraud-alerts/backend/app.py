import logging
import os
from pathlib import Path
import re
import sys

from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

# Plan/Act/Observe/Adapt stages are logged at INFO from routes/detection.py -
# without this, Flask's default logging level (WARNING) would silently drop
# them and the loop would never visibly fire in the console during a demo.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def _load_env_file():
    # .env lives at the repo root, several levels above this file - walk up
    # to find it (same pattern as services/prompt_loader.py's prompts-dir
    # search) so this works regardless of the working directory it's run from.
    for candidate in [BASE_DIR, *BASE_DIR.parents]:
        env_file = candidate / ".env"
        if env_file.is_file():
            load_dotenv(env_file)
            return


_load_env_file()

from routes.rules import rules_bp
from routes.alerts import alerts_bp
from routes.detection import detection_bp
from routes.ai import ai_bp
from routes.mcp import mcp_bp
from routes.rag import rag_bp
from routes.agents import agents_bp
from services import llm_client, mcp_client, multi_agent_client, rag_client


# Browsers may call this API only from the fraud tabs: port 3003 on the same
# host this API answers on, since the tab calls http://<its own host>:5003.
# That holds when the home page frames the tab too, because a framed page
# keeps its own origin. flask-cors echoes an allowed origin back, but its
# pattern cannot compare hosts, so same_host_tabs_only() refuses every other
# page before a route runs; that keeps the decision and CRUD routes away from
# other websites. FRAUD_FRONTEND_ORIGINS adds exact origins (comma-separated),
# e.g. a proxied cloud frontend. Server-side callers send no Origin.
FRAUD_TAB_PORT = 3003
FRAUD_TAB_ORIGIN = re.compile(r"^https?://[^/]+:3003$")


def extra_origins():
    # A trailing slash, as copied from the address bar, is dropped: browsers
    # send the Origin header without one, so it would never match.
    origins = (origin.strip().rstrip("/") for origin in os.getenv("FRAUD_FRONTEND_ORIGINS", "").split(","))
    return [origin for origin in origins if origin]


def allowed_origins():
    return [FRAUD_TAB_ORIGIN, *extra_origins()]


def origin_allowed(origin, host, extra):
    """The fraud tab next to this API, or an origin named in FRAUD_FRONTEND_ORIGINS."""
    if origin in extra:
        return True
    try:
        page = urlparse(origin)
        return (page.scheme in ("http", "https") and page.port == FRAUD_TAB_PORT
                and page.hostname == urlparse(f"//{host}").hostname)
    except ValueError:  # a malformed port in either header
        return False


def create_app():
    app = Flask(__name__)
    CORS(app, origins=allowed_origins())
    extra = extra_origins()

    @app.before_request
    def same_host_tabs_only():
        origin = request.headers.get("Origin")
        if origin is not None and not origin_allowed(origin, request.host, extra):
            return jsonify({"error": "fraud-service answers only its own tabs from a browser"}), 403
        return None

    app.register_blueprint(rules_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(detection_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(mcp_bp)
    app.register_blueprint(rag_bp)
    app.register_blueprint(agents_bp)

    @app.get("/api/health")
    def health():
        # Configuration only, no calls out, so health stays instant. CI and the
        # cloud deploy read the flags to show each integration is present but
        # switched off.
        return jsonify({
            "service": "fraud-service",
            "status": "running",
            "ai_mode": {"enabled": llm_client.enabled(), "provider": llm_client.provider()},
            "mcp": {"enabled": mcp_client.enabled(), "url": mcp_client.server_url()},
            "rag": {"enabled": rag_client.enabled(), "url": rag_client.server_url()},
            "multi_agent": {"enabled": multi_agent_client.enabled(), "url": multi_agent_client.server_url()},
        })

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=False, threaded=True)  # noqa: S104 - the container must accept connections from other containers
