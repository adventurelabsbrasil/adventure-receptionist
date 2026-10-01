import json
from pathlib import Path

import pytest

from buzz.evals import EvalError, evaluate_fixture, evaluate_paths
from buzz.providers import DeterministicProvider


ROOT = Path(__file__).parents[1]


def test_evaluate_paths_runs_both_official_buzz_cases_without_persistence():
    reports = evaluate_paths([
        ROOT / "evals/osana/diagnose-readiness.json",
        ROOT / "evals/liara/diagnose-readiness.json",
    ])

    assert [report.fixture_name for report in reports] == [
        "osana-diagnose-readiness",
        "liara-diagnose-readiness",
    ]
    assert all(report.passed for report in reports)
    assert reports[0].checks["classification"] is True
    assert reports[1].checks["context"] is True
    assert reports[1].provider == "deterministic"


def test_evaluate_fixture_reports_expected_contract_and_handoff():
    fixture_path = ROOT / "evals/liara/diagnose-readiness.json"
    report = evaluate_fixture(fixture_path, DeterministicProvider())

    assert report.passed is True
    assert report.checks == {
        "classification": True,
        "context": True,
        "provider": True,
        "handoff": True,
    }
    assert report.source_ids == [
        "liara-canon-snapshot",
        "liara-runtime-snapshot",
        "liara-data-model-snapshot",
    ]
    assert report.document_ids == report.source_ids


def test_evaluate_fixture_rejects_mismatched_expectation(tmp_path):
    fixture = json.loads((ROOT / "evals/osana/diagnose-readiness.json").read_text())
    fixture["expected"]["entity_type"] = "agent"
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture))

    report = evaluate_fixture(fixture_path, DeterministicProvider())

    assert report.passed is False
    assert report.checks["classification"] is False
    assert any("entity_type" in failure for failure in report.failures)


def test_evaluate_fixture_surfaces_preflight_errors():
    fixture_path = ROOT / "evals/liara/diagnose-readiness.json"

    class BrokenProvider:
        def complete(self, _request):
            raise AssertionError("provider should not be called after preflight failure")

    with pytest.raises(EvalError, match="preflight"):
        evaluate_fixture(fixture_path, BrokenProvider(), manifest=ROOT / "examples/osana/manifest.yaml")
