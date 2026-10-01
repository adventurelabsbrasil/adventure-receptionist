from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ContextPack, Task
from .sources import PreflightBlocked, SourceRegistry


class GitHubReadError(RuntimeError):
    """Raised when a read-only GitHub operation cannot be completed safely."""


@dataclass(frozen=True)
class GitHubReadResult:
    repository: str
    mode: str
    items: list[dict[str, Any]] = field(default_factory=list)
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "mode": self.mode,
            "fetched_at": self.fetched_at,
            "items": self.items,
        }

    def to_document(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


class GitHubReadClient:
    """Read-only GitHub adapter using the user's authenticated gh CLI."""

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = timeout_seconds

    def read(
        self,
        repository: str,
        *,
        state: str = "open",
        snapshot_path: Path | None = None,
    ) -> GitHubReadResult:
        _validate_repository(repository)
        if state not in {"open", "closed", "all"}:
            raise GitHubReadError(f"Unsupported GitHub issue state: {state}")
        if snapshot_path is not None:
            return self._read_snapshot(repository, snapshot_path)

        self._run_gh(["auth", "status"])
        payload = self._run_gh([
            "api",
            f"repos/{repository}/issues",
            "--method",
            "GET",
            "--paginate",
            "-f",
            f"state={state}",
            "-f",
            "per_page=100",
        ])
        try:
            raw_items = _decode_paginated_json(payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GitHubReadError("GitHub read unavailable: invalid JSON response") from exc
        return GitHubReadResult(repository, "live", _normalize_items(raw_items))

    def read_context(
        self,
        task: Task,
        registry: SourceRegistry,
        source_ref: str,
        repository: str,
        *,
        state: str = "open",
        snapshot_path: Path | None = None,
    ) -> ContextPack:
        """Preflight the allowlisted source before adding GitHub data to context."""
        try:
            context = registry.preflight(task, [source_ref])
        except PreflightBlocked:
            raise
        if snapshot_path is not None and registry.workspace is not None:
            try:
                snapshot_path.resolve().relative_to(registry.workspace)
            except ValueError as exc:
                raise PreflightBlocked("GitHub snapshot is outside the manifest workspace") from exc
        result = self.read(repository, state=state, snapshot_path=snapshot_path)
        context.documents[context.source_ids[0]] = result.to_document()
        context.constraints.update({"source_mode": result.mode, "repository": repository, "external_writes": False})
        context.validate()
        return context

    def _run_gh(self, arguments: list[str]) -> str:
        try:
            completed = subprocess.run(
                ["gh", *arguments],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitHubReadError("GitHub read unavailable: gh CLI could not be reached") from exc
        if completed.returncode != 0:
            raise GitHubReadError("GitHub read unavailable: gh command failed")
        return completed.stdout

    def _read_snapshot(self, repository: str, path: Path) -> GitHubReadResult:
        try:
            data = json.loads(path.read_text())
            snapshot_repository = data.get("repository", repository) if isinstance(data, dict) else repository
            raw_items = data.get("items", []) if isinstance(data, dict) else data
            if snapshot_repository != repository:
                raise GitHubReadError("GitHub snapshot repository does not match requested repository")
            if not isinstance(raw_items, list):
                raise TypeError("items must be a list")
        except GitHubReadError:
            raise
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GitHubReadError(f"GitHub snapshot unavailable: {path}") from exc
        return GitHubReadResult(repository, "snapshot", _normalize_items(raw_items))


def _validate_repository(repository: str) -> None:
    if repository.count("/") != 1 or any(not part for part in repository.split("/")):
        raise GitHubReadError("GitHub repository must use the OWNER/REPOSITORY format")


def _decode_paginated_json(payload: str) -> list[dict[str, Any]]:
    decoded = json.loads(payload)
    if isinstance(decoded, list):
        return decoded
    if isinstance(decoded, dict) and isinstance(decoded.get("items"), list):
        return decoded["items"]
    raise TypeError("GitHub response must be a list")


def _normalize_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("html_url") or item.get("url") or "")
        number = item.get("number")
        kind = "pull_request" if item.get("pull_request") or "/pull/" in url else "issue"
        key = url or f"{kind}:{number}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            "kind": kind,
            "number": number,
            "title": str(item.get("title", "")),
            "state": str(item.get("state", "unknown")),
            "url": url,
            "labels": [label.get("name", str(label)) if isinstance(label, dict) else str(label) for label in item.get("labels", [])],
            "updated_at": item.get("updated_at"),
        })
    return normalized
