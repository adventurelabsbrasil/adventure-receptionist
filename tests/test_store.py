import json

from buzz.models import ContextPack, Event, Handoff, Run, Task
from buzz.store import LocalBuzzStore


def test_local_store_persists_run_handoff_and_ordered_events(tmp_path):
    store = LocalBuzzStore(tmp_path)
    task = Task.new("Diagnose Osana readiness")
    run = Run(run_id="run-1", task_id=task.task_id)
    handoff = Handoff(
        handoff_id="handoff-1",
        task_id=task.task_id,
        from_profile="receptionist",
        to_profile="software-diagnostic-specialist",
        objective=task.objective,
        context_pack=ContextPack(task.task_id, ["fixture"], []),
    )

    store.save(task)
    store.save_run(run)
    store.save_handoff(handoff)
    store.append_event(Event.new("run.started", run.run_id, task_id=task.task_id))
    store.append_event(Event.new("task.triaged", run.run_id, task_id=task.task_id))

    assert store.get_run("run-1")["task_id"] == task.task_id
    assert [event["event_type"] for event in store.list_events("run-1")] == [
        "run.started",
        "task.triaged",
    ]
    first_line = (tmp_path / ".buzz" / "events.jsonl").read_text().splitlines()[0]
    assert json.loads(first_line)["run_id"] == "run-1"


def test_store_reopens_task_after_triage_fields_are_saved(tmp_path):
    store = LocalBuzzStore(tmp_path)
    task = Task.new("Diagnose readiness")
    task.source_refs = ["source:osana-map-snapshot"]
    store.save(task)

    reopened = store.get_task(task.task_id)
    assert reopened is not None
    assert reopened.source_refs == ["source:osana-map-snapshot"]
