import pytest

from buzz.executors import ExecutorError, ExecutorRegistry


def test_default_registry_exposes_the_three_local_executor_profiles():
    registry = ExecutorRegistry.default()

    assert registry.ids() == [
        "receptionist",
        "software-diagnostic-specialist",
        "human-operator",
    ]
    assert registry.get("software-diagnostic-specialist").requires_human_approval is True


def test_registry_selects_executor_by_capability_without_fallback():
    registry = ExecutorRegistry.default()

    selected = registry.select(required_capabilities=["diagnose-readiness"])

    assert selected.executor_id == "software-diagnostic-specialist"
    assert selected.supports_autonomy("propose") is True

    with pytest.raises(ExecutorError, match="No executor supports capabilities"):
        registry.select(required_capabilities=["send-external-message"])


def test_registry_rejects_unknown_profile_and_unsupported_autonomy():
    registry = ExecutorRegistry.default()

    with pytest.raises(ExecutorError, match="Unknown executor profile"):
        registry.get("not-real")
    with pytest.raises(ExecutorError, match="does not support autonomy"):
        registry.validate_assignment("software-diagnostic-specialist", "execute-external")
