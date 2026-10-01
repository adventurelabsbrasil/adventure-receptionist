from pathlib import Path

import pytest

from buzz.models import Task
from buzz.sources import PreflightBlocked, SourceRegistry


def test_manifest_registry_reads_project_and_sources():
    registry = SourceRegistry.from_manifest(Path(__file__).parents[1] / "examples/osana/manifest.yaml")
    assert registry.project["id"] == "osana"
    assert registry.sources["osana-map-snapshot"].status == "snapshot"
    assert registry.external_writes is False


def test_preflight_returns_only_allowlisted_sources():
    registry = SourceRegistry.from_manifest(Path(__file__).parents[1] / "examples/osana/manifest.yaml")
    context = registry.preflight(
        Task.new("Diagnose readiness"),
        ["project:osana", "source:osana-map-snapshot", "engagement:salvador-autocenter-pilot"],
    )
    assert context.source_ids == ["osana-map-snapshot", "salvador-autocenter-pilot"]
    assert context.constraints == {"external_writes": False}


def test_preflight_blocks_unknown_source():
    registry = SourceRegistry.from_manifest(Path(__file__).parents[1] / "examples/osana/manifest.yaml")
    with pytest.raises(PreflightBlocked, match="outside manifest allowlist"):
        registry.preflight(Task.new("Diagnose readiness"), ["source:not-in-manifest"])


def test_preflight_blocks_material_stale_source(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "profile: test\n"
        "context_policy: explicit_allowlist\n"
        "sources:\n"
        "  - id: old-map\n"
        "    type: snapshot\n"
        "    authority: product_map\n"
        "    status: stale\n"
        "    access: local_only\n"
    )
    registry = SourceRegistry.from_manifest(manifest)
    with pytest.raises(PreflightBlocked, match="not decision-ready"):
        registry.preflight(Task.new("Diagnose readiness"), ["source:old-map"])
