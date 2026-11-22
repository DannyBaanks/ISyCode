"""EditPack: one manifest, one approval, all-or-rollback and explicit recovery."""
import hashlib
import os
from dataclasses import replace
from pathlib import Path

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.effect_ledger import CrashInjected
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_transaction import WorkspaceTransactionOwner
from isycode.workspace_trust import QUIET_CLASSIC_ACTIONS, QUIET_FLOW_ACTIONS

pytestmark = pytest.mark.skipif(os.name == "nt", reason="descriptor-safe writes are POSIX-only")


@pytest.fixture
def pack(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state" / "isycode"))
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    (root / "b.txt").write_text("b\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])
    approvals = ActionApprovalStore()
    owner = WorkspaceTransactionOwner(root, authority, approvals)
    return owner, authority, approvals, root.resolve()


def _preview(owner):
    return owner.preview([
        {"path": "a.txt", "old_text": "a", "new_text": "A"},
        {"path": "b.txt", "content": "B\n"},
    ])


def test_pack_applies_once_and_replays_the_same_receipt(pack):
    owner, _, approvals, root = pack
    preview = _preview(owner)
    assert preview.request.action_id == "workspace.files.transaction"
    assert len(preview.request.parameters["operations"]) == 2
    outcome = owner.apply(preview, approvals.issue(preview.request))
    assert outcome.decision == "ALLOW" and outcome.receipt is not None
    assert (root / "a.txt").read_text() == "A\n"
    assert (root / "b.txt").read_text() == "B\n"

    restarted = WorkspaceTransactionOwner(root, owner.authority, ActionApprovalStore())
    replay = restarted.apply(preview, None)
    assert replay.decision == "ALLOW"
    assert replay.receipt.receipt_id == outcome.receipt.receipt_id
    assert replay.text == outcome.text


def test_pack_requires_grant_and_one_fresh_approval(pack):
    owner, authority, approvals, root = pack
    preview = _preview(owner)
    authority.set_grant("workspace.files.write", enabled=False)
    assert owner.apply(preview, approvals.issue(preview.request)).decision == "DENY"
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])
    assert owner.apply(preview, None).decision == "DENY"
    assert (root / "a.txt").read_text() == "a\n"
    assert (root / "b.txt").read_text() == "b\n"


def test_every_pack_path_must_be_granted(pack):
    owner, authority, approvals, root = pack
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root / "a.txt"])
    preview = _preview(owner)
    outcome = owner.apply(preview, approvals.issue(preview.request))
    assert outcome.decision == "DENY"
    assert "every edit pack path" in outcome.reason
    assert (root / "a.txt").read_text() == "a\n"
    assert (root / "b.txt").read_text() == "b\n"


def test_pack_is_not_in_quiet_profiles(pack):
    owner, _, _, _ = pack
    preview = _preview(owner)
    assert preview.request.action_id not in QUIET_CLASSIC_ACTIONS
    assert preview.request.action_id not in QUIET_FLOW_ACTIONS


def test_drift_after_review_is_refused(pack):
    owner, _, approvals, root = pack
    preview = _preview(owner)
    (root / "a.txt").write_text("human\n")
    outcome = owner.apply(preview, approvals.issue(preview.request))
    assert outcome.decision == "DENY"
    assert (root / "a.txt").read_text() == "human\n"
    assert (root / "b.txt").read_text() == "b\n"


def test_tampered_manifest_is_refused(pack):
    owner, _, approvals, _ = pack
    preview = _preview(owner)
    request = ActionRequest(preview.request.action_id, preview.request.workspace_root,
                            preview.request.target,
                            {**preview.request.parameters, "manifest_sha256": "0" * 64},
                            execution_owner=preview.request.execution_owner)
    tampered = replace(preview, request=request)
    assert owner.apply(tampered, approvals.issue(request)).decision == "DENY"


def test_a_new_preview_can_retry_after_a_rollback(pack, monkeypatch):
    owner, _, approvals, root = pack
    preview = _preview(owner)
    import isycode.workspace_transaction as module
    real_apply = module.apply_file

    def fail_second(root, relative, payload, **kwargs):
        if relative == "b.txt":
            raise OSError("synthetic second-file failure")
        return real_apply(root, relative, payload, **kwargs)

    monkeypatch.setattr(module, "apply_file", fail_second)
    assert owner.apply(preview, approvals.issue(preview.request)).decision == "ERROR"
    monkeypatch.setattr(module, "apply_file", real_apply)
    # The same preview is the historical rolled-back operation. A fresh preview
    # is a new operation and may be approved and applied.
    assert owner.apply(preview, None).decision == "ERROR"
    retry = _preview(owner)
    assert retry.nonce != preview.nonce
    outcome = owner.apply(retry, approvals.issue(retry.request))
    assert outcome.decision == "ALLOW"
    assert (root / "a.txt").read_text() == "A\n"
    assert (root / "b.txt").read_text() == "B\n"


def test_failure_of_one_file_rolls_back_the_whole_pack(pack, monkeypatch):
    owner, _, approvals, root = pack
    preview = _preview(owner)
    import isycode.workspace_transaction as module
    real_apply = module.apply_file

    def fail_second(root, relative, payload, **kwargs):
        if relative == "b.txt":
            raise OSError("synthetic second-file failure")
        return real_apply(root, relative, payload, **kwargs)

    monkeypatch.setattr(module, "apply_file", fail_second)
    outcome = owner.apply(preview, approvals.issue(preview.request))
    assert outcome.decision == "ERROR"
    assert "rolled back" in outcome.text.lower()
    assert (root / "a.txt").read_text() == "a\n"
    assert (root / "b.txt").read_text() == "b\n"


@pytest.mark.parametrize("path", ["../outside", ".env", ".git/config", ".isyroot"])
def test_sensitive_or_outside_paths_are_refused(pack, path):
    owner, _, _, _ = pack
    with pytest.raises(ValueError):
        owner.preview([{"path": path, "content": "x\n"}])


def test_pack_limits_and_input_validation(pack):
    owner, _, _, root = pack
    with pytest.raises(ValueError, match="same path"):
        owner.preview([{"path": "a.txt", "content": "A\n"},
                       {"path": "a.txt", "content": "AA\n"}])
    with pytest.raises(ValueError, match="1-8"):
        owner.preview([{"path": f"f{i}.txt", "content": "x\n"} for i in range(9)])
    with pytest.raises(ValueError, match="48 KiB"):
        owner.preview([{"path": "big.txt", "content": "x" * (49 * 1024)}])
    with pytest.raises(ValueError, match="parent folders"):
        owner.preview([{"path": "missing/file.txt", "content": "x\n"}])
    with pytest.raises(ValueError, match="either content"):
        owner.preview([{"path": "a.txt", "content": "A\n", "old_text": "a", "new_text": "A"}])


def test_a_parent_disappearing_after_review_is_not_recreated(pack):
    owner, _, approvals, root = pack
    (root / "sub").mkdir()
    preview = owner.preview([{"path": "sub/new.txt", "content": "new\n"}])
    (root / "sub").rmdir()
    outcome = owner.apply(preview, approvals.issue(preview.request))
    assert outcome.decision == "DENY"
    assert not (root / "sub").exists()


def test_expected_sha256_binds_the_read_file(pack):
    owner, _, _, root = pack
    before = hashlib.sha256((root / "a.txt").read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="changed since you read it"):
        owner.preview([{"path": "a.txt", "content": "A\n", "expected_sha256": "0" * 64}])
    preview = owner.preview([{"path": "a.txt", "content": "A\n", "expected_sha256": before}])
    assert preview.paths == ("a.txt",)
    created = owner.preview([{"path": "new.txt", "content": "new\n", "expected_sha256": "absent"}])
    assert created.operations[0].created is True


@pytest.mark.parametrize("phase,expected_decision,expected_files", [
    ("after-reserve", "ALLOW", ("A\n", "B\n")),
    ("after-backup", "ALLOW", ("A\n", "B\n")),
    ("after-plan", "ALLOW", ("A\n", "B\n")),
    ("after-operation-claim", "ERROR", ("a\n", "b\n")),
    ("before-apply:0", "ERROR", ("a\n", "b\n")),
    ("after-mark-applying:0", "ERROR", ("a\n", "b\n")),
    ("after-apply:0", "ERROR", ("a\n", "b\n")),
    ("after-mark-applied:0", "ERROR", ("a\n", "b\n")),
    ("before-commit", "NOT_VERIFIABLE", ("A\n", "B\n")),
    ("after-ledger-commit", "NOT_VERIFIABLE", ("A\n", "B\n")),
    ("after-action-receipt", "NOT_VERIFIABLE", ("A\n", "B\n")),
    ("after-operation-receipt", "ALLOW", ("A\n", "B\n")),
])
def test_crash_windows_settle_without_repeating_an_effect(
        pack, phase, expected_decision, expected_files):
    owner, authority, approvals, root = pack
    preview = _preview(owner)
    with pytest.raises(CrashInjected):
        owner.apply(preview, approvals.issue(preview.request), crash_at=phase)
    restarted = WorkspaceTransactionOwner(root, authority, ActionApprovalStore())
    # Before the operation claim no effect was registered, so a new approval is
    # required. After it, recovery never consumes another approval.
    approval = None if expected_decision != "ALLOW" or phase == "after-operation-receipt" \
        else restarted.approvals.issue(preview.request)
    outcome = restarted.apply(preview, approval)
    assert outcome.decision == expected_decision, outcome.reason
    assert (root / "a.txt").read_text() == expected_files[0]
    assert (root / "b.txt").read_text() == expected_files[1]


def test_human_divergence_during_crash_is_uncertain_not_rolled_back(pack):
    owner, authority, approvals, root = pack
    preview = _preview(owner)
    with pytest.raises(CrashInjected):
        owner.apply(preview, approvals.issue(preview.request), crash_at="after-apply:0")
    (root / "a.txt").write_text("human bytes\n")
    restarted = WorkspaceTransactionOwner(root, authority, ActionApprovalStore())
    outcome = restarted.apply(preview, None)
    assert outcome.decision == "NOT_VERIFIABLE"
    assert (root / "a.txt").read_text() == "human bytes\n"
    assert (root / "b.txt").read_text() == "b\n"


def test_mode_divergence_during_crash_is_uncertain(pack):
    owner, authority, approvals, root = pack
    preview = _preview(owner)
    with pytest.raises(CrashInjected):
        owner.apply(preview, approvals.issue(preview.request), crash_at="after-apply:0")
    (root / "a.txt").chmod(0o600)
    restarted = WorkspaceTransactionOwner(root, authority, ActionApprovalStore())
    outcome = restarted.apply(preview, None)
    assert outcome.decision == "NOT_VERIFIABLE"
    assert (root / "a.txt").read_text() == "A\n"
    assert (root / "a.txt").stat().st_mode & 0o777 == 0o600
