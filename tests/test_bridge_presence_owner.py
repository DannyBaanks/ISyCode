"""BridgePresenceOwner: the presence read is deny-by-default and digest-bound."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from isycode.approvals import ActionApprovalStore
from isycode.bridge_presence import BridgePresenceOwner
from isycode.workspace_authority import WorkspaceAuthority


def _owner(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / ".isyroot").write_text("")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state")
    authority.set_mode("security")
    return BridgePresenceOwner(root, authority, ActionApprovalStore()), authority


def test_prepare_is_digest_bound_and_read_only(tmp_path):
    owner, _ = _owner(tmp_path)
    request = owner.prepare()
    assert request.action_id == "bridge.agents"
    assert request.execution_owner == "bridge_presence"
    assert len(request.digest) == 64
    assert Path(request.parameters["handshake"]).is_file()


def test_read_denies_without_grant_and_changes_nothing(tmp_path):
    owner, _ = _owner(tmp_path)
    outcome, rows = owner.read(owner.prepare(), None)
    assert outcome.decision == "DENY"
    assert rows == []


def test_read_denies_when_the_reviewed_handshake_changes(tmp_path):
    owner, authority = _owner(tmp_path)
    authority.set_grant("bridge.agents", enabled=True)
    request = owner.prepare()
    tampered = type(request)(request.action_id, request.workspace_root, request.target,
                             {**request.parameters, "operation": "send"},
                             execution_owner=request.execution_owner)
    outcome, rows = owner.read(tampered, None)
    assert outcome.decision == "DENY"
    assert "handshake changed" in outcome.reason
    assert rows == []


def test_read_allow_path_returns_sanitized_rows(tmp_path, monkeypatch):
    owner, authority = _owner(tmp_path)
    authority.set_grant("bridge.agents", enabled=True)
    request = owner.prepare()
    fresh = datetime.now(timezone.utc).isoformat()

    class _Result:
        returncode = 0
        stdout = f"  alpha  caps=[audit] last_hb={fresh} status=working\n"
        stderr = ""

    monkeypatch.setattr("isycode.bridge_presence.subprocess.run", lambda *a, **k: _Result())
    approval = owner.approvals.issue(request)
    outcome, rows = owner.read(request, approval)
    assert outcome.decision == "ALLOW"
    assert rows and rows[0]["name"] == "alpha"
    assert json.loads(outcome.text) == rows
    assert outcome.receipt is not None


def test_read_denies_when_the_subprocess_fails(tmp_path, monkeypatch):
    owner, authority = _owner(tmp_path)
    authority.set_grant("bridge.agents", enabled=True)
    request = owner.prepare()

    def _boom(*args, **kwargs):
        raise OSError("no handshake")

    monkeypatch.setattr("isycode.bridge_presence.subprocess.run", _boom)
    approval = owner.approvals.issue(request)
    outcome, rows = owner.read(request, approval)
    assert outcome.decision == "ERROR"
    assert rows == []
