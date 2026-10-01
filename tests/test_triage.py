import json
from pathlib import Path

from buzz.models import Task
from buzz.triage import triage_osana


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
