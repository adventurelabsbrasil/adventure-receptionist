import pytest

from buzz.models import ContextPack, Handoff, Source, Task, transition_task


def test_task_follows_canonical_pipeline():
    task = Task.new("diagnose Osana")
    transition_task(task, "triage")
    transition_task(task, "ready")
    transition_task(task, "in_progress")
    transition_task(task, "in_review")
    transition_task(task, "approved")
    transition_task(task, "completed")
    assert task.status == "completed"


def test_invalid_task_transition_is_rejected():
    with pytest.raises(ValueError, match="Invalid task transition"):
        transition_task(Task.new("diagnose Osana"), "completed")


def test_deprecated_source_requires_replacement():
    source = Source("old", "repository", "historical_only", "deprecated", "local_only")
    with pytest.raises(ValueError, match="superseded_by"):
        source.validate()


def test_handoff_requires_executor_and_valid_autonomy():
    handoff = Handoff(
        handoff_id="handoff-1",
        task_id="task-1",
        from_profile="receptionist",
        to_profile="software-diagnostic-specialist",
        objective="diagnose readiness",
        context_pack=ContextPack("task-1", ["project:osana"], ["osana-map"]),
    )
    handoff.validate()
