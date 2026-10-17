"""Workflow store: an in-memory map backed by one JSON file per workflow.

The file copy means a server restart does not lose a workflow that is waiting
for its human decision, and the agentic loop's review mode can read a finished
workflow without asking the server.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from multi_agent_server.models import State, Workflow, new_workflow_id, now_iso


class WorkflowStore:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._items: dict[str, Workflow] = {}
        self._load()

    def _load(self) -> None:
        for path in sorted(self.directory.glob("wf_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue                  # valid JSON but not a workflow
                workflow = Workflow.from_dict(data)
            except (ValueError, TypeError, KeyError, AttributeError):
                continue                      # a damaged file is skipped, not fatal
            self._items[workflow.workflow_id] = workflow

    def create(self, feature: str, request: str, context: dict[str, Any]) -> Workflow:
        with self._lock:
            workflow_id = new_workflow_id()
            while workflow_id in self._items:
                workflow_id = new_workflow_id()
            workflow = Workflow(workflow_id=workflow_id, feature=feature, request=request, context=context)
            self._write(workflow)                 # on disk first: a failed write leaves no zombie in memory
            self._items[workflow_id] = workflow
            return workflow

    def get(self, workflow_id: str) -> Workflow | None:
        with self._lock:
            return self._items.get(workflow_id)

    def save(self, workflow: Workflow) -> None:
        with self._lock:
            workflow.updated_at = now_iso()
            self._items[workflow.workflow_id] = workflow
            self._write(workflow)

    def list(self, state: str | None = None) -> list[Workflow]:
        with self._lock:
            items = [w for w in self._items.values() if state is None or w.state == state]
        return sorted(items, key=lambda w: w.created_at, reverse=True)

    def count(self) -> int:
        with self._lock:
            return len(self._items)

    def _write(self, workflow: Workflow) -> None:
        """Write to a temp file then replace, so a crash never leaves half a record."""
        path = self.directory / f"{workflow.workflow_id}.json"
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(workflow.to_dict(), indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise


def is_valid_state(state: str) -> bool:
    return state in State.ALL
