from __future__ import annotations

import json
from typing import Any


def build_diagnostic_report(task: dict[str, Any], handoff: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic, read-only readiness report from an approved handoff."""
    documents = handoff.get("context_pack", {}).get("documents", {})
    snapshot = _first_json_document(documents)
    if snapshot is None:
        return {
            "task_id": task["task_id"],
            "project_id": task.get("project_id"),
            "mode": "snapshot_unstructured",
            "readiness": {},
            "gaps": [],
            "open_questions": ["The selected context does not contain a structured JSON snapshot."],
            "next_actions": handoff.get("next_actions", []),
            "external_effects": False,
        }

    gates = snapshot.get("approval_gates", [])
    gaps = [
        {
            "id": gate.get("id"),
            "status": gate.get("status"),
            "description": gate.get("description"),
            "evidence_required": gate.get("status") != "complete",
        }
        for gate in gates
        if gate.get("status") != "complete"
    ]
    return {
        "task_id": task["task_id"],
        "project_id": task.get("project_id"),
        "mode": snapshot.get("mode", "snapshot"),
        "provisional": bool(snapshot.get("provisional", True)),
        "readiness": {
            "lifecycle": snapshot.get("state", {}).get("lifecycle"),
            "maturity": snapshot.get("state", {}).get("maturity"),
            "validated_surface": snapshot.get("state", {}).get("validated_surface"),
            "live_state_available": snapshot.get("state", {}).get("live_state_available", False),
        },
        "capabilities": snapshot.get("capabilities", []),
        "boundaries": snapshot.get("boundaries", []),
        "gaps": gaps,
        "open_questions": snapshot.get("open_questions", []),
        "source_note": snapshot.get("source_note"),
        "next_actions": handoff.get("next_actions", []),
        "external_effects": False,
    }


def _first_json_document(documents: dict[str, str]) -> dict[str, Any] | None:
    for document in documents.values():
        try:
            value = json.loads(document)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    return None
