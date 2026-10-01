"""Serve ownership against the real adapter parser and Tailscale's HostPort keys.

`tailscale serve status --json` keys `Web` and `AllowFunnel` by "$DNS:$PORT"
(ipn.HostPort). These witnesses drive the real TailscaleAdapter through an
offline CLI emulator, so the owner cannot drift from the parser's route shape.
"""
import copy
import json

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.private_access import PrivateAccessStateStore
from isycode.tailscale import TailscaleAdapter, TailscaleCommandResult
from isycode.tailscale_serve import TailscaleServeOwner, serve_host_port
from isycode.workspace_authority import WorkspaceAuthority


DNS = "danny.tail123.ts.net"
HOST_PORT = f"{DNS}:443"
GATEWAY = "http://127.0.0.1:8787"


class TailscaleCLIEmulator:
    """Offline stand-in for the fixed CLI commands the owners run."""

    def __init__(self, node=None):
        self.node = node or {"TCP": {}, "Web": {}, "AllowFunnel": {}}
        self.mutations = []

    def __call__(self, argv, *, env, timeout, max_output):
        del env, timeout, max_output
        command = tuple(argv[1:])
        if command == ("version",):
            return TailscaleCommandResult(0, "1.84.0\n", "")
        if command == ("status", "--json"):
            return TailscaleCommandResult(0, json.dumps(
                {"BackendState": "Running", "Self": {"DNSName": DNS + "."}}), "")
        if command == ("serve", "get-config", "--all"):
            return TailscaleCommandResult(0, json.dumps({"version": "0.0.1", "services": {}}), "")
        if command == ("serve", "status", "--json"):
            return TailscaleCommandResult(0, json.dumps(self.node), "")
        if command[:4] == ("serve", "--https=443", "--set-path=/isycode", "--bg"):
            self.mutations.append(command)
            web = self.node.setdefault("Web", {})
            if command[-1] == "off":
                handlers = web.get(HOST_PORT, {}).get("Handlers", {})
                handlers.pop("/isycode", None)
                if not handlers:
                    web.pop(HOST_PORT, None)
                    self.node.get("TCP", {}).pop("443", None)
            else:
                web.setdefault(HOST_PORT, {"Handlers": {}})["Handlers"]["/isycode"] = {
                    "Proxy": command[-1]}
                self.node.setdefault("TCP", {})["443"] = {"HTTPS": True}
            return TailscaleCommandResult(0, "", "")
        raise AssertionError(f"unexpected Tailscale command {command!r}")


@pytest.fixture
def real_adapter(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    cli = tmp_path / "bin" / "tailscale"
    cli.parent.mkdir()
    cli.write_text("offline CLI stand-in", encoding="utf-8")
    cli.chmod(0o700)
    monkeypatch.setattr("isycode.tailscale.shutil.which",
                        lambda name: str(cli) if name == "tailscale" else None)
    root = tmp_path / "workspace"
    root.mkdir()

    def build(node=None):
        emulator = TailscaleCLIEmulator(node)
        adapter = TailscaleAdapter(runner=emulator, platform="linux",
                                   gateway_probe=lambda url: True,
                                   gateway_url=GATEWAY, gateway_port=8787)
        authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
        approvals = ActionApprovalStore()
        store = PrivateAccessStateStore(tmp_path / "private-access")
        owner = TailscaleServeOwner(root, authority, approvals, adapter=adapter,
                                    state_store=store, runner=emulator)
        for action in ("tailscale.inspect", "tailscale.serve.enable", "tailscale.serve.disable"):
            authority.set_grant(action, enabled=True, executables=[cli])
        return owner, emulator, approvals, store

    return build


def test_serve_host_port_matches_tailscale_web_keys():
    assert serve_host_port(DNS + ".") == HOST_PORT
    assert serve_host_port(DNS) == HOST_PORT


def test_enable_then_disable_round_trips_with_real_hostport_inventory(real_adapter):
    owner, emulator, approvals, store = real_adapter()

    preview = owner.preview_enable()
    assert preview.route.host == HOST_PORT
    outcome = owner.enable(preview, approvals.issue(preview.request))
    assert outcome.decision == "ALLOW", outcome.reason
    assert [route.host for route in store.load().owned_routes] == [HOST_PORT]

    disable = owner.preview_disable()
    assert disable.already_applied is False
    outcome = owner.disable(disable, approvals.issue(disable.request))
    assert outcome.decision == "ALLOW", outcome.reason
    assert store.load().owned_routes == ()
    assert HOST_PORT not in emulator.node.get("Web", {})


def test_unowned_isycode_route_at_hostport_is_never_overwritten(real_adapter):
    foreign = {"TCP": {"443": {"HTTPS": True}},
               "Web": {HOST_PORT: {"Handlers": {"/isycode": {"Proxy": "http://127.0.0.1:9999"}}}},
               "AllowFunnel": {}}
    owner, emulator, _, _ = real_adapter(copy.deepcopy(foreign))

    with pytest.raises(ValueError, match="without ISyCode ownership"):
        owner.preview_enable()
    assert emulator.mutations == []
    assert emulator.node == foreign


def test_funnel_on_the_same_hostport_still_blocks_changes(real_adapter):
    node = {"TCP": {"443": {"HTTPS": True}},
            "Web": {HOST_PORT: {"Handlers": {"/docs": {"Proxy": "http://127.0.0.1:9000"}}}},
            "AllowFunnel": {HOST_PORT: True}}
    owner, emulator, _, _ = real_adapter(node)

    with pytest.raises(ValueError, match="Serve inventory"):
        owner.preview_enable()
    assert emulator.mutations == []


def test_existing_route_on_same_hostport_is_preserved_through_enable_and_disable(real_adapter):
    docs = {"Proxy": "http://127.0.0.1:9000"}
    node = {"TCP": {"443": {"HTTPS": True}},
            "Web": {HOST_PORT: {"Handlers": {"/docs": dict(docs)}}}, "AllowFunnel": {}}
    owner, emulator, approvals, _ = real_adapter(node)

    preview = owner.preview_enable()
    assert owner.enable(preview, approvals.issue(preview.request)).decision == "ALLOW"
    disable = owner.preview_disable()
    assert owner.disable(disable, approvals.issue(disable.request)).decision == "ALLOW"
    assert emulator.node["Web"][HOST_PORT]["Handlers"] == {"/docs": docs}
    assert emulator.node["TCP"] == {"443": {"HTTPS": True}}


def test_unrelated_listener_change_during_enable_is_not_verifiable(real_adapter):
    owner, emulator, approvals, store = real_adapter()
    original = emulator.__call__

    def with_side_effect(argv, **kwargs):
        result = original(argv, **kwargs)
        if tuple(argv[1:4]) == ("serve", "--https=443", "--set-path=/isycode"):
            emulator.node["TCP"]["8443"] = {"HTTPS": True}
        return result

    owner.runner = with_side_effect
    preview = owner.preview_enable()
    outcome = owner.enable(preview, approvals.issue(preview.request))
    assert outcome.decision == "NOT_VERIFIABLE"
