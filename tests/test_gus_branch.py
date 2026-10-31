"""GUS branches (ADR 0013, MK5b): ISyCode creates only gus/<topic>, after an exact approval."""
import os
import subprocess
from pathlib import Path

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import ProductActionGate
from isycode.approvals import ActionApprovalStore
from isycode.git_owner import GitOwner, git_executable, gus_branch_name
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
    _git(root, "add", "app.py")
    _git(root, "commit", "-q", "-m", "init")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    approvals = ActionApprovalStore()
    return GitOwner(root, authority, approvals), authority, approvals, root.resolve()


def _branch(root):
    return _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()


@pytest.mark.parametrize("topic, name", [
    ("Fix the work list", "gus/fix-the-work-list"),
    ("  añadir botón GUS!!  ", "gus/a-adir-bot-n-gus"),
    ("../../main", "gus/main"),
    ("x" * 80, "gus/" + "x" * 48),
])
def test_branch_names_are_always_gus_slugs(topic, name):
    assert gus_branch_name(topic) == name


@pytest.mark.parametrize("topic", ["", "   ", "!!!", None])
def test_a_topic_without_letters_or_digits_is_refused(topic):
    with pytest.raises(ValueError):
        gus_branch_name(topic)


def test_classic_creates_the_branch_only_after_exact_approval_and_keeps_the_tree(repo):
    owner, authority, approvals, root = repo
    authority.set_mode("classic")
    (root / "app.py").write_text("x = 2\n")                    # unrelated work in progress
    preview = owner.preview_gus_branch("work list resize")
    assert preview.branch == "gus/work-list-resize" and preview.current == "main"
    assert owner.create_gus_branch(preview, None).decision == "DENY"
    assert _branch(root) == "main"
    outcome = owner.create_gus_branch(preview, approvals.issue(preview.request))
    assert outcome.decision == "ALLOW" and outcome.receipt is not None
    assert _branch(root) == "gus/work-list-resize"
    assert (root / "app.py").read_text() == "x = 2\n"         # nothing in the tree was touched
    assert ActionAuditJournal(root).verify().receipts == 1


def test_security_mode_never_creates_a_branch(repo):
    owner, authority, approvals, root = repo
    authority.set_mode("security")
    preview = owner.preview_gus_branch("anything")
    assert owner.create_gus_branch(preview, approvals.issue(preview.request)).decision == "DENY"
    assert _branch(root) == "main"


def test_an_existing_branch_or_a_moved_head_is_refused(repo):
    owner, authority, approvals, root = repo
    authority.set_mode("classic")
    _git(root, "branch", "gus/taken")
    with pytest.raises(ValueError, match="already exists"):
        owner.preview_gus_branch("taken")
    preview = owner.preview_gus_branch("later")
    (root / "app.py").write_text("x = 3\n")
    _git(root, "commit", "-qam", "moved")
    outcome = owner.create_gus_branch(preview, approvals.issue(preview.request))
    assert outcome.decision == "DENY" and "HEAD moved" in outcome.reason
    assert _branch(root) == "main"


def test_hooks_never_run_on_switch(repo):
    owner, authority, approvals, root = repo
    authority.set_mode("classic")
    marker = root.parent / "hook-ran"
    hook = root / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    preview = owner.preview_gus_branch("hooks")
    assert owner.create_gus_branch(preview, approvals.issue(preview.request)).decision == "ALLOW"
    assert not marker.exists()


@pytest.mark.parametrize("change", [
    {"branch": "main"}, {"branch": "gus/../main"}, {"branch": "feature/x"}, {"branch": "gus/UPPER"},
    {"base": "HEAD"}, {"base": "x" * 40}, {"extra": 1}, {"git": "/tmp/git"},
])
def test_boundary_rejects_forged_branch_requests(repo, change):
    owner, authority, approvals, root = repo
    authority.set_mode("classic")
    preview = owner.preview_gus_branch("real")
    params = {**dict(preview.request.parameters), **change}
    request = ActionRequest("git.branch.create", root, str(root), params, execution_owner="workspace_git")
    gate = ProductActionGate(root, authority, owner_id="workspace_git")
    _, decision = gate.authorize(request, approvals=approvals, approval=approvals.issue(request))
    assert not decision.allowed


def test_gus_branch_in_the_tui_refuses_by_default_then_creates_on_approval(tmp_path, monkeypatch, capsys):
    """/gus branch <topic>: the screen opens on Reject; only the approve button creates it."""
    import asyncio
    from pathlib import Path
    from test_daily_tui import configure
    from isycode.gus_roots import GusSettingsStore
    from isycode.tui import TUIApp
    from isycode.tui_screens_approval import GusBranchApprovalScreen
    root = configure(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".gitconfig").write_text("[user]\n\tname = Test\n\temail = test@example.com\n")
    for marker in ("src/isycode/gus_role.py", "src/isycode/agents/gus.md"):
        (root / marker).parent.mkdir(parents=True, exist_ok=True)
        (root / marker).write_text("# marker\n")
    store = GusSettingsStore()
    store.write({**store.read(), "target": str(Path(root).resolve())})
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")

    async def until(pilot, condition, what):
        for _ in range(200):
            if condition():
                return
            await pilot.pause(0.05)
        raise AssertionError(f"timed out waiting for {what}")

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.wait_for_ready()
            task = asyncio.ensure_future(app._create_gus_branch("Resize fix"))
            await until(pilot, lambda: isinstance(app.screen, GusBranchApprovalScreen)
                        and app.screen.focused is not None, "the branch approval")
            assert app.screen.focused.id == "gus-branch-reject"
            assert "gus/resize-fix" in str(app.screen.query_one("#gus-branch-title").render())
            await pilot.press("enter")                      # Reject is the default
            assert await asyncio.wait_for(task, 10) is None
            assert _branch(root) == "main"

            task = asyncio.ensure_future(app._create_gus_branch("Resize fix"))
            await until(pilot, lambda: isinstance(app.screen, GusBranchApprovalScreen)
                        and app.screen.focused is not None, "the branch approval")
            app.screen.dismiss(True)
            assert await asyncio.wait_for(task, 10) == "gus/resize-fix"
            assert _branch(root) == "gus/resize-fix"

    with capsys.disabled():
        asyncio.run(scenario())
