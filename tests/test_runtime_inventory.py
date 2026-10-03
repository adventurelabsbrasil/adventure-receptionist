import json
from pathlib import Path

import pytest

from buzz.runtime_inventory import InventoryError, build_inventory_report


ROOT = Path(__file__).parents[1]


def test_osana_inventory_separates_contexts_and_preserves_unavailable_state():
    report = build_inventory_report(ROOT / "examples/osana/snapshots/runtime-inventory.json")

    assert report["product_id"] == "osana"
    assert report["trace"] == {
        "runtime_id": None,
        "host_id": None,
        "channel": "none_confirmed",
        "transport": None,
    }
    by_subject = {(item["subject_type"], item["property"]): item for item in report["assertions"]}
    assert by_subject[("service", "deploy")]["value"] == "Vercel demo panel"
    assert by_subject[("runtime", "state")]["status"] == "unavailable"
    assert by_subject[("runtime", "state")]["provenance"]["mode"] == "snapshot"
    assert report["source_selection"]["fallback"] == "none"


def test_stale_snapshot_is_explicitly_reported():
    report = build_inventory_report(ROOT / "examples/liara/snapshots/runtime-inventory.json")

    assert report["sources"][0]["status"] == "stale"
    assert all(item["status"] == "stale" for item in report["assertions"])
    assert report["assertions"][0]["provenance"]["limitations"]


def test_buzz_snapshot_preserves_ollama_xeon_provenance_without_live_inference():
    report = build_inventory_report(ROOT / "examples/buzz/snapshots/runtime-inventory.json")

    assert report["product_id"] == "buzz"
    assert report["trace"] == {
        "runtime_id": "buzz-ollama-runtime",
        "host_id": "xeon",
        "channel": "cli",
        "transport": "ssh-tunnel-http",
    }
    by_subject = {(item["subject_type"], item["property"]): item for item in report["assertions"]}
    assert by_subject[("runtime", "provider")]["value"] == "ollama"
    assert by_subject[("service", "endpoint_mode")]["value"] == "remote"
    assert by_subject[("runtime", "live_state")]["status"] == "unavailable"
    assert by_subject[("runtime", "live_state")]["provenance"]["mode"] == "live"


def test_inventory_rejects_assertion_without_declared_source(tmp_path):
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps({
        "product_id": "test",
        "sources": [{"source_id": "known", "authority": "test", "mode": "snapshot", "status": "available"}],
        "assertions": [{"subject_type": "host", "subject_id": "h", "property": "state", "source_id": "missing"}],
    }))

    with pytest.raises(InventoryError, match="unknown source"):
        build_inventory_report(path)
