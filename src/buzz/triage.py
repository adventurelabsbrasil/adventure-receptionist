from __future__ import annotations

from .models import Task, TriageResult


def triage_osana(task: Task, fixture: dict) -> TriageResult:
    """Deterministic MVP triage; an LLM adapter will replace classification later."""
    return TriageResult(
        task_id=task.task_id,
        classification_status="provisional",
        project_id="osana",
        entity_type="product",
        client_relation="client_engagement",
        complexity="high",
        executor_profile="software-diagnostic-specialist",
        autonomy_level="propose",
        context_refs=fixture["context_refs"],
        findings=[
            "The task requires the Osana product MAP and active repository metadata.",
            "The real-world Salvador Autocenter pilot is a separate engagement context.",
            "External writes and live authentication are out of scope for this run.",
        ],
        next_actions=[
            "Review the MAP snapshot and identify missing readiness criteria.",
            "Prepare a diagnostic handoff for human review.",
            "Confirm the acceptance criteria for the Salvador Autocenter pilot.",
        ],
        material_uncertainties=[
            "The fixture is not a live GitHub read and may be stale.",
            "The current active repository list must be confirmed before execution.",
        ],
    )
