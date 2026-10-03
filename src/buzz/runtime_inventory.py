"""Local-only runtime and provenance inventory.

The adapter deliberately reads one explicit JSON snapshot.  It never probes a
host, opens a socket, authenticates, or selects another source when a source
is unavailable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INVENTORY_TYPES = {"product", "agent", "runtime", "host", "service", "database", "dependency", "channel", "transport"}
SOURCE_MODES = {"live", "snapshot"}
SOURCE_STATES = {"available", "stale", "unavailable"}


class InventoryError(ValueError):
    """Raised when a local inventory snapshot is malformed or unsafe."""


@dataclass(frozen=True)
class Provenance:
    source_id: str
    authority: str
    observed_at: str | None
    mode: str
    limitations: list[str]


@dataclass(frozen=True)
class InventoryAssertion:
    subject_type: str
    subject_id: str
    property: str
    value: Any
    status: str
    provenance: Provenance


def build_inventory_report(path: Path) -> dict[str, Any]:
    """Read and normalize one explicit, sanitized local snapshot."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryError(f"Cannot read inventory snapshot: {path}") from exc
    if not isinstance(raw, dict):
        raise InventoryError("Inventory snapshot must be a JSON object")

    product_id = raw.get("product_id")
    if not isinstance(product_id, str) or not product_id.strip():
        raise InventoryError("Inventory snapshot requires product_id")
    sources = _normalize_sources(raw.get("sources"))
    source_map = {source["source_id"]: source for source in sources}
    assertions: list[InventoryAssertion] = []
    for item in raw.get("assertions", []):
        if not isinstance(item, dict):
            raise InventoryError("Each inventory assertion must be an object")
        subject_type = item.get("subject_type")
        if subject_type not in INVENTORY_TYPES:
            raise InventoryError(f"Unknown inventory subject type: {subject_type}")
        source_id = item.get("source_id")
        if source_id not in source_map:
            raise InventoryError(f"Assertion references unknown source: {source_id}")
        source = source_map[source_id]
        assertions.append(InventoryAssertion(
            subject_type=subject_type,
            subject_id=_required(item, "subject_id"),
            property=_required(item, "property"),
            value=item.get("value"),
            status=source["status"],
            provenance=Provenance(
                source_id=source_id,
                authority=source["authority"],
                observed_at=source.get("observed_at"),
                mode=source["mode"],
                limitations=source["limitations"],
            ),
        ))

    trace = raw.get("trace", {})
    if not isinstance(trace, dict):
        raise InventoryError("trace must be an object")
    return {
        "schema_version": raw.get("schema_version", "runtime-inventory.v1"),
        "product_id": product_id,
        "mode": "snapshot",
        "sources": sources,
        "assertions": [asdict(assertion) for assertion in assertions],
        "trace": {
            "runtime_id": trace.get("runtime_id"),
            "host_id": trace.get("host_id"),
            "channel": trace.get("channel"),
            "transport": trace.get("transport"),
        },
        "external_effects": False,
        "source_selection": {"type": "explicit", "path": str(path.resolve()), "fallback": "none"},
    }


def _normalize_sources(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise InventoryError("Inventory snapshot requires at least one source")
    result = []
    for raw in value:
        if not isinstance(raw, dict):
            raise InventoryError("Each inventory source must be an object")
        source_id = _required(raw, "source_id")
        mode = raw.get("mode")
        if mode not in SOURCE_MODES:
            raise InventoryError(f"Source {source_id} has invalid mode: {mode}")
        status = raw.get("status")
        if status not in SOURCE_STATES:
            raise InventoryError(f"Source {source_id} has invalid status: {status}")
        limitations = raw.get("limitations", [])
        if not isinstance(limitations, list):
            raise InventoryError(f"Source {source_id} limitations must be a list")
        result.append({
            "source_id": source_id,
            "authority": _required(raw, "authority"),
            "observed_at": raw.get("observed_at"),
            "mode": mode,
            "status": status,
            "limitations": [str(item) for item in limitations],
        })
    return result


def _required(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InventoryError(f"Inventory object requires {key}")
    return value
