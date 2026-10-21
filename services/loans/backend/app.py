from pathlib import Path
import sys

from flask import Flask, jsonify
from flask_cors import CORS


BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from routes.ai import ai_bp
from routes.loans import loans_bp
from routes.mcp_mode import mcp_bp
from routes.multi_agent import multi_agent_bp
from routes.rag_mode import rag_bp
from routes.repayments import repayments_bp
from services import multi_agent_client


def create_app():
    app = Flask(__name__)
    CORS(app)

    app.register_blueprint(loans_bp)
    app.register_blueprint(repayments_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(mcp_bp)
    app.register_blueprint(rag_bp)
    app.register_blueprint(multi_agent_bp)

    @app.get("/api/health")
    def health():
        # Configuration only, no calls out, so health stays instant.
        return jsonify({
            "service": "loan-service",
            "status": "running",
            "multi_agent": {"enabled": multi_agent_client.enabled(), "url": multi_agent_client.server_url()},
        })

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=False, threaded=True)  # noqa: S104  # local service bind required for Docker host access
