import logging
import os
from pathlib import Path
import re
import sys

from dotenv import load_dotenv
from flask import Flask, jsonify
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


# Browsers call this API from the fraud tabs on port 3003 only - also when the
# home page frames them, since a framed page keeps its own origin. No other
# website may read the responses or send JSON, which keeps the Multi-Agent
# decision route out of their reach. FRAUD_FRONTEND_ORIGINS adds more
# (comma-separated); server-side callers send no Origin and are unaffected.
FRAUD_TAB_ORIGIN = re.compile(r"^https?://[^/]+:3003$")


def allowed_origins():
    extra = [origin.strip() for origin in os.getenv("FRAUD_FRONTEND_ORIGINS", "").split(",") if origin.strip()]
    return [FRAUD_TAB_ORIGIN, *extra]


def create_app():
    app = Flask(__name__)
    CORS(app, origins=allowed_origins())

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
