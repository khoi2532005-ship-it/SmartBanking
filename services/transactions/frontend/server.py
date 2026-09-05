import os

from flask import Flask, send_from_directory

app = Flask(__name__)

TABS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tabs")


@app.get("/")
def normal_tab():
    return send_from_directory(TABS_DIR, "transactions.html")


@app.get("/tabs/<path:filename>")
def tabs(filename):
    return send_from_directory(TABS_DIR, filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3005, debug=False)
