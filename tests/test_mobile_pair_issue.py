"""Replacing the Mobile Host PIN is an owned, granted, approved and journaled action."""
from pathlib import Path

import pytest

from isycode.action_runtime import ProductActionGate
from isycode.approvals import ActionApprovalStore
from isycode.authority_view import MOBILE_PAIR_ACTIONS, mobile_host_enabled
from isycode.mobile_host import MobileHost, MobileHostOwner
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority


@pytest.fixture
def pin_owner(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "workspace"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    owner = MobileHostOwner(root, authority, approvals, host=MobileHost())
    # Simulate a running loopback host without opening a socket in this test.
    owner.host._state = "ready"
    first_pin, _ = owner.host.rotate_pairing_code()
    return owner, authority, approvals, first_pin, tmp_path


def _grant(authority):
    authority.set_grant("mobile.host.start", enabled=True, network_hosts=["127.0.0.1:8765"])
    for action in MOBILE_PAIR_ACTIONS:
        authority.set_grant(action, enabled=True, targets=["mobile-host"])


def test_new_pin_requires_the_issue_grant(pin_owner):
    owner, authority, approvals, first_pin, _ = pin_owner
    request = owner.pin_request()
    issued, _, pin = owner.issue_pairing_pin(request, approvals.issue(request))
    assert not issued and pin is None
    assert owner.host.pairing_code_for_local_settings() == first_pin


def test_new_pin_requires_a_fresh_one_use_approval(pin_owner):
    owner, authority, approvals, first_pin, _ = pin_owner
    _grant(authority)
    request = owner.pin_request()
    assert owner.issue_pairing_pin(request, None)[0] is False
    assert owner.host.pairing_code_for_local_settings() == first_pin

    approval = approvals.issue(request)
    issued, _, pin = owner.issue_pairing_pin(request, approval)
    assert issued and pin and pin != first_pin
    # The approval was bound to the replaced challenge and consumed.
    assert owner.issue_pairing_pin(request, approval)[0] is False


def test_new_pin_invalidates_the_old_one_clears_lockout_and_stays_out_of_the_journal(pin_owner):
    owner, authority, approvals, first_pin, tmp_path = pin_owner
    _grant(authority)
    owner.host._pair_global_failures = [0.0] * 50
    request = owner.pin_request()
    issued, _, pin = owner.issue_pairing_pin(request, approvals.issue(request))

    assert issued
    assert owner.host.pairing_code_for_local_settings() == pin
    assert owner.host._pair_global_failures == []
    stored = b"".join(path.read_bytes() for path in (tmp_path / "state").rglob("*")
                      if path.is_file())
    assert pin.encode() not in stored and first_pin.encode() not in stored


def test_stale_request_after_the_pin_changed_is_refused(pin_owner):
    owner, authority, approvals, _, _ = pin_owner
    _grant(authority)
    stale = owner.pin_request()
    owner.host.rotate_pairing_code()
    issued, reason, pin = owner.issue_pairing_pin(stale, approvals.issue(stale))
    assert not issued and pin is None and "changed" in reason


def test_no_pin_is_issued_while_the_host_is_stopped(pin_owner):
    owner, authority, approvals, _, _ = pin_owner
    _grant(authority)
    owner.host._state = "stopped"
    request = owner.pin_request()
    assert owner.issue_pairing_pin(request, approvals.issue(request)) == (
        False, "Mobile Host is not running", None)


@pytest.mark.parametrize("target, parameters", [
    ("mobile-host", {"host": "0.0.0.0:8765", "replaces_challenge": "none"}),
    ("mobile-host", {"host": "127.0.0.1:8765", "replaces_challenge": "none", "ttl": 3600}),
    ("mobile-host", {"host": "127.0.0.1:8765", "replaces_challenge": "not-a-challenge"}),
    ("elsewhere", {"host": "127.0.0.1:8765", "replaces_challenge": "none"}),
])
def test_sentinel_rejects_any_other_pin_request_shape(pin_owner, target, parameters):
    owner, authority, approvals, _, _ = pin_owner
    _grant(authority)
    authority.set_grant("mobile.pair.issue", enabled=True, targets=["mobile-host", "elsewhere"])
    request = ActionRequest("mobile.pair.issue", owner.root, target, parameters,
                            execution_owner="mobile_host")
    gate = ProductActionGate(owner.root, authority, owner_id="mobile_host")
    assert not gate.authorize(request, approvals=approvals,
                              approval=approvals.issue(request))[1].allowed


def test_mobile_host_toggle_covers_the_issue_grant():
    start = {"enabled": True, "network_hosts": ["127.0.0.1:8765"]}
    pair = {"enabled": True, "targets": ["mobile-host"]}
    assert not mobile_host_enabled({"mobile.host.start": start, "mobile.pair": pair})
    assert mobile_host_enabled({"mobile.host.start": start, "mobile.pair": pair,
                                "mobile.pair.issue": pair})


def test_tui_replaces_the_pin_only_through_the_owner():
    import ast

    source = (Path(__file__).resolve().parents[1] / "src" / "isycode" / "tui.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    method = next(node for node in app.body
                  if isinstance(node, ast.AsyncFunctionDef) and node.name == "_issue_pairing_pin")
    # to_thread receives the owner method by reference, so check attribute uses.
    used = {node.attr for node in ast.walk(method) if isinstance(node, ast.Attribute)}
    assert "issue_pairing_pin" in used and "rotate_pairing_code" not in used
