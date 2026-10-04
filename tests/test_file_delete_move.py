"""Delete and move: owned, approved, verified, undoable, never outside the grant."""
import os
from pathlib import Path

import pytest

import isycode.action_runtime as action_runtime
import isycode.workspace_write as workspace_write
from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import EXPLICIT_DENY_ACTIONS, ProductActionGate
from isycode.approvals import ActionApprovalStore
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_write import WorkspaceWriteOwner

GRANTS = ("workspace.files.write", "workspace.files.restore",
          "workspace.files.delete", "workspace.files.move")


@pytest.fixture(params=["descriptors", "verified"])
def workspace(request, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    if request.param == "verified":
        if not os.path.exists("/proc/self/fd"):
            pytest.skip("verified mode needs /proc/self/fd on this host")
        monkeypatch.setattr(action_runtime, "use_verified_fs", lambda: True)
        monkeypatch.setattr(workspace_write, "use_verified_fs", lambda: True)
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "old.py").write_text("x = 1\n")
    (root / "logo.bin").write_bytes(b"\x00\xff" * 100)
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    approvals = ActionApprovalStore()
    return WorkspaceWriteOwner(root, authority, approvals), authority, approvals, root.resolve()


def _grant(authority, root, prefix=None):
    for action in GRANTS:
        authority.set_grant(action, enabled=True, path_prefixes=[prefix or root])


def _apply(owner, approvals, preview):
    return owner.apply(preview, approvals.issue(preview.request))


def test_delete_and_move_are_owned_not_explicitly_denied():
    assert not {"workspace.files.delete", "workspace.files.move"} & EXPLICIT_DENY_ACTIONS


def test_delete_shows_the_content_needs_approval_and_undo_restores_it(workspace):
    owner, authority, approvals, root = workspace
    _grant(authority, root)
    preview = owner.preview_delete("src/old.py")
    assert "-x = 1" in preview.diff
    assert owner.apply(preview, None).decision == "DENY"
    assert _apply(owner, approvals, preview).decision == "ALLOW"
    assert not (root / "src" / "old.py").exists()
    undo = owner.preview_undo()
    assert "+x = 1" in undo.diff
    assert _apply(owner, approvals, undo).decision == "ALLOW"
    assert (root / "src" / "old.py").read_text() == "x = 1\n"
    assert ActionAuditJournal(root).verify().receipts == 2


def test_a_file_edited_after_review_is_not_deleted(workspace):
    owner, authority, approvals, root = workspace
    _grant(authority, root)
    preview = owner.preview_delete("src/old.py")
    (root / "src" / "old.py").write_text("x = 2\n")
    assert _apply(owner, approvals, preview).decision == "DENY"
    assert (root / "src" / "old.py").exists()


def test_move_creates_folders_never_overwrites_and_undo_moves_back(workspace):
    owner, authority, approvals, root = workspace
    _grant(authority, root)
    preview = owner.preview_move("logo.bin", "assets/img/logo.bin")
    assert "rename to assets/img/logo.bin" in preview.diff
    assert _apply(owner, approvals, preview).decision == "ALLOW"
    assert (root / "assets" / "img" / "logo.bin").read_bytes() == b"\x00\xff" * 100
    assert not (root / "logo.bin").exists()
    (root / "taken.py").write_text("keep\n")
    with pytest.raises(ValueError, match="never overwrite"):
        owner.preview_move("src/old.py", "taken.py")
    undo = owner.preview_undo()
    assert undo.is_undo and _apply(owner, approvals, undo).decision == "ALLOW"
    assert (root / "logo.bin").exists() and not (root / "assets" / "img" / "logo.bin").exists()
    with pytest.raises(ValueError):
        owner.preview_undo()  # the only remaining checkpoints are undone


def test_a_destination_created_after_review_is_not_overwritten(workspace):
    owner, authority, approvals, root = workspace
    _grant(authority, root)
    preview = owner.preview_move("src/old.py", "src/new.py")
    (root / "src" / "new.py").write_text("someone else\n")
    assert _apply(owner, approvals, preview).decision != "ALLOW"
    assert (root / "src" / "new.py").read_text() == "someone else\n"
    assert (root / "src" / "old.py").read_text() == "x = 1\n"


def test_move_destination_must_be_inside_the_granted_paths(workspace):
    owner, authority, approvals, root = workspace
    _grant(authority, root, prefix=root / "src")
    preview = owner.preview_move("src/old.py", "outside_grant.py")
    outcome = _apply(owner, approvals, preview)
    assert outcome.decision == "DENY" and "destination" in outcome.reason
    assert (root / "src" / "old.py").exists()


@pytest.mark.parametrize("path, to", [
    ("src/old.py", ".env"), ("src/old.py", ".isyroot"), ("src/old.py", "../escape.py"),
    (".git/config", "x.py"),
])
def test_sensitive_or_escaping_moves_are_refused(workspace, path, to):
    owner, authority, _, root = workspace
    _grant(authority, root)
    with pytest.raises((OSError, ValueError)):
        owner.preview_move(path, to)


def test_classic_allows_delete_and_move_only_with_an_approval(workspace):
    owner, authority, approvals, root = workspace
    authority.set_mode("classic")
    delete = owner.preview_delete("src/old.py")
    assert owner.apply(delete, None).decision == "DENY"
    assert (root / "src" / "old.py").exists()
    move = owner.preview_move("src/old.py", "a.py")
    assert _apply(owner, approvals, move).decision == "ALLOW"
    assert (root / "a.py").exists() and not (root / "src" / "old.py").exists()


@pytest.mark.parametrize("change", [
    {"to": ".env"}, {"to": "../x.py"}, {"undo_of": "nope"}, {"new_folders": ("elsewhere",)},
    {"sha256": "x"}, {"extra": 1},
])
def test_boundary_rejects_forged_moves(workspace, change):
    owner, authority, approvals, root = workspace
    _grant(authority, root)
    preview = owner.preview_move("src/old.py", "lib/new.py")
    params = {**dict(preview.request.parameters), **change}
    request = ActionRequest("workspace.files.move", root, preview.request.target, params,
                            execution_owner="workspace_write")
    gate = ProductActionGate(root, authority, owner_id="workspace_write")
    _, decision = gate.authorize(request, approvals=approvals, approval=approvals.issue(request))
    assert not decision.allowed


def test_toolkit_button_grants_only_what_the_computer_supports(tmp_path, monkeypatch):
    from isycode.tui import TUIApp

    monkeypatch.setattr("isycode.tui_app_authority.sandbox_executable", lambda: None)
    app = TUIApp.__new__(TUIApp)
    app._workspace_root = tmp_path
    app._lsp_inventory = []
    actions = {action for action, _, _ in TUIApp._coding_toolkit_grants(app)}
    assert {"workspace.files.read", "workspace.files.delete", "workspace.files.move"} <= actions
    assert "workspace.command.run" not in actions and "git.commit" not in actions
    assert "lsp.diagnostics" not in actions
