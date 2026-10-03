from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .conversation import (
    ApprovalResponse,
    ConversationInput,
    ConversationOutput,
    ConversationTransport,
    build_approval_prompt,
)
from .models import Approval, Event, Task, transition_task
from .store import LocalBuzzStore


class ApprovalConversationService:
    """Reusable approval flow shared by CLI and future conversation channels."""

    def __init__(self, store: LocalBuzzStore, transport: ConversationTransport) -> None:
        self.store = store
        self.transport = transport

    def render(
        self,
        task: Task,
        handoff: dict[str, Any],
        approval: Approval | dict[str, Any],
        *,
        conversation_id: str,
    ) -> ConversationOutput:
        prompt = build_approval_prompt(asdict(task), handoff, asdict(approval) if isinstance(approval, Approval) else approval)
        return self.transport.render(prompt, conversation_id=conversation_id)

    def respond(
        self,
        task: Task,
        handoff: dict[str, Any],
        approval: Approval,
        envelope: ConversationInput,
        *,
        run_id: str,
    ) -> tuple[ApprovalResponse, bool]:
        """Apply at most one decision. Returns (normalized response, decision_recorded)."""
        envelope.validate()
        if envelope.task_id != task.task_id or envelope.approval_id != approval.approval_id:
            raise ValueError("Conversation envelope correlation does not match the approval")

        prompt = build_approval_prompt(asdict(task), handoff, asdict(approval))
        response = self.transport.receive(envelope, prompt)

        # A decided approval is terminal. A repeated request is observable by the caller,
        # but cannot mutate state or append a second decision event.
        if approval.status != "pending":
            return response, False

        if response.kind not in {"approve", "reject"}:
            self.store.append_event(Event.new(
                "approval.response_received",
                run_id,
                task_id=task.task_id,
                payload=_trace_payload(envelope, approval, response),
            ))
            return response, False

        if self._idempotency_seen(run_id, envelope.idempotency_key, approval.approval_id):
            return response, False

        approval.decide(
            "approved" if response.kind == "approve" else "rejected",
            decided_by=envelope.actor_id,
            reason=response.text,
        )
        transition_task(task, "approved" if response.kind == "approve" else "in_progress")
        self.store.save_approval(approval)
        self.store.save(task)
        self.store.append_event(Event.new(
            f"approval.{approval.status}",
            run_id,
            task_id=task.task_id,
            payload=_trace_payload(envelope, approval, response),
        ))
        return response, True

    def _idempotency_seen(self, run_id: str, key: str, approval_id: str) -> bool:
        return any(
            event.get("event_type") in {"approval.approved", "approval.rejected"}
            and event.get("payload", {}).get("idempotency_key") == key
            and event.get("payload", {}).get("approval_id") == approval_id
            for event in self.store.list_events(run_id)
        )


def _trace_payload(
    envelope: ConversationInput,
    approval: Approval,
    response: ApprovalResponse,
) -> dict[str, Any]:
    # Keep trace metadata useful for correlation without copying free-form content.
    return {
        "conversation_id": envelope.conversation_id,
        "channel": envelope.channel,
        "transport": envelope.transport,
        "actor_id": envelope.actor_id,
        "approval_id": approval.approval_id,
        "handoff_id": approval.handoff_id,
        "idempotency_key": envelope.idempotency_key,
        "response_kind": response.kind,
        "response_option": response.option_key,
    }
