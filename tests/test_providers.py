import json

import pytest

from buzz.providers import (
    DeterministicProvider,
    ModelRequest,
    OllamaProvider,
    ProviderConfig,
    ProviderContractError,
    ProviderRouter,
    ProviderUnavailable,
)


def test_deterministic_provider_returns_structured_response_offline():
    response = DeterministicProvider().complete(
        ModelRequest(operation="classify", input={"objective": "diagnose readiness"})
    )
    assert response.provider == "deterministic"
    assert response.output == {
        "operation": "classify",
        "input": {"objective": "diagnose readiness"},
    }


def test_provider_request_rejects_invalid_output_contract():
    with pytest.raises(ProviderContractError, match="object structured output"):
        DeterministicProvider().complete(
            ModelRequest(operation="classify", input={}, output_schema="freeform")
        )


def test_provider_request_rejects_zero_budget():
    with pytest.raises(ProviderContractError, match="max_output_tokens"):
        DeterministicProvider().complete(ModelRequest(operation="classify", input={}, max_output_tokens=0))


def test_router_rejects_unknown_provider_without_fallback():
    with pytest.raises(ProviderContractError, match="Unknown provider"):
        ProviderRouter(ProviderConfig()).select("made-up")


def test_deterministic_triage_synthesis_returns_structured_lists_without_network():
    response = DeterministicProvider().complete(ModelRequest(
        operation="triage_synthesis",
        input={"provisional": {"findings": ["known"], "next_actions": [], "material_uncertainties": []}},
        context_documents={"source": "only this document"},
    ))
    assert response.output["findings"] == ["known"]


def test_ollama_sends_only_selected_documents_and_parses_structured_output(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps({
                "response": '{"findings": [], "next_actions": [], "material_uncertainties": []}',
                "prompt_eval_count": 11,
                "eval_count": 7,
            }).encode()

    def fake_urlopen(http_request, timeout):
        captured["body"] = json.loads(http_request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("buzz.providers.request.urlopen", fake_urlopen)
    response = OllamaProvider(model="test-model", timeout_seconds=3).complete(ModelRequest(
        operation="triage_synthesis",
        input={"objective": "diagnose"},
        context_documents={"allowed": "only this"},
    ))

    prompt = json.loads(captured["body"]["prompt"])
    assert prompt["context"] == {"allowed": "only this"}
    assert "not-selected" not in captured["body"]["prompt"]
    assert captured["timeout"] == 3
    assert response.input_tokens == 11
    assert response.output_tokens == 7


def test_ollama_connection_failure_is_explicit(monkeypatch):
    from urllib.error import URLError

    def unavailable(*_args, **_kwargs):
        raise URLError("connection refused")

    monkeypatch.setattr("buzz.providers.request.urlopen", unavailable)
    with pytest.raises(ProviderUnavailable, match="Ollama provider unavailable"):
        OllamaProvider(timeout_seconds=1).complete(ModelRequest(operation="triage_synthesis", input={}))


def test_ollama_http_failure_includes_status(monkeypatch):
    from urllib.error import HTTPError

    def unavailable(*_args, **_kwargs):
        raise HTTPError("http://localhost:11434/api/generate", 500, "server error", {}, None)

    monkeypatch.setattr("buzz.providers.request.urlopen", unavailable)
    with pytest.raises(ProviderUnavailable, match="HTTP 500"):
        OllamaProvider().complete(ModelRequest(operation="triage_synthesis", input={}))


def test_ollama_invalid_structured_output_is_rejected(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b'{"response": "not-json"}'

    monkeypatch.setattr("buzz.providers.request.urlopen", lambda *_args, **_kwargs: Response())
    with pytest.raises(ProviderContractError, match="invalid structured output"):
        OllamaProvider().complete(ModelRequest(operation="triage_synthesis", input={}))


def test_ollama_missing_response_is_rejected_as_invalid_structured_output(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b'{"done": true}'

    monkeypatch.setattr("buzz.providers.request.urlopen", lambda *_args, **_kwargs: Response())
    with pytest.raises(ProviderContractError, match="invalid structured output"):
        OllamaProvider().complete(ModelRequest(operation="triage_synthesis", input={}))
