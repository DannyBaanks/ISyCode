"""Settings shows every saved grant, and never shows a runtime DENY as ON."""
from pathlib import Path

from isycode.action_runtime import ProductActionGate
from isycode.actions import ACTION_CATALOG
from isycode.approvals import ActionApprovalStore
from isycode.authority_view import (
    DEDICATED_CONTROLS, mobile_host_enabled, mobile_host_saved, other_saved_grants,
)
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority


def _all_saved() -> dict:
    return {action.id: {"enabled": True, "targets": ["t"]} for action in ACTION_CATALOG}


def test_every_saved_grant_has_a_visible_control_or_row():
    grants = _all_saved()
    listed = {row.action_id for row in other_saved_grants(grants)}
    assert listed | set(DEDICATED_CONTROLS) == {action.id for action in ACTION_CATALOG}
    assert not listed & set(DEDICATED_CONTROLS)


def test_other_saved_rows_mark_ownerless_grants_as_blocked():
    rows = {row.action_id: row for row in other_saved_grants(_all_saved())}
    assert rows["session.create"].state == "blocked"
    assert rows["bridge.connect"].state == "blocked"
    assert rows["tailscale.serve.enable"].state == "on"
    assert rows["tailscale.serve.enable"].approval_required is True


def test_disabled_grants_are_not_listed():
    assert other_saved_grants({"session.delete": {"enabled": False}}) == []


def test_mobile_host_toggle_requires_every_scoped_grant_and_reports_partials():
    start = {"enabled": True, "network_hosts": ["127.0.0.1:8765"]}
    pair = {"enabled": True, "targets": ["mobile-host"]}
    full = {"mobile.host.start": start, "mobile.pair": pair, "mobile.pair.issue": pair}
    assert mobile_host_enabled(full)
    assert not mobile_host_enabled({"mobile.host.start": start, "mobile.pair": pair})
    assert not mobile_host_enabled({"mobile.host.start": start})
    assert mobile_host_saved({"mobile.host.start": start})
    wrong_scope = {"enabled": True, "network_hosts": ["0.0.0.0:8765"]}
    assert not mobile_host_enabled({**full, "mobile.host.start": wrong_scope})
    assert not mobile_host_saved({})


def test_revoking_mobile_host_grants_makes_the_runtime_deny_start(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    root = tmp_path / "workspace"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    request = ActionRequest("mobile.host.start", root, "127.0.0.1:8765",
                            {"bind": "127.0.0.1", "port": 8765, "transport": "loopback"},
                            execution_owner="mobile_host")
    gate = ProductActionGate(root, authority, owner_id="mobile_host")

    authority.set_grant("mobile.host.start", enabled=True, network_hosts=["127.0.0.1:8765"])
    for action in ("mobile.pair", "mobile.pair.issue"):
        authority.set_grant(action, enabled=True, targets=["mobile-host"])
    assert gate.authorize(request, approvals=approvals,
                          approval=approvals.issue(request))[1].allowed

    # Same writes as TUIApp._change_mobile_host_grant(False).
    authority.set_grant("mobile.host.start", enabled=False, network_hosts=[])
    for action in ("mobile.pair", "mobile.pair.issue"):
        authority.set_grant(action, enabled=False, targets=[])
    grants = authority.policy()["grants"]
    assert not mobile_host_enabled(grants) and not mobile_host_saved(grants)
    assert not gate.authorize(request, approvals=approvals,
                              approval=approvals.issue(request))[1].allowed
