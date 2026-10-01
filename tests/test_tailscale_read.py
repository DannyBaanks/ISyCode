"""Read owner witnesses for local Tailscale status."""
from isycode.approvals import ActionApprovalStore
from isycode.tailscale import TailscaleSnapshot
from isycode.tailscale_read import TailscaleReadOwner
from isycode.workspace_authority import WorkspaceAuthority


class Adapter:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = 0

    def inspect(self):
        self.calls += 1
        return self.snapshot

    def resolve_executable(self):
        return self.snapshot.executable


def test_tailscale_read_owner_inspects_and_journals_without_mutation(tmp_path):
    cli = tmp_path / "tailscale"
    cli.write_text("fake")
    cli.chmod(0o700)
    adapter = Adapter(TailscaleSnapshot(
        "signed_in", "empty", str(cli.resolve()), "1.80.0", "danny.tail.ts.net",
        (), "a" * 64, "http://127.0.0.1:8787", True))
    root = tmp_path / "workspace"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "auth")
    authority.set_grant("tailscale.inspect", enabled=True, executables=[cli])
    owner = TailscaleReadOwner(root, authority, ActionApprovalStore(), adapter=adapter)

    snapshot, outcome = owner.inspect()

    assert snapshot.state == "signed_in"
    assert outcome.decision == "ALLOW"
    assert outcome.receipt is not None
    assert adapter.calls == 1


def test_tailscale_read_owner_returns_missing_inventory_state(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    adapter = Adapter(TailscaleSnapshot("missing_cli"))
    owner = TailscaleReadOwner(root, WorkspaceAuthority(root, state_directory=tmp_path / "auth"),
                               ActionApprovalStore(), adapter=adapter)

    snapshot, outcome = owner.inspect()

    assert snapshot.state == "missing_cli"
    assert outcome.decision == "NOT_VERIFIABLE"
    assert adapter.calls == 1
