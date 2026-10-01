from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import LocalWorkspaceReadOwner, ProductActionGate
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority


def test_valid_read_has_allow_receipt_journal_and_verifiable_chain(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "README.md").write_text("fixture only\n", encoding="utf-8")
    state = tmp_path / "state"
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(state))
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])
    owner = LocalWorkspaceReadOwner(root, authority)

    allowed = owner.execute("workspace.files.read", {"path": "README.md"})
    authority.set_grant("workspace.files.read", enabled=False, path_prefixes=[root])
    denied = owner.execute("workspace.files.read", {"path": "README.md"})
    report = ActionAuditJournal.for_read_only_inspection(root).verify()

    assert allowed.decision == "ALLOW"
    assert allowed.receipt is not None and allowed.receipt.verify(
        ActionRequest("workspace.files.read", root, str(root / "README.md"),
                      {"path": "README.md"}, execution_owner="workspace_read"),
        allowed.text)
    assert denied.decision == "DENY"
    assert "fixture only" not in denied.text
    assert report.status == "PASS"
    assert report.decisions == 2
    assert report.receipts == 1


def test_valid_grant_without_registered_owner_denies_before_effect(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "secret.txt").write_text("must not escape", encoding="utf-8")
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])
    gate = ProductActionGate(root, authority, owner_id="missing_owner")
    request = ActionRequest("workspace.files.read", root, str(root / "secret.txt"),
                            {"path": "secret.txt"}, execution_owner="missing_owner")

    authority_decision, sentinel = gate.authorize(request)

    assert authority_decision.allowed
    assert sentinel.status == "DENY"
    assert any(check.name == "ExecutionOwnerBinding" and not check.passed
               for check in sentinel.checks)
