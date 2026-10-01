from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .sources import SourceRegistry
from .store import LocalBuzzStore


STALE_SOURCE_STATUSES = {"stale", "deprecated", "partial", "unavailable"}


def build_status(
    store: LocalBuzzStore,
    *,
    manifests: Iterable[Path] | None = None,
) -> dict[str, Any]:
    """Build a read-only operational snapshot from local Buzz state."""
    tasks = store.list()
    runs = store.list_runs()
    handoffs = store.list_handoffs()
    events = store.list_events()
    reasons = _latest_reasons(events)
    source_statuses = _source_statuses(manifests or [])

    stale = []
    for task in tasks:
        source_ids = [ref.removeprefix("source:") for ref in task.get("source_refs", []) if ref.startswith("source:")]
        stale_ids = [source_id for source_id in source_ids if source_statuses.get(source_id) in STALE_SOURCE_STATUSES]
        if stale_ids:
            stale.append({
                "task_id": task["task_id"],
                "project_id": task.get("project_id"),
                "source_ids": stale_ids,
                "reason": "source_not_decision_ready",
            })

    return {
        "tasks": [
            {
                **task,
                "age_hours": _age_hours(task.get("created_at")),
                "dependencies": task.get("source_refs", []) + task.get("unknowns", []),
                **({"reason": reasons[task["task_id"]]} if task["task_id"] in reasons else {}),
            }
            for task in tasks
        ],
        "runs": dict(Counter(run["status"] for run in runs)),
        "handoffs": len(handoffs),
        "stale": stale,
        "counts": dict(Counter(task["status"] for task in tasks)),
        "signals": {
            "wip": sum(task["status"] in {"in_progress", "in_review"} for task in tasks),
            "waiting": sum(task["status"] == "waiting" for task in tasks),
            "blocked": sum(task["status"] == "blocked" for task in tasks),
            "stale": len(stale),
            "oldest_task_age_hours": max((_age_hours(task.get("created_at")) for task in tasks), default=0),
        },
    }


def build_briefing(
    store: LocalBuzzStore,
    *,
    manifests: Iterable[Path] | None = None,
) -> dict[str, Any]:
    """Explain the next local operational actions without mutating state."""
    status = build_status(store, manifests=manifests)
    tasks = status["tasks"]
    task_by_id = {task["task_id"]: task for task in tasks}
    handoffs = store.list_handoffs()
    pending_approval_ids = {
        handoff["task_id"]
        for handoff in handoffs
        if handoff.get("approval_required", True)
        and task_by_id.get(handoff["task_id"], {}).get("status") not in {"approved", "completed", "archived"}
    }

    unblock: list[dict[str, Any]] = []
    for task in tasks:
        if task["status"] == "blocked":
            unblock.append({
                "task_id": task["task_id"],
                "reason": task.get("reason", "task_blocked"),
            })
    for run in store.list_runs():
        if run["status"] == "failed" and run["task_id"] not in {item["task_id"] for item in unblock}:
            task = task_by_id.get(run["task_id"], {})
            unblock.append({
                "task_id": run["task_id"],
                "reason": task.get("reason", "run_failed"),
            })

    must_do = [
        {"task_id": task["task_id"], "reason": "handoff_pending_approval"}
        for task in tasks
        if task["task_id"] in pending_approval_ids
    ]
    delegate = [
        {"task_id": task["task_id"], "to_profile": task["executor_profile"]}
        for task in tasks
        if task["status"] == "ready" and task.get("executor_profile")
    ]
    waiting = [
        {"task_id": task["task_id"], "reason": "task_waiting"}
        for task in tasks
        if task["status"] == "waiting"
    ]
    accounted = {item["task_id"] for item in unblock + must_do + delegate + waiting}
    watch = [
        {"task_id": task["task_id"], "status": task["status"]}
        for task in tasks
        if task["task_id"] not in accounted and task["status"] not in {"archived", "completed"}
    ]

    return {
        "must_do": must_do,
        "unblock": unblock,
        "delegate": delegate,
        "waiting": waiting,
        "watch": watch,
        "counts": status["counts"],
    }


def _latest_reasons(events: list[dict[str, Any]]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for event in events:
        if event.get("event_type") in {"source.preflight_blocked", "provider.failed"} and event.get("task_id"):
            reason = event.get("payload", {}).get("reason")
            if reason:
                reasons[event["task_id"]] = reason
    return reasons


def _source_statuses(manifests: Iterable[Path]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for manifest in manifests:
        registry = SourceRegistry.from_manifest(Path(manifest))
        statuses.update({source_id: source.status for source_id, source in registry.sources.items()})
    return statuses


def _age_hours(created_at: str | None) -> int:
    if not created_at:
        return 0
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return 0
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - created).total_seconds() // 3600))
