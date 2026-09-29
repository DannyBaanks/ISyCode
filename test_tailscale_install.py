"""Offline Tailscale apt preparation and exact package transaction witnesses."""
from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.action_audit import ActionAuditJournal
from isycode.tailscale import TailscaleCommandResult
from isycode.tailscale_install import (
    TailscalePackageInstallOwner, UbuntuDebianInstallPlan, _atomic_private_file,
    _inspect_key, _simulation,
)
from isycode.workspace_authority import WorkspaceAuthority


KEY = "2596A99EAAB33821893C0A79458CA832957F5868"
SOURCE = ("# Tailscale packages for ubuntu noble\n"
          "deb [signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg] "
          "https://pkgs.tailscale.com/stable/ubuntu noble main\n")
ARCHIVE = b"fake signed tailscale deb bytes"
VERSION = "1.2.3"
SIMULATION = ("Reading package lists...\n"
              "0 upgraded, 1 newly installed, 0 to remove and 0 not upgraded.\n"
              f"Inst tailscale ({VERSION} pkgs.tailscale.com [amd64])\n"
              f"Conf tailscale ({VERSION} pkgs.tailscale.com [amd64])\n")


class FakeApt:
    def __init__(self):
        self.plan = None
        self.calls = []
        self.privileged = []
        self.simulation = SIMULATION
        self.hooks = False

    def run(self, argv, *, env, timeout, max_output):
        self.calls.append(tuple(argv))
        plan = self.plan
        if argv[0].endswith("apt-config"):
            dump = (f'Dir::Etc "{plan.private_directory}";\n'
                    f'Dir::Etc::sourcelist "{plan.private_directory / "source.list"}";\n'
                    'Dir::Etc::main "/dev/null";\nDir::Etc::parts "-";\n')
            if self.hooks:
                dump += 'DPkg::Pre-Install-Pkgs:: "host-hook";\n'
            return TailscaleCommandResult(0, dump, "")
        if argv[-1] == "update":
            lists = plan.private_directory / "lists"
            prefix = f"pkgs.tailscale.com_stable_ubuntu_dists_noble_"
            (lists / (prefix + "InRelease")).write_bytes(b"signed release")
            (lists / (prefix + "main_binary-amd64_Packages.lz4")).write_bytes(b"signed package index")
            return TailscaleCommandResult(0, "updated", "")
        if argv[0].endswith("gpgv"):
            return TailscaleCommandResult(0, "signature valid", "")
        if "-s" in argv:
            return TailscaleCommandResult(0, self.simulation, "")
        if argv[0].endswith("apt-cache"):
            metadata = (f"Package: tailscale\nVersion: {VERSION}\nArchitecture: amd64\n"
                        "Filename: pool/tailscale_1.2.3_amd64.deb\n"
                        f"SHA256: {hashlib.sha256(ARCHIVE).hexdigest()}\n"
                        f"Size: {len(ARCHIVE)}\n")
            return TailscaleCommandResult(0, metadata, "")
        if argv[0].endswith("dpkg-query"):
            return TailscaleCommandResult(0, VERSION, "")
        pytest.fail(f"unexpected apt argv: {argv}")

    def privileged_run(self, argv, *, env, timeout, max_output):
        self.privileged.append(tuple(argv))
        return TailscaleCommandResult(0, "installed", "")


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
    fake = FakeApt()
    fetched = []

    def fetch(url, *, timeout, max_bytes):
        fetched.append(url)
        if url.endswith(".gpg"):
            return b"one pinned signing key"
        if url.endswith(".list"):
            return SOURCE.encode()
        if url.endswith(".deb"):
            return ARCHIVE
        pytest.fail(f"unapproved network URL: {url}")

    owner = TailscalePackageInstallOwner(
        root, authority, approvals, platform="linux",
        os_release=lambda: {"ID": "ubuntu", "VERSION_CODENAME": "noble"},
        apt_executable=str(apt), fetch=fetch,
        key_fingerprint=lambda _: KEY,
        run=fake.run, privileged_run=fake.privileged_run,
    )
    fake.plan = owner.plan()
    return owner, authority, approvals, fake, fetched


def prepare_approved(setup):
    owner, authority, approvals, *_ = setup
    request = owner.plan().prepare_request(owner.root)
    authority.set_grant("tailscale.install.prepare", enabled=True,
                        executables=[request.parameters["executable"]])
    return request, approvals.issue(request)


def prepared(setup):
    owner, authority, approvals, fake, fetched = setup
    request, approval = prepare_approved(setup)
    outcome = owner.prepare(request, approval)
    assert outcome.decision == "ALLOW", outcome.reason
    return owner.simulate()


@pytest.mark.parametrize("os_id,codename", [
    ("fedora", "noble"), ("ubuntu", "oracular"), ("debian", "buster"),
    ("ubuntu;id", "noble"),
])
def test_install_plan_rejects_unsupported_release(os_id, codename):
    with pytest.raises(ValueError):
        UbuntuDebianInstallPlan.for_release(os_id, codename, "/usr/bin/apt-get")


def test_preparation_requires_distinct_grant_and_one_use_approval_before_network_or_apt(setup):
    owner, authority, approvals, fake, fetched = setup
    request = owner.plan().prepare_request(owner.root)
    assert owner.prepare(request, approvals.issue(request)).decision == "DENY"
    assert not fetched and not fake.calls
    authority.set_grant("tailscale.install.prepare", enabled=True,
                        executables=[request.parameters["executable"]])
    assert owner.prepare(request, None).decision == "DENY"
    altered = replace(request, parameters={**request.parameters, "package": "curl"})
    assert owner.prepare(altered, approvals.issue(altered)).decision == "DENY"
    assert not fetched and not fake.calls
    approval = approvals.issue(request)
    assert owner.prepare(request, approval).decision == "ALLOW"
    assert owner.prepare(request, approval).decision == "DENY"
    assert owner.plan().private_directory.is_dir()
    assert str(owner.plan().private_directory).startswith(str(owner.root.parent / "state"))
    assert all("/etc/apt" not in str(path) for path in owner.plan().private_directory.iterdir())
    assert not fake.privileged
    assert any(url.endswith(".deb") for url in fetched)
    assert (owner.plan().private_directory / "cache" /
            "tailscale_1.2.3_amd64.deb").read_bytes() == ARCHIVE


def test_simulation_binds_single_package_version_hash_actions_and_service_effect(setup):
    transaction = prepared(setup)
    request = transaction.request(setup[0].root)
    preview = transaction.preview()
    assert request.parameters["package_version"] == VERSION
    assert request.parameters["package_actions"] == (
        f"Inst tailscale={VERSION}", f"Conf tailscale={VERSION}")
    assert request.parameters["archive_sha256"] == hashlib.sha256(ARCHIVE).hexdigest()
    assert request.parameters["package_service_effect"] == "may_start_or_restart_tailscaled"
    assert request.parameters["simulation_digest"] in preview
    assert "maintainer scripts and triggers run as root" in preview
    assert "may start or restart tailscaled" in preview
    assert "--no-upgrade --no-remove --no-download" in preview
    assert not setup[3].privileged


def test_exact_approved_install_uses_fixed_privilege_argv_and_receipt(setup):
    transaction = prepared(setup)
    owner, authority, approvals, fake, _ = setup
    request = transaction.request(owner.root)
    assert owner.install(request, approvals.issue(request)).decision == "DENY"
    assert not fake.privileged
    authority.set_grant("tailscale.install", enabled=True,
                        executables=[request.parameters["executable"]])
    approval = approvals.issue(request)
    fetched_before_install = list(setup[4])
    outcome = owner.install(request, approval)
    assert outcome.decision == "ALLOW", outcome.reason
    assert outcome.receipt.outcome == "SUCCESS"
    assert len(fake.privileged) == 1
    assert setup[4] == fetched_before_install
    argv = fake.privileged[0]
    assert argv[:2] == ("/usr/bin/pkexec", "/usr/bin/env")
    assert argv[3:] == transaction.install_argv
    assert "--no-download" in argv and "--no-remove" in argv
    assert owner.install(request, approval).decision == "DENY"
    report = ActionAuditJournal.for_read_only_inspection(owner.root).verify()
    assert report.status == "PASS"
    assert [item["outcome"] for item in report.recent if item.get("outcome")][-1] == "SUCCESS"


def test_dependency_transaction_routes_to_manual_without_privilege(setup):
    owner, _, _, fake, _ = setup
    prepare_approved_request, approval = prepare_approved(setup)
    fake.simulation = ("0 upgraded, 2 newly installed, 0 to remove and 0 not upgraded.\n"
                       "Inst dependency (1.0 repo [amd64])\n"
                       f"Inst tailscale ({VERSION} repo [amd64])\n"
                       f"Conf tailscale ({VERSION} repo [amd64])\n")
    outcome = owner.prepare(prepare_approved_request, approval)
    assert outcome.decision == "ERROR" and outcome.receipt.outcome == "FAILURE"
    with pytest.raises(ValueError):
        owner.simulate()
    assert not fake.privileged


def test_drift_after_final_approval_records_failure_without_privilege(setup):
    transaction = prepared(setup)
    owner, authority, approvals, fake, _ = setup
    request = transaction.request(owner.root)
    authority.set_grant("tailscale.install", enabled=True,
                        executables=[request.parameters["executable"]])
    fake.simulation = SIMULATION.replace("1 newly installed", "2 newly installed")
    outcome = owner.install(request, approvals.issue(request))
    assert outcome.decision == "ERROR"
    assert outcome.receipt.outcome == "FAILURE"
    assert not fake.privileged
    journal = ActionAuditJournal.for_read_only_inspection(owner.root)
    assert journal.verify().recent[-1]["outcome"] == "FAILURE"


def test_prepare_rejects_host_apt_hook_before_update_and_records_failure(setup):
    owner, _, _, fake, _ = setup
    request, approval = prepare_approved(setup)
    fake.hooks = True
    outcome = owner.prepare(request, approval)
    assert outcome.decision == "ERROR"
    assert outcome.receipt.outcome == "FAILURE"
    assert not any(call[-1] == "update" for call in fake.calls)
    assert owner.plan().private_directory.exists()  # Partial private state stays visible.
    assert not fake.privileged


def test_mutated_private_source_denies_install_before_privilege(setup):
    transaction = prepared(setup)
    owner, authority, approvals, fake, _ = setup
    request = transaction.request(owner.root)
    authority.set_grant("tailscale.install", enabled=True,
                        executables=[request.parameters["executable"]])
    (transaction.plan.private_directory / "source.list").write_text("forged")
    outcome = owner.install(request, approvals.issue(request))
    assert outcome.decision == "ERROR" and outcome.receipt.outcome == "FAILURE"
    assert not fake.privileged


def test_mutated_cached_archive_denies_install_before_privilege(setup):
    transaction = prepared(setup)
    owner, authority, approvals, fake, fetched = setup
    request = transaction.request(owner.root)
    authority.set_grant("tailscale.install", enabled=True,
                        executables=[request.parameters["executable"]])
    (transaction.plan.private_directory / "cache" / transaction.archive_name).write_bytes(b"forged")
    before = list(fetched)
    outcome = owner.install(request, approvals.issue(request))
    assert outcome.decision == "ERROR" and outcome.receipt.outcome == "FAILURE"
    assert not fake.privileged
    assert fetched == before


def test_wrong_key_records_redacted_prepare_failure(setup):
    owner, _, _, fake, _ = setup
    owner._key_fingerprint = lambda _: "0" * 40
    request, approval = prepare_approved(setup)
    outcome = owner.prepare(request, approval)
    assert outcome.decision == "ERROR" and outcome.receipt.outcome == "FAILURE"
    assert not fake.calls and not fake.privileged
    assert ActionAuditJournal.for_read_only_inspection(owner.root).verify().status == "PASS"


def test_signing_key_inspection_rejects_second_primary_key(monkeypatch):
    output = ("pub:::::::::\n"
              "fpr:::::::::2596A99EAAB33821893C0A79458CA832957F5868:\n"
              "pub:::::::::\n"
              "fpr:::::::::0000000000000000000000000000000000000000:\n")
    monkeypatch.setattr("isycode.tailscale_install._bounded_run",
                        lambda *_, **__: TailscaleCommandResult(0, output, ""))
    with pytest.raises(ValueError, match="structure"):
        _inspect_key(b"fake keyring")


def test_simulation_rejects_summary_embedded_in_other_text():
    with pytest.raises(ValueError, match="summary"):
        _simulation("10 upgraded, 1 newly installed, 0 to remove\n" + SIMULATION.split("\n", 2)[-1])


def test_atomic_publication_rejects_symlinked_parent(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    target = tmp_path / "outside"
    target.mkdir(mode=0o700)
    (private / "redirect").symlink_to(target, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        _atomic_private_file(private / "redirect" / "keyring.gpg", b"secret")
    assert not (target / "keyring.gpg").exists()
