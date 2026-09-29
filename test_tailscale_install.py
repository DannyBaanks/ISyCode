"""Offline contract tests for the explicitly approved Tailscale package owner."""
from dataclasses import replace

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.tailscale import TailscaleCommandResult, TailscaleSnapshot
from isycode.tailscale_install import (
    TailscalePackageInstallOwner, UbuntuDebianInstallPlan,
)
from isycode.workspace_authority import WorkspaceAuthority


KEY_FINGERPRINT = "2596A99EAAB33821893C0A79458CA832957F5868"
SOURCE = ("# Tailscale packages for ubuntu noble\n"
          "deb [signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg] "
          "https://pkgs.tailscale.com/stable/ubuntu noble main\n")


class FakePrivilege:
    def __init__(self, *, failure_at=None, stderr=""):
        self.calls = []
        self.failure_at = failure_at
        self.stderr = stderr

    def __call__(self, argv, *, timeout, max_output):
        self.calls.append((tuple(argv), timeout, max_output))
        code = 1 if len(self.calls) == self.failure_at else 0
        return TailscaleCommandResult(code, "", self.stderr if code else "")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "workspace"
    root.mkdir()
    apt = tmp_path / "apt-get"
    apt.write_text("fake executable", encoding="utf-8")
    apt.chmod(0o700)
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    privilege = FakePrivilege()
    fetched = []
    inventory_calls = []

    def fetch(url, *, timeout, max_bytes):
        fetched.append(url)
        return b"key" if url.endswith(".gpg") else SOURCE.encode()

    def inventory():
        inventory_calls.append(True)
        return TailscaleSnapshot("missing_cli")

    owner = TailscalePackageInstallOwner(
        root, authority, approvals, platform="linux",
        os_release=lambda: {"ID": "ubuntu", "VERSION_CODENAME": "noble"},
        apt_executable=str(apt), fetch=fetch,
        key_fingerprint=lambda _: KEY_FINGERPRINT,
        privileged_run=privilege, inventory=inventory,
        installed_file_state=lambda _: "absent",
    )
    return owner, authority, approvals, privilege, fetched, inventory_calls


def approved(setup):
    owner, authority, approvals, *_ = setup
    request = owner.plan().request(owner.root)
    authority.set_grant("tailscale.install", enabled=True,
                        executables=[request.parameters["executable"]])
    return request, approvals.issue(request)


@pytest.mark.parametrize("os_id,codename", [
    ("fedora", "noble"), ("ubuntu", "oracular"), ("debian", "buster"),
    ("ubuntu;id", "noble"),
])
def test_install_plan_rejects_unsupported_release(os_id, codename):
    with pytest.raises(ValueError):
        UbuntuDebianInstallPlan.for_release(os_id, codename, "/usr/bin/apt-get")


def test_plan_preview_binds_official_source_and_exact_package(setup):
    owner, *_ = setup
    plan = owner.plan()
    request = plan.request(owner.root)
    preview = plan.preview()
    assert request.parameters["package"] == "tailscale"
    assert request.parameters["repository_key_url"] == (
        "https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg")
    assert request.parameters["repository_list_url"] == (
        "https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list")
    assert KEY_FINGERPRINT in preview
    assert SOURCE.splitlines()[1] in preview
    assert "apt-get update" in preview and "apt-get install tailscale" in preview
    assert "/var/lib/apt/lists/isycode-tailscale" in preview
    assert request.parameters["package_service_effect"] == "may_start_or_restart_tailscaled"
    assert "may start or restart tailscaled" in preview


def test_install_requires_exact_grant_and_fresh_approval_before_effect(setup):
    owner, authority, approvals, privilege, fetched, _ = setup
    request = owner.plan().request(owner.root)
    assert owner.install(request, approvals.issue(request)).decision == "DENY"
    authority.set_grant("tailscale.install", enabled=True,
                        executables=[request.parameters["executable"]])
    assert owner.install(request, None).decision == "DENY"
    assert not privilege.calls and not fetched
    wrong = replace(request, parameters={**request.parameters, "package": "curl"})
    assert owner.install(wrong, approvals.issue(wrong)).decision == "DENY"
    assert not privilege.calls


def test_verified_install_uses_fixed_non_shell_operations_and_reinspects(setup):
    owner, _, _, privilege, fetched, inventory_calls = setup
    request, approval = approved(setup)
    outcome = owner.install(request, approval)
    assert outcome.decision == "ALLOW"
    assert outcome.receipt is not None
    assert outcome.receipt.verify(request, outcome.text)
    assert len(fetched) == 2
    assert inventory_calls == [True]
    assert all(isinstance(argv, tuple) and argv[0] == "/usr/bin/pkexec"
               and all(isinstance(part, str) for part in argv)
               and 0 < timeout <= 120 and max_output <= 65536
               for argv, timeout, max_output in privilege.calls)
    commands = [call[0] for call in privilege.calls]
    apt = request.parameters["executable"]
    assert any(apt in cmd and "update" in cmd for cmd in commands)
    assert any(apt in cmd and "tailscale" in cmd for cmd in commands)
    assert all("Dir::State::lists=/var/lib/apt/lists/isycode-tailscale" in cmd
               for cmd in commands if apt in cmd)
    assert any("APT::Update::Error-Mode=any" in cmd for cmd in commands)
    assert any("/usr/bin/install" in cmd and "-d" in cmd for cmd in commands)
    assert all("systemctl" not in cmd and "up" not in cmd for cmd in commands)
    assert owner.install(request, approval).decision == "DENY"


def test_wrong_signing_key_never_prompts_for_privilege(setup):
    owner, _, _, privilege, _, _ = setup
    owner._key_fingerprint = lambda _: "0" * 40
    request, approval = approved(setup)
    outcome = owner.install(request, approval)
    assert outcome.decision == "ERROR"
    assert "signing key" in outcome.reason
    assert privilege.calls == []


def test_changed_repository_source_never_prompts_for_privilege(setup):
    owner, _, _, privilege, _, _ = setup
    owner._fetch = lambda url, **_: b"deb https://evil.invalid/ stable main\n"
    request, approval = approved(setup)
    assert owner.install(request, approval).decision == "ERROR"
    assert privilege.calls == []


@pytest.mark.parametrize("failure_at,stderr", [
    (1, "Authentication canceled"), (3, "Could not get lock /var/lib/dpkg/lock"),
    (4, "https://private.invalid/?token=supersecret"),
])
def test_privilege_cancellation_apt_lock_and_failure_are_redacted(setup, failure_at, stderr):
    owner, _, _, _, _, _ = setup
    owner._privileged_run = FakePrivilege(failure_at=failure_at, stderr=stderr)
    request, approval = approved(setup)
    outcome = owner.install(request, approval)
    assert outcome.decision == "ERROR"
    assert "supersecret" not in outcome.reason + outcome.text
    assert "private.invalid" not in outcome.reason + outcome.text


def test_timeout_records_failure_without_following_steps(setup):
    owner, _, _, privilege, _, _ = setup

    def timeout(argv, **_):
        privilege.calls.append(tuple(argv))
        raise TimeoutError("https://secret.invalid?token=hidden")

    owner._privileged_run = timeout
    request, approval = approved(setup)
    outcome = owner.install(request, approval)
    assert outcome.decision == "ERROR"
    assert len(privilege.calls) == 1
    assert "hidden" not in outcome.reason + outcome.text


def test_service_effect_change_invalidates_approval_before_privilege(setup):
    owner, _, approvals, privilege, fetched, _ = setup
    request, approval = approved(setup)
    understated = replace(request, parameters={**request.parameters,
                          "package_service_effect": "no_service_start"})
    omitted = replace(request, parameters={key: value for key, value in
                      request.parameters.items() if key != "package_service_effect"})
    assert owner.install(understated, approval).decision == "DENY"
    assert owner.install(understated, approvals.issue(understated)).decision == "DENY"
    assert owner.install(omitted, approvals.issue(omitted)).decision == "DENY"
    assert privilege.calls == [] and fetched == []
    assert owner.install(request, approval).decision == "ALLOW"
