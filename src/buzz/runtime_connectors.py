"""Explicit read-only connectors for runtime/provenance inventory."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from typing import Any

from .runtime_inventory import normalize_inventory_report


class RuntimeConnectorError(RuntimeError):
    """Raised when a selected live connector cannot complete its read."""


class GitHubRuntimeInventoryConnector:
    """Read repository and workflow metadata through the authenticated gh CLI."""

    connector_id = "github"

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        if timeout_seconds <= 0:
            raise RuntimeConnectorError("timeout must be greater than zero")
        self.timeout_seconds = timeout_seconds

    def read(self, repository: str) -> dict[str, Any]:
        _validate_repository(repository)
        self._run_gh(["auth", "status"])
        repo = self._get_json(["api", f"repos/{repository}", "--method", "GET"])
        runs = self._get_json(["api", f"repos/{repository}/actions/runs", "--method", "GET", "-f", "per_page=1"])
        observed_at = datetime.now(timezone.utc).isoformat()
        workflow_runs = runs.get("workflow_runs", []) if isinstance(runs, dict) else []
        latest_run = workflow_runs[0] if isinstance(workflow_runs, list) and workflow_runs else None
        return normalize_inventory_report(
            {
                "product_id": repository,
                "mode": "live",
                "sources": [
                    {
                        "source_id": "github-repository",
                        "authority": "github",
                        "observed_at": observed_at,
                        "mode": "live",
                        "status": "available",
                        "limitations": ["GitHub metadata does not prove a deployment is serving traffic"],
                    },
                    {
                        "source_id": "github-runtime-signal",
                        "authority": "github",
                        "observed_at": observed_at,
                        "mode": "live",
                        "status": "unavailable",
                        "limitations": [
                            "A workflow run is not proof of a live runtime or ingress channel",
                            "latest_workflow_run_present=" + str(bool(latest_run)).lower(),
                        ],
                    },
                ],
                "assertions": [
                    {"subject_type": "product", "subject_id": repository, "property": "repository", "value": repo.get("html_url"), "source_id": "github-repository"},
                    {"subject_type": "runtime", "subject_id": repository, "property": "state", "value": "unavailable", "source_id": "github-runtime-signal"},
                    {"subject_type": "host", "subject_id": repository, "property": "identity", "value": None, "source_id": "github-runtime-signal"},
                    {"subject_type": "channel", "subject_id": repository, "property": "transport", "value": None, "source_id": "github-runtime-signal"},
                ],
                "trace": {"runtime_id": None, "host_id": None, "channel": None, "transport": None},
            },
            source_selection={"type": "connector", "connector": self.connector_id, "repository": repository, "fallback": "none"},
        )

    def _get_json(self, arguments: list[str]) -> dict[str, Any]:
        payload = self._run_gh(arguments)
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeConnectorError("GitHub connector returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise RuntimeConnectorError("GitHub connector returned a non-object response")
        return value

    def _run_gh(self, arguments: list[str]) -> str:
        try:
            completed = subprocess.run(
                ["gh", *arguments], capture_output=True, text=True,
                timeout=self.timeout_seconds, check=False, shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeConnectorError("GitHub connector unavailable: gh CLI timeout or launch failure") from exc
        if completed.returncode != 0:
            raise RuntimeConnectorError("GitHub connector unavailable: gh command failed")
        return completed.stdout


def _validate_repository(repository: str) -> None:
    if repository.count("/") != 1 or any(not part for part in repository.split("/")):
        raise RuntimeConnectorError("GitHub repository must use the OWNER/REPOSITORY format")
