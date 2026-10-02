import json
from dataclasses import replace
from pathlib import Path

from buzz.models import Task
import pytest

from buzz.providers import DeterministicProvider, ModelResponse, ProviderContractError
from buzz.executors import ExecutorError
from buzz.sources import SourceRegistry
from buzz.triage import handoff_from_triage, synthesize_triage, triage_fixture, triage_osana


def test_osana_fixture_produces_scoped_handoff():
    fixture_path = Path(__file__).parents[1] / "evals/osana/diagnose-readiness.json"
    fixture = json.loads(fixture_path.read_text())
    result = triage_osana(Task.new(fixture["input"]), fixture)

    assert result.project_id == "osana"
    assert result.entity_type == "product"
    assert result.complexity == "high"
    assert result.executor_profile == "software-diagnostic-specialist"
    assert result.autonomy_level == "propose"
    assert result.context_refs == fixture["context_refs"]
    assert result.material_uncertainties


def test_liara_fixture_separates_internal_agent_from_product_project():
    fixture_path = Path(__file__).parents[1] / "evals/liara/diagnose-readiness.json"
    fixture = json.loads(fixture_path.read_text())
    result = triage_fixture(Task.new(fixture["input"]), fixture)

    assert result.project_id == "liara"
    assert result.entity_type == "agent"
    assert result.client_relation == "internal"
    assert result.complexity == "high"
    assert result.executor_profile == "software-diagnostic-specialist"
    assert result.autonomy_level == "propose"
    assert result.context_refs == fixture["context_refs"]
    assert result.material_uncertainties


def test_triage_synthesis_receives_only_context_pack_documents():
    root = Path(__file__).parents[1]
    fixture = json.loads((root / "evals/liara/diagnose-readiness.json").read_text())
    result = triage_fixture(Task.new(fixture["input"]), fixture)
    registry = SourceRegistry.from_manifest(root / "examples/liara/manifest.yaml")
    pack = registry.preflight(Task.new("same task"), ["source:liara-canon-snapshot"])

    synthesized, telemetry = synthesize_triage(result, pack, DeterministicProvider())

    assert synthesized.project_id == "liara"
    assert telemetry["validation_result"] == "valid"
    assert set(pack.documents) == {"liara-canon-snapshot"}


def test_invalid_provider_synthesis_blocks_handoff():
    class InvalidProvider:
        def complete(self, _request):
            return ModelResponse("fake", "test", {"findings": []})

    root = Path(__file__).parents[1]
    fixture = json.loads((root / "evals/liara/diagnose-readiness.json").read_text())
    result = triage_fixture(Task.new(fixture["input"]), fixture)
    pack = SourceRegistry.from_manifest(root / "examples/liara/manifest.yaml").preflight(
        Task.new("same task"), ["source:liara-canon-snapshot"]
    )

    with pytest.raises(ProviderContractError, match="exactly findings"):
        synthesize_triage(result, pack, InvalidProvider())


def test_handoff_validates_executor_registry_and_requires_human_approval():
    root = Path(__file__).parents[1]
    fixture = json.loads((root / "evals/osana/diagnose-readiness.json").read_text())
    task = Task.new(fixture["input"])
    result = triage_osana(task, fixture)
    pack = SourceRegistry.from_manifest(root / "examples/osana/manifest.yaml").preflight(
        task, result.context_refs
    )

    handoff = handoff_from_triage(task, result, pack)

    assert handoff.to_profile == "software-diagnostic-specialist"
    assert handoff.autonomy_level == "propose"
    assert handoff.approval_required is True

    with pytest.raises(ExecutorError, match="Unknown executor profile"):
        handoff_from_triage(task, replace(result, executor_profile="not-real"), pack)
