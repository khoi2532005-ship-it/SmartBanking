"""Process supervisor for the Transactions feature.

Runs the SQLite database service, the API service, and the static frontend
server in one container, matching the pattern used by the other feature modules.
"""

import os
import signal
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SERVICES = [
    ("database-service", os.path.join(BASE_DIR, "database", "app.py")),
    ("backend-service", os.path.join(BASE_DIR, "backend", "app.py")),
    ("frontend-static", os.path.join(BASE_DIR, "frontend", "server.py")),
]

processes = []


def shutdown(*_args):
    for name, proc in processes:
        if proc.poll() is None:
            print(f"Stopping {name}...")
            proc.terminate()
    for _name, proc in processes:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    sys.exit(0)


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)


def main():
    for name, path in SERVICES:
        print(f"Starting {name} ({path})")
        processes.append((name, subprocess.Popen([sys.executable, path])))
        time.sleep(0.5)

    while True:
        for name, proc in processes:
            code = proc.poll()
            if code is not None:
                print(f"{name} exited with code {code}; shutting down container")
                shutdown()
        time.sleep(1)


if __name__ == "__main__":
    main()
