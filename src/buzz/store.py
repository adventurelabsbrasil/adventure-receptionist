from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import Event, Handoff, Run, Task


class LocalTaskStore:
    """Compatibility adapter for callers that only need task persistence."""

    def __init__(self, root: Path) -> None:
        self._store = LocalBuzzStore(root)

    def save(self, task: Task) -> None:
        self._store.save(task)

    def list(self) -> list[dict[str, Any]]:
        return self._store.list()


class LocalBuzzStore:
    """Local adapter for Buzz state, with an append-only execution trail."""

    def __init__(self, root: Path, *, create: bool = True) -> None:
        self.root = root / ".buzz"
        self.tasks_root = self.root / "tasks"
        self.runs_root = self.root / "runs"
        self.handoffs_root = self.root / "handoffs"
        if create:
            for directory in (self.tasks_root, self.runs_root, self.handoffs_root):
                directory.mkdir(parents=True, exist_ok=True)
        self.events_path = self.root / "events.jsonl"

    def save(self, task: Task) -> None:
        task.validate()
        path = self.tasks_root / f"{task.task_id}.json"
        path.write_text(json.dumps(asdict(task), indent=2, ensure_ascii=False) + "\n")

    def list(self) -> list[dict[str, Any]]:
        return [json.loads(path.read_text()) for path in sorted(self.tasks_root.glob("*.json"))]

    def get_task(self, task_id: str) -> Task | None:
        path = self.tasks_root / f"{task_id}.json"
        if not path.exists():
            return None
        return Task(**json.loads(path.read_text()))

    def save_run(self, run: Run) -> None:
        run.validate()
        path = self.runs_root / f"{run.run_id}.json"
        path.write_text(json.dumps(asdict(run), indent=2, ensure_ascii=False) + "\n")

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        path = self.runs_root / f"{run_id}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def list_runs(self) -> list[dict[str, Any]]:
        return [json.loads(path.read_text()) for path in sorted(self.runs_root.glob("*.json"))]

    def save_handoff(self, handoff: Handoff) -> None:
        handoff.validate()
        path = self.handoffs_root / f"{handoff.handoff_id}.json"
        path.write_text(json.dumps(asdict(handoff), indent=2, ensure_ascii=False) + "\n")

    def get_handoff(self, task_id: str) -> dict[str, Any] | None:
        for path in sorted(self.handoffs_root.glob("*.json")):
            handoff = json.loads(path.read_text())
            if handoff["task_id"] == task_id:
                return handoff
        return None

    def list_handoffs(self) -> list[dict[str, Any]]:
        return [json.loads(path.read_text()) for path in sorted(self.handoffs_root.glob("*.json"))]

    def append_event(self, event: Event) -> None:
        event.validate()
        with self.events_path.open("a") as stream:
            stream.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")

    def list_events(self, run_id: str | None = None) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        events = [json.loads(line) for line in self.events_path.read_text().splitlines() if line]
        return [event for event in events if run_id is None or event["run_id"] == run_id]
