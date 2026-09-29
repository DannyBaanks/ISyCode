"""Explicitly approved Ubuntu/Debian Tailscale package installation.

The owner accepts one immutable apt recipe. Network, key inspection, privilege,
and inventory boundaries are injectable so tests never change the host.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import selectors
import signal
import time
from pathlib import Path
import secrets
import sys
import tempfile
from dataclasses import dataclass
from typing import Callable, Literal, Mapping
from urllib import request as urlrequest

from isycode.action_runtime import (
    ActionOutcome, ActionReceipt, ProductActionGate, TailscaleAuthorityFacts,
)
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.security import ActionRequest
from isycode.tailscale import _bounded_run
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_setup import state_root


KEY_FINGERPRINT = "2596A99EAAB33821893C0A79458CA832957F5868"
PACKAGE_SERVICE_EFFECT = "may_start_or_restart_tailscaled"
MAX_PACKAGE = 80 * 1024 * 1024
MAX_INDEXES = 32 * 1024 * 1024
APT_TIMEOUT = 90.0
INSTALL_TIMEOUT = 240.0
SUPPORTED = {
    "ubuntu": frozenset({"focal", "jammy", "noble"}),
    "debian": frozenset({"bullseye", "bookworm", "trixie"}),
}
MAX_FETCH = 16 * 1024
MAX_OUTPUT = 64 * 1024
FETCH_TIMEOUT = 8.0


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
    private_directory: Path
    source_text: str
    config_text: str
    update_argv: tuple[str, ...]

    @classmethod
    def for_release(cls, os_id: str, codename: str, apt_executable: str,
                    private_directory: Path | None = None):
        if (os_id not in SUPPORTED or codename not in SUPPORTED[os_id]
                or not isinstance(apt_executable, str)
                or Path(apt_executable).name != "apt-get"
                or not Path(apt_executable).is_absolute()):
            raise ValueError("unsupported Tailscale apt release or executable")
        base = f"https://pkgs.tailscale.com/stable/{os_id}"
        key_url = f"{base}/{codename}.noarmor.gpg"
        list_url = f"{base}/{codename}.tailscale-keyring.list"
        directory = Path(private_directory or (state_root() / "tailscale-apt" / "preview"))
        if (not directory.is_absolute() or any(c.isspace() or c in {'"', "'", "\\"}
                                                for c in str(directory))):
            raise ValueError("private package path cannot be represented safely")
        keyring = directory / "keyring.gpg"
        source_path = directory / "source.list"
        source = (f"# Tailscale packages for {os_id} {codename}\n"
                  f"deb [signed-by={keyring}] {base} {codename} main\n")
        config = (f'Dir::Etc "{directory}";\n'
                  f'Dir::Etc::main "/dev/null";\n'
                  f'Dir::Etc::parts "-";\n'
                  f'Dir::Etc::sourcelist "{source_path}";\n'
                  f'Dir::Etc::sourceparts "-";\n'
                  f'Dir::Etc::trusted "/dev/null";\n'
                  f'Dir::Etc::trustedparts "-";\n'
                  f'Dir::Etc::preferences "/dev/null";\n'
                  f'Dir::Etc::preferencesparts "-";\n'
                  f'Dir::Etc::netrc "/dev/null";\n'
                  f'Dir::Etc::netrcparts "-";\n'
                  f'Dir::State::lists "{directory / "lists"}";\n'
                  f'Dir::Cache::archives "{directory / "cache"}";\n'
                  f'Dir::Cache::pkgcache "{directory / "pkgcache.bin"}";\n'
                  f'Dir::Cache::srcpkgcache "{directory / "srcpkgcache.bin"}";\n'
                  'APT::Get::AllowUnauthenticated "false";\n'
                  'Acquire::AllowInsecureRepositories "false";\n'
                  'APT::Update::Error-Mode "any";\n'
                  'APT::Install-Recommends "false";\n'
                  'APT::Install-Suggests "false";\n')
        config += 'Acquire::Languages "none";\n'
        update = (apt_executable, "update")
        return cls(os_id, codename, apt_executable, base, key_url, list_url,
                   KEY_FINGERPRINT, "tailscale", PACKAGE_SERVICE_EFFECT,
                   directory, source, config, update)

    def prepare_request(self, root: Path) -> ActionRequest:
        return ActionRequest("tailscale.install.prepare", root, "tailscale", {
            "executable": self.apt_executable, "os_id": self.os_id,
            "os_codename": self.codename, "repository_key_url": self.key_url,
            "repository_list_url": self.list_url, "package": self.package,
            "package_service_effect": self.package_service_effect,
            "private_directory": str(self.private_directory),
            "key_fingerprint": self.signing_key_fingerprint,
            "source_sha256": _sha(self.source_text.encode()),
            "config_sha256": _sha(self.config_text.encode()),
            "update_argv": self.update_argv,
        }, execution_owner="tailscale_package_install")

    def prepare_preview(self) -> str:
        return (f"Tailscale package source: {self.repository_uri} {self.codename} main\n"
                f"Signing key: {self.key_url}\n"
                f"Signing key fingerprint: {self.signing_key_fingerprint}\n"
                f"Private keyring, source, signed indexes and package cache: "
                f"{self.private_directory}\n{self.source_text}"
                f"Exact isolated apt configuration:\n{self.config_text}"
                f"Prepare command: {' '.join(self.update_argv)} with isolated APT_CONFIG\n"
                "This preparation writes only private app state; it does not install a package.\n")


@dataclass(frozen=True)
class PreparedTransaction:
    plan: UbuntuDebianInstallPlan
    key_sha256: str
    source_sha256: str
    config_sha256: str
    indexes_digest: str
    version: str
    archive_sha256: str
    archive_name: str
    simulation_digest: str
    package_actions: tuple[str, ...]
    install_argv: tuple[str, ...]

    @property
    def privilege_argv(self) -> tuple[str, ...]:
        return ("/usr/bin/pkexec", "/usr/bin/env",
                f"APT_CONFIG={self.plan.private_directory / 'apt.conf'}",
                *self.install_argv)

    def request(self, root: Path) -> ActionRequest:
        plan = self.plan
        return ActionRequest("tailscale.install", root, "tailscale", {
            "executable": plan.apt_executable, "os_id": plan.os_id,
            "os_codename": plan.codename, "repository_key_url": plan.key_url,
            "repository_list_url": plan.list_url, "package": "tailscale",
            "package_service_effect": PACKAGE_SERVICE_EFFECT,
            "private_directory": str(plan.private_directory),
            "key_fingerprint": KEY_FINGERPRINT,
            "key_sha256": self.key_sha256,
            "source_sha256": self.source_sha256,
            "config_sha256": self.config_sha256,
            "indexes_digest": self.indexes_digest,
            "package_version": self.version,
            "archive_sha256": self.archive_sha256,
            "archive_name": self.archive_name,
            "simulation_digest": self.simulation_digest,
            "package_actions": self.package_actions,
            "install_argv": self.install_argv,
            "privilege_argv": self.privilege_argv,
        }, execution_owner="tailscale_package_install")

    def preview(self) -> str:
        return (f"Official Tailscale source: {self.plan.repository_uri} "
                f"{self.plan.codename} main\n"
                f"Signing key fingerprint: {KEY_FINGERPRINT}\n"
                f"Verified key SHA256: {self.key_sha256}\n"
                f"Signed index digest: {self.indexes_digest}\n"
                f"Exact package: tailscale={self.version}\n"
                f"Verified archive SHA256: {self.archive_sha256}\n"
                f"Package actions: {', '.join(self.package_actions)}\n"
                f"Simulation digest: {self.simulation_digest}\n"
                f"Exact privileged argv: {' '.join(self.privilege_argv)}\n"
                "The exact signed Tailscale package's maintainer scripts and triggers "
                "run as root and may start or restart tailscaled.\n")


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
    primary_keys = 0
    primary_fingerprint = None
    awaiting_primary_fingerprint = False
    for line in result.stdout.splitlines():
        fields = line.split(":")
        if fields[0] == "pub":
            primary_keys += 1
            awaiting_primary_fingerprint = True
        elif fields[0] == "fpr" and awaiting_primary_fingerprint:
            primary_fingerprint = fields[9] if len(fields) > 9 else None
            awaiting_primary_fingerprint = False
        elif fields[0] != "fpr":
            awaiting_primary_fingerprint = False
    if (primary_keys != 1 or not isinstance(primary_fingerprint, str)
            or len(primary_fingerprint) != 40):
        raise ValueError("Tailscale signing key has unexpected structure")
    return primary_fingerprint


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _private_file(path: Path, *, max_bytes: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes
                or info.st_uid != os.getuid()):
            raise ValueError("private package file is unsafe")
        data = os.read(fd, max_bytes + 1)
        if len(data) != info.st_size or len(data) > max_bytes:
            raise ValueError("private package file changed")
        return data
    finally:
        os.close(fd)


def _private_directory(path: Path, *, create: bool = False) -> None:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077):
        raise ValueError("private package directory is unsafe")


def _atomic_private_file(path: Path, data: bytes) -> None:
    """Publish a complete file once; never replace an existing state file."""
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise ValueError("private package directory is unsafe")
        temporary = path.name + "." + secrets.token_hex(8) + ".tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.link(temporary, path.name, src_dir_fd=directory,
                    dst_dir_fd=directory, follow_symlinks=False)
            os.fsync(directory)
        finally:
            os.unlink(temporary, dir_fd=directory)
    finally:
        os.close(directory)


def _index_files(plan: UbuntuDebianInstallPlan) -> tuple[tuple[str, str], ...]:
    directory = plan.private_directory / "lists"
    _private_directory(directory)
    prefix = f"pkgs.tailscale.com_stable_{plan.os_id}_dists_{plan.codename}_"
    files: list[tuple[str, str]] = []
    total = 0
    for item in directory.iterdir():
        if item.name in {"lock", "partial", "auxfiles"}:
            continue
        if not item.name.startswith(prefix):
            raise ValueError("unexpected apt index file")
        data = _private_file(item, max_bytes=MAX_INDEXES)
        total += len(data)
        if total > MAX_INDEXES or len(files) >= 12:
            raise ValueError("apt indexes exceed bound")
        files.append((item.name, _sha(data)))
    names = [name for name, _ in files]
    if (sum(name.endswith("_InRelease") for name in names) != 1
            or sum("_Packages" in name for name in names) != 1):
        raise ValueError("signed Tailscale index is incomplete")
    return tuple(sorted(files))


def _index_digest(files: tuple[tuple[str, str], ...]) -> str:
    return _sha(json.dumps(files, separators=(",", ":")).encode())


_SIM_ACTION = re.compile(r"^(Inst|Conf|Remv|Purg) (\S+)(?: \(([^ )]+)[^)]*\))?.*$")
_VERSION = re.compile(r"[A-Za-z0-9.+:~_-]{1,160}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _simulation(stdout: str, version: str | None = None) -> tuple[str, tuple[str, ...]]:
    summary = re.compile(r"^0 upgraded, 1 newly installed, 0 to remove and [0-9]+ not upgraded\.$")
    if (len(stdout.encode()) > MAX_OUTPUT
            or sum(bool(summary.fullmatch(line)) for line in stdout.splitlines()) != 1):
        raise ValueError("apt transaction summary is not exact")
    actions = []
    for line in stdout.splitlines():
        match = _SIM_ACTION.match(line)
        if match:
            if match.group(1) not in {"Inst", "Conf"} or match.group(2) != "tailscale":
                raise ValueError("apt transaction includes another package action")
            actions.append((match.group(1), match.group(3)))
        elif line.startswith(("E:", "W:", "WARNING:", "The following additional packages")):
            raise ValueError("apt transaction has warnings or dependencies")
    if len(actions) != 2 or [item[0] for item in actions] != ["Inst", "Conf"]:
        raise ValueError("apt transaction is not one Tailscale install")
    observed = actions[0][1]
    if (not isinstance(observed, str) or not _VERSION.fullmatch(observed)
            or actions[1][1] != observed or (version is not None and version != observed)):
        raise ValueError("apt version is ambiguous")
    return observed, (f"Inst tailscale={observed}", f"Conf tailscale={observed}")


def _package_metadata(stdout: str, version: str) -> tuple[str, str, int]:
    matching = []
    for block in stdout.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if fields.get("Package") == "tailscale" and fields.get("Version") == version:
            matching.append(fields)
    if len(matching) != 1:
        raise ValueError("signed Tailscale package metadata is ambiguous")
    item = matching[0]
    filename = item.get("Filename", "")
    digest = item.get("SHA256", "")
    size = item.get("Size", "")
    if (not filename.startswith("pool/") or ".." in Path(filename).parts
            or not re.fullmatch(r"[A-Za-z0-9_./+~-]+\.deb", filename)
            or not _HASH.fullmatch(digest) or not size.isdecimal()
            or not 0 < int(size) <= MAX_PACKAGE):
        raise ValueError("signed Tailscale archive metadata is invalid")
    return filename, digest, int(size)


def _bounded_privileged(argv: tuple[str, ...], *, env: Mapping[str, str],
                        timeout: float, max_output: int):
    """Bound a privilege prompt and its process group without a shell."""
    from isycode.tailscale import TailscaleCommandResult
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=dict(env), close_fds=True, start_new_session=True)
    chunks = {process.stdout: bytearray(), process.stderr: bytearray()}
    selector = selectors.DefaultSelector()
    deadline = time.monotonic() + timeout
    try:
        for pipe in chunks:
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("privileged apt operation timed out")
            for key, _ in selector.select(remaining):
                data = os.read(key.fileobj.fileno(), 4096)
                if not data:
                    selector.unregister(key.fileobj)
                else:
                    chunks[key.fileobj].extend(data)
                    if sum(len(value) for value in chunks.values()) > max_output:
                        raise ValueError("privileged apt output exceeded limit")
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
        return TailscaleCommandResult(process.returncode,
                                     chunks[process.stdout].decode(errors="replace"),
                                     chunks[process.stderr].decode(errors="replace"))
    finally:
        selector.close()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        for pipe in chunks:
            pipe.close()


class TailscalePackageInstallOwner:
    """Two approvals: private signed-index preparation, then one exact package install."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore, *, platform: str | None = None,
                 os_release: Callable[[], Mapping[str, str]] = _read_os_release,
                 apt_executable: str = "/usr/bin/apt-get",
                 fetch: Callable = _fetch_exact,
                 key_fingerprint: Callable[[bytes], str] = _inspect_key,
                 run: Callable = _bounded_run,
                 privileged_run: Callable = _bounded_privileged):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self._platform = sys.platform if platform is None else platform
        self._os_release = os_release
        self._apt_executable = apt_executable
        self._fetch = fetch
        self._key_fingerprint = key_fingerprint
        self._run = run
        self._privileged_run = privileged_run
        self._nonce = secrets.token_hex(16)
        self._prepared: UbuntuDebianInstallPlan | None = None
        self._transaction: PreparedTransaction | None = None

    def plan(self) -> UbuntuDebianInstallPlan:
        if self._platform != "linux":
            raise ValueError("Tailscale package installation is supported only on Linux")
        release = self._os_release()
        if not isinstance(release, Mapping):
            raise ValueError("OS release information is unavailable")
        executable = Path(self._apt_executable).resolve(strict=True)
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("apt-get executable is unavailable")
        root_id = _sha(str(self.root).encode())[:16]
        directory = state_root().expanduser().absolute() / "tailscale-apt" / f"{root_id}-{self._nonce}"
        return UbuntuDebianInstallPlan.for_release(
            release.get("ID"), release.get("VERSION_CODENAME"), str(executable), directory)

    def _gate(self, plan: UbuntuDebianInstallPlan) -> ProductActionGate:
        facts = TailscaleAuthorityFacts(package_manager=plan.apt_executable,
                                        os_id=plan.os_id, os_codename=plan.codename)
        return ProductActionGate(self.root, self.authority,
                                 owner_id="tailscale_package_install",
                                 tailscale_facts=facts)

    def _receipt(self, gate: ProductActionGate, request: ActionRequest,
                 outcome: str, phase: str) -> ActionOutcome:
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), request.action_id,
                                request.digest, "ALLOW", outcome,
                                _sha(f"{outcome}:{phase}".encode()))
        if not gate.persist_receipt(request, receipt):
            return ActionOutcome("Tailscale package status is not verifiable.",
                                 "NOT_VERIFIABLE", None, "durable receipt unavailable")
        if outcome == "SUCCESS":
            return ActionOutcome("Tailscale package step completed.", "ALLOW", receipt, phase)
        return ActionOutcome("Tailscale package step stopped.", "ERROR", receipt,
                             f"{phase} failed; private state and any package state remain visible")

    def _environment(self, plan: UbuntuDebianInstallPlan) -> dict[str, str]:
        return {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
                "APT_CONFIG": str(plan.private_directory / "apt.conf"),
                "DEBIAN_FRONTEND": "noninteractive"}

    def _checked_run(self, plan: UbuntuDebianInstallPlan,
                     argv: tuple[str, ...], *, timeout: float = APT_TIMEOUT) -> str:
        result = self._run(argv, env=self._environment(plan),
                           timeout=timeout, max_output=MAX_OUTPUT)
        if result.returncode != 0:
            raise ValueError("bounded package process failed")
        return result.stdout

    def _verify_apt_config(self, plan: UbuntuDebianInstallPlan) -> None:
        dump = self._checked_run(plan, ("/usr/bin/apt-config", "dump"))
        lower = dump.lower()
        if ("pre-invoke" in lower or "post-invoke" in lower or "pre-install-pkgs" in lower
                or "hook" in lower or f'Dir::Etc "{plan.private_directory}";' not in dump
                or f'Dir::Etc::sourcelist "{plan.private_directory / "source.list"}";' not in dump
                or 'Dir::Etc::main "/dev/null";' not in dump
                or 'Dir::Etc::parts "-";' not in dump):
            raise ValueError("host apt configuration or hook is loaded")

    def _verify_indexes(self, plan: UbuntuDebianInstallPlan) -> str:
        files = _index_files(plan)
        name = next(name for name, _ in files if name.endswith("_InRelease"))
        self._checked_run(plan, ("/usr/bin/gpgv", "--keyring",
                                  str(plan.private_directory / "keyring.gpg"),
                                  str(plan.private_directory / "lists" / name)))
        return _index_digest(files)

    def prepare(self, request: ActionRequest,
                approval: ActionApproval | None) -> ActionOutcome:
        try:
            plan = self.plan()
            if request != plan.prepare_request(self.root):
                return ActionOutcome("Tailscale preparation denied.", "DENY", None,
                                     "request differs from the exact private plan")
            gate = self._gate(plan)
            _, decision = gate.authorize(request, approvals=self.approvals, approval=approval)
            if not decision.allowed:
                return ActionOutcome("Tailscale preparation denied.", "DENY", None,
                                     "workspace grant, Sentinel, approval, or journal denied")
        except (OSError, ValueError, TypeError):
            return ActionOutcome("Tailscale preparation denied.", "DENY", None,
                                 "installation plan or durable journal unavailable")
        phase = "key verification"
        try:
            key = self._fetch(plan.key_url, timeout=FETCH_TIMEOUT, max_bytes=MAX_FETCH)
            if (not isinstance(key, bytes) or not 0 < len(key) <= MAX_FETCH
                    or self._key_fingerprint(key) != KEY_FINGERPRINT):
                raise ValueError("key mismatch")
            phase = "source verification"
            official_source = (f"# Tailscale packages for {plan.os_id} {plan.codename}\n"
                               f"deb [signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg] "
                               f"{plan.repository_uri} {plan.codename} main\n").encode()
            source = self._fetch(plan.list_url, timeout=FETCH_TIMEOUT, max_bytes=MAX_FETCH)
            if source != official_source:
                raise ValueError("official source mismatch")
            phase = "private publication"
            state = state_root().expanduser().absolute()
            state.mkdir(mode=0o700, parents=True, exist_ok=True)
            state_info = state.lstat()
            if not stat.S_ISDIR(state_info.st_mode) or state_info.st_uid != os.getuid():
                raise ValueError("application state root is unsafe")
            state.chmod(0o700)
            _private_directory(state)
            parent = state / "tailscale-apt"
            parent.mkdir(mode=0o700, exist_ok=True)
            _private_directory(parent)
            _private_directory(plan.private_directory, create=True)
            for name in ("lists", "cache"):
                child = plan.private_directory / name
                _private_directory(child, create=True)
                if name == "lists":
                    _private_directory(child / "partial", create=True)
                else:
                    _private_directory(child / "partial", create=True)
            _atomic_private_file(plan.private_directory / "keyring.gpg", key)
            _atomic_private_file(plan.private_directory / "source.list", plan.source_text.encode())
            _atomic_private_file(plan.private_directory / "apt.conf", plan.config_text.encode())
            phase = "apt isolation"
            self._verify_apt_config(plan)
            phase = "signed index update"
            self._checked_run(plan, plan.update_argv)
            phase = "signed index verification"
            self._verify_indexes(plan)
            self._prepared = plan
            phase = "exact transaction and package preparation"
            self.simulate()
            return self._receipt(gate, request, "SUCCESS", "signed private package prepared")
        except (OSError, ValueError, TypeError, TimeoutError, subprocess.TimeoutExpired):
            self._prepared = None
            self._transaction = None
            return self._receipt(gate, request, "FAILURE", phase)

    def simulate(self) -> PreparedTransaction:
        """Read signed private indexes; return an immutable exact one-package proposal."""
        plan = self._prepared
        if plan is None or plan != self.plan():
            raise ValueError("approved package preparation is unavailable")
        if self._transaction is not None:
            return self._transaction
        self._verify_apt_config(plan)
        indexes_digest = self._verify_indexes(plan)
        key_sha = _sha(_private_file(plan.private_directory / "keyring.gpg", max_bytes=MAX_FETCH))
        source_sha = _sha(_private_file(plan.private_directory / "source.list", max_bytes=MAX_FETCH))
        config_sha = _sha(_private_file(plan.private_directory / "apt.conf", max_bytes=MAX_FETCH))
        if (source_sha != _sha(plan.source_text.encode())
                or config_sha != _sha(plan.config_text.encode())):
            raise ValueError("private package source or configuration changed")
        preliminary = self._checked_run(plan, (plan.apt_executable, "-s", "install",
                                               "--no-install-recommends", "--no-upgrade",
                                               "--no-remove", "tailscale"))
        version, _ = _simulation(preliminary)
        install_argv = (plan.apt_executable, "install", "--yes", "--no-upgrade",
                        "--no-remove", "--no-download", "--no-install-recommends",
                        f"tailscale={version}")
        simulated = self._checked_run(plan, (plan.apt_executable, "-s", *install_argv[1:]))
        _, actions = _simulation(simulated, version)
        metadata = self._checked_run(plan, ("/usr/bin/apt-cache", "show", "tailscale"))
        archive_name, archive_sha, archive_size = _package_metadata(metadata, version)
        package_url = f"{plan.repository_uri}/{archive_name}"
        archive = self._fetch(package_url, timeout=30.0, max_bytes=MAX_PACKAGE)
        if (not isinstance(archive, bytes) or len(archive) != archive_size
                or _sha(archive) != archive_sha):
            raise ValueError("downloaded package differs from signed index")
        _atomic_private_file(plan.private_directory / "cache" / Path(archive_name).name, archive)
        transaction = PreparedTransaction(plan, key_sha, source_sha, config_sha,
                                          indexes_digest, version, archive_sha,
                                          Path(archive_name).name, _sha(simulated.encode()),
                                          actions, install_argv)
        self._transaction = transaction
        return transaction

    def install(self, request: ActionRequest,
                approval: ActionApproval | None) -> ActionOutcome:
        try:
            transaction = self._transaction
            if (transaction is None or transaction.plan != self.plan()
                    or request != transaction.request(self.root)):
                return ActionOutcome("Tailscale installation denied.", "DENY", None,
                                     "request does not match the simulated transaction")
            plan = transaction.plan
            gate = self._gate(plan)
            _, decision = gate.authorize(request, approvals=self.approvals, approval=approval)
            if not decision.allowed:
                return ActionOutcome("Tailscale installation denied.", "DENY", None,
                                     "workspace grant, Sentinel, approval, or journal denied")
        except (OSError, ValueError, TypeError):
            return ActionOutcome("Tailscale installation denied.", "DENY", None,
                                 "installation plan or durable journal unavailable")
        phase = "transaction recheck"
        try:
            self._verify_apt_config(plan)
            if (_sha(_private_file(plan.private_directory / "keyring.gpg", max_bytes=MAX_FETCH))
                    != transaction.key_sha256
                    or _sha(_private_file(plan.private_directory / "source.list", max_bytes=MAX_FETCH))
                    != transaction.source_sha256
                    or _sha(_private_file(plan.private_directory / "apt.conf", max_bytes=MAX_FETCH))
                    != transaction.config_sha256
                    or self._verify_indexes(plan) != transaction.indexes_digest):
                raise ValueError("signed private repository changed")
            simulated = self._checked_run(plan, (plan.apt_executable, "-s", *transaction.install_argv[1:]))
            version, actions = _simulation(simulated, transaction.version)
            if (actions != transaction.package_actions
                    or _sha(simulated.encode()) != transaction.simulation_digest):
                raise ValueError("apt transaction changed")
            phase = "package archive verification"
            metadata = self._checked_run(plan, ("/usr/bin/apt-cache", "show", "tailscale"))
            filename, digest, size = _package_metadata(metadata, version)
            if Path(filename).name != transaction.archive_name or digest != transaction.archive_sha256:
                raise ValueError("signed archive metadata changed")
            archive = _private_file(plan.private_directory / "cache" / transaction.archive_name,
                                    max_bytes=MAX_PACKAGE)
            if len(archive) != size or _sha(archive) != digest:
                raise ValueError("prepared package archive changed")
            phase = "privileged package install"
            privileged_argv = ("/usr/bin/pkexec", "/usr/bin/env",
                               f"APT_CONFIG={plan.private_directory / 'apt.conf'}",
                               *transaction.install_argv)
            result = self._privileged_run(privileged_argv,
                                          env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
                                          timeout=INSTALL_TIMEOUT, max_output=MAX_OUTPUT)
            if result.returncode != 0:
                raise ValueError("package manager or OS privilege prompt failed")
            phase = "installed package inventory"
            inventory = self._checked_run(plan, ("/usr/bin/dpkg-query", "-W", "-f=${Version}", "tailscale"))
            if inventory.strip() != transaction.version:
                raise ValueError("installed package version differs")
            return self._receipt(gate, request, "SUCCESS", "exact Tailscale package installed")
        except (OSError, ValueError, TypeError, TimeoutError, subprocess.TimeoutExpired):
            return self._receipt(gate, request, "FAILURE", phase)


__all__ = ["TailscalePackageInstallOwner", "UbuntuDebianInstallPlan", "PreparedTransaction"]
