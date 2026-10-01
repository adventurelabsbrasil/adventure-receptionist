from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderContractError(ValueError):
    """Raised when a provider request or response violates the structured contract."""


@dataclass(frozen=True)
class ModelRequest:
    operation: str
    input: dict[str, Any]
    context_refs: list[str] = field(default_factory=list)
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
        response = ModelResponse(
            provider=self.name,
            model=self.model,
            output={"operation": request.operation, "input": request.input},
        )
        response.validate()
        return response


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
    ]
