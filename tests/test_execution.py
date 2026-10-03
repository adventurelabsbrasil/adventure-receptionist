import pytest

from buzz.execution import ExecutionConfirmationService
from buzz.models import Approval, Task, transition_task
from buzz.store import LocalBuzzStore


def _approved_context(tmp_path):
    store = LocalBuzzStore(tmp_path)
    task = Task(task_id="task-1", objective="review", status="in_review")
    transition_task(task, "approved")
    approval = Approval(
        approval_id="approval-1",
        task_id=task.task_id,
        handoff_id="handoff-1",
        status="approved",
        decided_by="rodrigo",
    )
    store.save(task)
    store.save_approval(approval)
    return store, task, approval


def test_confirmation_records_human_attestation_and_completes_task(tmp_path):
    store, task, approval = _approved_context(tmp_path)

    result = ExecutionConfirmationService(store).confirm(
        task, approval, actor_id="rodrigo", run_id="run-1", idempotency_key="confirm-1"
    )

    assert result.recorded is True
    assert result.status == "completed"
    assert result.event_id
    assert store.get_task(task.task_id).status == "completed"
    event = store.list_events("run-1")[0]
    assert event["event_type"] == "execution.confirmed"
    assert event["payload"] == {
        "approval_id": "approval-1",
        "handoff_id": "handoff-1",
        "actor_id": "rodrigo",
        "idempotency_key": "confirm-1",
        "confirmation_mode": "human_attestation",
    }


def test_confirmation_requires_approved_handoff_and_human_identity(tmp_path):
    store = LocalBuzzStore(tmp_path)
    task = Task(task_id="task-1", objective="review", status="in_review")
    approval = Approval(approval_id="approval-1", task_id=task.task_id, handoff_id="handoff-1")
    service = ExecutionConfirmationService(store)

    with pytest.raises(ValueError, match="approved approval"):
        service.confirm(task, approval, actor_id="rodrigo", run_id="run-1")

    approval.status = "approved"
    with pytest.raises(ValueError, match="human actor"):
        service.confirm(task, approval, actor_id="", run_id="run-1")


def test_confirmation_is_idempotent_and_does_not_append_a_second_event(tmp_path):
    store, task, approval = _approved_context(tmp_path)
    service = ExecutionConfirmationService(store)

    first = service.confirm(task, approval, actor_id="rodrigo", run_id="run-1", idempotency_key="confirm-1")
    second = service.confirm(task, approval, actor_id="another-human", run_id="run-1", idempotency_key="confirm-1")

    assert first.event_id == second.event_id
    assert second.recorded is False
    assert second.already_confirmed is True
    assert len(store.list_events("run-1")) == 1
