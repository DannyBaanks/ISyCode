"""Offline end-to-end private tailnet lifecycle using fake command owners."""
from pathlib import Path

from isycode.approvals import ActionApprovalStore
from isycode.private_access import PrivateAccessStateStore
from isycode.tailscale import ServeRoute, TailscaleSnapshot
from isycode.tailscale_read import TailscaleReadOwner
from isycode.tailscale_serve import TailscaleServeOwner
from isycode.workspace_authority import WorkspaceAuthority
from test_tailscale_serve import FakeAdapter, FakeRunner, GATEWAY, HOST, PATH, snapshot_with_routes


def test_private_access_preflight_enable_verify_disable_keeps_other_route(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    root = tmp_path / "workspace"
    root.mkdir()
    cli = tmp_path / "tailscale"
    cli.write_text("fake CLI", encoding="utf-8")
    cli.chmod(0o700)
    other = ServeRoute("docs.tail123.ts.net", "/docs", "http://127.0.0.1:9000", True)
    snapshot = TailscaleSnapshot(
        "signed_in", "existing", str(cli.resolve()), "1.80.0", HOST, (other,), "a" * 64,
        GATEWAY, True, serve_node_config='{"TCP":{},"Web":{"docs.tail123.ts.net":'
        '{"Handlers":{"/docs":{"Proxy":"http://127.0.0.1:9000"}}}},"AllowFunnel":{}}',
        serve_services_config='{"version":"0.0.1","services":{}}')
    adapter = FakeAdapter(snapshot)
    adapter.resolve_executable = lambda: str(cli.resolve())
    runner = FakeRunner(adapter)
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    authority.set_grant("tailscale.inspect", enabled=True, executables=[cli])
    authority.set_grant("tailscale.serve.enable", enabled=True, executables=[cli])
    authority.set_grant("tailscale.serve.disable", enabled=True, executables=[cli])
    read_owner = TailscaleReadOwner(root, authority, approvals, adapter=adapter)

    before, preflight = read_owner.inspect()
    assert preflight.decision == "ALLOW" and preflight.receipt is not None
    assert before.routes == (other,)

    state = PrivateAccessStateStore(tmp_path / "private")
    owner = TailscaleServeOwner(root, authority, approvals, adapter=adapter,
                                state_store=state, runner=runner)
    enable_preview = owner.preview_enable()
    enable = owner.enable(enable_preview, approvals.issue(enable_preview.request))
    assert enable.decision == "ALLOW" and enable.receipt is not None
    assert adapter.snapshot.routes == (other, ServeRoute(HOST, PATH, GATEWAY, True))

    verified, readback = read_owner.inspect()
    assert readback.decision == "ALLOW" and readback.receipt is not None
    assert any(route.path == PATH and route.target == GATEWAY for route in verified.routes)

    disable_preview = owner.preview_disable()
    disable = owner.disable(disable_preview, approvals.issue(disable_preview.request))
    assert disable.decision == "ALLOW" and disable.receipt is not None
    assert adapter.snapshot.routes == (other,)
    assert state.load().owned_routes == ()
    assert len({preflight.receipt.receipt_id, enable.receipt.receipt_id,
                readback.receipt.receipt_id, disable.receipt.receipt_id}) == 4


def test_cancelled_private_route_preview_has_no_command_or_saved_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    root = tmp_path / "workspace"
    root.mkdir()
    cli = tmp_path / "tailscale"
    cli.write_text("fake CLI", encoding="utf-8")
    cli.chmod(0o700)
    adapter = FakeAdapter(TailscaleSnapshot(
        "signed_in", "empty", str(cli.resolve()), "1.80.0", HOST, (), "a" * 64,
        GATEWAY, True, serve_node_config='{"TCP":{},"Web":{},"AllowFunnel":{}}',
        serve_services_config='{"version":"0.0.1","services":{}}'))
    runner = FakeRunner(adapter)
    root_auth = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    root_auth.set_grant("tailscale.serve.enable", enabled=True, executables=[cli])
    store = PrivateAccessStateStore(tmp_path / "private")
    owner = TailscaleServeOwner(root, root_auth, ActionApprovalStore(), adapter=adapter,
                                state_store=store, runner=runner)

    owner.preview_enable()  # Opening and cancelling the confirmation view is read-only.

    assert runner.calls == []
    assert store.load().owned_routes == ()
    assert adapter.snapshot.serve_state == "empty"
