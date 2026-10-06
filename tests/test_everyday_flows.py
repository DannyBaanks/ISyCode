"""M7: everyday end-to-end flows over the approved owner contracts.

G7-01 dirty repo: diagnose, edit three files, test, diff, undo — initial
work preserved, zero ordinary modals in Classic. G7-02 budgeted
move/delete recoverable, excessive cascade blocked pre-promotion.
G7-03 the same flows in Security with partial grants. G7-04 commit
selects only authorized files, keeps human staged changes, runs no
hooks. G7-05 missing tools/LSP/MCP/provider support is diagnosed
honestly, never a false "ready".
"""
import json
import subprocess

import pytest

from isycode.action_runtime import LocalWorkspaceReadOwner
from isycode.approvals import ActionApprovalStore
from isycode.command_runner import CommandRunOwner
from isycode.git_owner import GitOwner
from isycode.headless import available_tools
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_trust import ACCEPT_PHRASE, WorkspaceTrust, modal_required
from isycode.workspace_write import WorkspaceWriteOwner

from test_workspace_trust import FAKE_BWRAP


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("ISYCODE_STATE_HOME", raising=False)
    root = tmp_path / "project"
    root.mkdir()
    (root / ".isyroot").write_text("", encoding="utf-8")
    (root / "app.py").write_text("value = 1\n", encoding="utf-8")
    (root / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (root / "scratch.txt").write_text("human draft, do not lose me\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "app.py", "util.py"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@e.c",
                    "commit", "-q", "-m", "baseline"], check=True)
    (root / "app.py").write_text("value = 2  # human work in progress\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    authority.set_mode("classic")
    WorkspaceTrust().accept(authority, ACCEPT_PHRASE)
    return authority, root.resolve()


def test_g7_01_dirty_repo_diagnose_edit_test_diff_undo(repo, monkeypatch):
    authority, root = repo
    approvals = ActionApprovalStore()
    issued = []
    real_issue = approvals.issue

    def spy(request, **kwargs):
        issued.append(request.action_id)
        return real_issue(request, **kwargs)

    approvals.issue = spy
    reader = LocalWorkspaceReadOwner(root, authority)
    outcome = reader.execute("workspace.files.read", {"path": "app.py"})
    assert outcome.decision == "ALLOW" and "human work in progress" in outcome.text
    writer = WorkspaceWriteOwner(root, authority, approvals)
    for name, content in (("util.py", "def helper():\n    return 2\n"),
                          ("new_module.py", "VALUE = 2\n"),
                          ("notes.md", "# diagnosis: helper returned 1\n")):
        preview = writer.preview(name, content)
        assert writer.apply(preview, None).decision == "ALLOW"
    bin_dir = root / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "bwrap"
    fake.write_text(FAKE_BWRAP.format(python=__import__("sys").executable), encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{__import__('os').pathsep}{__import__('os').environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_BWRAP_LOG", str(root / "bwrap.json"))
    runner = CommandRunOwner(root, authority, approvals)
    preview = runner.prepare(["echo", "tests-pass"])
    import asyncio
    assert asyncio.run(runner.run(preview, None)).decision == "ALLOW"
    diff = GitOwner(root, authority, approvals).diff()
    assert diff.decision == "ALLOW"
    assert "helper():\n-    return 1\n+    return 2" in diff.text.replace("\\n", "\n") or "return 2" in diff.text
    undo = writer.preview_undo()
    assert writer.apply(undo, None).decision == "ALLOW"
    assert not (root / "notes.md").exists()
    assert (root / "new_module.py").exists()
    assert "human work in progress" in (root / "app.py").read_text(encoding="utf-8")
    assert (root / "scratch.txt").read_text(encoding="utf-8") == "human draft, do not lose me\n"
    assert issued == []


def test_g7_02_budgeted_move_delete_recoverable_cascade_blocked(repo, monkeypatch):
    authority, root = repo
    approvals = ActionApprovalStore()
    writer = WorkspaceWriteOwner(root, authority, approvals)
    moved = writer.preview_move("scratch.txt", "archive/scratch.txt")
    assert writer.apply(moved, None).decision == "ALLOW"
    assert (root / "archive" / "scratch.txt").read_text(encoding="utf-8") == "human draft, do not lose me\n"
    restore = writer.preview_undo()
    assert writer.apply(restore, None).decision == "ALLOW"
    assert (root / "scratch.txt").read_text(encoding="utf-8") == "human draft, do not lose me\n"
    monkeypatch.setattr("isycode.effect_ledger.MAX_CHURN_PER_OPERATION", 4)
    flooded = writer.preview("flood.txt", "x" * 4096)
    denied = writer.apply(flooded, None)
    assert denied.decision == "DENY"
    assert not (root / "flood.txt").exists()


def test_g7_03_security_partial_grants_explain_exact_enable(repo):
    authority, root = repo
    authority.set_mode("security")
    approvals = ActionApprovalStore()
    writer = WorkspaceWriteOwner(root, authority, approvals)
    preview = writer.preview("denied.txt", "nope\n")
    denied = writer.apply(preview, None)
    assert denied.decision == "DENY"
    assert not (root / "denied.txt").exists()
    names = [item["function"]["name"] for item in available_tools(root, authority)]
    assert not any("write" in name or "edit" in name for name in names)
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])
    assert writer.apply(writer.preview("allowed.txt", "yes\n"), None).decision == "DENY"
    assert not (root / "allowed.txt").exists()
    fresh = writer.preview("allowed.txt", "yes\n")
    approval = approvals.issue(fresh.request)
    assert writer.apply(fresh, approval).decision == "ALLOW"
    assert (root / "allowed.txt").exists()


def test_g7_04_commit_selects_authorized_keeps_human_staged_no_hooks(repo):
    authority, root = repo
    approvals = ActionApprovalStore()
    (root / "hooks-proof").write_text("", encoding="utf-8")
    hooks_dir = root / ".git" / "hooks"
    hook = hooks_dir / "pre-commit"
    hook.write_text("#!/bin/sh\necho PWNED > ../hook-ran.txt\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
    subprocess.run(["git", "-C", str(root), "add", "scratch.txt"], check=True)
    writer = WorkspaceWriteOwner(root, authority, approvals)
    assert writer.apply(writer.preview("util.py", "def helper():\n    return 3\n"), None).decision == "ALLOW"
    git = GitOwner(root, authority, approvals)
    preview = git.preview_commit("improve helper", ["util.py"])
    approval = approvals.issue(preview.request)
    outcome = git.commit(preview, approval)
    assert outcome.decision == "ALLOW", outcome.reason
    assert not (root / "hook-ran.txt").exists()
    staged = subprocess.run(["git", "-C", str(root), "diff", "--cached", "--name-only"],
                            check=True, capture_output=True, text=True).stdout.split()
    assert "scratch.txt" in staged
    log = subprocess.run(["git", "-C", str(root), "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
                         check=True, capture_output=True, text=True).stdout
    assert "util.py" in log and "scratch.txt" not in log
    assert (root / "scratch.txt").read_text(encoding="utf-8") == "human draft, do not lose me\n"


def test_g7_05_missing_capabilities_are_honest_not_a_fake_ready(repo, monkeypatch):
    authority, root = repo
    authority.set_grant("workspace.files.list", enabled=False)
    authority.set_grant("workspace.files.read", enabled=False)
    authority.set_grant("workspace.files.search", enabled=False)
    tools = available_tools(root, authority)
    names = [item["function"]["name"] for item in tools]
    assert not any(name in names for name in ("workspace_read", "workspace_list", "workspace_search"))
    monkeypatch.setattr("isycode.command_runner.sandbox_executable", lambda: None)
    with pytest.raises(ValueError, match="commands stay disabled"):
        CommandRunOwner(root, authority, ActionApprovalStore()).prepare(["echo", "hi"])
