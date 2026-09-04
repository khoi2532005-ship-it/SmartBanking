"""Tiny static file server for the Accounts & Customers frontend tabs.

Serves frontend/tabs/*.html so the shared HTMX index (or a browser, for
local testing) can load this feature's UI on its own port. Business logic
lives entirely in the backend/API service (port 5001) - this process only
serves static HTML/JS.
"""

import os

from flask import Flask, send_from_directory

app = Flask(__name__)

TABS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tabs")


@app.get("/")
def normal_tab():
    return send_from_directory(TABS_DIR, "normal.html")


@app.get("/ai-mode")
def ai_mode_tab():
    return send_from_directory(TABS_DIR, "ai-mode.html")


@app.get("/tabs/<path:filename>")
def tabs(filename):
    return send_from_directory(TABS_DIR, filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3001, debug=False)
