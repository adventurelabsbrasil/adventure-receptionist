from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ContextPack, Source, Task


class PreflightBlocked(ValueError):
    """Raised when the requested context cannot be trusted for a material decision."""


@dataclass
class SourceRegistry:
    project: dict[str, Any]
    context_policy: str
    sources: dict[str, Source]
    external_writes: bool = False
    provider: dict[str, Any] | None = None
    workspace: Path | None = None
    source_paths: dict[str, Path] | None = None

    @classmethod
    def from_manifest(cls, path: Path) -> "SourceRegistry":
        data = _parse_manifest(path)
        sources = {}
        source_paths: dict[str, Path] = {}
        workspace = path.resolve().parent
        for raw in data.get("sources", []):
            source = Source(
                source_id=raw["id"],
                source_type=raw["type"],
                authority=raw["authority"],
                status=raw["status"],
                access=raw["access"],
            )
            source.validate()
            sources[source.source_id] = source
            if raw.get("path"):
                source_path = (workspace / str(raw["path"])).resolve()
                try:
                    source_path.relative_to(workspace)
                except ValueError as exc:
                    raise PreflightBlocked(
                        f"Source {source.source_id} is outside the manifest workspace"
                    ) from exc
                if not source_path.is_file():
                    raise PreflightBlocked(f"Source {source.source_id} file does not exist: {raw['path']}")
                source_paths[source.source_id] = source_path
        return cls(
            project=data.get("project", {}),
            context_policy=data.get("context_policy", "explicit_allowlist"),
            sources=sources,
            external_writes=data.get("external_writes", False),
            provider=data.get("provider"),
            workspace=workspace,
            source_paths=source_paths,
        )

    def preflight(
        self,
        task: Task,
        context_refs: list[str],
        *,
        material_source_ids: list[str] | None = None,
    ) -> ContextPack:
        if self.context_policy != "explicit_allowlist":
            raise PreflightBlocked(f"Unsupported context policy: {self.context_policy}")
        if not context_refs:
            raise PreflightBlocked("No explicit context references were provided")

        source_ids = [_source_id_from_ref(ref) for ref in context_refs if _source_id_from_ref(ref)]
        unknown = [source_id for source_id in source_ids if source_id not in self.sources]
        if unknown:
            raise PreflightBlocked(f"Sources outside manifest allowlist: {', '.join(unknown)}")

        blocked = [
            source_id
            for source_id in source_ids
            if source_id not in self.sources
            or self.sources[source_id].status in {"stale", "deprecated", "partial", "unavailable"}
        ]
        if blocked:
            raise PreflightBlocked(f"Material sources are not decision-ready: {', '.join(sorted(blocked))}")

        missing_paths = [source_id for source_id in source_ids if self.sources[source_id].source_id not in (self.source_paths or {})]
        if missing_paths and any(source_id.startswith("liara-") for source_id in missing_paths):
            raise PreflightBlocked(f"Sources lack an explicitly permitted snapshot path: {', '.join(missing_paths)}")

        documents = {
            source_id: path.read_text(encoding="utf-8")
            for source_id, path in (self.source_paths or {}).items()
            if source_id in source_ids
        }

        return ContextPack(
            task_id=task.task_id,
            context_refs=context_refs,
            source_ids=source_ids,
            constraints={"external_writes": self.external_writes},
            documents=documents,
        )

    def summary(self) -> list[dict[str, Any]]:
        return [
            {
                "source_id": source.source_id,
                "type": source.source_type,
                "authority": source.authority,
                "status": source.status,
                "access": source.access,
                **({"path": str((self.source_paths or {})[source.source_id])} if source.source_id in (self.source_paths or {}) else {}),
            }
            for source in self.sources.values()
        ]


def _source_id_from_ref(reference: str) -> str | None:
    if reference.startswith("source:"):
        return reference.removeprefix("source:")
    if reference.startswith("engagement:"):
        return reference.removeprefix("engagement:")
    return None


def _scalar(value: str) -> Any:
    if value == "true":
        return True
    if value == "false":
        return False
    return value.strip('"\'')


def _parse_manifest(path: Path) -> dict[str, Any]:
    """Parse the deliberately small manifest subset used by the local MVP."""
    data: dict[str, Any] = {"sources": []}
    current: dict[str, Any] | None = None
    section: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not raw_line.startswith((" ", "\t")) and not line.startswith("- "):
            current = None
            section = None
        if line.startswith("- "):
            if section != "sources":
                raise ValueError("Only sources may use list entries in the MVP manifest")
            current = {}
            data["sources"].append(current)
            line = line[2:].strip()
        if ":" not in line:
            raise ValueError(f"Invalid manifest line: {raw_line}")
        key, value = (part.strip() for part in line.split(":", 1))
        if value:
            if current is not None and section == "sources":
                current[key] = _scalar(value)
            elif section in {"project", "provider"}:
                data[section][key] = _scalar(value)
            elif section:
                data[section][key] = _scalar(value)
            else:
                data[key] = _scalar(value)
        else:
            section = key
            if section == "project":
                data["project"] = {}
            elif section != "sources":
                data[section] = {}
            current = None
    return data
