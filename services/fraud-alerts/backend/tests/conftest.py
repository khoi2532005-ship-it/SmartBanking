"""Puts the repo root on sys.path, so the unit tests can run the shared
Multi-Agent Server in this process.

pytest has already put this backend directory first (tests/ is a package), so
fraud's own services/ and routes/ packages are still found before anything at
the repo root.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))   # append: the backend's own services/ and routes/ must win
