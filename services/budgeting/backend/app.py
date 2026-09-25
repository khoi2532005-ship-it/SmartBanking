from pathlib import Path
import sys

from flask import Flask, jsonify
from flask_cors import CORS


BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from routes.agents import agents_bp
from routes.budgets import budgets_bp
from routes.insights import insights_bp
from routes.ui import ui_bp
from services import llm_client, mcp_client, rag_client


def create_app():
    app = Flask(__name__)
    CORS(app)

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
            "mcp": {"enabled": mcp_client.enabled(), "url": mcp_client.server_url()},
            "rag": {"enabled": rag_client.enabled(), "url": rag_client.server_url()},
        })

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5004, debug=False, threaded=True)
