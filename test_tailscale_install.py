"""Offline contract tests for the explicitly approved Tailscale package owner."""
from dataclasses import replace

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.action_audit import ActionAuditJournal
from isycode.tailscale import TailscaleCommandResult
from isycode.tailscale_install import (
    TailscalePackageInstallOwner, UbuntuDebianInstallPlan, _inspect_key,
)
from isycode.workspace_authority import WorkspaceAuthority


KEY_FINGERPRINT = "2596A99EAAB33821893C0A79458CA832957F5868"
SOURCE = ("# Tailscale packages for ubuntu noble\n"
          "deb [signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg] "
          "https://pkgs.tailscale.com/stable/ubuntu noble main\n")


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
    fetched = []

    def fetch(url, *, timeout, max_bytes):
        fetched.append(url)
        return b"key" if url.endswith(".gpg") else SOURCE.encode()

    owner = TailscalePackageInstallOwner(
        root, authority, approvals, platform="linux",
        os_release=lambda: {"ID": "ubuntu", "VERSION_CODENAME": "noble"},
        apt_executable=str(apt), fetch=fetch,
        key_fingerprint=lambda _: KEY_FINGERPRINT,
    )
    return owner, authority, approvals, fetched


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
    owner, authority, approvals, fetched = setup
    request = owner.plan().request(owner.root)
    assert owner.install(request, approvals.issue(request)).decision == "DENY"
    authority.set_grant("tailscale.install", enabled=True,
                        executables=[request.parameters["executable"]])
    assert owner.install(request, None).decision == "DENY"
    assert not fetched
    wrong = replace(request, parameters={**request.parameters, "package": "curl"})
    assert owner.install(wrong, approvals.issue(wrong)).decision == "DENY"
    assert not fetched


def test_approved_request_cannot_mutate_before_transaction_is_previewed(setup, monkeypatch):
    owner, _, _, fetched = setup
    monkeypatch.setattr("isycode.tailscale_install._bounded_run",
                        lambda *_, **__: pytest.fail("process launched before transaction approval"))
    request, approval = approved(setup)
    outcome = owner.install(request, approval)
    assert outcome.decision == "ERROR"
    assert outcome.receipt is not None
    assert outcome.receipt.outcome == "FAILURE"
    assert "transaction" in outcome.reason
    assert fetched == [
        "https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg",
        "https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list",
    ]
    report = ActionAuditJournal.for_read_only_inspection(owner.root).verify()
    assert report.status == "PASS"
    assert report.recent[-1]["outcome"] == "FAILURE"


def test_signing_key_inspection_rejects_second_primary_key(monkeypatch):
    output = ("pub:::::::::\n"
              "fpr:::::::::2596A99EAAB33821893C0A79458CA832957F5868:\n"
              "pub:::::::::\n"
              "fpr:::::::::0000000000000000000000000000000000000000:\n")
    monkeypatch.setattr("isycode.tailscale_install._bounded_run",
                        lambda *_, **__: TailscaleCommandResult(0, output, ""))
    with pytest.raises(ValueError, match="structure"):
        _inspect_key(b"fake keyring")


def test_wrong_signing_key_never_prompts_for_privilege(setup):
    owner, _, _, _ = setup
    owner._key_fingerprint = lambda _: "0" * 40
    request, approval = approved(setup)
    outcome = owner.install(request, approval)
    assert outcome.decision == "ERROR"
    assert "signing key" in outcome.reason
    assert outcome.receipt is not None and outcome.receipt.outcome == "FAILURE"


def test_changed_repository_source_never_prompts_for_privilege(setup):
    owner, _, _, _ = setup
    owner._fetch = lambda url, **_: b"deb https://evil.invalid/ stable main\n"
    request, approval = approved(setup)
    assert owner.install(request, approval).decision == "ERROR"


def test_network_error_is_redacted_in_durable_failure_receipt(setup):
    owner, _, _, _ = setup
    owner._fetch = lambda *_, **__: (_ for _ in ()).throw(
        TimeoutError("https://private.invalid/?token=hidden"))
    request, approval = approved(setup)
    outcome = owner.install(request, approval)
    assert outcome.decision == "ERROR"
    assert outcome.receipt is not None
    assert "hidden" not in outcome.reason + outcome.text
    journal = ActionAuditJournal.for_read_only_inspection(owner.root)
    assert "hidden" not in journal.path.read_text(encoding="utf-8")


def test_service_effect_change_invalidates_approval_before_privilege(setup):
    owner, _, approvals, fetched = setup
    request, approval = approved(setup)
    understated = replace(request, parameters={**request.parameters,
                          "package_service_effect": "no_service_start"})
    omitted = replace(request, parameters={key: value for key, value in
                      request.parameters.items() if key != "package_service_effect"})
    assert owner.install(understated, approval).decision == "DENY"
    assert owner.install(understated, approvals.issue(understated)).decision == "DENY"
    assert owner.install(omitted, approvals.issue(omitted)).decision == "DENY"
    assert fetched == []
    assert owner.install(request, approval).decision == "ERROR"
