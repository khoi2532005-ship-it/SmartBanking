import os

from flask import Flask, send_from_directory

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TABS_DIR = os.path.join(BASE_DIR, "tabs")
# The shared theme and vendored htmx: copied to /app/shared-frontend in the
# image (server.py is /app/frontend/server.py), or shared/frontend in a repo checkout.
_SHARED_CANDIDATES = (
    os.path.join(BASE_DIR, "..", "shared-frontend"),
    os.path.join(BASE_DIR, "..", "..", "..", "shared", "frontend"),
)
SHARED_FRONTEND_DIR = os.path.abspath(
    next((path for path in _SHARED_CANDIDATES if os.path.isdir(path)), _SHARED_CANDIDATES[0])
)


@app.get("/")
def normal_tab():
    return send_from_directory(TABS_DIR, "transactions.html")


@app.get("/tabs/<path:filename>")
def tabs(filename):
    return send_from_directory(TABS_DIR, filename)


@app.get("/js/<path:filename>")
def js_file(filename):
    return send_from_directory(os.path.join(SHARED_FRONTEND_DIR, "js"), filename)


@app.get("/css/<path:filename>")
def css_file(filename):
    return send_from_directory(os.path.join(SHARED_FRONTEND_DIR, "css"), filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3005, debug=False)
