import os

from flask import Flask, send_from_directory

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TABS_DIR = os.path.join(BASE_DIR, "tabs")
SHARED_FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "..", "shared-frontend"))


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
