from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


TASK_STATUSES = (
    "captured",
    "triage",
    "ready",
    "in_progress",
    "waiting",
    "in_review",
    "approved",
    "completed",
    "archived",
    "blocked",
)

AUTONOMY_LEVELS = ("observe", "propose", "execute-local", "execute-external")
SOURCE_STATUSES = ("verified", "snapshot", "active", "stale", "deprecated", "partial", "unavailable")

_TASK_TRANSITIONS: dict[str, set[str]] = {
    "captured": {"triage", "archived"},
    "triage": {"ready", "waiting", "archived"},
    "ready": {"in_progress", "waiting", "archived"},
    "in_progress": {"waiting", "in_review", "blocked", "archived"},
    "blocked": {"ready", "in_progress", "waiting", "archived"},
    "waiting": {"ready", "in_progress", "archived"},
    "in_review": {"approved", "in_progress", "waiting", "archived"},
    "approved": {"completed", "in_progress", "archived"},
    "completed": {"archived"},
    "archived": set(),
}


def transition_task(task: "Task", next_status: str) -> "Task":
    """Apply one canonical task transition and reject invalid state changes."""
    if next_status not in TASK_STATUSES and next_status != "blocked":
        raise ValueError(f"Unknown task status: {next_status}")
    if next_status not in _TASK_TRANSITIONS.get(task.status, set()):
        raise ValueError(f"Invalid task transition: {task.status} -> {next_status}")
    task.status = next_status
    return task


@dataclass
class Task:
    task_id: str
    objective: str
    status: str = "captured"
    project_id: str | None = None
    entity_type: str | None = None
    client_relation: str | None = None
    complexity: str | None = None
    executor_profile: str | None = None
    autonomy_level: str = "observe"
    source_refs: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)

    @classmethod
    def new(cls, objective: str) -> "Task":
        return cls(task_id=f"task-{uuid4().hex[:10]}", objective=objective)

    def validate(self) -> None:
        if not self.objective.strip():
            raise ValueError("Task objective cannot be empty")
        if self.status not in TASK_STATUSES:
            raise ValueError(f"Unknown task status: {self.status}")
        if self.autonomy_level not in AUTONOMY_LEVELS:
            raise ValueError(f"Unknown autonomy level: {self.autonomy_level}")


@dataclass
class Entity:
    entity_id: str
    entity_type: str
    ownership: str
    purpose: str
    lifecycle: str
    client_relation: str | None = None
    classification_status: str = "provisional"


@dataclass
class Source:
    source_id: str
    source_type: str
    authority: str
    status: str
    access: str
    last_verified_at: str | None = None
    freshness_ttl_hours: int | None = None
    superseded_by: str | None = None

    def validate(self) -> None:
        if self.status not in SOURCE_STATUSES:
            raise ValueError(f"Unknown source status: {self.status}")
        if self.status == "deprecated" and not self.superseded_by:
            raise ValueError("Deprecated sources must declare superseded_by")


@dataclass
class ContextPack:
    task_id: str
    context_refs: list[str]
    source_ids: list[str]
    constraints: dict[str, Any] = field(default_factory=dict)
    uncertainty_policy: str = "material_only"

    def validate(self) -> None:
        if not self.task_id:
            raise ValueError("ContextPack requires task_id")
        if not self.context_refs and not self.source_ids:
            raise ValueError("ContextPack requires at least one context or source reference")


@dataclass
class Finding:
    finding_id: str
    statement: str
    certainty: str
    source_refs: list[str] = field(default_factory=list)
    impact: str = "medium"

    def validate(self) -> None:
        if not self.statement.strip():
            raise ValueError("Finding statement cannot be empty")
        if self.certainty not in {"confirmed", "probable", "uncertain"}:
            raise ValueError(f"Unknown finding certainty: {self.certainty}")


@dataclass
class Handoff:
    handoff_id: str
    task_id: str
    from_profile: str
    to_profile: str
    objective: str
    context_pack: ContextPack
    next_actions: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    autonomy_level: str = "propose"
    approval_required: bool = True

    def validate(self) -> None:
        if self.autonomy_level not in AUTONOMY_LEVELS:
            raise ValueError(f"Unknown autonomy level: {self.autonomy_level}")
        if not self.to_profile:
            raise ValueError("Handoff requires a target executor profile")
        if self.context_pack.task_id != self.task_id:
            raise ValueError("Handoff context_pack must belong to the handoff task")
        self.context_pack.validate()
        for finding in self.findings:
            finding.validate()


@dataclass
class Run:
    run_id: str
    task_id: str
    status: str = "started"
    step_id: str | None = None
    provider: str | None = None
    model: str | None = None
    source_snapshot_ids: list[str] = field(default_factory=list)
    idempotency_key: str | None = None
    started_at: str = field(default_factory=now_iso)
    finished_at: str | None = None

    def validate(self) -> None:
        if not self.run_id or not self.task_id:
            raise ValueError("Run requires run_id and task_id")
        if self.status not in {"started", "completed", "failed", "cancelled"}:
            raise ValueError(f"Unknown run status: {self.status}")


@dataclass
class Event:
    event_id: str
    event_type: str
    run_id: str
    task_id: str | None = None
    step_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: str = field(default_factory=now_iso)

    @classmethod
    def new(
        cls,
        event_type: str,
        run_id: str,
        *,
        task_id: str | None = None,
        step_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> "Event":
        return cls(
            event_id=f"event-{uuid4().hex[:10]}",
            event_type=event_type,
            run_id=run_id,
            task_id=task_id,
            step_id=step_id,
            payload=payload or {},
        )

    def validate(self) -> None:
        if not self.event_type.strip():
            raise ValueError("Event type cannot be empty")
        if not self.run_id:
            raise ValueError("Event requires run_id")


@dataclass
class TriageResult:
    task_id: str
    classification_status: str
    project_id: str
    entity_type: str
    client_relation: str
    complexity: str
    executor_profile: str
    autonomy_level: str
    context_refs: list[str]
    findings: list[str]
    next_actions: list[str]
    material_uncertainties: list[str]
    generated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
