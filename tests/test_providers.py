import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from buzz.providers import (
    ApiProvider,
    DeterministicProvider,
    ModelRequest,
    OllamaProvider,
    ProviderConfig,
    ProviderContractError,
    ProviderRouter,
    ProviderUnavailable,
    provider_config,
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


def test_router_accepts_explicit_remote_ollama_endpoint():
    provider = ProviderRouter(ProviderConfig(ollama_base_url="http://xeon.example:11434")).select("ollama")
    assert provider.base_url == "http://xeon.example:11434"


def test_ollama_override_does_not_inherit_deterministic_model():
    provider = ProviderRouter(ProviderConfig(name="deterministic", model="rules-v1")).select("ollama")
    assert provider.model == "llama3.2:3b"


def test_ollama_model_can_be_selected_by_environment(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
    provider = ProviderRouter(ProviderConfig()).select("ollama")
    assert provider.model == "qwen2.5:3b"


def test_ollama_timeout_can_be_selected_by_environment_for_provider_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "90")
    provider = ProviderRouter(ProviderConfig(name="deterministic", timeout_seconds=10)).select("ollama")
    assert provider.timeout_seconds == 90


def test_ollama_endpoint_mode_can_be_selected_by_environment(monkeypatch):
    monkeypatch.setenv("OLLAMA_ENDPOINT_MODE", "remote")
    provider = ProviderRouter(provider_config({"name": "deterministic"})).select("ollama")
    assert provider.endpoint_mode == "remote"


def test_ollama_manifest_base_url_is_used_when_provider_is_ollama():
    config = ProviderConfig(**{
        "name": "ollama",
        "ollama_base_url": "http://xeon.example:11434",
    })
    assert ProviderRouter(config).select().base_url == "http://xeon.example:11434"


def test_ollama_tunnel_can_mark_remote_backend_explicitly():
    provider = ProviderRouter(ProviderConfig(
        ollama_base_url="http://127.0.0.1:11434",
        endpoint_mode="remote",
    )).select("ollama")
    assert provider.endpoint_mode == "remote"


def test_ollama_base_url_can_be_selected_by_environment(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11435")
    assert ProviderRouter(provider_config({"name": "ollama"})).select().base_url == "http://127.0.0.1:11435"


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


def test_ollama_retries_transient_failure_and_reports_cost(monkeypatch):
    attempts = {"count": 0}

    def fake_urlopen(*_args, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            from urllib.error import HTTPError
            raise HTTPError("http://localhost:11434/api/generate", 503, "busy", {}, None)

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps({
                    "response": '{"findings": [], "next_actions": [], "material_uncertainties": []}',
                    "prompt_eval_count": 100,
                    "eval_count": 25,
                }).encode()

        return Response()

    monkeypatch.setattr("buzz.providers.request.urlopen", fake_urlopen)
    response = OllamaProvider(
        retry_attempts=1,
        input_cost_per_1k=1.0,
        output_cost_per_1k=2.0,
    ).complete(ModelRequest(operation="triage_synthesis", input={}))

    assert attempts["count"] == 2
    assert response.retries == 1
    assert response.estimated_cost_usd == 0.15


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


def test_api_provider_sends_structured_request_and_reports_cost_without_exposing_key(monkeypatch):
    captured = {}
    monkeypatch.setenv("TEST_API_KEY", "unit-test-key")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": '{"findings": [], "next_actions": [], "material_uncertainties": []}'}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 25},
            }).encode()

    def fake_urlopen(http_request, timeout):
        captured["body"] = json.loads(http_request.data)
        captured["authorization"] = http_request.headers["Authorization"]
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("buzz.providers.request.urlopen", fake_urlopen)
    response = ApiProvider(
        model="test-model",
        base_url="https://example.test/v1",
        api_key_env="TEST_API_KEY",
        timeout_seconds=3,
        input_cost_per_1k=1.0,
        output_cost_per_1k=2.0,
    ).complete(ModelRequest(operation="triage_synthesis", input={}, context_documents={"allowed": "yes"}))

    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["messages"][0]["content"].find("output_schema_definition") >= 0
    assert captured["timeout"] == 3
    assert captured["authorization"] == "Bearer unit-test-key"
    assert response.output["findings"] == []
    assert response.estimated_cost_usd == 0.15


def test_api_provider_works_against_controlled_local_http_endpoint(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "unit-test-key")
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib handler API
            received["payload"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            body = json.dumps({
                "choices": [{"message": {"content": '{"findings": [], "next_actions": [], "material_uncertainties": []}'}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    except PermissionError:
        pytest.skip("sandbox does not permit binding a local controlled endpoint")
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = ApiProvider(
            model="controlled-local-model",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key_env="TEST_API_KEY",
        ).complete(ModelRequest(
            operation="triage_synthesis",
            input={},
            prompt_version="prompt.v1",
            schema_version="schema.v1",
            policy_version="policy.v1",
        ))
    finally:
        server.shutdown()
        server.server_close()

    assert response.output["findings"] == []
    assert received["payload"]["response_format"] == {"type": "json_object"}
    assert "prompt.v1" in received["payload"]["messages"][0]["content"]


def test_api_provider_retries_transient_failure_and_fails_without_fallback(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "unit-test-key")
    attempts = {"count": 0}

    def unavailable(*_args, **_kwargs):
        attempts["count"] += 1
        from urllib.error import HTTPError
        raise HTTPError("https://example.test/v1/chat/completions", 503, "busy", {}, None)

    monkeypatch.setattr("buzz.providers.request.urlopen", unavailable)
    with pytest.raises(ProviderUnavailable, match="HTTP 503"):
        ApiProvider(api_key_env="TEST_API_KEY", retry_attempts=2).complete(
            ModelRequest(operation="triage_synthesis", input={})
        )
    assert attempts["count"] == 3
