"""Offline tests for the explicitly approved interactive Tailscale login owner."""
from dataclasses import dataclass
from pathlib import Path

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.security import ActionRequest
from isycode.tailscale import TailscaleSnapshot
from isycode.tailscale_login import TailscaleLoginOwner
from isycode.workspace_authority import WorkspaceAuthority


class FakePipe:
    def __init__(self, data=b""):
        self.data = bytearray(data)

    def read_available(self, limit):
        result = bytes(self.data[:limit])
        del self.data[:len(result)]
        return result

    def close(self):
        pass


class FakeProcess:
    def __init__(self, stdout=b"", stderr=b"", returncode=None):
        self.stdout = FakePipe(stdout)
        self.stderr = FakePipe(stderr)
        self.returncode = returncode
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class FakeAdapter:
    def __init__(self, executable):
        self.snapshot = TailscaleSnapshot("signed_out", executable=executable,
                                         version="1.80.0")

    def inspect(self):
        return self.snapshot

    def resolve_executable(self):
        return self.snapshot.executable


@dataclass
class LoginFixture:
    root: Path
    executable: Path
    authority: WorkspaceAuthority
    approvals: ActionApprovalStore
    adapter: FakeAdapter
    owner: TailscaleLoginOwner
    launched: list
    process: FakeProcess


@pytest.fixture
def login_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "workspace"
    root.mkdir()
    executable = tmp_path / "tailscale"
    executable.write_text("fake executable", encoding="utf-8")
    executable.chmod(0o700)
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    authority.set_grant("tailscale.login", enabled=True, executables=[executable])
    # The preview reads the CLI only through the gated read-only inventory owner.
    authority.set_grant("tailscale.inspect", enabled=True, executables=[executable])
    approvals = ActionApprovalStore()
    adapter = FakeAdapter(str(executable.resolve()))
    launched = []
    process = FakeProcess()

    def popen(argv, **kwargs):
        launched.append((tuple(argv), kwargs))
        return process

    owner = TailscaleLoginOwner(root, authority, approvals,
                                adapter=adapter, popen=popen)
    return LoginFixture(root, executable, authority, approvals, adapter, owner,
                        launched, process)


def test_login_preview_is_fixed_and_approval_precedes_launch(login_fixture):
    fixture = login_fixture
    request = fixture.owner.login_request()
    preview = fixture.owner.preview(request)
    assert "tailscale login" in preview
    assert "login.tailscale.com" in preview
    assert "auth-key" not in preview
    assert fixture.owner.begin_login(request, None).decision == "DENY"
    assert fixture.launched == []

    approval = fixture.approvals.issue(request)
    outcome = fixture.owner.begin_login(request, approval)
    assert outcome.decision == "ALLOW"
    assert fixture.launched[0][0] == (str(fixture.executable.resolve()), "login")
    assert fixture.launched[0][1]["shell"] is False
    assert fixture.launched[0][1]["stdin"] is not None
    assert fixture.launched[0][1]["env"] == {
        "PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}


def test_login_url_and_cli_output_are_redacted_from_state_and_receipts(login_fixture):
    fixture = login_fixture
    secret = "super-secret-auth-material"
    fixture.process.stdout.data.extend(
        f"visit https://login.tailscale.com/a/AbCdEf0123456789\n{secret}".encode())
    request = fixture.owner.login_request()
    attempt = fixture.owner.begin_login(request, fixture.approvals.issue(request))
    status = fixture.owner.poll(attempt.text.split()[-1])
    assert status.state == "pending"
    assert status.login_url == "https://login.tailscale.com/a/AbCdEf0123456789"
    assert secret not in repr(status)
    assert secret not in repr(attempt.receipt)
    assert secret not in repr(fixture.owner)
    attempt_id = attempt.text.split()[-1]
    assert secret not in fixture.owner._attempts[attempt_id].url_candidate
    # The durable journal stores digests and action metadata only; it never
    # receives either the CLI buffer or the ephemeral authorization URL.
    from isycode.action_audit import ActionAuditJournal
    journal = ActionAuditJournal.for_read_only_inspection(fixture.root)
    if journal.path.exists():
        contents = journal.path.read_text(encoding="utf-8")
        assert secret not in contents
        assert "https://login.tailscale.com/a/" not in contents


def test_login_completes_only_after_signed_in_inventory(login_fixture):
    fixture = login_fixture
    request = fixture.owner.login_request()
    started = fixture.owner.begin_login(request, fixture.approvals.issue(request))
    attempt_id = started.text.split()[-1]
    fixture.process.returncode = 0
    fixture.adapter.snapshot = TailscaleSnapshot("signed_in", executable=str(fixture.executable.resolve()),
                                                 version="1.80.0", dns_name="device.ts.net")
    status = fixture.owner.poll(attempt_id)
    assert status.state == "signed_in"
    assert status.login_url is None
    assert status.receipt is not None
    assert status.receipt.outcome == "SUCCESS"


def test_cli_failure_is_generic_and_does_not_expose_stderr(login_fixture):
    fixture = login_fixture
    fixture.process.stderr.data.extend(b"credential=do-not-leak")
    fixture.process.returncode = 7
    request = fixture.owner.login_request()
    started = fixture.owner.begin_login(request, fixture.approvals.issue(request))
    status = fixture.owner.poll(started.text.split()[-1])
    assert status.state == "failed"
    assert "do-not-leak" not in repr(status)
    assert status.receipt is not None and status.receipt.outcome == "FAILURE"


def test_login_timeout_kills_only_its_child(login_fixture, monkeypatch):
    fixture = login_fixture
    request = fixture.owner.login_request()
    started = fixture.owner.begin_login(request, fixture.approvals.issue(request))
    attempt_id = started.text.split()[-1]
    fixture.owner._clock = lambda: 10**9
    status = fixture.owner.poll(attempt_id)
    assert status.state == "timed_out"
    assert fixture.process.killed


def test_cancel_discards_attempt_without_tailnet_logout(login_fixture):
    fixture = login_fixture
    request = fixture.owner.login_request()
    started = fixture.owner.begin_login(request, fixture.approvals.issue(request))
    attempt_id = started.text.split()[-1]
    status = fixture.owner.cancel(attempt_id)
    assert status.state == "cancelled"
    assert fixture.process.killed
    assert fixture.launched[0][0][-1] == "login"


def test_new_owner_cannot_resume_in_memory_login_or_reuse_auth_material(login_fixture):
    fixture = login_fixture
    request = fixture.owner.login_request()
    started = fixture.owner.begin_login(request, fixture.approvals.issue(request))
    attempt_id = started.text.split()[-1]
    replacement = TailscaleLoginOwner(fixture.root, fixture.authority,
                                      fixture.approvals, adapter=fixture.adapter,
                                      popen=lambda *_args, **_kwargs: pytest.fail("must not relaunch"))
    assert replacement.poll(attempt_id).state == "unknown"


def test_malformed_or_untrusted_login_url_is_not_exposed(login_fixture):
    fixture = login_fixture
    fixture.process.stdout.data.extend(
        b"https://evil.example/a/12345678 https://login.tailscale.com.evil/a/12345678")
    request = fixture.owner.login_request()
    started = fixture.owner.begin_login(request, fixture.approvals.issue(request))
    status = fixture.owner.poll(started.text.split()[-1])
    assert status.login_url is None


def test_official_login_url_can_be_recognized_across_pipe_reads(login_fixture):
    fixture = login_fixture
    request = fixture.owner.login_request()
    started = fixture.owner.begin_login(request, fixture.approvals.issue(request))
    attempt_id = started.text.split()[-1]
    fixture.process.stdout.data.extend(b"https://login.tailscale.com/a/AbCdEf0")
    assert fixture.owner.poll(attempt_id).login_url is None
    fixture.process.stdout.data.extend(b"123456789\n")
    assert fixture.owner.poll(attempt_id).login_url == (
        "https://login.tailscale.com/a/AbCdEf0123456789")


def test_login_preview_reads_no_inventory_without_the_read_only_grant(login_fixture):
    fixture = login_fixture
    fixture.authority.set_grant("tailscale.inspect", enabled=False, executables=[])
    calls = []
    fixture.adapter.inspect = lambda: calls.append("inspect") or fixture.adapter.snapshot

    with pytest.raises(ValueError, match="not authorized"):
        fixture.owner.login_request()
    request = ActionRequest("tailscale.login", fixture.root, "tailscale",
                            {"executable": str(fixture.executable.resolve()), "operation": "login"},
                            execution_owner="tailscale_login")
    assert fixture.owner.begin_login(request, fixture.approvals.issue(request)).decision == "DENY"
    assert calls == [] and fixture.launched == []
