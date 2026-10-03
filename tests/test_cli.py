import json
import sys

import pytest

from buzz.cli import main
from buzz.providers import ModelResponse, ProviderContractError, ProviderUnavailable


def _workspace(tmp_path):
    (tmp_path / "examples" / "liara" / "snapshots").mkdir(parents=True)
    (tmp_path / "examples" / "liara" / "snapshots" / "canon.md").write_text("local canon")
    (tmp_path / "examples" / "liara" / "manifest.yaml").write_text(
        "project:\n  id: liara\n"
        "context_policy: explicit_allowlist\n"
        "sources:\n"
        "  - id: canon\n"
        "    type: snapshot\n"
        "    authority: test\n"
        "    status: snapshot\n"
        "    access: local_only\n"
        "    path: snapshots/canon.md\n"
        "external_writes: false\n"
    )
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({
        "project_id": "liara",
        "input": "diagnose readiness",
        "context_refs": ["source:canon"],
    }))
    return fixture, tmp_path / "examples" / "liara" / "manifest.yaml"


def test_triage_trace_records_provider_model_usage_sources_and_validation(tmp_path, monkeypatch, capsys):
    fixture, manifest = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["buzz", "triage", "--fixture", str(fixture), "--manifest", str(manifest)],
    )

    main()

    run = json.loads(next((tmp_path / ".buzz" / "runs").glob("*.json")).read_text())
    events = [json.loads(line) for line in (tmp_path / ".buzz" / "events.jsonl").read_text().splitlines()]
    provider_event = next(event for event in events if event["event_type"] == "provider.completed")
    handoff_event = next(event for event in events if event["event_type"] == "handoff.created")

    assert run["provider"] == "deterministic"
    assert run["model"] == "rules-v1"
    assert run["source_snapshot_ids"] == ["canon"]
    assert run["validation_result"] == "valid"
    assert {"input_tokens", "output_tokens", "latency_ms", "source_ids", "validation_result"} <= provider_event["payload"].keys()
    assert provider_event["payload"]["source_ids"] == ["canon"]
    assert handoff_event["payload"] == {
        "handoff_id": handoff_event["payload"]["handoff_id"],
        "to_profile": "software-diagnostic-specialist",
        "autonomy_level": "propose",
        "approval_required": True,
    }
    approval = json.loads(next((tmp_path / ".buzz" / "approvals").glob("*.json")).read_text())
    task = json.loads(next((tmp_path / ".buzz" / "tasks").glob("*.json")).read_text())
    assert approval["status"] == "pending"
    assert task["status"] == "in_review"
    assert any(event["event_type"] == "approval.requested" for event in events)


def test_human_can_approve_local_handoff_and_trace_decision(tmp_path, monkeypatch, capsys):
    fixture, manifest = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["buzz", "triage", "--fixture", str(fixture), "--manifest", str(manifest)])
    main()
    capsys.readouterr()

    task_id = json.loads(next((tmp_path / ".buzz" / "tasks").glob("*.json")).read_text())["task_id"]
    monkeypatch.setattr(sys, "argv", ["buzz", "approve", task_id, "--by", "rodrigo", "--reason", "reviewed locally"])
    main()

    output = json.loads(capsys.readouterr().out)
    assert output["approval"]["status"] == "approved"
    assert output["status"] == "approved"
    events = [json.loads(line) for line in (tmp_path / ".buzz" / "events.jsonl").read_text().splitlines()]
    assert any(event["event_type"] == "approval.approved" for event in events)


def test_human_can_confirm_execution_without_running_external_action(tmp_path, monkeypatch, capsys):
    fixture, manifest = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["buzz", "triage", "--fixture", str(fixture), "--manifest", str(manifest)])
    main()
    capsys.readouterr()

    task_id = json.loads(next((tmp_path / ".buzz" / "tasks").glob("*.json")).read_text())["task_id"]
    monkeypatch.setattr(sys, "argv", ["buzz", "approve", task_id, "--by", "rodrigo"])
    main()
    capsys.readouterr()

    monkeypatch.setattr(sys, "argv", ["buzz", "confirm-execution", task_id, "--by", "rodrigo", "--idempotency-key", "confirm-1"])
    main()
    output = json.loads(capsys.readouterr().out)

    assert output["status"] == "completed"
    assert output["execution_confirmed"] is True
    events = [json.loads(line) for line in (tmp_path / ".buzz" / "events.jsonl").read_text().splitlines()]
    confirmation = next(event for event in events if event["event_type"] == "execution.confirmed")
    assert confirmation["payload"]["confirmation_mode"] == "human_attestation"


def test_human_can_reject_local_handoff_without_external_effect(tmp_path, monkeypatch, capsys):
    fixture, manifest = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["buzz", "triage", "--fixture", str(fixture), "--manifest", str(manifest)])
    main()
    capsys.readouterr()

    task_id = json.loads(next((tmp_path / ".buzz" / "tasks").glob("*.json")).read_text())["task_id"]
    monkeypatch.setattr(sys, "argv", ["buzz", "reject", task_id, "--by", "rodrigo", "--reason", "needs more evidence"])
    main()

    output = json.loads(capsys.readouterr().out)
    assert output["approval"]["status"] == "rejected"
    assert output["status"] == "in_progress"


def test_review_command_builds_read_only_human_packet(tmp_path, monkeypatch, capsys):
    fixture, manifest = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["buzz", "triage", "--fixture", str(fixture), "--manifest", str(manifest)])
    main()
    capsys.readouterr()
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    task_id = json.loads(next((tmp_path / ".buzz" / "tasks").glob("*.json")).read_text())["task_id"]

    monkeypatch.setattr(sys, "argv", ["buzz", "review", task_id])
    main()

    packet = json.loads(capsys.readouterr().out)
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert packet["task"]["task_id"] == task_id
    assert packet["handoff"]["task_id"] == task_id
    assert packet["approval"]["status"] == "pending"
    assert packet["review"]["decision_required"] is True
    assert packet["review"]["external_effects"] is False
    assert packet["conversation"]["options"][0]["response_kind"] == "approve"
    assert packet["trace"]
    assert after == before


def test_diagnose_command_builds_snapshot_readiness_report_without_writing(tmp_path, monkeypatch, capsys):
    fixture, manifest = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["buzz", "triage", "--fixture", str(fixture), "--manifest", str(manifest)])
    main()
    capsys.readouterr()
    task_id = json.loads(next((tmp_path / ".buzz" / "tasks").glob("*.json")).read_text())["task_id"]
    monkeypatch.setattr(sys, "argv", ["buzz", "approve", task_id, "--by", "rodrigo"])
    main()
    capsys.readouterr()
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    monkeypatch.setattr(sys, "argv", ["buzz", "diagnose", task_id])
    main()

    report = json.loads(capsys.readouterr().out)
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert report["project_id"] == "liara"
    assert report["mode"] == "snapshot_unstructured"
    assert report["external_effects"] is False
    assert report["next_actions"]
    assert after == before


def test_prompt_renders_conversational_approval_and_respond_keeps_adjustment_pending(tmp_path, monkeypatch, capsys):
    fixture, manifest = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["buzz", "triage", "--fixture", str(fixture), "--manifest", str(manifest)])
    main()
    capsys.readouterr()
    task_id = json.loads(next((tmp_path / ".buzz" / "tasks").glob("*.json")).read_text())["task_id"]

    monkeypatch.setattr(sys, "argv", ["buzz", "prompt", task_id])
    main()
    prompt = capsys.readouterr().out
    assert "Escolha uma opção" in prompt
    assert "Ajustar" in prompt

    monkeypatch.setattr(sys, "argv", ["buzz", "respond", task_id, "--by", "rodrigo", "--text", "quero ajustar o escopo"])
    main()
    response = json.loads(capsys.readouterr().out)
    assert response["response"]["kind"] == "adjust"
    assert response["decision_recorded"] is False
    approval = json.loads(next((tmp_path / ".buzz" / "approvals").glob("*.json")).read_text())
    assert approval["status"] == "pending"


def test_conversational_approval_option_records_local_decision(tmp_path, monkeypatch, capsys):
    fixture, manifest = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["buzz", "triage", "--fixture", str(fixture), "--manifest", str(manifest)])
    main()
    capsys.readouterr()
    task_id = json.loads(next((tmp_path / ".buzz" / "tasks").glob("*.json")).read_text())["task_id"]

    monkeypatch.setattr(sys, "argv", ["buzz", "respond", task_id, "--by", "rodrigo", "--option", "1"])
    main()
    response = json.loads(capsys.readouterr().out)
    assert response["response"]["kind"] == "approve"
    assert response["approval"]["status"] == "approved"
    assert response["status"] == "approved"


def test_failed_provider_trace_keeps_standard_execution_metadata(tmp_path, monkeypatch):
    fixture, manifest = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["buzz", "triage", "--fixture", str(fixture), "--manifest", str(manifest)],
    )

    def fail_select(_self, _override=None):
        raise ProviderContractError("provider contract rejected")

    monkeypatch.setattr("buzz.cli.ProviderRouter.select", fail_select)
    with pytest.raises(SystemExit, match="2"):
        main()

    run = json.loads(next((tmp_path / ".buzz" / "runs").glob("*.json")).read_text())
    events = [json.loads(line) for line in (tmp_path / ".buzz" / "events.jsonl").read_text().splitlines()]
    failed_event = next(event for event in events if event["event_type"] == "provider.failed")

    assert run["provider"] == "deterministic"
    assert run["model"] == "rules-v1"
    assert run["source_snapshot_ids"] == ["canon"]
    assert run["validation_result"] == "failed"
    assert {"provider", "model", "input_tokens", "output_tokens", "latency_ms", "source_ids", "validation_result", "reason"} <= failed_event["payload"].keys()
    assert failed_event["payload"]["source_ids"] == ["canon"]


def test_providers_command_reports_deterministic_and_ollama_without_network(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["buzz", "providers"])

    main()

    providers = json.loads(capsys.readouterr().out)
    assert {provider["provider"] for provider in providers} == {"deterministic", "ollama", "api"}
    assert next(provider for provider in providers if provider["provider"] == "deterministic")["network"] is False


def test_inventory_ollama_connector_receives_explicit_runtime_metadata(monkeypatch, capsys):
    captured = {}

    class FakeOllamaConnector:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def read(self):
            return {"mode": "live", "trace": {"runtime_id": captured["runtime_id"], "host_id": captured["host_id"]}}

    monkeypatch.setattr("buzz.cli.OllamaRuntimeInventoryConnector", FakeOllamaConnector)
    monkeypatch.setattr(sys, "argv", [
        "buzz", "inventory", "--connector", "ollama",
        "--base-url", "http://127.0.0.1:11435", "--model", "llama3.2:3b",
        "--runtime-id", "buzz-ollama-runtime", "--host-id", "xeon",
        "--channel", "cli", "--transport", "ssh-tunnel-http",
    ])

    main()

    assert json.loads(capsys.readouterr().out)["trace"] == {
        "runtime_id": "buzz-ollama-runtime",
        "host_id": "xeon",
    }
    assert captured == {
        "base_url": "http://127.0.0.1:11435",
        "model": "llama3.2:3b",
        "runtime_id": "buzz-ollama-runtime",
        "host_id": "xeon",
        "channel": "cli",
        "transport": "ssh-tunnel-http",
        "timeout_seconds": 20.0,
    }


def test_executors_command_reports_local_catalog_without_network(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["buzz", "executors"])

    main()

    executors = json.loads(capsys.readouterr().out)
    assert [executor["executor_id"] for executor in executors] == [
        "receptionist",
        "software-diagnostic-specialist",
        "human-operator",
    ]
    specialist = executors[1]
    assert "diagnose-readiness" in specialist["capabilities"]
    assert specialist["requires_human_approval"] is True


def test_ollama_unavailable_fails_cli_without_fallback_or_handoff(tmp_path, monkeypatch, capsys):
    fixture, manifest = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["buzz", "triage", "--fixture", str(fixture), "--manifest", str(manifest), "--provider", "ollama"],
    )

    def unavailable(*_args, **_kwargs):
        raise ProviderUnavailable("Ollama provider unavailable at localhost:11434")

    monkeypatch.setattr("buzz.providers.request.urlopen", unavailable)
    with pytest.raises(SystemExit, match="2"):
        main()

    captured = capsys.readouterr()
    assert "Ollama provider unavailable" in captured.err
    assert not list((tmp_path / ".buzz" / "handoffs").glob("*.json"))
    run = json.loads(next((tmp_path / ".buzz" / "runs").glob("*.json")).read_text())
    assert run["provider"] == "ollama"
    assert run["model"] == "llama3.2"
    assert run["validation_result"] == "failed"


def test_invalid_provider_schema_fails_cli_without_handoff(tmp_path, monkeypatch):
    fixture, manifest = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["buzz", "triage", "--fixture", str(fixture), "--manifest", str(manifest)],
    )

    class InvalidProvider:
        def complete(self, _request):
            return ModelResponse("fake", "test-model", {"findings": []})

    monkeypatch.setattr("buzz.cli.ProviderRouter.select", lambda *_args, **_kwargs: InvalidProvider())
    with pytest.raises(SystemExit, match="2"):
        main()

    assert not list((tmp_path / ".buzz" / "handoffs").glob("*.json"))
    run = json.loads(next((tmp_path / ".buzz" / "runs").glob("*.json")).read_text())
    assert run["validation_result"] == "failed"
