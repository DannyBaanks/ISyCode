"""Fail-closed authority contracts for the optional private Tailscale flow."""
from dataclasses import replace

import pytest

from isycode.actions import ACTION_BY_ID
from isycode import action_runtime
from isycode.action_runtime import ProductActionGate
from isycode.approvals import ActionApprovalStore
from isycode.private_access import OwnedServeRoute
from isycode.security import ActionRequest, AuthorityDecision
from isycode.tailscale import ServeRoute
from isycode.workspace_authority import WorkspaceAuthority


ACTION_OWNER = {
    "tailscale.inspect": "tailscale_read",
    "tailscale.install": "tailscale_package_install",
    "tailscale.login": "tailscale_login",
    "tailscale.serve.enable": "tailscale_serve",
    "tailscale.serve.disable": "tailscale_serve",
}
GATEWAY = "http://127.0.0.1:8787"
HOST = "device.tail123.ts.net"
DIGEST = "a" * 64


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    cli = tmp_path / "tailscale"
    apt = tmp_path / "apt-get"
    wrong = tmp_path / "other"
    for path in (cli, apt, wrong):
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(0o700)
    route = ServeRoute(HOST, "/", GATEWAY, True)
    owned = OwnedServeRoute("isycode-gateway", HOST, "/", GATEWAY,
                            "2026-09-29T00:00:00Z", "online")
    facts = action_runtime.TailscaleAuthorityFacts(
        cli_executable=str(cli), package_manager=str(apt), os_id="ubuntu",
        os_codename="noble", gateway_url=GATEWAY, gateway_port=8787,
        route_id="isycode-gateway", proposed_route=route, live_routes=(route,),
        serve_inventory_complete=True, owned_route=owned,
        serve_digest=DIGEST,
    )
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    return root, cli, apt, wrong, facts, authority, approvals


def request_for(setup, action_id, **changes):
    root, cli, apt, _, _, _, _ = setup
    parameters = {
        "tailscale.inspect": {"executable": str(cli), "gateway_url": GATEWAY,
                              "gateway_port": 8787},
        "tailscale.install": {
            "executable": str(apt), "os_id": "ubuntu", "os_codename": "noble",
            "repository_key_url": "https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg",
            "repository_list_url": "https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list",
            "package": "tailscale",
            "package_service_effect": "may_start_or_restart_tailscaled",
        },
        "tailscale.login": {"executable": str(cli), "operation": "login"},
        "tailscale.serve.enable": {
            "executable": str(cli), "gateway_url": GATEWAY, "gateway_port": 8787,
            "route_id": "isycode-gateway", "route_host": HOST, "route_path": "/",
            "route_target": GATEWAY, "serve_digest": DIGEST, "mode": "private",
            "funnel": False,
        },
        "tailscale.serve.disable": {
            "executable": str(cli), "gateway_url": GATEWAY, "gateway_port": 8787,
            "route_id": "isycode-gateway", "route_host": HOST, "route_path": "/",
            "route_target": GATEWAY, "serve_digest": DIGEST, "mode": "private",
            "funnel": False,
        },
    }[action_id]
    parameters.update(changes)
    return ActionRequest(action_id, root, "tailscale", parameters,
                         execution_owner=ACTION_OWNER[action_id])


def authorize(setup, request, *, facts=None, approval=None):
    root, _, _, _, default_facts, authority, approvals = setup
    gate = ProductActionGate(root, authority, owner_id=request.execution_owner,
                             tailscale_facts=default_facts if facts is None else facts)
    return gate.authorize(request, approvals=approvals, approval=approval)[1]


def test_tailscale_catalog_effects_and_approval_contract():
    assert {(action, ACTION_BY_ID[action].effect, ACTION_BY_ID[action].approval_required)
            for action in ACTION_OWNER} == {
        ("tailscale.inspect", "read", False),
        ("tailscale.install", "process", True),
        ("tailscale.login", "process", True),
        ("tailscale.serve.enable", "process", True),
        ("tailscale.serve.disable", "process", True),
    }


@pytest.mark.parametrize("action_id", ACTION_OWNER)
def test_tailscale_actions_require_exact_grant_owner_and_fresh_approval(setup, action_id):
    root, cli, apt, wrong, facts, authority, approvals = setup
    request = request_for(setup, action_id)
    assert authorize(setup, request).status == "DENY"  # No grant.
    if action_id == "tailscale.inspect":
        authority.set_grant(action_id, enabled=True)
    else:
        authority.set_grant(action_id, enabled=True, executables=[cli, apt, wrong])
    assert authorize(setup, request).status == (
        "ALLOW" if action_id == "tailscale.inspect" else "DENY")

    other_owner = "tailscale_login" if request.execution_owner != "tailscale_login" else "tailscale_read"
    crossed = replace(request, execution_owner=other_owner)
    gate = ProductActionGate(root, authority, owner_id=other_owner, tailscale_facts=facts)
    crossed_approval = approvals.issue(crossed) if action_id != "tailscale.inspect" else None
    assert gate.authorize(crossed, approvals=approvals, approval=crossed_approval)[1].status == "DENY"

    if action_id == "tailscale.inspect":
        assert authorize(setup, request).status == "ALLOW"
    else:
        approval = approvals.issue(request)
        assert authorize(setup, request, approval=approval).status == "ALLOW"
        assert authorize(setup, request, approval=approval).status == "DENY"  # Replay.
        forged = replace(approvals.issue(request), expires_at=0)
        assert authorize(setup, request, approval=forged).status == "DENY"
        altered = replace(request, parameters={**request.parameters, "unexpected": True})
        assert authorize(setup, altered, approval=approvals.issue(request)).status == "DENY"


@pytest.mark.parametrize("action_id", ACTION_OWNER)
def test_tailscale_request_parameters_fail_closed(setup, action_id):
    root, cli, apt, wrong, facts, authority, approvals = setup
    if action_id == "tailscale.inspect":
        authority.set_grant(action_id, enabled=True)
    else:
        authority.set_grant(action_id, enabled=True, executables=[cli, apt, wrong])
    invalid_changes = [{"executable": str(wrong)}, {"unexpected": True}]
    if action_id == "tailscale.install":
        invalid_changes += [{"package": "other"}, {"os_id": "fedora"},
                            {"repository_key_url": "https://evil.example/key"},
                            {"package_service_effect": "no_service_start"}]
    if action_id in {"tailscale.inspect", "tailscale.serve.enable", "tailscale.serve.disable"}:
        invalid_changes += [{"gateway_url": "http://0.0.0.0:8787"},
                            {"gateway_port": 8788}]
    if action_id.startswith("tailscale.serve."):
        invalid_changes += [{"mode": "public"}, {"funnel": True},
                            {"route_id": "forged"}, {"route_host": "other.tail123.ts.net"},
                            {"route_target": "http://127.0.0.1:9999"},
                            {"serve_digest": "b" * 64}]
    for change in invalid_changes:
        request = request_for(setup, action_id, **change)
        approval = approvals.issue(request) if action_id != "tailscale.inspect" else None
        assert authorize(setup, request, approval=approval).status == "DENY", change


def test_tailscale_disable_requires_matching_owned_live_route(setup):
    root, cli, _, _, facts, authority, approvals = setup
    authority.set_grant("tailscale.serve.disable", enabled=True, executables=[cli])
    request = request_for(setup, "tailscale.serve.disable")
    forged = replace(facts, owned_route=replace(facts.owned_route, host="other.tail123.ts.net"))
    assert authorize(setup, request, facts=forged,
                     approval=approvals.issue(request)).status == "DENY"
    assert authorize(setup, request, facts=replace(facts, owned_route=None),
                     approval=approvals.issue(request)).status == "DENY"


def test_tailscale_empty_serve_configuration_can_enable(setup):
    root, cli, _, _, facts, authority, approvals = setup
    authority.set_grant("tailscale.serve.enable", enabled=True, executables=[cli])
    request = request_for(setup, "tailscale.serve.enable")
    empty = replace(facts, live_routes=(), owned_route=None)
    assert authorize(setup, request, facts=empty,
                     approval=approvals.issue(request)).status == "ALLOW"


def test_tailscale_matching_but_unowned_existing_route_cannot_enable(setup):
    root, cli, _, _, facts, authority, approvals = setup
    authority.set_grant("tailscale.serve.enable", enabled=True, executables=[cli])
    request = request_for(setup, "tailscale.serve.enable")
    unowned = replace(facts, owned_route=None)
    assert authorize(setup, request, facts=unowned,
                     approval=approvals.issue(request)).status == "DENY"


@pytest.mark.parametrize("live_routes,owned,complete,expected", [
    ((), False, True, "ALLOW"),
    ((ServeRoute("other.tail123.ts.net", "/", GATEWAY, True),), False, True, "ALLOW"),
    ((ServeRoute(HOST, "/", "http://127.0.0.1:9999", True),), False, True, "DENY"),
    ((ServeRoute(HOST, "/", GATEWAY, False),), False, True, "DENY"),
    ((), True, True, "DENY"),  # Stale ownership record must be resolved.
    (None, False, False, "DENY"),  # Unknown inventory is not a free target.
    ((), False, False, "DENY"),
])
def test_tailscale_enable_requires_verified_free_or_owned_target(
        setup, live_routes, owned, complete, expected):
    root, cli, _, _, facts, authority, approvals = setup
    authority.set_grant("tailscale.serve.enable", enabled=True, executables=[cli])
    request = request_for(setup, "tailscale.serve.enable")
    observed = replace(facts, live_routes=live_routes,
                       owned_route=facts.owned_route if owned else None,
                       serve_inventory_complete=complete)
    assert authorize(setup, request, facts=observed,
                     approval=approvals.issue(request)).status == expected


@pytest.mark.parametrize("live_routes,complete", [
    ((), True),
    ((ServeRoute(HOST, "/", "http://127.0.0.1:9999", True),), True),
    ((ServeRoute(HOST, "/", GATEWAY, False),), True),
    (None, False),
])
def test_tailscale_disable_requires_fresh_matching_live_route(
        setup, live_routes, complete):
    root, cli, _, _, facts, authority, approvals = setup
    authority.set_grant("tailscale.serve.disable", enabled=True, executables=[cli])
    request = request_for(setup, "tailscale.serve.disable")
    observed = replace(facts, live_routes=live_routes, serve_inventory_complete=complete)
    assert authorize(setup, request, facts=observed,
                     approval=approvals.issue(request)).status == "DENY"


def test_tailscale_missing_adapter_facts_deny_even_with_grant_and_approval(setup):
    root, cli, _, _, _, authority, approvals = setup
    authority.set_grant("tailscale.login", enabled=True, executables=[cli])
    request = request_for(setup, "tailscale.login")
    gate = ProductActionGate(root, authority, owner_id="tailscale_login")
    assert gate.authorize(request, approvals=approvals,
                          approval=approvals.issue(request))[1].status == "DENY"


def test_tailscale_approval_for_different_valid_route_digest_denies(setup):
    root, cli, _, _, facts, authority, approvals = setup
    authority.set_grant("tailscale.serve.enable", enabled=True, executables=[cli])
    original = request_for(setup, "tailscale.serve.enable")
    different = request_for(setup, "tailscale.serve.enable", serve_digest="b" * 64)
    updated_facts = replace(facts, serve_digest="b" * 64)
    assert authorize(setup, different, facts=updated_facts,
                     approval=approvals.issue(original)).status == "DENY"


def test_tailscale_expired_approval_denies(setup, monkeypatch):
    root, cli, _, _, _, authority, approvals = setup
    authority.set_grant("tailscale.login", enabled=True, executables=[cli])
    request = request_for(setup, "tailscale.login")
    approval = approvals.issue(request)
    monkeypatch.setattr("isycode.approvals.time.monotonic", lambda: approval.expires_at + 1)
    assert authorize(setup, request, approval=approval).status == "DENY"


def test_tailscale_systembilities_use_supplied_facts_without_filesystem_probes(setup, monkeypatch):
    root, _, _, _, facts, authority, _ = setup
    request = request_for(setup, "tailscale.inspect")
    gate = ProductActionGate(root, authority, owner_id="tailscale_read", tailscale_facts=facts)
    def forbidden(*args, **kwargs):
        raise AssertionError("Systembilities must not probe the filesystem")
    monkeypatch.setattr("isycode.action_runtime.Path.resolve", forbidden)
    monkeypatch.setattr("isycode.action_runtime.os.access", forbidden)
    decision = gate.sentinel.evaluate(
        request, AuthorityDecision(True, "grant:test", "fixture", request.digest))
    assert decision.status == "ALLOW"
