from pathlib import Path

import pytest

from buzz.models import Task
from buzz.sources import PreflightBlocked, SourceRegistry


def test_manifest_registry_reads_project_and_sources():
    root = Path(__file__).parents[1]
    registry = SourceRegistry.from_manifest(root / "examples/osana/manifest.yaml")
    assert registry.project["id"] == "osana"
    assert registry.sources["osana-map-snapshot"].status == "snapshot"
    assert registry.source_paths["osana-map-snapshot"] == (
        root / "examples/osana/snapshots/github.json"
    ).resolve()
    assert registry.external_writes is False


def test_osana_snapshot_declares_limited_repository_coverage():
    root = Path(__file__).parents[1]
    registry = SourceRegistry.from_manifest(root / "examples/osana/manifest.yaml")
    context = registry.preflight(Task.new("Diagnose Osana"), ["source:osana-map-snapshot"])

    assert '"project_id": "osana"' in context.documents["osana-map-snapshot"]
    assert '"provisional": true' in context.documents["osana-map-snapshot"]
    document = context.documents["osana-map-snapshot"]
    assert '"coverage": "multi_repository_inventory"' in document
    assert '"adventurelabsbrasil/adventure-labs"' in document
    assert '"adventurelabsbrasil/ssot"' in document
    assert '"adventurelabsbrasil/buzz"' in document
    assert "produto Buzz, não contexto da Osana" in document


def test_manifest_registry_reads_internal_liara_project():
    registry = SourceRegistry.from_manifest(Path(__file__).parents[1] / "examples/liara/manifest.yaml")

    assert registry.project == {
        "id": "liara",
        "type": "product",
        "ownership": "adventure",
        "lifecycle": "active",
        "purpose": "internal_marketing_operations",
    }
    assert registry.sources["liara-canon-snapshot"].status == "snapshot"
    assert registry.sources["liara-runtime-snapshot"].status == "snapshot"
    assert registry.external_writes is False
    assert registry.provider == {
        "name": "deterministic",
        "model": "rules-v1",
        "timeout_seconds": "10",
        "max_output_tokens": "1200",
    }


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


def test_liara_snapshot_documents_are_loaded_only_when_selected():
    root = Path(__file__).parents[1]
    registry = SourceRegistry.from_manifest(root / "examples/liara/manifest.yaml")
    context = registry.preflight(Task.new("Diagnose Liara"), ["source:liara-canon-snapshot"])

    assert set(context.documents) == {"liara-canon-snapshot"}
    assert "Identidade e ownership" in context.documents["liara-canon-snapshot"]


def test_snapshot_path_outside_manifest_workspace_is_blocked(tmp_path):
    outside = tmp_path.parent / "outside.md"
    outside.write_text("not permitted")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "project:\n  id: test\n"
        "sources:\n  - id: outside\n    type: snapshot\n"
        "    authority: test\n    status: snapshot\n    access: local_only\n"
        f"    path: {outside}\n"
    )
    with pytest.raises(PreflightBlocked, match="outside the manifest workspace"):
        SourceRegistry.from_manifest(manifest)
