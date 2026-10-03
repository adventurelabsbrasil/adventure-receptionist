"""Explicit read-only connectors for runtime/provenance inventory."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from typing import Any
from urllib import error, request
from urllib.parse import urlparse

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


class OllamaRuntimeInventoryConnector:
    """Read Ollama model metadata through one explicitly supplied HTTP endpoint."""

    connector_id = "ollama"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        runtime_id: str = "buzz-ollama-runtime",
        host_id: str | None = None,
        channel: str | None = None,
        transport: str | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not base_url.strip():
            raise RuntimeConnectorError("Ollama base URL is required")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeConnectorError("Ollama base URL must be an explicit HTTP(S) URL")
        if parsed.username or parsed.password:
            raise RuntimeConnectorError("Ollama base URL must not contain credentials")
        if not model.strip():
            raise RuntimeConnectorError("Ollama model is required")
        if not runtime_id.strip():
            raise RuntimeConnectorError("Ollama runtime_id must not be empty")
        if timeout_seconds <= 0:
            raise RuntimeConnectorError("timeout must be greater than zero")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.runtime_id = runtime_id
        self.host_id = host_id
        self.channel = channel
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    def read(self) -> dict[str, Any]:
        payload = self._get_json()
        models = payload.get("models")
        if not isinstance(models, list):
            raise RuntimeConnectorError("Ollama connector returned invalid models data")
        model_names = [
            item.get("name")
            for item in models
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ]
        model_available = self.model in model_names
        observed_at = datetime.now(timezone.utc).isoformat()
        model_source_id = "ollama-selected-model"
        model_limitations = [
            "the connector confirms model metadata only; it does not execute a generation",
            f"available_models={','.join(model_names)}",
        ]
        if not model_available:
            model_limitations.append("requested model was not present in the /api/tags response")
        host_limitations = [
            "host_id is explicit operator metadata; the Ollama endpoint does not prove SSH host identity",
        ]
        host_source_id = "ollama-host-metadata"
        channel_source_id = "ollama-channel-metadata"
        return normalize_inventory_report(
            {
                "product_id": "buzz",
                "mode": "live",
                "sources": [
                    {
                        "source_id": "ollama-tags",
                        "authority": "ollama",
                        "observed_at": observed_at,
                        "mode": "live",
                        "status": "available",
                        "limitations": [
                            "GET /api/tags only; no generation or write operation",
                            "the endpoint URL may be a local SSH tunnel",
                        ],
                    },
                    {
                        "source_id": model_source_id,
                        "authority": "ollama",
                        "observed_at": observed_at,
                        "mode": "live",
                        "status": "available" if model_available else "unavailable",
                        "limitations": model_limitations,
                    },
                    {
                        "source_id": host_source_id,
                        "authority": "operator_configuration",
                        "observed_at": observed_at if self.host_id else None,
                        "mode": "live",
                        "status": "available" if self.host_id else "unavailable",
                        "limitations": host_limitations if self.host_id else ["host_id was not supplied; endpoint response does not prove host identity"],
                    },
                    {
                        "source_id": channel_source_id,
                        "authority": "operator_configuration",
                        "observed_at": observed_at if self.channel and self.transport else None,
                        "mode": "live",
                        "status": "available" if self.channel and self.transport else "unavailable",
                        "limitations": ["channel and transport are explicit operator metadata"] if self.channel and self.transport else ["channel and transport were not supplied"],
                    },
                ],
                "assertions": [
                    {"subject_type": "runtime", "subject_id": self.runtime_id, "property": "provider", "value": "ollama", "source_id": "ollama-tags"},
                    {"subject_type": "runtime", "subject_id": self.runtime_id, "property": "model", "value": self.model, "source_id": model_source_id},
                    {"subject_type": "service", "subject_id": "ollama", "property": "endpoint_mode", "value": "remote", "source_id": "ollama-tags"},
                    {"subject_type": "host", "subject_id": self.host_id or "unconfirmed", "property": "identity", "value": self.host_id, "source_id": host_source_id},
                    {"subject_type": "channel", "subject_id": self.channel or "unconfirmed", "property": "transport", "value": self.transport, "source_id": channel_source_id},
                ],
                "trace": {
                    "runtime_id": self.runtime_id,
                    "host_id": self.host_id,
                    "channel": self.channel,
                    "transport": self.transport,
                },
            },
            source_selection={
                "type": "connector",
                "connector": self.connector_id,
                "base_url": self.base_url,
                "model": self.model,
                "fallback": "none",
            },
        )

    def _get_json(self) -> dict[str, Any]:
        http_request = request.Request(f"{self.base_url}/api/tags", method="GET")
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                value = json.loads(response.read().decode())
        except error.HTTPError as exc:
            raise RuntimeConnectorError(f"Ollama connector unavailable: HTTP {exc.code} ({exc.reason})") from exc
        except (OSError, error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeConnectorError(f"Ollama connector unavailable: {exc}") from exc
        if not isinstance(value, dict):
            raise RuntimeConnectorError("Ollama connector returned a non-object response")
        return value


def _validate_repository(repository: str) -> None:
    if repository.count("/") != 1 or any(not part for part in repository.split("/")):
        raise RuntimeConnectorError("GitHub repository must use the OWNER/REPOSITORY format")
