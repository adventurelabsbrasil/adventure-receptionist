from __future__ import annotations

import shutil
import json
import os
import time
from urllib import error, request
from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderContractError(ValueError):
    """Raised when a provider request or response violates the structured contract."""


@dataclass(frozen=True)
class ModelRequest:
    operation: str
    input: dict[str, Any]
    context_refs: list[str] = field(default_factory=list)
    context_documents: dict[str, str] = field(default_factory=dict)
    output_schema: str = "object"
    max_output_tokens: int = 1200

    def validate(self) -> None:
        if not self.operation.strip():
            raise ProviderContractError("ModelRequest requires operation")
        if self.output_schema != "object":
            raise ProviderContractError("Only object structured output is supported in the MVP")
        if self.max_output_tokens <= 0:
            raise ProviderContractError("max_output_tokens must be positive")


@dataclass(frozen=True)
class ModelResponse:
    provider: str
    model: str
    output: dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    retries: int = 0
    estimated_cost_usd: float = 0.0

    def validate(self) -> None:
        if not self.provider or not self.model:
            raise ProviderContractError("ModelResponse requires provider and model")
        if not isinstance(self.output, dict):
            raise ProviderContractError("ModelResponse output must be an object")


class ModelProvider(Protocol):
    """Small seam for any LLM provider; SDKs stay inside adapters."""

    name: str
    model: str

    def complete(self, request: ModelRequest) -> ModelResponse:
        ...


@dataclass(frozen=True)
class DeterministicProvider:
    """Always-available provider for contract tests and offline dry runs."""

    name: str = "deterministic"
    model: str = "rules-v1"

    def complete(self, request: ModelRequest) -> ModelResponse:
        request.validate()
        if request.operation == "triage_synthesis":
            provisional = request.input.get("provisional", {})
            output = {
                "findings": provisional.get("findings", []),
                "next_actions": provisional.get("next_actions", []),
                "material_uncertainties": provisional.get("material_uncertainties", []),
            }
        else:
            output = {"operation": request.operation, "input": request.input}
        response = ModelResponse(
            provider=self.name,
            model=self.model,
            output=output,
        )
        response.validate()
        return response


class ProviderUnavailable(RuntimeError):
    """Raised when the selected provider cannot be reached."""


@dataclass(frozen=True)
class ApiProvider:
    """OpenAI-compatible HTTP adapter; no provider SDK crosses this boundary."""

    model: str = "local-api-model"
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = 20.0
    retry_attempts: int = 1
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0
    name: str = "api"

    def complete(self, request_data: ModelRequest) -> ModelResponse:
        request_data.validate()
        if self.retry_attempts < 0:
            raise ProviderContractError("retry_attempts must be non-negative")
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise ProviderUnavailable(f"API provider is not configured: missing {self.api_key_env}")
        payload = json.dumps({
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": json.dumps({
                    "operation": request_data.operation,
                    "input": request_data.input,
                    "context": request_data.context_documents,
                    "output_schema": request_data.output_schema,
                }, ensure_ascii=False),
            }],
            "response_format": {"type": "json_object"},
            "max_tokens": request_data.max_output_tokens,
        }).encode()
        started = time.perf_counter()
        last_error: ProviderUnavailable | None = None
        for attempt in range(self.retry_attempts + 1):
            http_request = request.Request(
                f"{self.base_url.rstrip('/')}/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            try:
                with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                    body = json.loads(response.read().decode())
                result = self._response(body, started, attempt)
                result.validate()
                return result
            except error.HTTPError as exc:
                last_error = ProviderUnavailable(
                    f"API provider unavailable at {self.base_url}: HTTP {exc.code} ({exc.reason})"
                )
                if exc.code not in {408, 429} and not 500 <= exc.code < 600:
                    break
            except (OSError, error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = ProviderUnavailable(f"API provider unavailable at {self.base_url}: {exc}")
            if attempt < self.retry_attempts:
                continue
        assert last_error is not None
        raise last_error

    def _response(
        self,
        body: dict[str, Any],
        started: float,
        attempt: int,
    ) -> ModelResponse:
        try:
            choice = body["choices"][0]["message"]["content"]
            output = json.loads(choice) if isinstance(choice, str) else choice
            usage = body.get("usage", {})
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
            cost = (input_tokens / 1000 * self.input_cost_per_1k) + (
                output_tokens / 1000 * self.output_cost_per_1k
            )
            return ModelResponse(
                provider=self.name,
                model=self.model,
                output=output,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=round((time.perf_counter() - started) * 1000),
                retries=attempt,
                estimated_cost_usd=round(cost, 8),
            )
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderContractError(f"API provider returned invalid structured output: {exc}") from exc


@dataclass(frozen=True)
class OllamaProvider:
    model: str = "llama3.2"
    base_url: str = "http://localhost:11434"
    timeout_seconds: float = 10.0
    name: str = "ollama"

    def complete(self, request_data: ModelRequest) -> ModelResponse:
        request_data.validate()
        prompt = json.dumps({
            "operation": request_data.operation,
            "input": request_data.input,
            "context": request_data.context_documents,
            "output_schema": request_data.output_schema,
        }, ensure_ascii=False)
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"num_predict": request_data.max_output_tokens},
        }).encode()
        started = time.perf_counter()
        http_request = request.Request(
            f"{self.base_url.rstrip('/')}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode())
        except error.HTTPError as exc:
            raise ProviderUnavailable(
                f"Ollama provider unavailable at {self.base_url}: HTTP {exc.code} ({exc.reason})"
            ) from exc
        except (OSError, error.URLError, TimeoutError) as exc:
            raise ProviderUnavailable(
                f"Ollama provider unavailable at {self.base_url}: {exc}"
            ) from exc
        try:
            output = body.get("response")
            if isinstance(output, str):
                output = json.loads(output)
            result = ModelResponse(
                provider=self.name,
                model=self.model,
                output=output,
                input_tokens=int(body.get("prompt_eval_count", 0)),
                output_tokens=int(body.get("eval_count", 0)),
                latency_ms=round((time.perf_counter() - started) * 1000),
            )
            result.validate()
            return result
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderContractError(f"Ollama returned invalid structured output: {exc}") from exc


@dataclass(frozen=True)
class ProviderConfig:
    name: str = "deterministic"
    model: str | None = None
    timeout_seconds: float = 10.0
    max_output_tokens: int = 1200
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    retry_attempts: int = 1
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0


class ProviderRouter:
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def select(self, override: str | None = None) -> ModelProvider:
        name = override or self.config.name
        if name == "deterministic":
            return DeterministicProvider(model=self.config.model or "rules-v1")
        if name == "ollama":
            return OllamaProvider(
                model=self.config.model or "llama3.2",
                timeout_seconds=self.config.timeout_seconds,
            )
        if name == "api":
            return ApiProvider(
                model=self.config.model or "local-api-model",
                base_url=self.config.base_url,
                api_key_env=self.config.api_key_env,
                timeout_seconds=self.config.timeout_seconds,
                retry_attempts=self.config.retry_attempts,
                input_cost_per_1k=self.config.input_cost_per_1k,
                output_cost_per_1k=self.config.output_cost_per_1k,
            )
        raise ProviderContractError(f"Unknown provider: {name}")


def provider_config(data: dict[str, Any] | None) -> ProviderConfig:
    data = data or {}
    return ProviderConfig(
        name=str(data.get("name", "deterministic")),
        model=data.get("model"),
        timeout_seconds=float(data.get("timeout_seconds", 10.0)),
        max_output_tokens=int(data.get("max_output_tokens", 1200)),
        base_url=str(data.get("base_url", "https://api.openai.com/v1")),
        api_key_env=str(data.get("api_key_env", "OPENAI_API_KEY")),
        retry_attempts=int(data.get("retry_attempts", 1)),
        input_cost_per_1k=float(data.get("input_cost_per_1k", 0.0)),
        output_cost_per_1k=float(data.get("output_cost_per_1k", 0.0)),
    )


def provider_inventory() -> list[dict[str, Any]]:
    """Report local capabilities without authenticating or contacting providers."""
    return [
        {"provider": "deterministic", "available": True, "model": "rules-v1", "network": False},
        {
            "provider": "ollama",
            "available": shutil.which("ollama") is not None,
            "model": None,
            "network": True,
            "configured": False,
        },
        {
            "provider": "api",
            "available": bool(os.environ.get("OPENAI_API_KEY")),
            "model": None,
            "network": True,
            "configured": bool(os.environ.get("OPENAI_API_KEY")),
        },
    ]
