import json
import sys

import pytest

from buzz.cli import main
from buzz.providers import ProviderContractError


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

    assert run["provider"] == "deterministic"
    assert run["model"] == "rules-v1"
    assert run["source_snapshot_ids"] == ["canon"]
    assert run["validation_result"] == "valid"
    assert {"input_tokens", "output_tokens", "latency_ms", "source_ids", "validation_result"} <= provider_event["payload"].keys()
    assert provider_event["payload"]["source_ids"] == ["canon"]


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
