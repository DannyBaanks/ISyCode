"""Real local Git with only the network boundary replaced by owned fixtures."""
import asyncio
import subprocess

import pytest

from core.github_service import GitHubError, GitHubService, GitSyncService
from core.processes import ProcessOutput


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_IDE_HOME", str(tmp_path / "private"))
    root = tmp_path / "checkout"
    root.mkdir()
    git(root, "init", "-b", "feature")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    (root / "code.py").write_text("old")
    git(root, "add", "code.py")
    git(root, "commit", "-m", "base")
    base = git(root, "rev-parse", "HEAD")
    (root / "code.py").write_text("new")
    git(root, "add", "code.py")
    git(root, "commit", "-m", "incoming feature")
    target = git(root, "rev-parse", "HEAD")
    # Create an independent local branch, then return the owned fixture to base.
    git(root, "branch", "incoming", target)
    git(root, "switch", "-c", "local", base)
    git(root, "remote", "add", "upstream", "https://github.com/Fixture/project.git")
    git(root, "update-ref", "refs/remotes/upstream/feature", base)
    git(root, "config", "branch.local.remote", "upstream")
    git(root, "config", "branch.local.merge", "refs/heads/feature")
    sync = GitSyncService(root)
    original = sync._git
    async def network_fixture(args, **kwargs):
        if args[0] == "fetch":
            assert "refs/heads/feature:refs/remotes/upstream/feature" in args
            git(root, "update-ref", "refs/remotes/upstream/feature", target)
            return ProcessOutput(0, b"", b"")
        if args[0] == "ls-remote":
            return ProcessOutput(0, (target + "\trefs/heads/feature\n").encode(), b"")
        return await original(args, **kwargs)
    async def account(self, args):
        assert args[-1] == "user"
        return {"login": "Fixture"}
    monkeypatch.setattr(sync, "_git", network_fixture)
    monkeypatch.setattr(GitHubService, "_gh", account)
    return root, sync, base, target


def test_counts_use_actual_upstream_and_dirty_tree_blocks_pull(checkout):
    root, sync, _, _ = checkout
    status = asyncio.run(sync.inspect(refresh=True, expected_repo="Fixture/project"))
    assert status.branch == "local" and status.remote_branch == "feature"
    assert (status.ahead, status.behind, status.fresh, status.can_update) == (0, 1, True, True)
    (root / "untracked.txt").write_text("keep me")
    status = asyncio.run(sync.inspect())
    assert status.behind == 1 and status.untracked == 1 and not status.can_update
    with pytest.raises(GitHubError, match="carpeta sin cambios"):
        asyncio.run(sync.preview_pull("Fixture/project"))
    assert (root / "untracked.txt").read_text() == "keep me"


def test_reviewed_fast_forward_updates_files_and_suppresses_hooks(checkout):
    root, sync, base, target = checkout
    hook = root / ".git" / "hooks" / "post-merge"
    hook.write_text("#!/bin/sh\nprintf bad > hook-ran\n")
    hook.chmod(0o755)
    async def update():
        preview = await sync.preview_pull("Fixture/project")
        assert preview.files == (("M", "code.py"),)
        assert preview.status.head == base
        return await sync.apply_pull(preview.id, operator_approved=True)
    status, receipt = asyncio.run(update())
    assert status.head == target and status.behind == 0
    assert receipt["status"] == "updated"
    assert (root / "code.py").read_text() == "new"
    assert not (root / "hook-ran").exists()


def test_changed_base_after_review_is_preserved(checkout):
    root, sync, _, _ = checkout
    async def update():
        preview = await sync.preview_pull("Fixture/project")
        (root / "local.py").write_text("local")
        git(root, "add", "local.py")
        git(root, "commit", "-m", "local work")
        with pytest.raises(GitHubError, match="cambiaron"):
            await sync.apply_pull(preview.id, operator_approved=True)
    asyncio.run(update())
    assert (root / "local.py").read_text() == "local"
    assert (root / "code.py").read_text() == "old"


def test_catalog_is_verified_by_request_and_keeps_private_repos(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_IDE_HOME", str(tmp_path))
    service = GitHubService()
    calls = []
    async def fake(args):
        calls.append(args[-1])
        if args[-1] == "user":
            return {"login": "Fixture"}
        return [{"html_url": "https://github.com/Fixture/private", "full_name": "Fixture/private", "private": True},
                {"html_url": "https://github.com/Other/public", "full_name": "Other/public"}]
    monkeypatch.setattr(service, "_gh", fake)
    report = asyncio.run(service.catalog())
    assert report["verified"] and calls[0] == "user"
    assert [(r["name"], r["private"]) for r in report["repositories"]] == [("Fixture/private", True)]


@pytest.mark.parametrize("state", ["detached", "no_upstream", "shallow", "diverged"])
def test_unsupported_git_states_disable_update(checkout, state):
    root, sync, base, target = checkout
    git(root, "remote", "add", "origin", "https://github.com/Fixture/project.git")
    if state == "detached":
        git(root, "checkout", "--detach", base)
    elif state == "no_upstream":
        git(root, "config", "--unset", "branch.local.merge")
    elif state == "shallow":
        (root / ".git/shallow").write_text(base + "\n")
    else:
        (root / "local.py").write_text("local")
        git(root, "add", "local.py")
        git(root, "commit", "-m", "divergent local")
        git(root, "update-ref", "refs/remotes/upstream/feature", target)
    report = asyncio.run(sync.inspect())
    assert report.state == state and not report.can_update


def test_effective_filters_block_preview_without_executing_driver(checkout):
    root, sync, _, _ = checkout
    (root / ".gitattributes").write_text("code.py filter=unsafe-fixture\n")
    with pytest.raises(GitHubError, match="filtros"):
        asyncio.run(sync.preview_pull("Fixture/project"))
    assert (root / "code.py").read_text() == "old"


def test_expired_account_never_shows_verified_catalog(tmp_path, monkeypatch):
    service = GitHubService()
    async def expired(args):
        raise GitHubError("account expired fixture")
    monkeypatch.setattr(service, "_gh", expired)
    with pytest.raises(GitHubError):
        asyncio.run(service.catalog())


def test_current_and_linked_worktree_have_explicit_independent_paths(checkout, tmp_path):
    from core.github_service import RepoLinkStore
    root, sync, base, target = checkout
    git(root, "remote", "add", "origin", "https://github.com/Fixture/project.git")
    other = tmp_path / "linked-worktree"
    git(root, "worktree", "add", "-b", "another-local", str(other), base)
    git(other, "config", "branch.another-local.remote", "upstream")
    git(other, "config", "branch.another-local.merge", "refs/heads/feature")
    asyncio.run(sync.link("Fixture/project"))
    asyncio.run(GitSyncService(other).link("Fixture/project"))
    assert {row["folder"] for row in RepoLinkStore().list()} == {str(root), str(other)}
    assert asyncio.run(GitSyncService(other).inspect()).fresh is False
