import json

from buzz.briefing import build_briefing, build_status
from buzz.cli import main
from buzz.models import ContextPack, Event, Handoff, Run, Task
from buzz.store import LocalBuzzStore


def _task(store, *, status="captured", source_refs=None, executor_profile=None):
    task = Task.new("Diagnose readiness")
    task.status = status
    task.source_refs = source_refs or []
    task.executor_profile = executor_profile
    store.save(task)
    return task


def test_status_groups_local_tasks_and_runs_without_writing(tmp_path):
    store = LocalBuzzStore(tmp_path)
    blocked = _task(store, status="blocked")
    _task(store, status="waiting")
    run = Run(run_id="run-blocked", task_id=blocked.task_id, status="failed")
    store.save_run(run)
    store.append_event(Event.new(
        "provider.failed",
        run.run_id,
        task_id=blocked.task_id,
        payload={"reason": "Ollama provider unavailable"},
    ))
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    report = build_status(store)

    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert report["counts"]["blocked"] == 1
    assert report["counts"]["waiting"] == 1
    assert report["runs"]["failed"] == 1
    assert blocked.task_id in {task["task_id"] for task in report["tasks"]}
    blocked_report = next(task for task in report["tasks"] if task["task_id"] == blocked.task_id)
    assert blocked_report["age_hours"] >= 0
    assert blocked_report["dependencies"] == []
    assert report["signals"]["blocked"] == 1
    assert report["signals"]["wip"] == 0
    assert after == before


def test_briefing_explains_blocked_and_pending_approval(tmp_path):
    store = LocalBuzzStore(tmp_path)
    blocked = _task(store, status="blocked")
    ready = _task(store, status="ready", executor_profile="software-diagnostic-specialist")
    run = Run(run_id="run-1", task_id=blocked.task_id, status="failed")
    store.save_run(run)
    store.append_event(Event.new(
        "source.preflight_blocked",
        run.run_id,
        task_id=blocked.task_id,
        payload={"reason": "Material sources are not decision-ready"},
    ))
    handoff = Handoff(
        handoff_id="handoff-1",
        task_id=ready.task_id,
        from_profile="receptionist",
        to_profile="software-diagnostic-specialist",
        objective=ready.objective,
        context_pack=ContextPack(ready.task_id, ["fixture"], ["local"], documents={"local": "snapshot"}),
    )
    store.save_handoff(handoff)

    report = build_briefing(store)

    assert [item["task_id"] for item in report["unblock"]] == [blocked.task_id]
    assert report["unblock"][0]["reason"] == "Material sources are not decision-ready"
    assert [item["task_id"] for item in report["must_do"]] == [ready.task_id]
    assert report["must_do"][0]["reason"] == "handoff_pending_approval"
    assert [item["task_id"] for item in report["delegate"]] == [ready.task_id]


def test_status_reports_stale_sources_from_explicit_manifests(tmp_path):
    store = LocalBuzzStore(tmp_path)
    task = _task(store, status="waiting", source_refs=["source:old-snapshot"])
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "project:\n"
        "  id: test\n"
        "sources:\n"
        "  - id: old-snapshot\n"
        "    type: snapshot\n"
        "    authority: test\n"
        "    status: stale\n"
        "    access: local_only\n"
    )

    report = build_status(store, manifests=[manifest])

    assert report["stale"][0]["task_id"] == task.task_id
    assert report["stale"][0]["source_ids"] == ["old-snapshot"]


def test_briefing_json_is_serializable(tmp_path):
    report = build_briefing(LocalBuzzStore(tmp_path))

    json.dumps(report)
    assert set(report) == {"must_do", "unblock", "delegate", "waiting", "watch", "counts"}


def test_status_and_briefing_commands_are_read_only(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr("sys.argv", ["buzz", "status"])
    main()
    status_output = json.loads(capsys.readouterr().out)

    monkeypatch.setattr("sys.argv", ["buzz", "briefing"])
    main()
    briefing_output = json.loads(capsys.readouterr().out)

    assert status_output["counts"] == {}
    assert briefing_output["must_do"] == []
    assert list(tmp_path.rglob("*")) == []
