"""Static file server for the budgets frontend microservice (development).

In Docker this role is filled by nginx (see frontend/Dockerfile). This script
exists so the feature can be demonstrated without Docker installed.

It serves two directories under one origin, matching the container layout:

    /            -> shared/frontend   (index.html, css/, js/)
    /tabs/...    -> this feature's tabs/

Run:  python services/budgeting/frontend/serve.py
Then: http://localhost:8030/tabs/budgets.html
"""

from pathlib import Path
import os

from flask import Flask, redirect, send_from_directory


FRONTEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = FRONTEND_DIR.parents[1]
SHARED_DIR = REPO_ROOT / "shared" / "frontend"
TABS_DIR = FRONTEND_DIR / "tabs"

PORT = int(os.getenv("FRONTEND_PORT", "8030"))

app = Flask(__name__)


@app.get("/")
def home():
    return redirect("/tabs/budgets.html")


@app.get("/tabs/<path:filename>")
def tabs(filename):
    return send_from_directory(TABS_DIR, filename)


@app.get("/<path:filename>")
def shared(filename):
    return send_from_directory(SHARED_DIR, filename)


if __name__ == "__main__":
    if not SHARED_DIR.is_dir():
        raise SystemExit(f"shared frontend directory not found: {SHARED_DIR}")
    print(f"Serving shared frontend from {SHARED_DIR}")
    print(f"Serving feature tabs   from {TABS_DIR}")
    print(f"Open http://localhost:{PORT}/tabs/budgets.html")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
