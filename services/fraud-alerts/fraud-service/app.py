import logging
from pathlib import Path
import sys

from flask import Flask, jsonify
from flask_cors import CORS

# Plan/Act/Observe/Adapt stages are logged at INFO from routes/detection.py -
# without this, Flask's default logging level (WARNING) would silently drop
# them and the loop would never visibly fire in the console during a demo.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from routes.rules import rules_bp
from routes.alerts import alerts_bp
from routes.detection import detection_bp
from routes.ai import ai_bp


def create_app():
    app = Flask(__name__)
    CORS(app)

    app.register_blueprint(rules_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(detection_bp)
    app.register_blueprint(ai_bp)

    @app.get("/api/health")
    def health():
        return jsonify({"service": "fraud-service", "status": "running"})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=False, threaded=True)
