from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .briefing import build_briefing, build_status
from .approval_service import ApprovalConversationService
from .conversation import (
    ConversationInput,
    LocalConversationTransport,
    TelegramDryRunTransport,
    build_approval_prompt,
)
from .diagnostics import build_diagnostic_report
from .runtime_inventory import InventoryError, build_inventory_report
from .runtime_connectors import GitHubRuntimeInventoryConnector, RuntimeConnectorError
from .execution import ExecutionConfirmationService
from .evals import EvalError, evaluate_fixture, evaluate_paths
from .executors import ExecutorError, ExecutorRegistry
from .github import GitHubReadClient, GitHubReadError
from .models import Approval, Event, Run, Task, now_iso, transition_task
from .providers import ProviderContractError, ProviderRouter, ProviderUnavailable, provider_config, provider_inventory
from .store import LocalBuzzStore
from .sources import PreflightBlocked, SourceRegistry
from .triage import handoff_from_triage, synthesize_triage, triage_fixture


def _conversation_transport(name: str):
    if name == "telegram-dry-run":
        return TelegramDryRunTransport()
    return LocalConversationTransport()


def _approval_run_id(store: LocalBuzzStore, task_id: str) -> str:
    run = next((item for item in store.list_runs() if item["task_id"] == task_id), None)
    return run["run_id"] if run else f"run-approval-{task_id.removeprefix('task-')}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="buzz", description="Adventure Agent Orchestration Control Plane")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="initialize a Buzz workspace")
    init.add_argument("--scope", choices=["project", "global", "both"], default="project")

    sub.add_parser("doctor", help="check local runtime capabilities")
    sub.add_parser("providers", help="show local model provider capabilities")
    sub.add_parser("executors", help="show local executor profiles")
    github = sub.add_parser("github-read", help="read GitHub issues and pull requests without writing")
    github.add_argument("--repo", required=True, help="GitHub repository in OWNER/REPOSITORY format")
    github.add_argument("--state", choices=["open", "closed", "all"], default="open")
    github.add_argument("--snapshot", type=Path, help="read a local GitHub snapshot instead of gh")
    github.add_argument("--manifest", type=Path, help="manifest that allowlists the context source")
    github.add_argument("--source", dest="source_ref", help="allowlisted source reference")
    status = sub.add_parser("status", help="show local task state")
    status.add_argument("--manifest", type=Path, action="append", help="local manifest to inspect")
    blocked = sub.add_parser("blocked", help="show blocked tasks and failed runs")
    blocked.add_argument("--manifest", type=Path, action="append", help="local manifest to inspect")
    stale = sub.add_parser("stale", help="show tasks using non-ready sources")
    stale.add_argument("--manifest", type=Path, action="append", help="local manifest to inspect")
    approvals = sub.add_parser("pending-approvals", help="show handoffs awaiting approval")
    approvals.add_argument("--manifest", type=Path, action="append", help="local manifest to inspect")
    for decision in ("approve", "reject"):
        decision_parser = sub.add_parser(decision, help=f"{decision} a local handoff proposal")
        decision_parser.add_argument("task_id")
        decision_parser.add_argument("--by", required=True, dest="decided_by", help="human reviewer identity")
        decision_parser.add_argument("--reason", help="optional review note")
    confirm = sub.add_parser("confirm-execution", help="record a human confirmation without executing an action")
    confirm.add_argument("task_id")
    confirm.add_argument("--by", required=True, dest="actor_id", help="human confirming the execution")
    confirm.add_argument("--idempotency-key", default=None)
    briefing = sub.add_parser("briefing", help="show a local operational briefing")
    briefing.add_argument("--manifest", type=Path, action="append", help="local manifest to inspect")

    sources = sub.add_parser("sources", help="show configured source status")
    sources.add_argument("--manifest", type=Path, default=Path("examples/osana/manifest.yaml"))

    preflight = sub.add_parser("preflight", help="validate task context against a manifest")
    preflight.add_argument("task_id")
    preflight.add_argument("--manifest", type=Path, default=Path("examples/osana/manifest.yaml"))

    handoff = sub.add_parser("handoff", help="show the task handoff")
    handoff.add_argument("task_id")

    review = sub.add_parser("review", help="show a read-only human review packet")
    review.add_argument("task_id")

    prompt = sub.add_parser("prompt", help="show a conversational approval prompt")
    prompt.add_argument("task_id")
    prompt.add_argument("--json", action="store_true", dest="as_json", help="emit the transport-neutral prompt as JSON")
    prompt.add_argument("--transport", choices=["local-dry-run", "telegram-dry-run"], default="local-dry-run")
    prompt.add_argument("--conversation-id", default=None)

    response = sub.add_parser("respond", help="simulate a conversational approval response locally")
    response.add_argument("task_id")
    response.add_argument("--by", required=True, dest="decided_by", help="human reviewer identity")
    response_input = response.add_mutually_exclusive_group(required=True)
    response_input.add_argument("--option", choices=["1", "2", "3"], help="prompt option key")
    response_input.add_argument("--text", help="free-text response")
    response.add_argument("--transport", choices=["local-dry-run", "telegram-dry-run"], default="local-dry-run")
    response.add_argument("--conversation-id", default=None)
    response.add_argument("--idempotency-key", default=None)

    diagnose = sub.add_parser("diagnose", help="build a read-only readiness report from an approved handoff")
    diagnose.add_argument("task_id")

    inventory = sub.add_parser("inventory", help="show runtime/provenance inventory")
    inventory_input = inventory.add_mutually_exclusive_group(required=True)
    inventory_input.add_argument("--fixture", type=Path, help="explicit local JSON inventory snapshot")
    inventory_input.add_argument("--connector", choices=["github"], help="explicit live read-only connector")
    inventory.add_argument("--repo", help="OWNER/REPOSITORY for the GitHub connector")
    inventory.add_argument("--timeout", type=float, default=20.0, help="live connector timeout in seconds")

    run = sub.add_parser("run", help="inspect a local Buzz run")
    run.add_argument("run_id", help="run identifier")
    run.add_argument("--trace", action="store_true", help="include ordered events")

    intake = sub.add_parser("intake", help="capture a task")
    intake.add_argument("--text", required=True, help="natural-language objective")

    triage = sub.add_parser("triage", help="run a local project triage fixture")
    triage.add_argument("--fixture", type=Path, required=True)
    triage.add_argument("--manifest", type=Path, help="manifest for the fixture project")
    triage.add_argument("--provider", choices=["deterministic", "ollama"], help="provider override")

    evaluation = sub.add_parser("eval", help="evaluate Buzz fixtures without persisting state")
    evaluation.add_argument("--fixture", type=Path, action="append", help="fixture to evaluate; defaults to Osana and Liara")
    evaluation.add_argument("--manifest", type=Path, help="manifest for a single fixture")
    evaluation.add_argument("--provider", choices=["deterministic", "ollama"], help="provider override")
    return parser


def main() -> None:
    args = _parser().parse_args()
    root = Path.cwd()

    if args.command == "init":
        buzz_dir = root / ".buzz"
        buzz_dir.mkdir(exist_ok=True)
        (buzz_dir / "manifest.yaml").write_text(
            "profile: adventure\ncontext_policy: explicit_allowlist\nlanguage: pt-BR\n"
        )
        print(f"Initialized {args.scope} Buzz workspace at {buzz_dir}")
        return

    if args.command == "doctor":
        print(json.dumps({
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "python_supported": sys.version_info >= (3, 11),
            "local_storage": "available",
            "github": "not_checked",
            "external_writes": False,
        }, indent=2))
        return

    if args.command == "providers":
        print(json.dumps(provider_inventory(), indent=2, ensure_ascii=False))
        return

    if args.command == "executors":
        print(json.dumps(ExecutorRegistry.default().summary(), indent=2, ensure_ascii=False))
        return

    if args.command == "github-read":
        if bool(args.manifest) != bool(args.source_ref):
            print(json.dumps({"error": "--manifest and --source must be provided together"}, ensure_ascii=False), file=sys.stderr)
            raise SystemExit(2)
        try:
            client = GitHubReadClient()
            if args.manifest:
                registry = SourceRegistry.from_manifest(args.manifest)
                context = client.read_context(
                    Task.new(f"Read GitHub context for {args.repo}"),
                    registry,
                    args.source_ref,
                    args.repo,
                    state=args.state,
                    snapshot_path=args.snapshot,
                )
                output = {"mode": context.constraints["source_mode"], "context_pack": context.__dict__}
            else:
                output = client.read(args.repo, state=args.state, snapshot_path=args.snapshot).to_dict()
        except (GitHubReadError, PreflightBlocked, ValueError) as error:
            print(json.dumps({"error": str(error)}, indent=2, ensure_ascii=False), file=sys.stderr)
            raise SystemExit(2)
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    if args.command == "eval":
        fixture_paths = args.fixture or [
            root / "evals/osana/diagnose-readiness.json",
            root / "evals/liara/diagnose-readiness.json",
        ]
        if args.manifest and len(fixture_paths) != 1:
            print(json.dumps({"error": "--manifest requires exactly one --fixture"}, ensure_ascii=False), file=sys.stderr)
            raise SystemExit(2)
        provider = None
        if args.provider:
            manifest_path = args.manifest or root / "examples" / json.loads(fixture_paths[0].read_text())["project_id"] / "manifest.yaml"
            registry = SourceRegistry.from_manifest(manifest_path)
            provider = ProviderRouter(provider_config(registry.provider)).select(args.provider)
        try:
            if args.manifest:
                reports = [evaluate_fixture(fixture_paths[0], provider, manifest=args.manifest)]
            else:
                reports = evaluate_paths(fixture_paths, provider)
        except EvalError as error:
            print(json.dumps({"error": str(error)}, indent=2, ensure_ascii=False), file=sys.stderr)
            raise SystemExit(2)
        output = {"passed": all(report.passed for report in reports), "reports": [report.to_dict() for report in reports]}
        print(json.dumps(output, indent=2, ensure_ascii=False))
        if not output["passed"]:
            raise SystemExit(1)
        return

    if args.command == "inventory":
        try:
            if args.fixture:
                if args.repo:
                    raise InventoryError("--repo is only valid with --connector github")
                report = build_inventory_report(args.fixture)
            else:
                if not args.repo:
                    raise InventoryError("--repo is required with --connector github")
                report = GitHubRuntimeInventoryConnector(timeout_seconds=args.timeout).read(args.repo)
            print(json.dumps(report, indent=2, ensure_ascii=False))
        except (InventoryError, RuntimeConnectorError) as error:
            print(json.dumps({"error": str(error)}, indent=2, ensure_ascii=False), file=sys.stderr)
            raise SystemExit(2)
        return

    read_only = args.command in {"status", "blocked", "stale", "pending-approvals", "briefing", "github-read", "review", "prompt", "diagnose"}
    store = LocalBuzzStore(root, create=not read_only)

    if args.command == "sources":
        registry = SourceRegistry.from_manifest(args.manifest)
        print(json.dumps({"project": registry.project, "sources": registry.summary()}, indent=2, ensure_ascii=False))
        return

    if args.command == "intake":
        task = Task.new(args.text)
        run = Run(run_id=f"run-{task.task_id.removeprefix('task-')}", task_id=task.task_id)
        store.save(task)
        store.save_run(run)
        store.append_event(Event.new("task.captured", run.run_id, task_id=task.task_id, payload={"objective": task.objective}))
        print(json.dumps({"task_id": task.task_id, "status": task.status, "objective": task.objective}, indent=2, ensure_ascii=False))
        return

    if args.command == "triage":
        fixture = json.loads(args.fixture.read_text())
        task = Task.new(fixture["input"])
        run = Run(run_id=f"run-{task.task_id.removeprefix('task-')}", task_id=task.task_id)
        store.save(task)
        store.save_run(run)
        store.append_event(Event.new("task.captured", run.run_id, task_id=task.task_id, payload={"objective": task.objective}))
        result = triage_fixture(task, fixture)
        manifest = args.manifest or Path(f"examples/{result.project_id}/manifest.yaml")
        registry = SourceRegistry.from_manifest(manifest)
        try:
            context_pack = registry.preflight(task, result.context_refs)
        except PreflightBlocked as error:
            run.status = "failed"
            run.validation_result = "blocked_preflight"
            run.finished_at = now_iso()
            store.save_run(run)
            store.append_event(Event.new("source.preflight_blocked", run.run_id, task_id=task.task_id, payload={"reason": str(error)}))
            print(json.dumps({"error": str(error), "task_id": task.task_id}, indent=2, ensure_ascii=False), file=sys.stderr)
            raise SystemExit(2)
        run.source_snapshot_ids = context_pack.source_ids
        config = provider_config(registry.provider if hasattr(registry, "provider") else None)
        router = ProviderRouter(config)
        try:
            selected_provider = router.select(args.provider)
            result, telemetry = synthesize_triage(
                result,
                context_pack,
                selected_provider,
                objective=task.objective,
                max_output_tokens=config.max_output_tokens,
            )
        except (ProviderContractError, ProviderUnavailable) as error:
            run.status = "failed"
            run.provider = args.provider or config.name
            run.model = config.model or ("llama3.2" if (args.provider or config.name) == "ollama" else "rules-v1")
            run.validation_result = "failed"
            run.finished_at = now_iso()
            store.save_run(run)
            store.append_event(Event.new(
                "provider.failed",
                run.run_id,
                task_id=task.task_id,
                payload={
                    "provider": run.provider,
                    "model": run.model,
                    "input_tokens": run.input_tokens,
                    "output_tokens": run.output_tokens,
                    "latency_ms": run.latency_ms,
                    "source_ids": run.source_snapshot_ids,
                    "validation_result": run.validation_result,
                    "reason": str(error),
                },
            ))
            print(json.dumps({"error": str(error), "task_id": task.task_id}, indent=2, ensure_ascii=False), file=sys.stderr)
            raise SystemExit(2)
        run.provider = telemetry["provider"]
        run.model = telemetry["model"]
        run.input_tokens = telemetry["input_tokens"]
        run.output_tokens = telemetry["output_tokens"]
        run.latency_ms = telemetry["latency_ms"]
        run.validation_result = telemetry["validation_result"]
        run.status = "completed"
        run.finished_at = now_iso()
        store.save_run(run)
        store.append_event(Event.new("provider.completed", run.run_id, task_id=task.task_id, payload={**telemetry, "source_ids": context_pack.source_ids}))
        try:
            handoff = handoff_from_triage(task, result, context_pack)
        except ExecutorError as error:
            run.status = "failed"
            run.validation_result = "executor_invalid"
            run.finished_at = now_iso()
            store.save_run(run)
            store.append_event(Event.new(
                "handoff.rejected",
                run.run_id,
                task_id=task.task_id,
                payload={
                    "executor_profile": result.executor_profile,
                    "autonomy_level": result.autonomy_level,
                    "approval_required": True,
                    "source_ids": context_pack.source_ids,
                    "validation_result": run.validation_result,
                    "reason": str(error),
                },
            ))
            print(json.dumps({"error": str(error), "task_id": task.task_id}, indent=2, ensure_ascii=False), file=sys.stderr)
            raise SystemExit(2)
        store.save_handoff(handoff)
        approval = None
        if handoff.approval_required:
            approval = Approval(
                approval_id=f"approval-{task.task_id.removeprefix('task-')}",
                task_id=task.task_id,
                handoff_id=handoff.handoff_id,
            )
            store.save_approval(approval)
        task.project_id = result.project_id
        task.entity_type = result.entity_type
        task.client_relation = result.client_relation
        task.complexity = result.complexity
        task.executor_profile = result.executor_profile
        task.autonomy_level = result.autonomy_level
        task.source_refs = result.context_refs
        task.unknowns = result.material_uncertainties
        transition_task(task, "triage")
        transition_task(task, "ready")
        transition_task(task, "in_progress")
        transition_task(task, "in_review")
        store.save(task)
        store.append_event(Event.new("source.preflight", run.run_id, task_id=task.task_id, payload={"source_ids": context_pack.source_ids}))
        store.append_event(Event.new("task.triaged", run.run_id, task_id=task.task_id, payload=result.to_dict()))
        store.append_event(Event.new(
            "handoff.created",
            run.run_id,
            task_id=task.task_id,
            payload={
                "handoff_id": handoff.handoff_id,
                "to_profile": handoff.to_profile,
                "autonomy_level": handoff.autonomy_level,
                "approval_required": handoff.approval_required,
            },
        ))
        if approval is not None:
            store.append_event(Event.new(
                "approval.requested",
                run.run_id,
                task_id=task.task_id,
                payload={"approval_id": approval.approval_id, "handoff_id": handoff.handoff_id},
            ))
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command in {"approve", "reject"}:
        task = store.get_task(args.task_id)
        if task is None:
            print(json.dumps({"error": f"Task not found: {args.task_id}"}, indent=2), file=sys.stderr)
            raise SystemExit(1)
        approval_data = store.get_pending_approval(args.task_id)
        if approval_data is None:
            print(json.dumps({"error": f"Pending approval not found for task: {args.task_id}"}, indent=2), file=sys.stderr)
            raise SystemExit(1)
        approval = store.get_approval(approval_data["approval_id"])
        assert approval is not None
        decision = "approved" if args.command == "approve" else "rejected"
        try:
            approval.decide(decision, decided_by=args.decided_by, reason=args.reason)
            next_status = "approved" if decision == "approved" else "in_progress"
            transition_task(task, next_status)
        except ValueError as error:
            print(json.dumps({"error": str(error), "task_id": args.task_id}, indent=2), file=sys.stderr)
            raise SystemExit(2)
        store.save_approval(approval)
        store.save(task)
        run = next((item for item in store.list_runs() if item["task_id"] == task.task_id), None)
        run_id = run["run_id"] if run else f"run-approval-{task.task_id.removeprefix('task-')}"
        store.append_event(Event.new(
            f"approval.{decision}",
            run_id,
            task_id=task.task_id,
            payload={
                "approval_id": approval.approval_id,
                "handoff_id": approval.handoff_id,
                "decided_by": approval.decided_by,
                "reason": approval.reason,
            },
        ))
        print(json.dumps({"task_id": task.task_id, "approval": approval.__dict__, "status": task.status}, indent=2, ensure_ascii=False))
        return

    if args.command == "confirm-execution":
        task = store.get_task(args.task_id)
        approval_data = next((item for item in store.list_approvals() if item["task_id"] == args.task_id), None)
        if task is None:
            print(json.dumps({"error": f"Task not found: {args.task_id}"}, indent=2), file=sys.stderr)
            raise SystemExit(1)
        if approval_data is None:
            print(json.dumps({"error": f"Approval not found for task: {args.task_id}"}, indent=2), file=sys.stderr)
            raise SystemExit(1)
        approval = store.get_approval(approval_data["approval_id"])
        assert approval is not None
        try:
            confirmation = ExecutionConfirmationService(store).confirm(
                task,
                approval,
                actor_id=args.actor_id,
                run_id=_approval_run_id(store, task.task_id),
                idempotency_key=args.idempotency_key,
            )
        except ValueError as error:
            print(json.dumps({"error": str(error), "task_id": args.task_id}, indent=2), file=sys.stderr)
            raise SystemExit(2)
        print(json.dumps(confirmation.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command == "preflight":
        task = store.get_task(args.task_id)
        if task is None:
            print(json.dumps({"error": f"Task not found: {args.task_id}"}, indent=2), file=sys.stderr)
            raise SystemExit(1)
        registry = SourceRegistry.from_manifest(args.manifest)
        try:
            context = registry.preflight(task, task.source_refs)
        except PreflightBlocked as error:
            print(json.dumps({"task_id": task.task_id, "blocked": True, "reason": str(error)}, indent=2, ensure_ascii=False))
            raise SystemExit(2)
        print(json.dumps({"task_id": task.task_id, "blocked": False, "context_pack": context.__dict__}, indent=2, ensure_ascii=False))
        return

    if args.command == "handoff":
        handoff = store.get_handoff(args.task_id)
        if handoff is None:
            print(json.dumps({"error": f"Handoff not found for task: {args.task_id}"}, indent=2), file=sys.stderr)
            raise SystemExit(1)
        print(json.dumps(handoff, indent=2, ensure_ascii=False))
        return

    if args.command == "review":
        task = store.get_task(args.task_id)
        if task is None:
            print(json.dumps({"error": f"Task not found: {args.task_id}"}, indent=2), file=sys.stderr)
            raise SystemExit(1)
        handoff = store.get_handoff(args.task_id)
        if handoff is None:
            print(json.dumps({"error": f"Handoff not found for task: {args.task_id}"}, indent=2), file=sys.stderr)
            raise SystemExit(1)
        approval = next(
            (item for item in store.list_approvals() if item["task_id"] == args.task_id),
            None,
        )
        run = next(
            (item for item in store.list_runs() if item["task_id"] == args.task_id),
            None,
        )
        trace = store.list_events(run["run_id"]) if run else []
        prompt = build_approval_prompt(asdict(task), handoff, approval) if approval else None
        print(json.dumps({
            "task": asdict(task),
            "handoff": handoff,
            "approval": approval,
            "run": run,
            "trace": trace,
            "conversation": prompt.to_dict() if prompt else None,
            "review": {
                "decision_required": bool(approval and approval["status"] == "pending"),
                "external_effects": False,
                "context_refs": task.source_refs,
                "material_uncertainties": task.unknowns,
                "next_actions": handoff["next_actions"],
            },
        }, indent=2, ensure_ascii=False))
        return

    if args.command == "prompt":
        task = store.get_task(args.task_id)
        handoff = store.get_handoff(args.task_id)
        approval = next((item for item in store.list_approvals() if item["task_id"] == args.task_id), None)
        if task is None or handoff is None or approval is None:
            print(json.dumps({"error": f"Approval context not found for task: {args.task_id}"}, indent=2), file=sys.stderr)
            raise SystemExit(1)
        service = ApprovalConversationService(store, _conversation_transport(args.transport))
        rendered = service.render(
            task,
            handoff,
            approval,
            conversation_id=args.conversation_id or f"conversation-{task.task_id}",
        )
        if args.as_json:
            print(json.dumps(rendered.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(rendered.text)
        return

    if args.command == "respond":
        task = store.get_task(args.task_id)
        approval_data = store.get_pending_approval(args.task_id)
        handoff = store.get_handoff(args.task_id)
        approval_data = approval_data or next(
            (item for item in store.list_approvals() if item["task_id"] == args.task_id),
            None,
        )
        if task is None or approval_data is None or handoff is None:
            print(json.dumps({"error": f"Pending approval context not found for task: {args.task_id}"}, indent=2), file=sys.stderr)
            raise SystemExit(1)
        approval = store.get_approval(approval_data["approval_id"])
        assert approval is not None
        transport = _conversation_transport(args.transport)
        conversation_id = args.conversation_id or f"conversation-{task.task_id}"
        envelope = ConversationInput(
            conversation_id=conversation_id,
            channel=transport.channel,
            transport=transport.name,
            actor_id=args.decided_by,
            task_id=task.task_id,
            approval_id=approval.approval_id,
            idempotency_key=args.idempotency_key or f"{conversation_id}:{approval.approval_id}:{args.option or args.text}",
            text=args.text,
            option_key=args.option,
        )
        service = ApprovalConversationService(store, transport)
        try:
            response, decision_recorded = service.respond(
                task,
                handoff,
                approval,
                envelope,
                run_id=_approval_run_id(store, task.task_id),
            )
        except ValueError as error:
            print(json.dumps({"error": str(error), "task_id": args.task_id}, indent=2), file=sys.stderr)
            raise SystemExit(2)
        if not decision_recorded:
            print(json.dumps({
                "task_id": task.task_id,
                "response": response.__dict__,
                "decision_recorded": False,
                "approval": approval.__dict__,
                "message": "A aprovação continua pendente; esclareça ou ajuste a proposta." if approval.status == "pending" else "A aprovação já foi decidida; nenhuma nova decisão foi registrada.",
            }, indent=2, ensure_ascii=False))
            return
        print(json.dumps({"task_id": task.task_id, "response": response.__dict__, "approval": approval.__dict__, "status": task.status}, indent=2, ensure_ascii=False))
        return

    if args.command == "diagnose":
        task = store.get_task(args.task_id)
        if task is None:
            print(json.dumps({"error": f"Task not found: {args.task_id}"}, indent=2), file=sys.stderr)
            raise SystemExit(1)
        handoff = store.get_handoff(args.task_id)
        if handoff is None:
            print(json.dumps({"error": f"Handoff not found for task: {args.task_id}"}, indent=2), file=sys.stderr)
            raise SystemExit(1)
        approval = next(
            (item for item in store.list_approvals() if item["task_id"] == args.task_id),
            None,
        )
        if approval is None or approval["status"] != "approved":
            print(json.dumps({
                "error": "Diagnostic requires an approved handoff",
                "task_id": args.task_id,
            }, indent=2), file=sys.stderr)
            raise SystemExit(2)
        print(json.dumps(build_diagnostic_report(asdict(task), handoff), indent=2, ensure_ascii=False))
        return

    if args.command == "run":
        run = store.get_run(args.run_id)
        if run is None:
            print(json.dumps({"error": f"Run not found: {args.run_id}"}, indent=2), file=sys.stderr)
            raise SystemExit(1)
        output = {"run": run}
        if args.trace:
            output["events"] = store.list_events(args.run_id)
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    if args.command in {"status", "blocked", "stale", "pending-approvals", "briefing"}:
        manifests = args.manifest if hasattr(args, "manifest") and args.manifest else sorted((root / "examples").glob("*/manifest.yaml"))
        if args.command == "status":
            output = build_status(store, manifests=manifests)
        elif args.command == "blocked":
            output = {"blocked": build_briefing(store, manifests=manifests)["unblock"]}
        elif args.command == "stale":
            output = {"stale": build_status(store, manifests=manifests)["stale"]}
        elif args.command == "pending-approvals":
            output = {"pending_approvals": build_briefing(store, manifests=manifests)["must_do"]}
        else:
            output = build_briefing(store, manifests=manifests)
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    _parser().print_help()
