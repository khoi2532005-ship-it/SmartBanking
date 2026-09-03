from pathlib import Path
import sys

from flask import Flask, jsonify
from flask_cors import CORS


BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from routes.budgets import budgets_bp
from routes.insights import insights_bp
from routes.ui import ui_bp


def create_app():
    app = Flask(__name__)
    CORS(app)

    app.register_blueprint(budgets_bp)
    app.register_blueprint(insights_bp)
    app.register_blueprint(ui_bp)

    @app.get("/api/health")
    def health():
        return jsonify({"service": "budgets-service", "status": "running"})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5004, debug=False, threaded=True)
