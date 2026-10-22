"""Helpers shared by the Release 2 review modes.

The three modes (multi_agent_review, testing_review, cloud_deployment_review)
review evidence files rather than live services, so they share the file
readers and the small grounding checks that OBSERVE needs: "is this number on
this line", "which line carries this label". Nothing here calls a model.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"


def has_number(line: str, value: Any) -> bool:
    """`value` appears on `line` as a whole number token (commas ignored)."""
    return re.search(rf"(?<![\d.]){re.escape(str(value))}(?![\d])", line.replace(",", "")) is not None


def line_for(output: str, label: str) -> str:
    """The output line that starts with `<label>:` (case-insensitive), or ''."""
    for line in output.splitlines():
        if line.strip().lower().startswith(label.lower() + ":"):
            return line.strip()
    return ""


def read_json(path: Path) -> dict[str, Any] | None:
    """A JSON object from `path`, or None when the file is missing or not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Every JSON object line of `path`; lines that are not objects are skipped."""
    return read_jsonl_counted(path)[0]


def read_jsonl_counted(path: Path) -> tuple[list[dict[str, Any]], int]:
    """(every JSON object line of `path`, how many non-blank lines were not one).

    The count lets a review say that part of an audit file could not be read
    instead of reviewing what is left as if it were complete."""
    records: list[dict[str, Any]] = []
    unreadable = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return records, 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            unreadable += 1
            continue
        if isinstance(item, dict):
            records.append(item)
        else:
            unreadable += 1
    return records, unreadable


def rate(value: Any) -> str:
    """A 0..1 rate as the two-decimal text the entries quote, or n/a."""
    return "n/a" if value is None else f"{float(value):.2f}"


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)
