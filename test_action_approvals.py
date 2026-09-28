from pathlib import Path

from isycode.approvals import ActionApprovalStore
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority


def test_approval_is_bound_to_request_digest_and_consumed_once(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state")
    authority.set_grant("workspace.files.delete", enabled=True,
                        path_prefixes=[root])
    approvals = ActionApprovalStore()
    request = ActionRequest("workspace.files.delete", root, target="old.txt")
    token = approvals.issue(request)

    allowed = authority.evaluate(request, approvals=approvals, approval=token)
    replay = authority.evaluate(request, approvals=approvals, approval=token)

    assert allowed.allowed
    assert not replay.allowed


def test_approval_for_one_target_cannot_authorize_another(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state")
    authority.set_grant("workspace.files.delete", enabled=True,
                        path_prefixes=[root])
    approvals = ActionApprovalStore()
    approved = ActionRequest("workspace.files.delete", root, target="old.txt")
    changed = ActionRequest("workspace.files.delete", root, target="important.txt")
    token = approvals.issue(approved)

    decision = authority.evaluate(changed, approvals=approvals, approval=token)

    assert not decision.allowed


def test_action_requiring_approval_denies_without_fresh_human_token(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state")
    authority.set_grant("workspace.files.delete", enabled=True,
                        path_prefixes=[root])
    request = ActionRequest("workspace.files.delete", root, target="old.txt")

    decision = authority.evaluate(request)

    assert not decision.allowed
    assert "approval" in decision.reason.casefold()


def test_approval_token_does_not_reveal_secret_in_repr(tmp_path):
    request = ActionRequest("role.select", tmp_path)
    token = ActionApprovalStore().issue(request)

    assert token.token not in repr(token)
