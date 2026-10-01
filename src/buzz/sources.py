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

    @classmethod
    def from_manifest(cls, path: Path) -> "SourceRegistry":
        data = _parse_manifest(path)
        sources = {}
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
        return cls(
            project=data.get("project", {}),
            context_policy=data.get("context_policy", "explicit_allowlist"),
            sources=sources,
            external_writes=data.get("external_writes", False),
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

        material = set(material_source_ids or source_ids)
        blocked = [
            source_id
            for source_id in material
            if source_id not in self.sources
            or self.sources[source_id].status in {"stale", "deprecated", "partial", "unavailable"}
        ]
        if blocked:
            raise PreflightBlocked(f"Material sources are not decision-ready: {', '.join(sorted(blocked))}")

        return ContextPack(
            task_id=task.task_id,
            context_refs=context_refs,
            source_ids=source_ids,
            constraints={"external_writes": self.external_writes},
        )

    def summary(self) -> list[dict[str, Any]]:
        return [
            {
                "source_id": source.source_id,
                "type": source.source_type,
                "authority": source.authority,
                "status": source.status,
                "access": source.access,
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
    for raw_line in path.read_text().splitlines():
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
            elif section == "project":
                data["project"][key] = _scalar(value)
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
