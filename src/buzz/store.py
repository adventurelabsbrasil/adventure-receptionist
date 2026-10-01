from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import Task


class LocalTaskStore:
    """Deep module for local task persistence; replaceable by a remote adapter later."""

    def __init__(self, root: Path) -> None:
        self.root = root / ".buzz" / "tasks"
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, task: Task) -> None:
        path = self.root / f"{task.task_id}.json"
        path.write_text(json.dumps(asdict(task), indent=2, ensure_ascii=False) + "\n")

    def list(self) -> list[dict]:
        return [json.loads(path.read_text()) for path in sorted(self.root.glob("*.json"))]
