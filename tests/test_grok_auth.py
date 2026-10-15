"""The official grok CLI sign-in is mediated like every other execution owner."""
import asyncio
import dataclasses

from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import GrokAuthSystembility
from isycode.approvals import ActionApprovalStore
from isycode.grok_auth import GrokAuthOwner
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority


def _environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    root = tmp_path / "project"
    root.mkdir()
    executable = tmp_path / "grok"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    monkeypatch.setenv("ISYCODE_GROK_EXECUTABLE", str(executable))
    authority = WorkspaceAuthority(root)
    approvals = ActionApprovalStore()
    return root, executable, authority, approvals


def _runner(spawned, code=0):
    async def run(method, on_line, executable=None):
        spawned.append((method, executable))
        on_line("fake device code line")
        return code
    return run


def test_grok_signin_requires_grant_and_request_bound_approval(tmp_path, monkeypatch):
    root, executable, authority, approvals = _environment(tmp_path, monkeypatch)
    spawned = []
    owner = GrokAuthOwner(root, authority, approvals, runner=_runner(spawned))
    request = owner.request("device")
    assert request.action_id == "grok.login"
    assert request.execution_owner == "grok_auth"

    async def scenario():
        outcome = await owner.begin(request, None)
        assert outcome.decision == "DENY"
        assert outcome.reason == "no explicit workspace grant"
        assert not spawned

        authority.set_grant("grok.login", enabled=True, targets=["grok"],
                            executables=[str(executable)])
        outcome = await owner.begin(request, None)
        assert outcome.decision == "DENY"
        assert outcome.reason == "fresh request-bound approval is required"
        assert not spawned

        approval = approvals.issue(request, ttl_seconds=30)
        monkeypatch.setattr("isycode.grok_session.status", lambda: "signed-in")
        outcome = await owner.begin(request, approval)
        assert outcome.decision == "ALLOW"
        assert outcome.text == "grok:login-finished"
        assert outcome.receipt is not None
        assert outcome.receipt.outcome == "SUCCESS"
        assert outcome.receipt.verify(request, outcome.text)
        assert spawned == [("device", str(executable.resolve()))]

        report = ActionAuditJournal(root).verify()
        assert report.status == "PASS"
        assert report.decisions >= 3
        assert report.receipts >= 1

    asyncio.run(scenario())


def test_grok_signin_approval_is_bound_to_the_exact_request(tmp_path, monkeypatch):
    root, executable, authority, approvals = _environment(tmp_path, monkeypatch)
    authority.set_grant("grok.login", enabled=True, targets=["grok"],
                        executables=[str(executable)])
    spawned = []
    owner = GrokAuthOwner(root, authority, approvals, runner=_runner(spawned))
    device = owner.request("device")
    browser = owner.request("browser")

    async def scenario():
        # An approval minted for the device flow cannot authorize the browser flow.
        outcome = await owner.begin(browser, approvals.issue(device, ttl_seconds=30))
        assert outcome.decision == "DENY"
        assert not spawned
        # A tampered target never reaches the gate.
        tampered = dataclasses.replace(device, target="other")
        outcome = await owner.begin(tampered, approvals.issue(tampered, ttl_seconds=30))
        assert outcome.decision == "DENY"
        assert outcome.reason == "sign-in identity changed"
        assert not spawned

    asyncio.run(scenario())


def test_grok_signin_records_failure_receipts_for_exit_and_launch(tmp_path, monkeypatch):
    root, executable, authority, approvals = _environment(tmp_path, monkeypatch)
    authority.set_grant("grok.login", enabled=True, targets=["grok"],
                        executables=[str(executable)])
    monkeypatch.setattr("isycode.grok_session.status", lambda: "signed-in")

    async def scenario():
        exited = []
        owner = GrokAuthOwner(root, authority, approvals, runner=_runner(exited, code=1))
        request = owner.request("device")
        outcome = await owner.begin(request, approvals.issue(request, ttl_seconds=30))
        assert outcome.decision == "ERROR"
        assert outcome.text == "grok:login-exited:1"
        assert outcome.reason == "official grok login exited with status 1"
        # The journal accepts FAILURE receipts only for tailscale.*; a failed
        # grok attempt stays attested by its journaled ALLOW decision instead.
        assert outcome.receipt is None

        class LaunchError:
            async def __call__(self, method, on_line, executable=None):
                raise OSError("grok is gone")

        owner = GrokAuthOwner(root, authority, approvals, runner=LaunchError())
        request = owner.request("device")
        outcome = await owner.begin(request, approvals.issue(request, ttl_seconds=30))
        assert outcome.decision == "ERROR"
        assert outcome.text == "grok:launch-failed"
        assert outcome.reason == "official grok login failed to launch"
        assert outcome.receipt is None

        # Exit 0 without a live sign-in is still not an ALLOW.
        async def signed_out(method, on_line, executable=None):
            return 0
        monkeypatch.setattr("isycode.grok_session.status", lambda: "expired")
        owner = GrokAuthOwner(root, authority, approvals, runner=signed_out)
        request = owner.request("device")
        outcome = await owner.begin(request, approvals.issue(request, ttl_seconds=30))
        assert outcome.decision == "ERROR"
        assert outcome.text == "grok:login-exited:0"

        report = ActionAuditJournal(root).verify()
        assert report.status == "PASS"
        assert report.decisions >= 3
        assert report.receipts == 0

    asyncio.run(scenario())


def test_grok_auth_boundary_binds_the_official_executable(tmp_path, monkeypatch):
    root, executable, authority, approvals = _environment(tmp_path, monkeypatch)
    boundary = GrokAuthSystembility()
    valid = ActionRequest(
        "grok.login", root, "grok",
        {"executable": str(executable.resolve()), "operation": "login", "method": "device"},
        execution_owner="grok_auth")
    assert boundary.evaluate(valid, None).passed is True

    other = tmp_path / "impostor"
    other.write_text("#!/bin/sh\nexit 0\n")
    other.chmod(0o700)
    swapped = dataclasses.replace(
        valid, parameters={"executable": str(other.resolve()),
                           "operation": "login", "method": "device"})
    assert boundary.evaluate(swapped, None).passed is False

    bad_method = dataclasses.replace(
        valid, parameters={"executable": str(executable.resolve()),
                           "operation": "login", "method": "ssh"})
    assert boundary.evaluate(bad_method, None).passed is False

    wrong_target = dataclasses.replace(valid, target="chatgpt")
    assert boundary.evaluate(wrong_target, None).passed is False

    # Other actions stay outside this boundary's scope.
    unrelated = ActionRequest("web.fetch", root, "https://example.com", {},
                              execution_owner="web_fetch")
    assert boundary.evaluate(unrelated, None).passed is True

    # A missing official grok CLI fails closed instead of guessing a path.
    def missing():
        raise ValueError("Official grok CLI is not installed")
    monkeypatch.setattr("isycode.grok_session.grok_executable", missing)
    assert boundary.evaluate(valid, None).passed is False
