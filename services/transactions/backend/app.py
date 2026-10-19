from pathlib import Path
import os
import sys

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

FRONTEND_DIR = (BASE_DIR.parent / "frontend").resolve()
TABS_DIR = FRONTEND_DIR / "tabs"
_SHARED_CANDIDATES = (
    FRONTEND_DIR.parent / "shared-frontend",
    FRONTEND_DIR.parents[1] / "shared" / "frontend",
)
SHARED_FRONTEND_DIR = str(
    next((path for path in _SHARED_CANDIDATES if path.is_dir()), _SHARED_CANDIDATES[0])
)

from routes.agents import agents_bp
from routes.transactions import transactions_bp
from routes.ui import ui_bp
from services import llm_client, mcp_client, multi_agent_client, rag_client

DEFAULT_ORIGINS = r"^https?://[^/]+:(3005|3000)$"


def allowed_origins():
    extra = [
        o.strip()
        for o in os.getenv("TRANSACTIONS_FRONTEND_ORIGINS", "").split(",")
        if o.strip()
    ]
    return [DEFAULT_ORIGINS, *extra]


def create_app():
    app = Flask(__name__)
    CORS(app, origins=allowed_origins())

    @app.get("/")
    def index():
        return send_from_directory(str(TABS_DIR), "transactions.html")

    @app.get("/tabs/<path:filename>")
    def tabs(filename):
        return send_from_directory(str(TABS_DIR), filename)

    @app.get("/js/<path:filename>")
    def js_file(filename):
        return send_from_directory(str(Path(SHARED_FRONTEND_DIR) / "js"), filename)

    @app.get("/css/<path:filename>")
    def css_file(filename):
        return send_from_directory(str(Path(SHARED_FRONTEND_DIR) / "css"), filename)

    app.register_blueprint(transactions_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(ui_bp)

    @app.get("/api/health")
    def health():
        return jsonify(
            {
                "service": "transactions-service",
                "status": "running",
                "llm": llm_client.provider(),
                "mcp": {
                    "enabled": mcp_client.enabled(),
                    "url": mcp_client.server_url(),
                },
                "rag": {
                    "enabled": rag_client.enabled(),
                    "url": rag_client.server_url(),
                },
                "multi_agent": {
                    "enabled": multi_agent_client.enabled(),
                    "url": multi_agent_client.server_url(),
                },
            }
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=False, threaded=True)
