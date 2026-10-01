from __future__ import annotations

from .models import ContextPack, Handoff, Task, TriageResult
from .providers import ModelProvider, ModelRequest, ProviderContractError


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


def triage_liara(task: Task, fixture: dict) -> TriageResult:
    """Deterministic Liara triage against local, sanitized source snapshots."""
    return TriageResult(
        task_id=task.task_id,
        classification_status="provisional",
        project_id="liara",
        entity_type="agent",
        client_relation="internal",
        complexity="high",
        executor_profile="software-diagnostic-specialist",
        autonomy_level="propose",
        context_refs=fixture["context_refs"],
        findings=[
            "Liara is an Adventure-internal marketing operations agent/product.",
            "The local canon describes Meta Ads and Google Ads read operations and gated write proposals.",
            "Runtime, database and platform state are represented by snapshots in this run; no live authentication is available.",
        ],
        next_actions=[
            "Compare the Liara canon with the local runtime and database schema snapshots.",
            "Separate active Liara 2.0 capabilities from legacy Liara 1.x behavior.",
            "Prepare a human-review handoff for the next readiness milestone.",
        ],
        material_uncertainties=[
            "The snapshots do not prove the current server, database or scheduler state.",
            "External platform credentials and live permissions were not checked.",
            "The next Liara 2.0 milestone must be confirmed against the current roadmap.",
        ],
    )


def triage_fixture(task: Task, fixture: dict) -> TriageResult:
    """Select project-specific triage while keeping the CLI pipeline generic."""
    triage_by_project = {"osana": triage_osana, "liara": triage_liara}
    project_id = fixture.get("project_id")
    if project_id not in triage_by_project:
        raise ValueError(f"Unsupported fixture project: {project_id}")
    return triage_by_project[project_id](task, fixture)


def synthesize_triage(
    result: TriageResult,
    context_pack: ContextPack,
    provider: ModelProvider,
    *,
    objective: str | None = None,
    max_output_tokens: int = 1200,
) -> tuple[TriageResult, dict[str, int | str]]:
    """Use the selected provider only for interpretation, never for policy/state."""
    response = provider.complete(ModelRequest(
        operation="triage_synthesis",
        input={
            "objective": objective or result.task_id,
            "provisional": {
                "findings": result.findings,
                "next_actions": result.next_actions,
                "material_uncertainties": result.material_uncertainties,
            },
            "classification": {
                "project_id": result.project_id,
                "entity_type": result.entity_type,
                "complexity": result.complexity,
            },
        },
        context_refs=context_pack.context_refs,
        context_documents=context_pack.documents,
        max_output_tokens=max_output_tokens,
    ))
    output = response.output
    required = {"findings", "next_actions", "material_uncertainties"}
    if set(output) != required or any(
        not isinstance(output[key], list) or not all(isinstance(item, str) for item in output[key])
        for key in required
    ):
        raise ProviderContractError(
            "triage_synthesis response must contain exactly findings, next_actions and material_uncertainties lists"
        )
    result.findings = output["findings"]
    result.next_actions = output["next_actions"]
    result.material_uncertainties = output["material_uncertainties"]
    return result, {
        "provider": response.provider,
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "latency_ms": response.latency_ms,
        "validation_result": "valid",
    }


def handoff_from_triage(task: Task, result: TriageResult, context_pack: ContextPack) -> Handoff:
    return Handoff(
        handoff_id=f"handoff-{task.task_id.removeprefix('task-')}",
        task_id=task.task_id,
        from_profile="receptionist",
        to_profile=result.executor_profile,
        objective=task.objective,
        context_pack=context_pack,
        next_actions=result.next_actions,
        autonomy_level=result.autonomy_level,
        approval_required=True,
    )
