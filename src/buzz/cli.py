from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .models import Event, Run, Task
from .store import LocalBuzzStore
from .triage import triage_osana


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="buzz", description="Adventure Agent Orchestration Control Plane")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="initialize a Buzz workspace")
    init.add_argument("--scope", choices=["project", "global", "both"], default="project")

    sub.add_parser("doctor", help="check local runtime capabilities")
    sub.add_parser("status", help="show local task state")
    sub.add_parser("briefing", help="show a local operational briefing")

    run = sub.add_parser("run", help="inspect a local Buzz run")
    run.add_argument("run_id", help="run identifier")
    run.add_argument("--trace", action="store_true", help="include ordered events")

    intake = sub.add_parser("intake", help="capture a task")
    intake.add_argument("--text", required=True, help="natural-language objective")

    triage = sub.add_parser("triage", help="run the local Osana triage fixture")
    triage.add_argument("--fixture", type=Path, required=True)
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

    store = LocalBuzzStore(root)

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
        run = Run(run_id=f"run-{task.task_id.removeprefix('task-')}", task_id=task.task_id, status="completed")
        store.save(task)
        store.save_run(run)
        store.append_event(Event.new("task.captured", run.run_id, task_id=task.task_id, payload={"objective": task.objective}))
        result = triage_osana(task, fixture)
        store.append_event(Event.new("task.triaged", run.run_id, task_id=task.task_id, payload=result.to_dict()))
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
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

    if args.command == "status":
        print(json.dumps(store.list(), indent=2, ensure_ascii=False))
        return

    if args.command == "briefing":
        tasks = store.list()
        print(json.dumps({"must_do": [], "unblock": [], "delegate": [], "waiting": [], "watch": tasks}, indent=2, ensure_ascii=False))
        return

    _parser().print_help()
