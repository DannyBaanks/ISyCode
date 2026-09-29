"""Offline authority and route-preservation tests for private Tailscale Serve."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.private_access import OwnedServeRoute, PrivateAccessStateStore
from isycode.tailscale import ServeRoute, TailscaleCommandResult, TailscaleSnapshot
from isycode.tailscale_serve import TailscaleServeOwner
from isycode.workspace_authority import WorkspaceAuthority


GATEWAY = "http://127.0.0.1:8787"
HOST = "danny.tail123.ts.net"
PATH = "/isycode"
DIGEST = "a" * 64
OWNED_ID = "isycode-gateway"


def snapshot_with_routes(snapshot, routes, *, tcp=None, services=None):
    routes = tuple(routes)
    old_node = json.loads(snapshot.serve_node_config or "{}")
    old_services = json.loads(snapshot.serve_services_config or "{}")
    web = {}
    for route in routes:
        web.setdefault(route.host, {"Handlers": {}})["Handlers"][route.path] = {
            "Proxy": route.target,
        }
    node = {**old_node, "TCP": tcp if tcp is not None else old_node.get("TCP", {}),
            "Web": web, "AllowFunnel": old_node.get("AllowFunnel", {})}
    service_config = (services if services is not None else old_services)
    return replace(
        snapshot,
        serve_state="empty" if not routes and not tcp and not services else "existing",
        routes=routes,
        serve_digest=hashlib.sha256(repr((routes, tcp, services)).encode()).hexdigest(),
        serve_node_config=json.dumps(node, sort_keys=True),
        serve_services_config=json.dumps(service_config, sort_keys=True),
    )


class FakeAdapter:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.snapshots = []

    def inspect(self):
        self.snapshots.append(self.snapshot)
        return self.snapshot


class FakeRunner:
    def __init__(self, adapter):
        self.adapter = adapter
        self.calls = []
        self.result = TailscaleCommandResult(0, "ignored output", "")

    def __call__(self, argv, **kwargs):
        argv = tuple(argv)
        self.calls.append((argv, kwargs))
        before = self.adapter.snapshot
        if self.result.returncode == 0:
            if argv[-1] == "off":
                routes = tuple(route for route in before.routes
                               if (route.host, route.path) != (HOST, PATH))
            else:
                routes = before.routes + (ServeRoute(HOST, PATH, GATEWAY, True),)
            self.adapter.snapshot = snapshot_with_routes(before, routes)
        return self.result


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    root = tmp_path / "workspace"
    root.mkdir()
    cli = tmp_path / "tailscale"
    cli.write_text("fake CLI", encoding="utf-8")
    cli.chmod(0o700)
    snapshot = TailscaleSnapshot(
        "signed_in", "empty", str(cli.resolve()), "1.80.0", HOST, (), DIGEST,
        GATEWAY, True, serve_node_config=json.dumps(
            {"TCP": {}, "Web": {}, "AllowFunnel": {}}, sort_keys=True),
        serve_services_config=json.dumps({"version": "0.0.1", "services": {}},
                                         sort_keys=True))
    adapter = FakeAdapter(snapshot)
    runner = FakeRunner(adapter)
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    store = PrivateAccessStateStore(tmp_path / "private-access")
    owner = TailscaleServeOwner(root, authority, approvals,
                                adapter=adapter, state_store=store, runner=runner)
    return root, cli, adapter, runner, authority, approvals, store, owner


def approve(setup, action):
    root, cli, _, _, authority, approvals, _, _ = setup
    authority.set_grant(action, enabled=True, executables=[cli])
    preview = setup[-1].preview_enable() if action.endswith("enable") else setup[-1].preview_disable()
    return preview, approvals.issue(preview.request)


def owned_route():
    return OwnedServeRoute(OWNED_ID, HOST, PATH, GATEWAY,
                           "2026-09-29T10:00:00Z", "online")


def test_enable_preview_shows_exact_private_route_and_operation(setup):
    *_, owner = setup
    preview = owner.preview_enable()
    assert preview.route == ServeRoute(HOST, PATH, GATEWAY, True)
    assert preview.request.parameters["serve_argv"] == (
        str(setup[1].resolve()), "serve", "--https=443", "--set-path=/isycode",
        "--bg", GATEWAY)
    assert "https://danny.tail123.ts.net/isycode" in preview.description
    assert "http://127.0.0.1:8787" in preview.description
    assert "reset" not in preview.description.casefold()
    assert preview.request.parameters["funnel"] is False


def test_enable_requires_fresh_approval_then_verifies_and_records_route(setup):
    preview, approval = approve(setup, "tailscale.serve.enable")
    owner = setup[-1]
    result = owner.enable(preview, approval)
    assert result.decision == "ALLOW"
    assert result.receipt is not None and result.receipt.outcome == "SUCCESS"
    assert setup[3].calls[0][0] == preview.request.parameters["serve_argv"]
    saved = setup[6].load().owned_routes
    assert len(saved) == 1
    assert (saved[0].route_id, saved[0].host, saved[0].path, saved[0].target,
            saved[0].last_verified_status) == (
                OWNED_ID, HOST, PATH, GATEWAY, "online")


def test_opening_preview_and_cancelling_has_no_mutation(setup):
    owner = setup[-1]
    first = owner.preview_enable()
    second = owner.preview_enable()
    assert first.request == second.request
    assert setup[3].calls == []
    assert setup[6].load().owned_routes == ()


def test_enable_denies_missing_grant_or_approval_without_command(setup):
    owner = setup[-1]
    preview = owner.preview_enable()
    assert owner.enable(preview, None).decision == "DENY"
    assert setup[3].calls == []
    setup[4].set_grant("tailscale.serve.enable", enabled=True, executables=[setup[1]])
    assert owner.enable(preview, None).decision == "DENY"
    assert setup[3].calls == []


def test_enable_fails_closed_when_host_path_is_already_owned_by_other_target(setup):
    route = ServeRoute(HOST, PATH, "http://127.0.0.1:9999", True)
    setup[2].snapshot = snapshot_with_routes(setup[2].snapshot, (route,))
    with pytest.raises(ValueError, match="configured without ISyCode ownership"):
        setup[-1].preview_enable()


def test_enable_allows_other_live_routes_and_preserves_them(setup):
    unrelated = ServeRoute("other.tail123.ts.net", "/docs", "http://127.0.0.1:9999", True)
    setup[2].snapshot = snapshot_with_routes(setup[2].snapshot, (unrelated,))
    preview = setup[-1].preview_enable()
    setup[4].set_grant("tailscale.serve.enable", enabled=True, executables=[setup[1]])
    result = setup[-1].enable(preview, setup[5].issue(preview.request))
    assert result.decision == "ALLOW"
    assert setup[2].snapshot.routes == (unrelated, ServeRoute(HOST, PATH, GATEWAY, True))


def test_enable_preserves_tcp_listeners_and_service_config(setup):
    tcp = {"443": {"HTTPS": True}}
    services = {"svc:abc": {"Ports": {"443": "http://127.0.0.1:9090"}}}
    setup[2].snapshot = snapshot_with_routes(setup[2].snapshot, (), tcp=tcp,
                                            services={"version": "0.0.1",
                                                      "services": services})
    preview = setup[-1].preview_enable()
    setup[4].set_grant("tailscale.serve.enable", enabled=True, executables=[setup[1]])
    result = setup[-1].enable(preview, setup[5].issue(preview.request))
    assert result.decision == "ALLOW"
    assert json.loads(setup[2].snapshot.serve_node_config)["TCP"] == tcp
    assert json.loads(setup[2].snapshot.serve_services_config)["services"] == services


def test_enable_reports_not_verifiable_if_unrelated_tcp_config_changes(setup):
    class MutatingRunner(FakeRunner):
        def __call__(self, argv, **kwargs):
            super().__call__(argv, **kwargs)
            snapshot = self.adapter.snapshot
            node = json.loads(snapshot.serve_node_config)
            node["TCP"]["9443"] = {"HTTPS": True}
            self.adapter.snapshot = replace(
                snapshot, serve_node_config=json.dumps(node, sort_keys=True))

    setup[3].__class__ = MutatingRunner
    preview = setup[-1].preview_enable()
    setup[4].set_grant("tailscale.serve.enable", enabled=True, executables=[setup[1]])
    result = setup[-1].enable(preview, setup[5].issue(preview.request))
    assert result.decision == "NOT_VERIFIABLE"
    assert setup[6].load().owned_routes


def test_route_drift_after_preview_requires_new_approval_and_runs_no_command(setup):
    preview = setup[-1].preview_enable()
    setup[2].snapshot = replace(setup[2].snapshot, serve_state="existing",
                                serve_digest="b" * 64)
    setup[4].set_grant("tailscale.serve.enable", enabled=True, executables=[setup[1]])
    result = setup[-1].enable(preview, setup[5].issue(preview.request))
    assert result.decision == "DENY"
    assert setup[3].calls == []


def test_enable_rejects_non_loopback_gateway_and_unverified_health(setup):
    setup[2].snapshot = replace(setup[2].snapshot, gateway_url="http://0.0.0.0:8787")
    with pytest.raises(ValueError):
        setup[-1].preview_enable()
    setup[2].snapshot = replace(setup[2].snapshot, gateway_url=GATEWAY, gateway_healthy=False)
    with pytest.raises(ValueError, match="health"):
        setup[-1].preview_enable()


def test_enable_requires_complete_live_inventory(setup):
    setup[2].snapshot = replace(setup[2].snapshot, serve_state="conflict", serve_digest=None)
    with pytest.raises(ValueError, match="inventory"):
        setup[-1].preview_enable()


def test_enable_idempotent_only_for_matching_owned_live_route(setup):
    route = ServeRoute(HOST, PATH, GATEWAY, True)
    setup[2].snapshot = snapshot_with_routes(setup[2].snapshot, (route,))
    setup[6].record_owned_route(owned_route())
    preview, approval = approve(setup, "tailscale.serve.enable")
    result = setup[-1].enable(preview, approval)
    assert result.decision == "ALLOW"
    assert setup[3].calls == []


def test_disable_requires_owned_mapping_and_exact_off_command(setup):
    route = ServeRoute(HOST, PATH, GATEWAY, True)
    setup[2].snapshot = snapshot_with_routes(setup[2].snapshot, (route,))
    setup[6].record_owned_route(owned_route())
    preview, approval = approve(setup, "tailscale.serve.disable")
    result = setup[-1].disable(preview, approval)
    assert result.decision == "ALLOW"
    assert setup[3].calls[0][0] == preview.request.parameters["serve_argv"]
    assert setup[3].calls[0][0][-1] == "off"
    assert setup[6].load().owned_routes == ()


def test_disable_cannot_touch_matching_but_unowned_route(setup):
    setup[2].snapshot = snapshot_with_routes(setup[2].snapshot,
                                          (ServeRoute(HOST, PATH, GATEWAY, True),))
    with pytest.raises(ValueError, match="no ISyCode-owned route"):
        setup[-1].preview_disable()
    assert setup[3].calls == []


def test_disable_clears_stale_ownership_when_live_route_is_already_absent(setup):
    setup[6].record_owned_route(owned_route())
    preview, approval = approve(setup, "tailscale.serve.disable")
    result = setup[-1].disable(preview, approval)
    assert result.decision == "ALLOW"
    assert setup[3].calls == []
    assert setup[6].load().owned_routes == ()


def test_disable_preserves_unrelated_routes(setup):
    unrelated = ServeRoute("other.tail123.ts.net", "/", "http://127.0.0.1:9999", True)
    route = ServeRoute(HOST, PATH, GATEWAY, True)
    setup[2].snapshot = snapshot_with_routes(setup[2].snapshot, (unrelated, route))
    setup[6].record_owned_route(owned_route())
    preview, approval = approve(setup, "tailscale.serve.disable")
    result = setup[-1].disable(preview, approval)
    assert result.decision == "ALLOW"
    assert setup[2].snapshot.routes == (unrelated,)


def test_disable_remains_available_when_gateway_health_is_down(setup):
    route = ServeRoute(HOST, PATH, GATEWAY, True)
    setup[2].snapshot = replace(snapshot_with_routes(setup[2].snapshot, (route,)),
                                gateway_healthy=False)
    setup[6].record_owned_route(owned_route())
    preview, approval = approve(setup, "tailscale.serve.disable")
    result = setup[-1].disable(preview, approval)
    assert result.decision == "ALLOW"
    assert setup[6].load().owned_routes == ()


def test_disable_uses_saved_loopback_target_after_gateway_port_changes(setup):
    route = ServeRoute(HOST, PATH, GATEWAY, True)
    setup[2].snapshot = replace(snapshot_with_routes(setup[2].snapshot, (route,)),
                                gateway_url="http://127.0.0.1:8899")
    setup[6].record_owned_route(owned_route())
    preview, approval = approve(setup, "tailscale.serve.disable")
    assert preview.request.parameters["gateway_url"] == GATEWAY
    assert preview.argv[-2] == GATEWAY
    result = setup[-1].disable(preview, approval)
    assert result.decision == "ALLOW"


def test_cli_failure_does_not_claim_unverified_route_and_receipt_is_redacted(setup):
    preview, approval = approve(setup, "tailscale.serve.enable")
    setup[3].result = TailscaleCommandResult(1, "authkey=secret", "raw secret")
    result = setup[-1].enable(preview, approval)
    assert result.decision in {"ERROR", "NOT_VERIFIABLE"}
    assert "secret" not in repr(result.receipt)
    assert setup[6].load().owned_routes == ()


def test_only_fixed_private_commands_are_issued(setup):
    preview, approval = approve(setup, "tailscale.serve.enable")
    setup[-1].enable(preview, approval)
    argv = setup[3].calls[0][0]
    assert "reset" not in argv and "funnel" not in argv and "--bg" in argv
