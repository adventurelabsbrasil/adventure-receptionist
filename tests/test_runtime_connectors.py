import json
from types import SimpleNamespace

import pytest

from buzz.runtime_connectors import GitHubRuntimeInventoryConnector, OllamaRuntimeInventoryConnector, RuntimeConnectorError


def test_github_connector_preserves_live_mode_and_unknown_runtime(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1:3] == ["auth", "status"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[1:4] == ["api", "repos/acme/receptionist", "--method"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps({"html_url": "https://github.com/acme/receptionist"}), stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps({"workflow_runs": []}), stderr="")

    monkeypatch.setattr("buzz.runtime_connectors.subprocess.run", fake_run)
    report = GitHubRuntimeInventoryConnector(timeout_seconds=3).read("acme/receptionist")

    assert report["mode"] == "live"
    assert report["source_selection"] == {"type": "connector", "connector": "github", "repository": "acme/receptionist", "fallback": "none"}
    assert report["assertions"][0]["value"] == "https://github.com/acme/receptionist"
    assert report["assertions"][1]["status"] == "unavailable"
    assert calls[0] == ["gh", "auth", "status"]
    assert all("--method" in call and call[call.index("--method") + 1] == "GET" for call in calls[1:])


def test_github_connector_rejects_invalid_repository():
    with pytest.raises(RuntimeConnectorError, match="OWNER/REPOSITORY"):
        GitHubRuntimeInventoryConnector().read("receptionist")


def test_github_connector_does_not_fallback_on_command_failure(monkeypatch):
    monkeypatch.setattr("buzz.runtime_connectors.subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="failure"))

    with pytest.raises(RuntimeConnectorError, match="unavailable"):
        GitHubRuntimeInventoryConnector().read("acme/receptionist")


def test_ollama_connector_reads_models_without_shell_or_generation(monkeypatch):
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"models": [{"name": "llama3.2:3b"}]}).encode()

    def fake_urlopen(http_request, **kwargs):
        calls.append((http_request.get_method(), http_request.full_url, kwargs["timeout"]))
        return Response()

    monkeypatch.setattr("buzz.runtime_connectors.request.urlopen", fake_urlopen)
    monkeypatch.setattr("buzz.runtime_connectors.subprocess.run", lambda *_args, **_kwargs: pytest.fail("Ollama connector must not use subprocess"))

    report = OllamaRuntimeInventoryConnector(
        base_url="http://127.0.0.1:11435",
        model="llama3.2:3b",
        host_id="xeon",
        channel="cli",
        transport="ssh-tunnel-http",
    ).read()

    assert calls == [("GET", "http://127.0.0.1:11435/api/tags", 20.0)]
    assert report["mode"] == "live"
    assert report["trace"] == {
        "runtime_id": "buzz-ollama-runtime",
        "host_id": "xeon",
        "channel": "cli",
        "transport": "ssh-tunnel-http",
    }
    assert report["source_selection"]["fallback"] == "none"
    assert next(item for item in report["assertions"] if item["property"] == "model")["status"] == "available"


def test_ollama_connector_marks_missing_model_unavailable(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"models": [{"name": "qwen2.5:3b"}]}).encode()

    monkeypatch.setattr("buzz.runtime_connectors.request.urlopen", lambda *_args, **_kwargs: Response())
    report = OllamaRuntimeInventoryConnector(
        base_url="http://127.0.0.1:11435",
        model="llama3.2:3b",
    ).read()

    model_assertion = next(item for item in report["assertions"] if item["property"] == "model")
    assert model_assertion["status"] == "unavailable"
    assert model_assertion["provenance"]["mode"] == "live"


def test_ollama_connector_never_infers_missing_host_or_channel(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"models": [{"name": "llama3.2:3b"}]}).encode()

    monkeypatch.setattr("buzz.runtime_connectors.request.urlopen", lambda *_args, **_kwargs: Response())
    report = OllamaRuntimeInventoryConnector(
        base_url="http://127.0.0.1:11435",
        model="llama3.2:3b",
    ).read()

    by_property = {item["property"]: item for item in report["assertions"]}
    assert by_property["identity"]["status"] == "unavailable"
    assert by_property["transport"]["status"] == "unavailable"


def test_ollama_connector_rejects_credentials_in_endpoint():
    with pytest.raises(RuntimeConnectorError, match="credentials"):
        OllamaRuntimeInventoryConnector(
            base_url="http://token:secret@127.0.0.1:11435",
            model="llama3.2:3b",
        )


def test_ollama_connector_does_not_fallback_on_timeout(monkeypatch):
    monkeypatch.setattr("buzz.runtime_connectors.request.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("slow")))

    with pytest.raises(RuntimeConnectorError, match="unavailable"):
        OllamaRuntimeInventoryConnector(base_url="http://127.0.0.1:11435", model="llama3.2:3b").read()
