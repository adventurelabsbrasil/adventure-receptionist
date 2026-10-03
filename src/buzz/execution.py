from __future__ import annotations

from dataclasses import dataclass

from .models import Approval, Event, Task, transition_task
from .store import LocalBuzzStore


@dataclass(frozen=True)
class ExecutionConfirmation:
    task_id: str
    status: str
    recorded: bool
    already_confirmed: bool
    event_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "execution_confirmed": self.status == "completed",
            "recorded": self.recorded,
            "already_confirmed": self.already_confirmed,
            "event_id": self.event_id,
        }


class ExecutionConfirmationService:
    """Records a human attestation; it never executes an external action."""

    def __init__(self, store: LocalBuzzStore) -> None:
        self.store = store

    def confirm(
        self,
        task: Task,
        approval: Approval,
        *,
        actor_id: str,
        run_id: str,
        idempotency_key: str | None = None,
    ) -> ExecutionConfirmation:
        if not actor_id.strip():
            raise ValueError("Execution confirmation requires a human actor identity")
        if approval.task_id != task.task_id:
            raise ValueError("Approval does not belong to the task")
        if approval.status != "approved":
            raise ValueError("Execution confirmation requires an approved approval")

        key = idempotency_key or f"execution-confirmation:{task.task_id}"
        previous = self._find_confirmation(run_id, approval.approval_id, key)
        if previous is not None:
            return ExecutionConfirmation(task.task_id, task.status, False, True, previous["event_id"])
        if task.status == "completed":
            return ExecutionConfirmation(task.task_id, task.status, False, True)
        if task.status != "approved":
            raise ValueError(f"Execution confirmation requires an approved task, got: {task.status}")

        transition_task(task, "completed")
        self.store.save(task)
        event = Event.new(
            "execution.confirmed",
            run_id,
            task_id=task.task_id,
            payload={
                "approval_id": approval.approval_id,
                "handoff_id": approval.handoff_id,
                "actor_id": actor_id,
                "idempotency_key": key,
                "confirmation_mode": "human_attestation",
            },
        )
        self.store.append_event(event)
        return ExecutionConfirmation(task.task_id, task.status, True, False, event.event_id)

    def _find_confirmation(self, run_id: str, approval_id: str, idempotency_key: str) -> dict[str, object] | None:
        for event in self.store.list_events(run_id):
            if event.get("event_type") != "execution.confirmed":
                continue
            payload = event.get("payload", {})
            if payload.get("approval_id") == approval_id and payload.get("idempotency_key") == idempotency_key:
                return {"event_id": event["event_id"]}
        return None
