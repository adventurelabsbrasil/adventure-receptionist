from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import Task
from .providers import DeterministicProvider, ModelProvider, ProviderContractError
from .sources import PreflightBlocked, SourceRegistry
from .triage import handoff_from_triage, synthesize_triage, triage_fixture


class EvalError(ValueError):
    """Raised when an evaluation cannot execute its configured pipeline."""


@dataclass
class EvalReport:
    fixture_name: str
    project_id: str
    passed: bool
    checks: dict[str, bool]
    provider: str | None = None
    model: str | None = None
    source_ids: list[str] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalComparison:
    fixture_name: str
    candidates: dict[str, dict[str, Any]]
    disagreements: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(candidate["passed"] for candidate in self.candidates.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_name": self.fixture_name,
            "passed": self.passed,
            "candidates": self.candidates,
            "disagreements": self.disagreements,
        }


def evaluate_fixture(
    fixture_path: Path,
    provider: ModelProvider | None = None,
    *,
    manifest: Path | None = None,
) -> EvalReport:
    fixture = json.loads(fixture_path.read_text())
    project_id = fixture.get("project_id", "unknown")
    fixture_name = fixture.get("name", fixture_path.stem)
    selected_provider = provider or DeterministicProvider()
    task = Task.new(fixture["input"])
    registry_path = manifest or Path.cwd() / "examples" / project_id / "manifest.yaml"

    try:
        result = triage_fixture(task, fixture)
        registry = SourceRegistry.from_manifest(registry_path)
        context_pack = registry.preflight(task, result.context_refs)
    except (KeyError, ValueError, OSError) as error:
        raise EvalError(f"preflight: {error}") from error

    try:
        result, telemetry = synthesize_triage(
            result,
            context_pack,
            selected_provider,
            objective=task.objective,
            max_output_tokens=1200,
        )
    except (ProviderContractError, RuntimeError, ValueError) as error:
        raise EvalError(f"provider: {error}") from error

    checks: dict[str, bool] = {}
    failures: list[str] = []
    expected = fixture.get("expected", {})
    expected_fields = (
        "project_id",
        "entity_type",
        "client_relation",
        "complexity",
        "executor_profile",
        "autonomy_level",
    )
    mismatches = [
        f"{field} expected {expected[field]!r}, got {getattr(result, field)!r}"
        for field in expected_fields
        if field in expected and getattr(result, field) != expected[field]
    ]
    if "material_uncertainties" in expected:
        expected_uncertainties = bool(expected["material_uncertainties"])
        if bool(result.material_uncertainties) != expected_uncertainties:
            mismatches.append(
                "material_uncertainties expected "
                f"{expected_uncertainties!r}, got {bool(result.material_uncertainties)!r}"
            )
    checks["classification"] = not mismatches
    failures.extend(mismatches)

    expected_source_ids = [
        reference.removeprefix("source:").removeprefix("engagement:")
        for reference in result.context_refs
        if reference.startswith(("source:", "engagement:"))
    ]
    context_ok = context_pack.source_ids == expected_source_ids
    checks["context"] = context_ok
    if not context_ok:
        failures.append(
            f"context sources expected {expected_source_ids!r}, got {context_pack.source_ids!r}"
        )

    provider_ok = telemetry["validation_result"] == "valid"
    checks["provider"] = provider_ok
    if not provider_ok:
        failures.append(f"provider validation result was {telemetry['validation_result']!r}")

    handoff = handoff_from_triage(task, result, context_pack)
    try:
        handoff.validate()
        handoff_ok = True
    except ValueError as error:
        handoff_ok = False
        failures.append(f"handoff: {error}")
    checks["handoff"] = handoff_ok

    return EvalReport(
        fixture_name=fixture_name,
        project_id=project_id,
        passed=not failures,
        checks=checks,
        provider=str(telemetry["provider"]),
        model=str(telemetry["model"]),
        source_ids=context_pack.source_ids,
        document_ids=[source_id for source_id in context_pack.source_ids if source_id in context_pack.documents],
        failures=failures,
        result=result.to_dict(),
    )


def evaluate_paths(
    fixture_paths: list[Path],
    provider: ModelProvider | None = None,
    *,
    manifests: dict[str, Path] | None = None,
) -> list[EvalReport]:
    reports = []
    for fixture_path in fixture_paths:
        project_id = json.loads(fixture_path.read_text()).get("project_id", "")
        manifest = (manifests or {}).get(project_id)
        reports.append(evaluate_fixture(fixture_path, provider, manifest=manifest))
    return reports


def compare_fixture(
    fixture_path: Path,
    providers: dict[str, ModelProvider],
    *,
    manifest: Path | None = None,
) -> EvalComparison:
    """Run the same fixture against named providers and expose regressions explicitly."""
    reports = {
        name: evaluate_fixture(fixture_path, provider, manifest=manifest)
        for name, provider in providers.items()
    }
    if not reports:
        raise EvalError("comparison requires at least one provider")
    fields = ("classification", "context", "provider", "handoff")
    disagreements = [
        f"checks.{field} differs: "
        + repr({name: report.checks.get(field) for name, report in reports.items()})
        for field in fields
        if len({report.checks.get(field) for report in reports.values()}) > 1
    ]
    result_fields = (
        "project_id", "entity_type", "complexity", "executor_profile", "autonomy_level",
        "findings", "next_actions", "material_uncertainties",
    )
    for field in result_fields:
        values = {name: report.result.get(field) for name, report in reports.items()}
        normalized = {name: json.dumps(value, sort_keys=True, ensure_ascii=False) for name, value in values.items()}
        if len(set(normalized.values())) > 1:
            disagreements.append(f"result.{field} differs: {values!r}")
    return EvalComparison(
        fixture_name=next(iter(reports.values())).fixture_name,
        candidates={
            name: {
                "passed": report.passed,
                "provider": report.provider,
                "model": report.model,
                "checks": report.checks,
                "failures": report.failures,
            }
            for name, report in reports.items()
        },
        disagreements=disagreements,
    )
