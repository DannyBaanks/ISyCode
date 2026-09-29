"""Explicitly approved Ubuntu/Debian Tailscale package installation.

The owner accepts one immutable apt recipe. Network, key inspection, privilege,
and inventory boundaries are injectable so tests never change the host.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Callable, Literal, Mapping, Sequence
from urllib import request as urlrequest

from isycode.action_runtime import (
    ActionOutcome, ActionReceipt, ProductActionGate, TailscaleAuthorityFacts,
)
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.security import ActionRequest
from isycode.tailscale import TailscaleAdapter, TailscaleCommandResult, _bounded_run
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_setup import state_root


KEY_FINGERPRINT = "2596A99EAAB33821893C0A79458CA832957F5868"
PACKAGE_SERVICE_EFFECT = "may_start_or_restart_tailscaled"
KEYRING_PATH = Path("/usr/share/keyrings/tailscale-archive-keyring.gpg")
SOURCE_PATH = Path("/etc/apt/sources.list.d/tailscale.list")
APT_LISTS_PATH = Path("/var/lib/apt/lists/isycode-tailscale")
SUPPORTED = {
    "ubuntu": frozenset({"focal", "jammy", "noble"}),
    "debian": frozenset({"bullseye", "bookworm", "trixie"}),
}
MAX_FETCH = 16 * 1024
MAX_OUTPUT = 64 * 1024
FETCH_TIMEOUT = 8.0
COMMAND_TIMEOUT = 120.0


@dataclass(frozen=True)
class UbuntuDebianInstallPlan:
    os_id: str
    codename: str
    apt_executable: str
    repository_uri: str
    key_url: str
    list_url: str
    signing_key_fingerprint: str
    package: str
    package_service_effect: Literal["may_start_or_restart_tailscaled"]
    source_text: str
    update_argv: tuple[str, ...]
    install_argv: tuple[str, ...]

    @classmethod
    def for_release(cls, os_id: str, codename: str, apt_executable: str):
        if (os_id not in SUPPORTED or codename not in SUPPORTED[os_id]
                or not isinstance(apt_executable, str)
                or Path(apt_executable).name != "apt-get"
                or not Path(apt_executable).is_absolute()):
            raise ValueError("unsupported Tailscale apt release or executable")
        base = f"https://pkgs.tailscale.com/stable/{os_id}"
        key_url = f"{base}/{codename}.noarmor.gpg"
        list_url = f"{base}/{codename}.tailscale-keyring.list"
        source = (f"# Tailscale packages for {os_id} {codename}\n"
                  f"deb [signed-by={KEYRING_PATH}] {base} {codename} main\n")
        apt_options = (
            "-o", f"Dir::Etc::sourcelist={SOURCE_PATH}",
            "-o", "Dir::Etc::sourceparts=-",
            "-o", f"Dir::State::lists={APT_LISTS_PATH}",
            "-o", "APT::Get::AllowUnauthenticated=false",
            "-o", "Acquire::AllowInsecureRepositories=false",
            "-o", "APT::Update::Error-Mode=any",
        )
        update = (apt_executable, *apt_options, "update")
        install = (apt_executable, *apt_options, "install", "--yes",
                   "--no-install-recommends", "tailscale")
        return cls(os_id, codename, apt_executable, base, key_url, list_url,
                   KEY_FINGERPRINT, "tailscale", PACKAGE_SERVICE_EFFECT,
                   source, update, install)

    def request(self, root: Path) -> ActionRequest:
        return ActionRequest("tailscale.install", root, "tailscale", {
            "executable": self.apt_executable, "os_id": self.os_id,
            "os_codename": self.codename, "repository_key_url": self.key_url,
            "repository_list_url": self.list_url, "package": self.package,
            "package_service_effect": self.package_service_effect,
        }, execution_owner="tailscale_package_install")

    def preview(self) -> str:
        return (f"Tailscale package source: {self.repository_uri} {self.codename} main\n"
                f"Signing key: {self.key_url}\n"
                f"Signing key fingerprint: {self.signing_key_fingerprint}\n"
                f"Keyring: {KEYRING_PATH}\n"
                f"Repository source: {SOURCE_PATH}\n{self.source_text}"
                f"Isolated signed package indexes: {APT_LISTS_PATH}\n"
                f"Package changes: apt-get update; apt-get install {self.package}\n"
                "Package maintainer script may start or restart tailscaled.\n")


def _read_os_release() -> Mapping[str, str]:
    result: dict[str, str] = {}
    raw = Path("/etc/os-release").read_text(encoding="utf-8")
    if len(raw) > 16 * 1024:
        raise ValueError("OS release data exceeds limit")
    for line in raw.splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            result[key] = value.strip().strip('"')
    return result


class _NoRedirect(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("repository redirect is not allowed")


def _fetch_exact(url: str, *, timeout: float, max_bytes: int) -> bytes:
    if not url.startswith("https://pkgs.tailscale.com/stable/"):
        raise ValueError("unapproved package source")
    opener = urlrequest.build_opener(_NoRedirect)
    with opener.open(url, timeout=timeout) as response:
        if response.geturl() != url or response.status != 200:
            raise ValueError("package source did not match the approved URL")
        data = response.read(max_bytes + 1)
    if not data or len(data) > max_bytes:
        raise ValueError("package source is empty or oversized")
    return data


def _inspect_key(data: bytes) -> str:
    with tempfile.TemporaryDirectory(prefix="isycode-tailkey-") as directory:
        key_path = Path(directory) / "key.gpg"
        key_path.write_bytes(data)
        result = _bounded_run(
            ("/usr/bin/gpg", "--batch", "--no-default-keyring", "--show-keys",
             "--with-colons", str(key_path)),
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
            timeout=5.0, max_output=MAX_OUTPUT)
    if result.returncode:
        raise ValueError("Tailscale signing key could not be inspected")
    primary = [line.split(":")[9] for line in result.stdout.splitlines()
               if line.startswith("fpr:")]
    if len(primary) != 2 or not all(len(item) == 40 for item in primary):
        raise ValueError("Tailscale signing key has unexpected structure")
    return primary[0]


def _privileged_run(argv: Sequence[str], *, timeout: float,
                    max_output: int) -> TailscaleCommandResult:
    return _bounded_run(argv, env={"PATH": "/usr/bin:/bin", "LANG": "C",
                                   "LC_ALL": "C", "DEBIAN_FRONTEND": "noninteractive"},
                        timeout=timeout, max_output=max_output)


def _installed_file_state(path: Path) -> str:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "absent"
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FETCH:
        return "conflict"
    return "present"


class _InstallAttemptJournal:
    """Durable, minimal attempt status without network data or process output."""

    def __init__(self, root: Path):
        directory = state_root() / "tailscale-install"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if directory.is_symlink() or not directory.is_dir():
            raise OSError("install receipt directory is unsafe")
        directory.chmod(0o700)
        identity = hashlib.sha256(str(root).encode()).hexdigest()[:32]
        self.path = directory / f"attempts-{identity}.jsonl"

    def record(self, request: ActionRequest, *, phase: str, status: str) -> None:
        allowed_phases = {"authorized", "key", "source", "keyring", "repository",
                          "update", "install", "inventory", "complete"}
        if phase not in allowed_phases or status not in {"started", "failed", "success"}:
            raise ValueError("invalid install receipt status")
        body = {"time": time.time(), "action": "tailscale.install",
                "request_digest": request.digest, "phase": phase, "status": status}
        encoded = (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode()
        descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT |
                             getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1_000_000:
                raise OSError("install receipt file is unsafe or full")
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class TailscalePackageInstallOwner:
    """Install only the pinned official stable apt package after exact approval."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore, *, platform: str | None = None,
                 os_release: Callable[[], Mapping[str, str]] = _read_os_release,
                 apt_executable: str = "/usr/bin/apt-get",
                 fetch: Callable = _fetch_exact,
                 key_fingerprint: Callable[[bytes], str] = _inspect_key,
                 privileged_run: Callable = _privileged_run,
                 inventory: Callable = lambda: TailscaleAdapter().inspect(),
                 installed_file_state: Callable[[Path], str] = _installed_file_state):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self._platform = sys.platform if platform is None else platform
        self._os_release = os_release
        self._apt_executable = apt_executable
        self._fetch = fetch
        self._key_fingerprint = key_fingerprint
        self._privileged_run = privileged_run
        self._inventory = inventory
        self._installed_file_state = installed_file_state

    def plan(self) -> UbuntuDebianInstallPlan:
        if self._platform != "linux":
            raise ValueError("Tailscale package installation is supported only on Linux")
        release = self._os_release()
        if not isinstance(release, Mapping):
            raise ValueError("OS release information is unavailable")
        executable = Path(self._apt_executable).resolve(strict=True)
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("apt-get executable is unavailable")
        return UbuntuDebianInstallPlan.for_release(
            release.get("ID"), release.get("VERSION_CODENAME"), str(executable))

    def install(self, request: ActionRequest,
                approval: ActionApproval) -> ActionOutcome:
        try:
            plan = self.plan()
            if not isinstance(request, ActionRequest) or request != plan.request(self.root):
                return ActionOutcome("Tailscale installation denied.", "DENY", None,
                                     "request does not match the observed package plan")
            facts = TailscaleAuthorityFacts(package_manager=plan.apt_executable,
                                            os_id=plan.os_id, os_codename=plan.codename)
            gate = ProductActionGate(self.root, self.authority,
                                     owner_id="tailscale_package_install",
                                     tailscale_facts=facts)
            _, decision = gate.authorize(request, approvals=self.approvals, approval=approval)
            if not decision.allowed:
                return ActionOutcome("Tailscale installation denied.", "DENY", None,
                                     "workspace grant, Sentinel, approval, or journal denied")
            journal = _InstallAttemptJournal(self.root)
            journal.record(request, phase="authorized", status="started")
        except (OSError, ValueError, TypeError):
            return ActionOutcome("Tailscale installation denied.", "DENY", None,
                                 "installation plan or durable journal unavailable")

        phase = "key"
        try:
            key = self._fetch(plan.key_url, timeout=FETCH_TIMEOUT, max_bytes=MAX_FETCH)
            if (not isinstance(key, bytes) or not 0 < len(key) <= MAX_FETCH
                    or self._key_fingerprint(key) != plan.signing_key_fingerprint):
                raise ValueError("signing key identity mismatch")
            phase = "source"
            source = self._fetch(plan.list_url, timeout=FETCH_TIMEOUT, max_bytes=MAX_FETCH)
            if source != plan.source_text.encode("utf-8"):
                raise ValueError("official repository source mismatch")
            with tempfile.TemporaryDirectory(prefix="isycode-tailinstall-") as directory:
                key_file = Path(directory) / "keyring.gpg"
                source_file = Path(directory) / "tailscale.list"
                key_file.write_bytes(key)
                source_file.write_bytes(source)
                for label, path, expected in (("keyring", KEYRING_PATH, key),
                                               ("repository", SOURCE_PATH, source)):
                    phase = label
                    state = self._installed_file_state(path)
                    if state not in {"absent", "present"}:
                        raise ValueError("existing repository file conflicts with the plan")
                    if state == "present" and path.read_bytes() != expected:
                        raise ValueError("existing repository file conflicts with the plan")
                    if state == "absent":
                        staged = key_file if label == "keyring" else source_file
                        self._run_step(("/usr/bin/pkexec", "/usr/bin/install", "-m", "0644",
                                        str(staged), str(path)))
                phase = "repository"
                self._run_step(("/usr/bin/pkexec", "/usr/bin/install", "-d", "-m", "0755",
                                str(APT_LISTS_PATH)))
                phase = "update"
                self._run_step(("/usr/bin/pkexec", *plan.update_argv))
                phase = "install"
                self._run_step(("/usr/bin/pkexec", *plan.install_argv))
            phase = "inventory"
            self._inventory()
            result = "Tailscale package installation completed; inventory refreshed."
            receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), request.action_id,
                                    request.digest, "ALLOW", "SUCCESS",
                                    hashlib.sha256(result.encode()).hexdigest())
            if not gate.persist_receipt(request, receipt):
                raise OSError("durable action journal rejected success receipt")
            journal.record(request, phase="complete", status="success")
            return ActionOutcome(result, "ALLOW", receipt, "official apt recipe completed")
        except (OSError, ValueError, TypeError, TimeoutError) as exc:
            try:
                journal.record(request, phase=phase, status="failed")
            except (OSError, ValueError):
                return ActionOutcome("Tailscale installation status is not verifiable.",
                                     "NOT_VERIFIABLE", None,
                                     "durable failure receipt unavailable; inspect package state")
            reason = ("signing key verification failed" if phase == "key" else
                      "repository verification failed" if phase == "source" else
                      "OS authorization cancelled or package operation failed" if phase in
                      {"keyring", "repository", "update", "install"} else
                      "post-install inventory or receipt unavailable")
            return ActionOutcome("Tailscale installation did not complete; inspect package state.",
                                 "ERROR", None, reason)

    def _run_step(self, argv: tuple[str, ...]) -> None:
        result = self._privileged_run(argv, timeout=COMMAND_TIMEOUT,
                                      max_output=MAX_OUTPUT)
        if (not isinstance(result, TailscaleCommandResult)
                or len(result.stdout.encode()) + len(result.stderr.encode()) > MAX_OUTPUT
                or result.returncode != 0):
            raise ValueError("privileged package operation failed")


__all__ = ["TailscalePackageInstallOwner", "UbuntuDebianInstallPlan"]
