import json
from types import SimpleNamespace

import pytest

from buzz.github import GitHubReadClient, GitHubReadError
from buzz.cli import main
from buzz.models import Task
from buzz.sources import SourceRegistry


def test_live_read_checks_auth_uses_get_and_deduplicates_issue_pr_items(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1:3] == ["auth", "status"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps([
                {"number": 7, "title": "Roadmap item", "state": "open", "html_url": "https://github.com/acme/osana/issues/7", "labels": [], "updated_at": "2026-10-01T00:00:00Z"},
                {"number": 7, "title": "Roadmap item", "state": "open", "html_url": "https://github.com/acme/osana/issues/7", "labels": [], "updated_at": "2026-10-01T00:00:00Z"},
                {"number": 8, "title": "Fix", "state": "open", "html_url": "https://github.com/acme/osana/pull/8", "pull_request": {}, "labels": [], "updated_at": "2026-10-01T00:00:00Z"},
            ]),
            stderr="",
        )

    monkeypatch.setattr("buzz.github.subprocess.run", fake_run)
    result = GitHubReadClient().read("acme/osana")

    assert result.mode == "live"
    assert [item["kind"] for item in result.items] == ["issue", "pull_request"]
    api_call = calls[1][0]
    assert api_call[:4] == ["gh", "api", "repos/acme/osana/issues", "--method"]
    assert api_call[4] == "GET"
    assert calls[1][1]["shell"] is False


def test_snapshot_read_never_calls_gh(tmp_path, monkeypatch):
    snapshot = tmp_path / "github.json"
    snapshot.write_text(json.dumps({
        "repository": "acme/osana",
        "items": [
            {"kind": "issue", "number": 1, "title": "One", "state": "open", "url": "https://github.com/acme/osana/issues/1"},
            {"kind": "issue", "number": 1, "title": "Duplicate", "state": "open", "url": "https://github.com/acme/osana/issues/1"},
        ],
    }))

    def fail_run(*_args, **_kwargs):
        raise AssertionError("snapshot reads must not call gh")

    monkeypatch.setattr("buzz.github.subprocess.run", fail_run)
    result = GitHubReadClient().read("acme/osana", snapshot_path=snapshot)

    assert result.mode == "snapshot"
    assert len(result.items) == 1
    assert result.repository == "acme/osana"


def test_context_read_requires_allowlisted_source_before_live_read(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "project:\n  id: osana\n"
        "context_policy: explicit_allowlist\n"
        "sources:\n"
        "  - id: osana-github-live\n"
        "    type: github_issue_live\n"
        "    authority: github\n"
        "    status: active\n"
        "    access: read_only\n"
    )
    registry = SourceRegistry.from_manifest(manifest)
    client = GitHubReadClient()
    monkeypatch.setattr(client, "read", lambda *_args, **_kwargs: SimpleNamespace(
        mode="snapshot",
        repository="acme/osana",
        items=[{"kind": "issue", "number": 1, "title": "One", "state": "open", "url": "https://github.com/acme/osana/issues/1"}],
        to_document=lambda: "{\"items\": [{\"number\": 1}]}"),
    )

    context = client.read_context(Task.new("Read the MAP"), registry, "source:osana-github-live", "acme/osana")

    assert context.source_ids == ["osana-github-live"]
    assert set(context.documents) == {"osana-github-live"}
    assert context.constraints["source_mode"] == "snapshot"


def test_gh_failure_does_not_expose_command_output(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="token=secret", stderr="private failure")

    monkeypatch.setattr("buzz.github.subprocess.run", fake_run)

    with pytest.raises(GitHubReadError, match="GitHub read unavailable"):
        GitHubReadClient().read("acme/osana")


def test_github_read_cli_snapshot_is_read_only(tmp_path, monkeypatch, capsys):
    snapshot = tmp_path / "github.json"
    snapshot.write_text(json.dumps({
        "repository": "acme/osana",
        "items": [{"number": 3, "title": "Read me", "state": "open", "url": "https://github.com/acme/osana/issues/3"}],
    }))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["buzz", "github-read", "--repo", "acme/osana", "--snapshot", str(snapshot)])

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "snapshot"
    assert output["items"][0]["number"] == 3
    assert list(tmp_path.glob(".buzz")) == []
