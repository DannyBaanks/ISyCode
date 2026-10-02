"""Git status/diff/commit behind Authority, GitBoundary and approval; hostile repos refused."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import ProductActionGate
from isycode.approvals import ActionApprovalStore
from isycode.git_owner import GitOwner, git_executable
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority

pytestmark = pytest.mark.skipif(git_executable() is None, reason="git is not installed")


def _git(root, *args):
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(root.parent)}
    return subprocess.run(["git", *args], cwd=root, env=env, check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".gitconfig").write_text("[user]\n\tname = Test\n\temail = test@example.com\n")
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "app.py").write_text("x = 1\n")
    (root / ".env").write_text("TOKEN=secret\n")
    _git(root, "add", "app.py", ".env")
    _git(root, "commit", "-q", "-m", "init")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    approvals = ActionApprovalStore()
    return GitOwner(root, authority, approvals), authority, approvals, root.resolve()


def _grant(authority, *actions):
    for action in actions:
        authority.set_grant(action, enabled=True)


def test_nothing_runs_without_a_grant(repo):
    owner, *_ = repo
    assert owner.status().decision == "DENY"
    assert owner.diff().decision == "DENY"


def test_status_and_diff_hide_sensitive_files(repo):
    owner, authority, _, root = repo
    _grant(authority, "git.status", "git.diff")
    (root / "app.py").write_text("x = 2\n")
    (root / ".env").write_text("TOKEN=rotated\n")
    (root / "new.py").write_text("y = 1\n")
    status = json.loads(owner.status().text)
    assert status["branch"].startswith("main")
    assert {(e["status"], e["path"]) for e in status["changes"]} == {(" M", "app.py"), ("??", "new.py")}
    diff = owner.diff()
    assert diff.decision == "ALLOW" and "+x = 2" in json.loads(diff.text)["diff"]
    assert "TOKEN" not in diff.text
    assert owner.diff(".env").decision == "DENY"
    assert ActionAuditJournal(root).verify().receipts == 2


def test_is_path_tracked_is_bound_to_git_status_and_only_checks_isycode(repo):
    owner, authority, _, root = repo
    assert owner.is_path_tracked(".isycode").decision == "DENY"
    _grant(authority, "git.status")
    result = owner.is_path_tracked(".isycode")
    assert result.decision == "ALLOW" and json.loads(result.text)["tracked"] is False
    assert owner.is_path_tracked(".env").decision == "DENY"

    (root / ".isycode").mkdir()
    (root / ".isycode" / "config.json").write_text('{"version":1}\n')
    _git(root, "add", ".isycode/config.json")
    _git(root, "commit", "-q", "-m", "track config")
    tracked = owner.is_path_tracked(".isycode")
    assert tracked.decision == "ALLOW"
    assert json.loads(tracked.text)["tracked_paths"] == [".isycode/config.json"]


def test_classic_mode_reads_git_and_commits_only_after_exact_approval(repo):
    owner, authority, approvals, root = repo
    authority.set_mode("classic")
    (root / "app.py").write_text("x = 3\n")
    assert owner.status().decision == "ALLOW"
    preview = owner.preview_commit("change")
    assert owner.commit(preview, None).decision == "DENY"
    outcome = owner.commit(preview, approvals.issue(preview.request))
    assert outcome.decision == "ALLOW"
    assert _git(root, "log", "-1", "--format=%s").strip() == "change"


def test_commit_needs_approval_and_commits_exactly_the_reviewed_files(repo):
    owner, authority, approvals, root = repo
    _grant(authority, "git.commit")
    (root / "app.py").write_text("x = 2\n")
    (root / "new.py").write_text("y = 1\n")
    (root / ".env").write_text("TOKEN=rotated\n")
    preview = owner.preview_commit("Update app")
    assert preview.paths == ("app.py", "new.py")
    assert "+y = 1" in preview.diff and "TOKEN" not in preview.diff
    assert owner.commit(preview, None).decision == "DENY"
    outcome = owner.commit(preview, approvals.issue(preview.request))
    assert outcome.decision == "ALLOW"
    assert _git(root, "log", "-1", "--format=%s").strip() == "Update app"
    assert _git(root, "show", "--name-only", "--format=", "HEAD").split() == ["app.py", "new.py"]
    assert " M .env" in _git(root, "status", "--porcelain")


def test_a_change_after_review_is_not_committed(repo):
    owner, authority, approvals, root = repo
    _grant(authority, "git.commit")
    (root / "app.py").write_text("x = 2\n")
    preview = owner.preview_commit("Update app")
    (root / "app.py").write_text("x = 99\n")
    outcome = owner.commit(preview, approvals.issue(preview.request))
    assert outcome.decision == "DENY" and "changed after review" in outcome.reason
    assert _git(root, "log", "--format=%s").split() == ["init"]


def test_hooks_never_run_on_commit(repo):
    owner, authority, approvals, root = repo
    _grant(authority, "git.commit")
    marker = root.parent / "hook-ran"
    for hook in ("pre-commit", "commit-msg", "post-commit"):
        path = root / ".git" / "hooks" / hook
        path.write_text(f"#!/bin/sh\ntouch {marker}\n")
        path.chmod(0o755)
    (root / "app.py").write_text("x = 2\n")
    preview = owner.preview_commit("Update")
    assert owner.commit(preview, approvals.issue(preview.request)).decision == "ALLOW"
    assert not marker.exists()


@pytest.mark.parametrize("key, value", [
    ("core.fsmonitor", "touch /tmp/isycode-pwned"),
    ("core.pager", "sh"),
    ("filter.evil.clean", "sh -c id"),
    ("diff.evil.textconv", "sh"),
    ("include.path", "/tmp/other"),
    ("core.hooksPath", "/tmp/hooks"),
    ("credential.helper", "store"),
])
def test_repositories_that_configure_programs_are_refused(repo, key, value):
    owner, authority, _, root = repo
    _grant(authority, "git.status", "git.diff", "git.commit")
    _git(root, "config", key, value)
    outcome = owner.status()
    assert outcome.decision == "DENY" and "programs git would run" in outcome.reason
    with pytest.raises(ValueError):
        owner.preview_commit("x", ["app.py"])


def test_worktree_links_and_missing_repositories_are_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "plain"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    _grant(authority, "git.status")
    owner = GitOwner(root, authority)
    assert "not a git repository" in owner.status().reason
    (root / ".git").write_text("gitdir: /elsewhere\n")
    assert "not worktree links" in owner.status().reason


@pytest.mark.parametrize("paths", [[".env"], ["../x"], ["missing.py"], []])
def test_commit_paths_must_be_changed_non_sensitive_files(repo, paths):
    owner, authority, _, root = repo
    (root / ".env").write_text("TOKEN=rotated\n")
    with pytest.raises(ValueError):
        owner.preview_commit("x", paths)


@pytest.mark.parametrize("change", [
    {"git": "/tmp/git"}, {"message": ""}, {"paths": (".env",)}, {"paths": ()},
    {"diff_sha256": "x"}, {"extra": 1},
])
def test_boundary_rejects_forged_commit_requests(repo, change):
    owner, authority, approvals, root = repo
    _grant(authority, "git.commit")
    (root / "app.py").write_text("x = 2\n")
    preview = owner.preview_commit("Update")
    params = {**dict(preview.request.parameters), **change}
    request = ActionRequest("git.commit", root, str(root), params, execution_owner="workspace_git")
    gate = ProductActionGate(root, authority, owner_id="workspace_git")
    _, decision = gate.authorize(request, approvals=approvals, approval=approvals.issue(request))
    assert not decision.allowed


def test_commit_screen_rejects_by_default(repo):
    import asyncio

    from textual.app import App
    from isycode.tui import CommitApprovalScreen

    owner, _, _, root = repo
    (root / "app.py").write_text("x = 2\n")
    preview = owner.preview_commit("Update")
    results = []

    class Host(App):
        def on_mount(self):
            self.push_screen(CommitApprovalScreen(preview), results.append)

    async def scenario(action):
        async with Host().run_test() as pilot:
            await pilot.pause()
            await action(pilot)
            await pilot.pause()

    asyncio.run(scenario(lambda pilot: pilot.press("escape")))
    asyncio.run(scenario(lambda pilot: pilot.press("enter")))
    asyncio.run(scenario(lambda pilot: pilot.click("#commit-approval-apply")))
    assert results == [False, False, True]


def test_worktree_config_is_allowed_but_its_file_is_still_checked(repo):
    owner, authority, _, root = repo
    _grant(authority, "git.status")
    _git(root, "config", "extensions.worktreeConfig", "true")
    assert owner.status().decision == "ALLOW"
    (root / ".git" / "config.worktree").write_text("[core]\n\tfsmonitor = touch /tmp/x\n")
    outcome = owner.status()
    assert outcome.decision == "DENY" and "core.fsmonitor" in outcome.reason
