"""The two audit files Lecture 10 names, as append-only JSON Lines.

    workflow_history.jsonl     chronological execution history: one record per
                               state change or stage outcome
    coordination_audit.jsonl   coordination decisions and audit events:
                               handoffs, revision requests, timeouts and
                               fallbacks, human decisions, completion gates

Every record carries the workflow id, the workflow state, a UTC timestamp and,
where a model took part, the role and model name, so a reader can reconstruct
who did what and when without the server running.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from multi_agent_server import config
from multi_agent_server.models import Workflow, now_iso


class AuditLog:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.history_path = self.directory / config.HISTORY_FILE
        self.coordination_path = self.directory / config.COORDINATION_FILE
        self._lock = threading.Lock()

    # ---- writers ----------------------------------------------------------

    def history(self, workflow: Workflow, event: str, *, role: str = "", model: str = "",
                detail: dict[str, Any] | None = None) -> dict[str, Any]:
        record = {
            "ts": now_iso(),
            "workflow_id": workflow.workflow_id,
            "feature": workflow.feature,
            "state": workflow.state,
            "event": event,
            "role": role,
            "model": model,
            "detail": detail or {},
        }
        self._append(self.history_path, record)
        return record

    def coordination(self, workflow: Workflow, decision: str, *, actor: str = "orchestrator",
                     detail: dict[str, Any] | None = None) -> dict[str, Any]:
        record = {
            "ts": now_iso(),
            "workflow_id": workflow.workflow_id,
            "state": workflow.state,
            "decision": decision,
            "actor": actor,
            "detail": detail or {},
        }
        self._append(self.coordination_path, record)
        return record

    # ---- readers (used by the review mode and the validation script) ------

    def read_history(self, workflow_id: str | None = None) -> list[dict[str, Any]]:
        return self._read(self.history_path, workflow_id)

    def read_coordination(self, workflow_id: str | None = None) -> list[dict[str, Any]]:
        return self._read(self.coordination_path, workflow_id)

    # ---- internals ---------------------------------------------------------

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False)
        with self._lock, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    @staticmethod
    def _read(path: Path, workflow_id: str | None) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if workflow_id is None or record.get("workflow_id") == workflow_id:
                records.append(record)
        return records
