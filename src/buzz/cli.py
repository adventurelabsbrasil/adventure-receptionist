from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .briefing import build_briefing, build_status
from .evals import EvalError, evaluate_fixture, evaluate_paths
from .github import GitHubReadClient, GitHubReadError
from .models import Event, Run, Task, now_iso
from .providers import ProviderContractError, ProviderRouter, ProviderUnavailable, provider_config, provider_inventory
from .store import LocalBuzzStore
from .sources import PreflightBlocked, SourceRegistry
from .triage import handoff_from_triage, synthesize_triage, triage_fixture


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="buzz", description="Adventure Agent Orchestration Control Plane")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="initialize a Buzz workspace")
    init.add_argument("--scope", choices=["project", "global", "both"], default="project")

    sub.add_parser("doctor", help="check local runtime capabilities")
    sub.add_parser("providers", help="show local model provider capabilities")
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
    briefing = sub.add_parser("briefing", help="show a local operational briefing")
    briefing.add_argument("--manifest", type=Path, action="append", help="local manifest to inspect")

    sources = sub.add_parser("sources", help="show configured source status")
    sources.add_argument("--manifest", type=Path, default=Path("examples/osana/manifest.yaml"))

    preflight = sub.add_parser("preflight", help="validate task context against a manifest")
    preflight.add_argument("task_id")
    preflight.add_argument("--manifest", type=Path, default=Path("examples/osana/manifest.yaml"))

    handoff = sub.add_parser("handoff", help="show the task handoff")
    handoff.add_argument("task_id")

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

    read_only = args.command in {"status", "blocked", "stale", "pending-approvals", "briefing", "github-read"}
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
            store.append_event(Event.new("provider.failed", run.run_id, task_id=task.task_id, payload={"reason": str(error)}))
            print(json.dumps({"error": str(error), "task_id": task.task_id}, indent=2, ensure_ascii=False), file=sys.stderr)
            raise SystemExit(2)
        run.provider = telemetry["provider"]
        run.model = telemetry["model"]
        run.input_tokens = telemetry["input_tokens"]
        run.output_tokens = telemetry["output_tokens"]
        run.latency_ms = telemetry["latency_ms"]
        run.source_snapshot_ids = context_pack.source_ids
        run.validation_result = telemetry["validation_result"]
        run.status = "completed"
        run.finished_at = now_iso()
        store.save_run(run)
        store.append_event(Event.new("provider.completed", run.run_id, task_id=task.task_id, payload={**telemetry, "source_ids": context_pack.source_ids}))
        handoff = handoff_from_triage(task, result, context_pack)
        store.save_handoff(handoff)
        task.project_id = result.project_id
        task.entity_type = result.entity_type
        task.client_relation = result.client_relation
        task.complexity = result.complexity
        task.executor_profile = result.executor_profile
        task.autonomy_level = result.autonomy_level
        task.source_refs = result.context_refs
        task.unknowns = result.material_uncertainties
        store.save(task)
        store.append_event(Event.new("source.preflight", run.run_id, task_id=task.task_id, payload={"source_ids": context_pack.source_ids}))
        store.append_event(Event.new("task.triaged", run.run_id, task_id=task.task_id, payload=result.to_dict()))
        store.append_event(Event.new("handoff.created", run.run_id, task_id=task.task_id, payload={"handoff_id": handoff.handoff_id, "to_profile": handoff.to_profile}))
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
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
