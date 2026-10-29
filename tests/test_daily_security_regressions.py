"""Adversarial regressions for daily workspace authorization."""
from dataclasses import replace
import os
import subprocess
import sys
from pathlib import Path

import pytest

from isycode.action_runtime import ProductActionGate
from isycode.approvals import ActionApprovalStore
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_write import CheckpointStore, WorkspaceWriteOwner


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "workspace"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    owner = WorkspaceWriteOwner(root, authority, approvals,
                                checkpoints=CheckpointStore(root, tmp_path / "checkpoints"))
    return root, authority, approvals, owner


def test_classic_preserves_explicit_action_revocation(workspace):
    root, authority, _, _ = workspace
    authority.set_mode("classic")
    authority.set_grant("workspace.files.read", enabled=False)
    request = ActionRequest("workspace.files.read", root, str(root / "a.txt"),
                            execution_owner="workspace_read")
    assert not authority.evaluate(request).allowed


def test_undo_rejects_content_not_bound_to_approved_request(workspace):
    root, authority, approvals, owner = workspace
    authority.set_mode("classic")
    target = root / "a.txt"
    target.write_text("original\n")
    write = owner.preview("a.txt", "reviewed\n")
    assert owner.apply(write, approvals.issue(write.request)).decision == "ALLOW"
    undo = owner.preview_undo()
    forged = replace(undo, content="unapproved attacker content\n")
    outcome = owner.apply(forged, approvals.issue(undo.request))
    assert outcome.decision == "DENY"
    assert target.read_text() == "reviewed\n"


def test_delete_rejects_forged_checkpoint_content(workspace):
    root, authority, approvals, owner = workspace
    authority.set_grant("workspace.files.delete", enabled=True, path_prefixes=[root])
    target = root / "a.txt"
    target.write_text("original\n")
    preview = owner.preview_delete("a.txt")
    forged = replace(preview, content="attacker checkpoint\n")
    outcome = owner.apply(forged, approvals.issue(preview.request))
    assert outcome.decision == "DENY"
    assert target.read_text() == "original\n"


def test_gate_rejects_authority_for_another_workspace(workspace, tmp_path):
    root, _, _, _ = workspace
    other = tmp_path / "other"
    other.mkdir()
    other_authority = WorkspaceAuthority(other, state_directory=tmp_path / "other-state")
    other_authority.set_mode("classic")
    request = ActionRequest("session.resume", other, "sessions", {"operation": "list"},
                            execution_owner="chat_sessions")
    gate = ProductActionGate(root, other_authority, owner_id="chat_sessions")
    assert not gate.authorize(request)[1].allowed


@pytest.mark.parametrize("kind", ["write", "move"])
def test_file_change_rejects_unbound_review_display(workspace, kind):
    root, authority, approvals, owner = workspace
    authority.set_grant("workspace.files." + kind, enabled=True, path_prefixes=[root])
    target = root / "a.txt"
    target.write_text("original\n")
    preview = (owner.preview("a.txt", "changed\n") if kind == "write"
               else owner.preview_move("a.txt", "b.txt"))
    forged = replace(preview, diff="Harmless read-only operation; no file changes.\n")
    assert owner.apply(forged, approvals.issue(preview.request)).decision == "DENY"
    assert target.read_text() == "original\n"
    assert not (root / "b.txt").exists()


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='named pipes require POSIX')
def test_reading_a_named_pipe_returns_without_waiting_for_a_writer(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    os.mkfifo(root / 'input.txt')
    source = Path(__file__).resolve().parents[1] / 'src'
    code = '''
import sys
from pathlib import Path
from isycode.workspace_authority import WorkspaceAuthority
from isycode.action_runtime import LocalWorkspaceReadOwner
root = Path(sys.argv[1])
authority = WorkspaceAuthority(root)
authority.set_mode('classic')
outcome = LocalWorkspaceReadOwner(root, authority).execute('workspace.files.read', {'path': 'input.txt'})
assert outcome.decision in {'DENY', 'ERROR'}, outcome
assert outcome.receipt is None
print('refused')
'''
    result = subprocess.run([sys.executable, '-c', code, str(root)],
        env={**os.environ, 'PYTHONPATH': str(source), 'ISYCODE_STATE_HOME': str(tmp_path / 'state')},
        capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'refused'
