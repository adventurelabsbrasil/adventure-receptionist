import json
from types import SimpleNamespace

import pytest

from buzz.runtime_connectors import GitHubRuntimeInventoryConnector, RuntimeConnectorError


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
