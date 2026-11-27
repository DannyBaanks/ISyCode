"""Read-only REST fixtures; never use an account or token from this computer."""
import asyncio

import pytest

from core.github_service import GitHubError, GitHubService


def fixture_responses(repo="Fixture/project"):
    return {
        "user": {"login": "Fixture"},
        "repos/" + repo: {"full_name": repo, "description": "Native IDE", "private": True,
                          "default_branch": "main", "language": "Python", "stargazers_count": 8,
                          "forks_count": 2, "pushed_at": "2026-10-11T02:00:00Z"},
        "pulls": [{"number": 7, "title": "<script>not executable</script>", "draft": True,
                   "user": {"login": "Fixture"}, "html_url": "https://evil.invalid/token"}],
        "issues": [{"number": 7, "pull_request": {}, "title": "This is a PR"},
                   {"number": 12, "title": "Layout"}],
        "commits": [{"sha": "a" * 40, "commit": {"message": "Polish\nprivate full body",
                     "author": {"name": "Fixture", "date": "2026-10-11T02:00:00Z"}}}],
        "actions": {"workflow_runs": [{"id": 91, "name": "Tests", "status": "completed",
                    "conclusion": "failure", "head_branch": "main"}]}}


def fake_api(data, calls, *, denied=None):
    async def query(args):
        assert args[:3] == ["api", "--hostname", "github.com"]
        endpoint = args[-1]
        calls.append(endpoint)
        key = "user" if endpoint == "user" else endpoint if endpoint in data else (
            "actions" if "/actions/" in endpoint else endpoint.split("/")[-1].split("?")[0])
        if key == denied:
            raise GitHubError("fixture permission denied")
        return data[key]
    return query


def test_remote_activity_without_local_folder_is_read_only_and_bounded(monkeypatch):
    service = GitHubService()
    calls = []
    monkeypatch.setattr(service, "_gh", fake_api(fixture_responses(), calls))
    report = asyncio.run(service.repository_details("Fixture/project"))
    assert report["branch"] == "main" and report["stars"] == 8
    assert calls[0] == "user" and len(calls) == 6
    assert all("per_page=30" in call for call in calls[2:])
    sections = report["sections"]
    assert len(sections["issues"]["rows"]) == 1
    assert sections["pulls"]["rows"][0]["url"] == "https://github.com/Fixture/project/pull/7"
    assert sections["commits"]["rows"][0]["title"] == "Polish"
    assert "private full body" not in str(report)
    assert sections["actions"]["rows"][0]["conclusion"] == "failure"


def test_actions_permission_failure_is_unknown_not_success(monkeypatch):
    service = GitHubService()
    monkeypatch.setattr(service, "_gh", fake_api(fixture_responses(), [], denied="actions"))
    report = asyncio.run(service.repository_details("Fixture/project"))
    assert not report["sections"]["actions"]["available"]
    assert report["sections"]["pulls"]["available"]


def test_account_switch_stops_before_repository_query(monkeypatch):
    service = GitHubService()
    calls = []
    data = fixture_responses()
    data["user"] = {"login": "Other"}
    monkeypatch.setattr(service, "_gh", fake_api(data, calls))
    with pytest.raises(GitHubError, match="cuenta activa"):
        asyncio.run(service.repository_details("Fixture/project"))
    assert calls == ["user"]


def test_recent_sample_limit_is_explicit_and_unknown_counters_preserved(monkeypatch):
    service = GitHubService()
    data = fixture_responses()
    data["pulls"] *= 35
    data["repos/Fixture/project"]["stargazers_count"] = "invalid"
    monkeypatch.setattr(service, "_gh", fake_api(data, []))
    report = asyncio.run(service.repository_details("Fixture/project"))
    assert report["stars"] is None
    assert len(report["sections"]["pulls"]["rows"]) == 30
    assert report["sections"]["pulls"]["limited"]


def test_activity_panel_loads_on_selection_without_enabling_pull(qtbot, tmp_path, monkeypatch):
    from ui.app import AppController
    from ui.panels.github import GitHubPanel
    from PySide6.QtCore import Qt
    panel = GitHubPanel(AppController(tmp_path))
    qtbot.addWidget(panel)
    panel.show()
    monkeypatch.setattr(panel.service, "_gh", fake_api(fixture_responses(), []))
    panel._catalog_ready({"verified": True, "login": "Fixture", "may_have_more": False,
                          "repositories": [{"name": "Fixture/project", "private": True}]})
    qtbot.waitUntil(lambda: panel.metrics["stars"].text() == "8", timeout=3000)
    qtbot.waitUntil(lambda: panel._worker is None)
    assert panel._selected_folder == ""
    assert not panel.pull_button.isEnabled() and not panel.refresh_button.isEnabled()
    assert "<script>not executable</script>" in panel.activity_views["pulls"].toPlainText()
    assert "https://evil.invalid" not in panel.activity_views["pulls"].toHtml()
    assert "private full body" not in panel.activity_views["commits"].toPlainText()
    panel.search.setText("fixture/project")
    assert not panel.tree.topLevelItem(0).isHidden()
    assert panel.tree.topLevelItem(0).data(0, Qt.ItemDataRole.UserRole) == ("Fixture/project", "")
    panel._selected_repo = "Fixture/other"
    report = asyncio.run(panel.service.repository_details("Fixture/project"))
    panel.metrics["stars"].setText("unchanged")
    panel._show_activity(report)
    assert panel.metrics["stars"].text() == "unchanged"
