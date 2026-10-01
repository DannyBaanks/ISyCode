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
        self.stage = {}
        self.substitute_copy = False
        self.bad_stat = None
        self.bad_stat_fields = "1000\t400\tregular file\t1\t0"
        self.bad_hash = None

    def run(self, argv, *, env, timeout, max_output):
        self.calls.append(tuple(argv))
        plan = self.plan
        if argv[0].endswith("apt-config"):
            directory = Path(env["APT_CONFIG"]).parent
            dump = (f'Dir::Etc "{directory}";\n'
                    f'Dir::Etc::sourcelist "{directory / "source.list"}";\n'
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
        assert argv[0] == "/usr/bin/pkexec"
        command = argv[1:]
        if command[0] == "/usr/bin/stat":
            path = command[-1]
            if path == str(self.bad_stat):
                return TailscaleCommandResult(0, self.bad_stat_fields, "")
            item = self.stage.get(path)
            if item is None:
                return TailscaleCommandResult(1, "", "No such file or directory")
            kind, mode, data = item
            if command[1] == "--printf=%F":
                return TailscaleCommandResult(0, kind, "")
            return TailscaleCommandResult(0, f"0\t{mode:o}\t{kind}\t1\t{len(data)}", "")
        if command[0] == "/usr/bin/install":
            for path in command[5:]:
                self.stage[path] = ("directory", 0o700, b"")
            return TailscaleCommandResult(0, "", "")
        if command[0] == "/usr/bin/dd":
            options = dict(part.split("=", 1) for part in command[1:] if "=" in part)
            if self.substitute_copy:
                source_path = Path(options["if"])
                oversized = source_path.parent / "substituted-large-source"
                oversized.write_bytes(b"x" * (int(options["count"]) + 100))
                source_path.unlink()
                source_path.symlink_to(oversized)
                self.substitute_copy = False
            with open(options["if"], "rb") as source:
                data = source.read(int(options["count"]))
            self.stage[options["of"]] = ("regular file", 0o600, data)
            return TailscaleCommandResult(0, "", "")
        if command[0] == "/usr/bin/chmod":
            path = command[-1]
            if path in self.stage:
                kind, _, data = self.stage[path]
                self.stage[path] = (kind, int(command[1], 8), data)
            return TailscaleCommandResult(0, "", "")
        if command[0] == "/usr/bin/sha256sum":
            path = command[-1]
            digest = hashlib.sha256(self.stage[path][2]).hexdigest()
            if path == str(self.bad_hash):
                digest = "0" * 64
            return TailscaleCommandResult(0, f"{digest} *{path}\n", "")
        if command[0] == "/usr/bin/env":
            assert command[1].startswith("APT_CONFIG=/var/lib/isycode/tailscale/")
            assert command[2] == "DEBIAN_FRONTEND=noninteractive"
            subcommand = command[3:]
            if subcommand[0].endswith("apt-get") and "-s" not in subcommand:
                return TailscaleCommandResult(0, "installed", "")
            return self.run(subcommand, env={"APT_CONFIG": command[1].split("=", 1)[1]},
                            timeout=timeout, max_output=max_output)
        pytest.fail(f"unexpected privileged argv: {argv}")


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
    fake.stage["/var"] = ("directory", 0o755, b"")
    fake.stage["/var/lib"] = ("directory", 0o755, b"")
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


def staged(setup):
    transaction = prepared(setup)
    owner, authority, approvals, *_ = setup
    request = transaction.stage_request(owner.root)
    authority.set_grant("tailscale.install.stage", enabled=True,
                        executables=[request.parameters["executable"]])
    outcome = owner.stage(request, approvals.issue(request))
    assert outcome.decision == "ALLOW", outcome.reason
    return transaction


def stage_approved(setup, transaction):
    owner, authority, approvals, *_ = setup
    request = transaction.stage_request(owner.root)
    authority.set_grant("tailscale.install.stage", enabled=True,
                        executables=[request.parameters["executable"]])
    return request, approvals.issue(request)


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
    assert request.parameters["stage_manifest_digest"] in preview
    assert str(transaction.stage_directory) in transaction.stage_preview()
    assert "maintainer scripts and triggers run as root" in preview
    assert "may start or restart tailscaled" in preview
    assert "--no-upgrade --no-remove --no-download" in preview
    assert not setup[3].privileged


def test_stage_request_and_preview_bind_every_privileged_operation(setup):
    transaction = prepared(setup)
    owner, authority, approvals, fake, _ = setup
    request = transaction.stage_request(owner.root)
    operations = request.parameters["stage_operations"]
    preview = transaction.stage_preview()
    assert operations
    assert all(operation[0] == "/usr/bin/pkexec" for operation in operations)
    for item in transaction.stage_artifacts:
        target = transaction.stage_directory / item.relative_name
        assert str(item.source) in preview and str(target) in preview
        assert str(item.size) in preview and item.sha256 in preview
        assert any(operation[1] == "/usr/bin/dd" and
                   f"if={item.source}" in operation and f"of={target}" in operation and
                   f"count={item.size + 1}" in operation for operation in operations)
        assert any(operation[1] == "/usr/bin/sha256sum" and str(target) in operation
                   for operation in operations)
    assert "install -d -m 0700" in preview
    assert "chmod 0400" in preview
    assert "stat" in preview and "sha256sum" in preview
    authority.set_grant("tailscale.install.stage", enabled=True,
                        executables=[request.parameters["executable"]])
    altered = replace(request, parameters={**request.parameters,
                                           "stage_operations": operations[:-1]})
    assert owner.stage(altered, approvals.issue(altered)).decision == "DENY"
    assert not fake.privileged
    assert owner.stage(request, approvals.issue(request)).decision == "ALLOW"
    assert set(fake.privileged) <= set(operations)


@pytest.mark.parametrize("phase", ["stage", "install"])
def test_total_deadline_exhausts_across_multiple_privilege_prompts(setup, monkeypatch, phase):
    import isycode.tailscale_install as installer

    transaction = prepared(setup) if phase == "stage" else staged(setup)
    owner, authority, approvals, fake, _ = setup
    clock = [0.0]
    timeouts = []
    original = fake.privileged_run

    def delayed(argv, *, env, timeout, max_output):
        timeouts.append(timeout)
        clock[0] += 2.0
        return original(argv, env=env, timeout=timeout, max_output=max_output)

    owner._privileged_run = delayed
    monkeypatch.setattr(installer.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(installer, "STAGE_TIMEOUT" if phase == "stage" else "FINAL_TIMEOUT", 5.0)
    request = transaction.stage_request(owner.root) if phase == "stage" else transaction.request(owner.root)
    authority.set_grant(request.action_id, enabled=True,
                        executables=[request.parameters["executable"]])
    outcome = (owner.stage(request, approvals.issue(request)) if phase == "stage"
               else owner.install(request, approvals.issue(request)))
    assert outcome.decision == "ERROR" and outcome.receipt.outcome == "FAILURE"
    assert len(timeouts) >= 2 and all(0 < later < earlier
                                      for earlier, later in zip(timeouts, timeouts[1:]))
    assert not any(call[1:] == transaction.privilege_argv[1:] for call in fake.privileged)


def test_install_requires_separate_verified_root_stage(setup):
    transaction = prepared(setup)
    owner, authority, approvals, fake, _ = setup
    request = transaction.request(owner.root)
    authority.set_grant("tailscale.install", enabled=True,
                        executables=[request.parameters["executable"]])
    assert owner.install(request, approvals.issue(request)).decision == "DENY"
    assert not fake.privileged
    stage_request = transaction.stage_request(owner.root)
    assert owner.stage(stage_request, approvals.issue(stage_request)).decision == "DENY"
    assert not fake.privileged


def test_stage_substituted_source_is_bounded_quarantined_and_never_installed(setup):
    transaction = prepared(setup)
    owner, _, _, fake, _ = setup
    fake.substitute_copy = True
    request, approval = stage_approved(setup, transaction)
    outcome = owner.stage(request, approval)
    assert outcome.decision == "ERROR" and outcome.receipt.outcome == "FAILURE"
    copies = [call for call in fake.privileged if call[1] == "/usr/bin/dd"]
    assert copies and all(any(arg.startswith("count=") for arg in call) for call in copies)
    first_copy = copies[0]
    first_target = next(arg.split("=", 1)[1] for arg in first_copy if arg.startswith("of="))
    first_limit = int(next(arg.split("=", 1)[1] for arg in first_copy if arg.startswith("count=")))
    assert len(fake.stage[first_target][2]) == first_limit
    assert fake.stage[str(transaction.stage_directory)][1] == 0
    assert not any(call[1:] == transaction.privilege_argv[1:] for call in fake.privileged)
    assert ActionAuditJournal.for_read_only_inspection(owner.root).verify().status == "PASS"


@pytest.mark.parametrize("kind", ["directory", "symbolic link"])
def test_stage_rejects_existing_or_symlink_path_before_copy(setup, kind):
    transaction = prepared(setup)
    owner, _, _, fake, _ = setup
    fake.stage[str(transaction.stage_directory)] = (kind, 0o700, b"")
    request, approval = stage_approved(setup, transaction)
    outcome = owner.stage(request, approval)
    assert outcome.decision == "ERROR" and outcome.receipt.outcome == "FAILURE"
    assert not any(call[1] == "/usr/bin/dd" for call in fake.privileged)


def test_stage_rejects_symlinked_root_prefix_before_copy(setup):
    transaction = prepared(setup)
    owner, _, _, fake, _ = setup
    fake.bad_stat = Path("/var/lib/isycode")
    fake.bad_stat_fields = "0\t700\tsymbolic link\t1\t0"
    request, approval = stage_approved(setup, transaction)
    outcome = owner.stage(request, approval)
    assert outcome.decision == "ERROR" and outcome.receipt.outcome == "FAILURE"
    assert not any(call[1] == "/usr/bin/dd" for call in fake.privileged)


@pytest.mark.parametrize("defect", ["owner", "mode", "hash"])
def test_stage_rejects_wrong_root_metadata_or_hash(setup, defect):
    transaction = prepared(setup)
    owner, _, _, fake, _ = setup
    target = transaction.stage_directory / "keyring.gpg"
    if defect in {"owner", "mode"}:
        fake.bad_stat = target
        fake.bad_stat_fields = ("1000\t400\tregular file\t1\t20" if defect == "owner"
                                else "0\t600\tregular file\t1\t20")
    else:
        fake.bad_hash = target
    request, approval = stage_approved(setup, transaction)
    outcome = owner.stage(request, approval)
    assert outcome.decision == "ERROR" and outcome.receipt.outcome == "FAILURE"
    assert fake.stage[str(transaction.stage_directory)][1] == 0
    assert not any(call[1:] == transaction.privilege_argv[1:] for call in fake.privileged)


def test_exact_approved_install_uses_fixed_privilege_argv_and_receipt(setup):
    transaction = staged(setup)
    owner, authority, approvals, fake, _ = setup
    request = transaction.request(owner.root)
    before_denial = list(fake.privileged)
    assert owner.install(request, approvals.issue(request)).decision == "DENY"
    assert fake.privileged == before_denial
    authority.set_grant("tailscale.install", enabled=True,
                        executables=[request.parameters["executable"]])
    approval = approvals.issue(request)
    fetched_before_install = list(setup[4])
    outcome = owner.install(request, approval)
    assert outcome.decision == "ALLOW", outcome.reason
    assert outcome.receipt.outcome == "SUCCESS"
    installs = [call for call in fake.privileged if call[1:] == transaction.privilege_argv[1:]]
    assert len(installs) == 1
    assert setup[4] == fetched_before_install
    argv = installs[0]
    assert argv[:2] == ("/usr/bin/pkexec", "/usr/bin/env")
    assert argv[4:] == transaction.install_argv
    assert argv[3] == "DEBIAN_FRONTEND=noninteractive"
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
    transaction = staged(setup)
    owner, authority, approvals, fake, _ = setup
    request = transaction.request(owner.root)
    authority.set_grant("tailscale.install", enabled=True,
                        executables=[request.parameters["executable"]])
    fake.simulation = SIMULATION.replace("1 newly installed", "2 newly installed")
    outcome = owner.install(request, approvals.issue(request))
    assert outcome.decision == "ERROR"
    assert outcome.receipt.outcome == "FAILURE"
    assert not any(call[1:] == transaction.privilege_argv[1:] for call in fake.privileged)
    journal = ActionAuditJournal.for_read_only_inspection(owner.root)
    assert journal.verify().recent[-1]["outcome"] == "FAILURE"


def test_root_stage_drift_after_final_approval_stops_before_apt(setup):
    transaction = staged(setup)
    owner, authority, approvals, fake, _ = setup
    request = transaction.request(owner.root)
    authority.set_grant("tailscale.install", enabled=True,
                        executables=[request.parameters["executable"]])
    target = str(transaction.stage_directory / "keyring.gpg")
    kind, mode, _ = fake.stage[target]
    fake.stage[target] = (kind, mode, b"changed")
    outcome = owner.install(request, approvals.issue(request))
    assert outcome.decision == "ERROR" and outcome.receipt.outcome == "FAILURE"
    assert not any(call[1:] == transaction.privilege_argv[1:] for call in fake.privileged)


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


def test_mutated_private_source_cannot_change_root_stage_install(setup):
    transaction = staged(setup)
    owner, authority, approvals, fake, _ = setup
    request = transaction.request(owner.root)
    authority.set_grant("tailscale.install", enabled=True,
                        executables=[request.parameters["executable"]])
    (transaction.plan.private_directory / "source.list").write_text("forged")
    outcome = owner.install(request, approvals.issue(request))
    assert outcome.decision == "ALLOW" and outcome.receipt.outcome == "SUCCESS"
    assert any(call[1:] == transaction.privilege_argv[1:] for call in fake.privileged)


def test_mutated_private_archive_cannot_change_root_stage_install(setup):
    transaction = staged(setup)
    owner, authority, approvals, fake, fetched = setup
    request = transaction.request(owner.root)
    authority.set_grant("tailscale.install", enabled=True,
                        executables=[request.parameters["executable"]])
    (transaction.plan.private_directory / "cache" / transaction.archive_name).write_bytes(b"forged")
    before = list(fetched)
    outcome = owner.install(request, approvals.issue(request))
    assert outcome.decision == "ALLOW" and outcome.receipt.outcome == "SUCCESS"
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
