import pytest

from buzz.approval_service import ApprovalConversationService
from buzz.conversation import (
    ApprovalPrompt,
    ConversationInput,
    LocalConversationTransport,
    TelegramDryRunTransport,
    build_approval_prompt,
    parse_approval_response,
)
from buzz.models import Approval, Task
from buzz.store import LocalBuzzStore


def _prompt():
    return build_approval_prompt(
        {"task_id": "task-1", "objective": "diagnose readiness", "project_id": "generic", "unknowns": ["live state"]},
        {"objective": "prepare a local report", "next_actions": ["review the local snapshot"]},
        {"approval_id": "approval-1"},
    )


def test_prompt_has_choices_and_is_transport_neutral():
    prompt = _prompt()

    assert [option.key for option in prompt.options] == ["1", "2", "3"]
    assert "somente leitura" in prompt.render()
    assert prompt.to_dict()["external_effects"] is False


def test_free_text_and_choice_responses_are_normalized_without_deciding():
    prompt = _prompt()

    assert parse_approval_response("1", prompt).kind == "approve"
    assert parse_approval_response("não vou aprovar", prompt).kind == "reject"
    assert parse_approval_response("quero ajustar o escopo", prompt).kind == "adjust"
    assert parse_approval_response("o que falta confirmar?", prompt).kind == "clarify"
    assert parse_approval_response("talvez depois", prompt).kind == "unknown"


def test_local_and_telegram_dry_run_render_the_same_prompt_without_network():
    prompt = _prompt()

    local = LocalConversationTransport().render(prompt, conversation_id="conversation-1")
    telegram = TelegramDryRunTransport().render(prompt, conversation_id="conversation-1")

    assert local.text == telegram.text == prompt.render()
    assert [button["key"] for button in telegram.buttons] == ["1", "2", "3"]
    assert telegram.channel == "telegram"
    assert telegram.transport == "telegram-dry-run"


def test_transports_normalize_option_and_text_the_same_way():
    prompt = _prompt()
    transport = TelegramDryRunTransport()
    common = {
        "conversation_id": "conversation-1",
        "channel": "telegram",
        "transport": "telegram-dry-run",
        "actor_id": "rodrigo",
        "task_id": prompt.task_id,
        "approval_id": prompt.approval_id,
        "idempotency_key": "response-1",
    }

    option = transport.receive(ConversationInput(**common, option_key="1"), prompt)
    text = transport.receive(ConversationInput(**common, text="aprovo"), prompt)
    assert option.kind == text.kind == "approve"


def test_transport_rejects_wrong_correlation_and_missing_human_identity():
    prompt = _prompt()
    transport = LocalConversationTransport()
    common = {
        "conversation_id": "conversation-1",
        "channel": "local",
        "transport": "local-dry-run",
        "actor_id": "rodrigo",
        "task_id": prompt.task_id,
        "approval_id": prompt.approval_id,
        "idempotency_key": "response-1",
        "option_key": "1",
    }
    with pytest.raises(ValueError, match="correlation"):
        transport.receive(ConversationInput(**{**common, "task_id": "task-other"}), prompt)
    with pytest.raises(ValueError, match="human actor"):
        transport.receive(ConversationInput(**{**common, "actor_id": ""}), prompt)


def test_service_keeps_adjustment_pending_and_records_transport_trace(tmp_path):
    store = LocalBuzzStore(tmp_path)
    task = Task(task_id="task-1", objective="review", status="in_review")
    approval = Approval(approval_id="approval-1", task_id=task.task_id, handoff_id="handoff-1")
    handoff = {"handoff_id": "handoff-1", "task_id": task.task_id, "objective": "review", "next_actions": ["inspect"]}
    store.save(task)
    store.save_approval(approval)
    service = ApprovalConversationService(store, LocalConversationTransport())

    response, recorded = service.respond(
        task, handoff, approval,
        ConversationInput(
            conversation_id="conversation-1", channel="local", transport="local-dry-run",
            actor_id="rodrigo", task_id=task.task_id, approval_id=approval.approval_id,
            idempotency_key="adjust-1", text="quero ajustar o escopo",
        ),
        run_id="run-1",
    )

    assert response.kind == "adjust"
    assert recorded is False
    assert approval.status == "pending"
    event = store.list_events("run-1")[-1]
    assert event["event_type"] == "approval.response_received"
    assert {"channel", "transport", "conversation_id", "approval_id", "idempotency_key"} <= event["payload"].keys()


def test_service_idempotency_does_not_decide_or_trace_twice(tmp_path):
    store = LocalBuzzStore(tmp_path)
    task = Task(task_id="task-1", objective="review", status="in_review")
    approval = Approval(approval_id="approval-1", task_id=task.task_id, handoff_id="handoff-1")
    handoff = {"handoff_id": "handoff-1", "task_id": task.task_id, "objective": "review", "next_actions": ["inspect"]}
    store.save(task)
    store.save_approval(approval)
    service = ApprovalConversationService(store, LocalConversationTransport())
    envelope = ConversationInput(
        conversation_id="conversation-1", channel="local", transport="local-dry-run",
        actor_id="rodrigo", task_id=task.task_id, approval_id=approval.approval_id,
        idempotency_key="approve-1", option_key="1",
    )

    assert service.respond(task, handoff, approval, envelope, run_id="run-1")[1] is True
    event_count = len(store.list_events("run-1"))
    assert service.respond(task, handoff, approval, envelope, run_id="run-1")[1] is False
    assert len(store.list_events("run-1")) == event_count
    assert approval.decided_by == "rodrigo"
