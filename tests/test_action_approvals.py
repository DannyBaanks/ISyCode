from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

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
    original_decision = authority.evaluate(approved, approvals=approvals, approval=token)

    assert not decision.allowed
    assert original_decision.allowed


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


def test_concurrent_approval_replay_can_succeed_only_once(tmp_path):
    request = ActionRequest("role.select", tmp_path)
    store = ActionApprovalStore()
    approval = store.issue(request)
    barrier = Barrier(8)

    def consume():
        barrier.wait()
        return store.consume(request, approval)

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _index: consume(), range(8)))

    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 7


@pytest.mark.parametrize("ttl", [float("nan"), float("inf"), "not-a-number"])
def test_approval_rejects_non_finite_or_invalid_lifetime(tmp_path, ttl):
    request = ActionRequest("role.select", tmp_path)

    with pytest.raises(ValueError, match="finite number"):
        ActionApprovalStore().issue(request, ttl_seconds=ttl)


def test_approval_pending_store_has_a_hard_capacity(tmp_path, monkeypatch):
    request = ActionRequest("role.select", tmp_path)
    store = ActionApprovalStore()
    monkeypatch.setattr(ActionApprovalStore, "MAX_PENDING_APPROVALS", 1)
    store.issue(request)

    with pytest.raises(RuntimeError, match="Too many pending approvals"):
        store.issue(request)


def test_expired_approval_is_removed_and_cannot_authorize(tmp_path, monkeypatch):
    import isycode.approvals as approvals_module

    request = ActionRequest("role.select", tmp_path)
    now = 100.0
    monkeypatch.setattr(approvals_module.time, "monotonic", lambda: now)
    store = ActionApprovalStore()
    approval = store.issue(request, ttl_seconds=1)
    now += 2

    assert not store.consume(request, approval)
    assert approval.token not in store._tokens
