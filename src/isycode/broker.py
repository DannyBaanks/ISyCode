"""Reviewed semantic broker provisioning and registered lifecycle owners."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import ProxyHandler, build_opener

from isycode.action_runtime import ActionOutcome, ActionReceipt, ProductActionGate
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_setup import state_root


MAX_RECIPE_FILE_BYTES = 2_000_000
MAX_LOG_BYTES = 64 * 1024
RECIPE_FILES = ("Dockerfile", "requirements.txt", "semantic_gateway/app.py",
                "semantic_gateway/manager.py")


@dataclass(frozen=True)
class BrokerRecipe:
    source_root: Path
    digest: str
    files: tuple[tuple[str, str], ...]


class BrokerRegistry:
    """Private, project-external inventory for brokers managed by ISyCode."""

    VERSION = 1
    MAX_BYTES = 1_000_000

    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory or (state_root() / "semantic-brokers"))
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise ValueError("broker state directory must be a real directory")
        self.directory = self.directory.resolve(strict=True)
        if os.name == "posix":
            self.directory.chmod(0o700)
        self.path = self.directory / "registry.json"

    @staticmethod
    def root_id(project: Path) -> str:
        return hashlib.sha256(str(project.resolve(strict=False)).encode()).hexdigest()[:16]

    def _load(self) -> dict[str, Any]:
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return {"version": self.VERSION, "brokers": {}}
        if not stat.S_ISREG(info.st_mode) or info.st_size > self.MAX_BYTES:
            raise ValueError("broker registry is not a bounded regular file")
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("version") != self.VERSION
                or not isinstance(value.get("brokers"), dict)):
            raise ValueError("broker registry is malformed")
        return value

    def list_for_workspace(self, workspace: Path) -> list[dict[str, Any]]:
        root = workspace.resolve(strict=True)
        result = []
        for broker_id, item in self._load()["brokers"].items():
            if not isinstance(item, dict) or item.get("workspace_root") != str(root):
                continue
            project = Path(str(item.get("project_root", "")))
            try:
                if _canonical_registered_project_path(root, project) != project:
                    continue
            except (OSError, RuntimeError):
                continue
            if (broker_id != self.root_id(project)
                    or not self._valid_entry(broker_id, item)):
                continue
            result.append(dict(item))
        return sorted(result, key=lambda item: str(item.get("project_root", "")))

    def get(self, workspace: Path, project: Path) -> dict[str, Any] | None:
        root = workspace.resolve(strict=True)
        canonical_project = _canonical_registered_project_path(root, project)
        value = self._load()["brokers"].get(self.root_id(canonical_project))
        if not isinstance(value, dict) or value.get("workspace_root") != str(root):
            return None
        if (value.get("project_root") != str(canonical_project)
                or not self._valid_entry(self.root_id(canonical_project), value)):
            raise ValueError("broker registry identity does not match its project path")
        return dict(value)

    @staticmethod
    def _valid_entry(broker_id: str, item: dict[str, Any]) -> bool:
        digest = item.get("recipe_digest")
        return (
            item.get("container") == f"isycode-semantic-{broker_id}"
            and item.get("network") == f"isycode-internal-{broker_id}"
            and re_full_hex(digest, 64)
            and item.get("image") == f"isycode-semantic-broker:{digest[:16]}"
            and type(item.get("host_port")) is int
            and 1 <= item["host_port"] <= 65535
            and item.get("status") in {"healthy", "stopped", "unverified"}
            and type(item.get("updated_at")) is int
            and _valid_proxy_metadata(item)
        )

    def register(self, workspace: Path, project: Path, *, recipe_digest: str,
                 image: str, container: str, network: str, host_port: int,
                 container_ip: str | None = None, proxy_pid: int | None = None) -> None:
        root = workspace.resolve(strict=True)
        project = _canonical_project_root(root, project)
        root_id = self.root_id(project)
        expected_container = f"isycode-semantic-{root_id}"
        expected_network = f"isycode-internal-{root_id}"
        if (container != expected_container or network != expected_network
                or not re_full_hex(recipe_digest, 64)
                or image != f"isycode-semantic-broker:{recipe_digest[:16]}"
                or not isinstance(host_port, int) or not 1 <= host_port <= 65535
                or (container_ip is None) != (proxy_pid is None)
                or (container_ip is not None and not _is_private_ipv4(container_ip))
                or (proxy_pid is not None and (type(proxy_pid) is not int or proxy_pid <= 1))):
            raise ValueError("broker registration does not match its deterministic identity")
        state = self._load()
        state["brokers"][root_id] = {
            "workspace_root": str(root), "project_root": str(project),
            "recipe_digest": recipe_digest, "image": image, "container": container,
            "network": network, "host_port": host_port,
            "status": "healthy", "updated_at": int(time.time()),
        }
        if container_ip is not None and proxy_pid is not None:
            state["brokers"][root_id].update({
                "transport": "loopback_proxy", "container_ip": container_ip,
                "proxy_pid": proxy_pid,
            })
        self._write(state)

    def update_proxy(self, workspace: Path, project: Path, *, host_port: int,
                     container_ip: str, proxy_pid: int) -> dict[str, Any]:
        root = workspace.resolve(strict=True)
        project = _canonical_registered_project_path(root, project)
        if (not 1 <= host_port <= 65535 or not _is_private_ipv4(container_ip)
                or type(proxy_pid) is not int or proxy_pid <= 1):
            raise ValueError("broker proxy metadata is invalid")
        state = self._load()
        item = state["brokers"].get(self.root_id(project))
        if not isinstance(item, dict) or item.get("workspace_root") != str(root):
            raise FileNotFoundError("managed broker is not registered")
        item.update({"transport": "loopback_proxy", "container_ip": container_ip,
                     "host_port": host_port, "proxy_pid": proxy_pid,
                     "updated_at": int(time.time())})
        self._write(state)
        return dict(item)

    def update_status(self, workspace: Path, project: Path, status: str) -> dict[str, Any]:
        if status not in {"healthy", "stopped", "unverified"}:
            raise ValueError("unknown broker status")
        root = workspace.resolve(strict=True)
        project = _canonical_registered_project_path(root, project)
        state = self._load()
        broker_id = self.root_id(project)
        item = state["brokers"].get(broker_id)
        if not isinstance(item, dict) or item.get("workspace_root") != str(root):
            raise FileNotFoundError("managed broker is not registered")
        item["status"] = status
        item["updated_at"] = int(time.time())
        self._write(state)
        return dict(item)

    def remove(self, workspace: Path, project: Path) -> None:
        root = workspace.resolve(strict=True)
        project = _canonical_registered_project_path(root, project)
        state = self._load()
        item = state["brokers"].get(self.root_id(project))
        if not isinstance(item, dict) or item.get("workspace_root") != str(root):
            raise FileNotFoundError("managed broker is not registered")
        del state["brokers"][self.root_id(project)]
        self._write(state)

    def _write(self, value: dict[str, Any]) -> None:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
        if len(payload.encode("utf-8")) > self.MAX_BYTES:
            raise ValueError("broker registry exceeds its size limit")
        temporary = self.directory / (".registry-" + os.urandom(8).hex() + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            if os.name == "posix":
                self.path.chmod(0o600)
        finally:
            if temporary.exists():
                temporary.unlink()


def re_full_hex(value: Any, length: int) -> bool:
    return (isinstance(value, str) and len(value) == length
            and all(char in "0123456789abcdef" for char in value))


def _is_private_ipv4(value: Any) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except (TypeError, ValueError):
        return False
    return address.version == 4 and address.is_private and not address.is_loopback


def _valid_proxy_metadata(item: dict[str, Any]) -> bool:
    transport = item.get("transport")
    if transport is None:  # Legacy registry entry; retained for safe migration.
        return True
    return (transport == "loopback_proxy"
            and _is_private_ipv4(item.get("container_ip"))
            and type(item.get("proxy_pid")) is int and item["proxy_pid"] > 1)


def _proxy_process_matches(pid: int, broker_id: str, host_port: int,
                           container_ip: str) -> bool:
    """Fail closed unless the PID is our exact proxy on this Linux host."""
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8").split("\0")
    except (OSError, UnicodeError):
        return False
    return ("-m" in command and "isycode.broker_proxy" in command
            and "--broker-id" in command and broker_id in command
            and "--port" in command and str(host_port) in command
            and "--target-ip" in command and container_ip in command)


def _stop_proxy(pid: int | None, broker_id: str, host_port: int,
                container_ip: str) -> None:
    if not isinstance(pid, int) or pid <= 1 or not _proxy_process_matches(
            pid, broker_id, host_port, container_ip):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)


def _start_proxy(broker_id: str, container_ip: str,
                 preferred_port: int | None = None) -> tuple[int, int]:
    if not _is_private_ipv4(container_ip):
        raise ValueError("Docker returned a non-private broker address")
    if os.name != "posix" or not Path("/proc/self/cmdline").exists():
        raise RuntimeError("loopback broker proxy requires a Linux process identity check")
    bind = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if preferred_port is not None:
            bind.bind(("127.0.0.1", preferred_port))
            port = preferred_port
        else:
            bind.bind(("127.0.0.1", 0))
            port = int(bind.getsockname()[1])
    finally:
        bind.close()
    package_root = Path(__file__).resolve().parents[2]
    source_root = package_root / "src"
    proxy_environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(source_root),
        "PYTHONIOENCODING": "utf-8",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "isycode.broker_proxy", "--broker-id", broker_id,
         "--target-ip", container_ip, "--port", str(port)],
        cwd=package_root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
        env=proxy_environment,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("loopback broker proxy exited before binding")
        if (_proxy_process_matches(process.pid, broker_id, port, container_ip)
                and _tcp_accepts(port)):
            return port, process.pid
        time.sleep(0.05)
    _stop_proxy(process.pid, broker_id, port, container_ip)
    raise RuntimeError("loopback broker proxy did not become ready")


def _tcp_accepts(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def _container_ip(docker: str, container: str, network: str) -> str:
    result = subprocess.run(
        [docker, "inspect", "--format", "{{json .NetworkSettings.Networks}}", container],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=10, check=False, text=True)
    if result.returncode != 0:
        raise RuntimeError("Docker could not inspect the broker network address")
    networks = json.loads(result.stdout)
    endpoint = networks.get(network) if isinstance(networks, dict) else None
    address = endpoint.get("IPAddress") if isinstance(endpoint, dict) else None
    if not _is_private_ipv4(address):
        raise RuntimeError("broker has no private IPv4 address on its internal network")
    return address


def _wait_for_health(port: int, *, timeout_seconds: float = 20) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    opener = build_opener(ProxyHandler({}))
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with opener.open(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                body = response.read(16_384)
                if response.status == 200 and body:
                    value = json.loads(body)
                    if isinstance(value, dict) and value.get("status") == "ok":
                        return value
                    raise RuntimeError("broker health response was malformed")
                raise RuntimeError("broker health endpoint did not return HTTP 200")
        except (OSError, TimeoutError) as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"broker health check timed out ({type(last_error).__name__})")


def _configured_isyco_root() -> Path:
    configured = os.environ.get("ISYCO_ROOT", "").strip()
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.extend((Path.home() / "Development" / "ISyCo",
                       Path.home() / "Development" / "ISyCo Git" / "ISyCo"))
    for candidate in candidates:
        try:
            root = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if ((root / "tools" / "semantic_gateway" / "Dockerfile").is_file()
                and (root / "tools" / "semantic_gateway" / "semantic_gateway" / "app.py").is_file()):
            return root
    raise FileNotFoundError("configured ISyCo checkout with semantic broker recipe was not found")


def load_reviewed_recipe() -> BrokerRecipe:
    """Read a bounded allowlist of recipe files; reject links and special files."""
    checkout = _configured_isyco_root()
    source_candidate = checkout / "tools" / "semantic_gateway"
    if source_candidate.is_symlink():
        raise ValueError("semantic broker recipe directory must not be a symlink")
    source = source_candidate
    try:
        source = source.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("semantic broker recipe is unavailable") from exc
    if not source.is_dir() or checkout not in source.parents:
        raise ValueError("semantic broker recipe escaped the configured checkout")
    entries: list[tuple[str, str]] = []
    hasher = hashlib.sha256(b"isycode-semantic-broker-recipe-v1\0")
    for relative in RECIPE_FILES:
        path = source / relative
        cursor = source
        try:
            for component in Path(relative).parts:
                cursor = cursor / component
                component_metadata = cursor.lstat()
                if stat.S_ISLNK(component_metadata.st_mode):
                    raise ValueError("semantic broker recipe must not traverse symlinks")
            metadata = cursor.lstat()
        except OSError as exc:
            raise ValueError("semantic broker recipe is incomplete") from exc
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_RECIPE_FILE_BYTES:
            raise ValueError("semantic broker recipe contains an unsafe or oversized file")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ValueError("semantic broker recipe could not be read") from exc
        digest = hashlib.sha256(content).hexdigest()
        entries.append((relative, digest))
        hasher.update(relative.encode("utf-8") + b"\0" + content + b"\0")
    return BrokerRecipe(source, hasher.hexdigest(), tuple(entries))


def _canonical_project_root(workspace: Path, selected: Path) -> Path:
    root = workspace.expanduser().resolve(strict=True)
    raw = selected.expanduser()
    lexical = Path(os.path.abspath(raw if raw.is_absolute() else root / raw))
    if lexical != root and root not in lexical.parents:
        raise ValueError("selected project root must stay inside the active .isyroot")
    cursor = root
    for part in lexical.relative_to(root).parts:
        cursor = cursor / part
        try:
            if stat.S_ISLNK(cursor.lstat().st_mode):
                raise ValueError("selected project root must not traverse a symlink")
        except FileNotFoundError as exc:
            raise ValueError("selected project root does not exist") from exc
    canonical = lexical.resolve(strict=True)
    if not canonical.is_dir() or (canonical != root and root not in canonical.parents):
        raise ValueError("selected project root is not a directory inside .isyroot")
    return canonical


def _canonical_registered_project_path(workspace: Path, registered: Path) -> Path:
    """Validate a recorded project path even if that directory was later removed."""
    root = workspace.expanduser().resolve(strict=True)
    raw = registered.expanduser()
    lexical = Path(os.path.abspath(raw if raw.is_absolute() else root / raw))
    if lexical != root and root not in lexical.parents:
        raise ValueError("registered project path escapes the active .isyroot")
    cursor = root
    for component in lexical.relative_to(root).parts:
        cursor = cursor / component
        try:
            if stat.S_ISLNK(cursor.lstat().st_mode):
                raise ValueError("registered project path traverses a symlink")
        except FileNotFoundError:
            break
    resolved = lexical.resolve(strict=False)
    if resolved != lexical or (resolved != root and root not in resolved.parents):
        raise ValueError("registered project path is no longer canonical")
    return resolved


def provision_requests(workspace: Path, project: Path, recipe: BrokerRecipe,
                       docker_executable: str) -> tuple[ActionRequest, ActionRequest]:
    """Create the exact pair of immutable actions the user reviews and approves."""
    root = workspace.expanduser().resolve(strict=True)
    project = _canonical_project_root(root, project)
    docker = str(Path(docker_executable).expanduser().resolve(strict=True))
    root_id = hashlib.sha256(str(project).encode("utf-8")).hexdigest()[:16]
    image = f"isycode-semantic-broker:{recipe.digest[:16]}"
    common = {"executable": docker, "recipe_digest": recipe.digest}
    build = ActionRequest(
        "broker.build", root, str(project),
        {**common, "operation": "build", "source_root": str(recipe.source_root),
         "build_network": "docker-daemon-default", "image": image},
        execution_owner="broker_provision")
    start = ActionRequest(
        "broker.start", root, str(project),
        {**common, "operation": "start", "image": image,
         "container": f"isycode-semantic-{root_id}",
         "network_name": f"isycode-internal-{root_id}",
         "network": "internal", "mount_read_only": True,
         "bind_host": "127.0.0.1", "credentials_mounted": False,
         "read_only": True, "cap_drop": "ALL", "no_new_privileges": True,
         "pids_limit": 128, "memory_limit": "2g", "tmpfs_limit": "128m"},
        execution_owner="broker_provision")
    return build, start


class BrokerPreviewOwner:
    """Create a non-executing, request-bound preview of the fixed broker recipe."""

    def __init__(self, workspace: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore):
        self.workspace = workspace.expanduser().resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.gate = ProductActionGate(self.workspace, authority, owner_id="broker_preview")

    def preview(self, selected_root: Path, approval: ActionApproval | None) -> ActionOutcome:
        try:
            project = _canonical_project_root(self.workspace, selected_root)
            recipe = load_reviewed_recipe()
            read_request = ActionRequest(
                "workspace.files.read", self.workspace, str(project), {"path": str(project)},
                execution_owner="broker_preview")
            _, read_decision = self.gate.authorize(read_request)
            if not read_decision.allowed:
                return ActionOutcome(
                    "Broker preview denied.", "DENY", None,
                    "an explicit workspace.files.read grant is required for the selected project root")
            request = ActionRequest(
                "broker.preview", self.workspace, str(project),
                {"recipe_digest": recipe.digest, "source_root": str(recipe.source_root),
                 "mount": "read-only", "network": "internal-only", "port_host": "127.0.0.1"},
                execution_owner="broker_preview")
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return ActionOutcome("Broker preview denied.", "DENY", None,
                                 f"recipe/root unavailable ({type(exc).__name__})")
        authority, decision = self.gate.authorize(
            request, approvals=self.approvals, approval=approval)
        if not decision.allowed:
            return ActionOutcome("Broker preview denied.", "DENY", None,
                                 "; ".join(item.reason for item in decision.checks if not item.passed))
        plan = {
            "operation": "preview-only",
            "project_root": str(project),
            "recipe_root": str(recipe.source_root),
            "recipe_digest": recipe.digest,
            "recipe_files": [{"path": path, "sha256": digest} for path, digest in recipe.files],
            "image": f"isycode-semantic-broker:{recipe.digest[:16]}",
            "mount": {"source": str(project), "target": "/workspace", "read_only": True},
            "network": {"mode": "internal-only", "host_exposure": "127.0.0.1 only"},
            "hardening": ["read_only", "cap_drop: ALL", "no-new-privileges",
                          "pids_limit: 128", "bounded tmpfs", "no credentials mounted"],
            "executed": False,
        }
        text = json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2)
        return ActionOutcome(text, "ALLOW", None,
                             "reviewable plan only; Docker was not started")


class BrokerProvisionOwner:
    """Build and start the reviewed broker only behind two approved actions."""

    def __init__(self, workspace: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore):
        self.workspace = workspace.expanduser().resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.gate = ProductActionGate(self.workspace, authority, owner_id="broker_provision")

    def provision(self, selected_root: Path, build_approval: ActionApproval | None,
                  start_approval: ActionApproval | None) -> ActionOutcome:
        try:
            project = _canonical_project_root(self.workspace, selected_root)
            recipe = load_reviewed_recipe()
            docker = shutil.which("docker")
            if not docker:
                raise FileNotFoundError("Docker executable is unavailable")
            docker = str(Path(docker).resolve(strict=True))
            build_request, start_request = provision_requests(
                self.workspace, project, recipe, docker)
            image = build_request.parameters["image"]
            if "," in str(project):
                raise ValueError("selected path contains a Docker mount separator")
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return ActionOutcome("Semantic broker provisioning denied.", "DENY", None,
                                 f"root/recipe unavailable ({type(exc).__name__})")

        read_request = ActionRequest(
            "workspace.files.read", self.workspace, str(project), {"path": str(project)},
            execution_owner="broker_provision")
        _, read_decision = self.gate.authorize(read_request)
        if not read_decision.allowed:
            return ActionOutcome("Semantic broker provisioning denied.", "DENY", None,
                                 "an explicit workspace.files.read grant is required for the selected project")
        container = start_request.parameters["container"]
        try:
            existing = subprocess.run(
                [docker, "inspect", container], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ActionOutcome("Semantic broker provisioning denied.", "ERROR", None,
                                 f"Docker identity check failed ({type(exc).__name__}); nothing was built")
        if existing.returncode == 0:
            try:
                registered = BrokerRegistry().get(self.workspace, project)
            except (OSError, RuntimeError, TypeError, ValueError):
                registered = None
            if registered is not None:
                return ActionOutcome(
                    "Semantic broker already registered.", "DENY", None,
                    f"No image was rebuilt. Use Manage broker for {project} to check health or start it.")
            return ActionOutcome(
                "Semantic broker provisioning denied.", "DENY", None,
                "the deterministic container name is occupied by an unregistered container; no build ran")
        _, build_decision = self.gate.authorize(
            build_request, approvals=self.approvals, approval=build_approval)
        if not build_decision.allowed:
            return ActionOutcome("Semantic broker build denied.", "DENY", None,
                                 "; ".join(check.reason for check in build_decision.checks if not check.passed))
        _, start_decision = self.gate.authorize(
            start_request, approvals=self.approvals, approval=start_approval)
        if not start_decision.allowed:
            return ActionOutcome("Semantic broker start denied.", "DENY", None,
                                 "; ".join(check.reason for check in start_decision.checks if not check.passed))

        # Re-read and compare the recipe after both one-use approvals were consumed.
        try:
            current = load_reviewed_recipe()
            if current.digest != recipe.digest:
                raise ValueError("broker recipe changed after approval")
            build = subprocess.run(
                [docker, "build", "--tag", image, str(recipe.source_root)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=600, check=False,
            )
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            return ActionOutcome("Semantic broker build failed.", "ERROR", None,
                                 f"Docker build failed ({type(exc).__name__}); no project files were changed")
        if build.returncode != 0:
            return ActionOutcome("Semantic broker build failed.", "ERROR", None,
                                 f"Docker exited with status {build.returncode}; no project files were changed")

        network = start_request.parameters["network_name"]
        root_id = hashlib.sha256(str(project).encode("utf-8")).hexdigest()[:16]
        created_network = False
        started_container = False
        proxy_port: int | None = None
        proxy_pid: int | None = None
        container_ip: str | None = None
        try:
            network_create = subprocess.run(
                [docker, "network", "create", "--driver", "bridge", "--internal",
                 "--label", "isycode.managed=true", "--label", f"isycode.root={root_id}", network],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=30, check=False)
            if network_create.returncode != 0:
                raise RuntimeError("the isolated Docker network could not be created")
            created_network = True
            network_check = subprocess.run(
                [docker, "network", "inspect", "--format", "{{.Internal}}", network],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=10, check=False, text=True)
            if network_check.returncode != 0 or network_check.stdout.strip().casefold() != "true":
                raise RuntimeError("Docker network is not isolated")
            run = subprocess.run(
                [docker, "run", "--detach", "--name", container,
                 "--network", network,
                 "--label", "isycode.managed=true", "--label", f"isycode.root={root_id}",
                 "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--pids-limit", "128", "--memory", "2g", "--cpus", "1",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m",
                "--env", "ISYCO_ROOT=/workspace",
                "--env", "SEMANTIC_MAX_RESPONSE_BYTES=1048576",
                "--env", "SEMANTIC_MAX_RESULTS=250",
                "--env", "SEMANTIC_MAX_CONTEXT_CHARS=24000",
                "--env", "SEMANTIC_ENABLE_RIPGREP=1",
                "--env", "SEMANTIC_SCAN_TIMEOUT_SECONDS=12",
                "--env", "SEMANTIC_MAX_SCAN_FILES=20000",
                "--mount", f"type=bind,source={project},target=/workspace,readonly",
                 image], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, timeout=45, check=False, text=True)
            if run.returncode != 0:
                raise RuntimeError("Docker did not start the isolated broker")
            started_container = True
            container_ip = _container_ip(docker, container, network)
            proxy_port, proxy_pid = _start_proxy(root_id, container_ip)
            host_port = proxy_port
            _wait_for_health(host_port)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            # Remove only the deterministic container and network just created
            # by this owner; a failed health check must not leave a ghost broker.
            cleanup_commands = []
            if proxy_pid is not None and proxy_port is not None and container_ip is not None:
                _stop_proxy(proxy_pid, root_id, proxy_port, container_ip)
            if started_container:
                cleanup_commands.append([docker, "rm", "--force", container])
            if created_network:
                cleanup_commands.append([docker, "network", "rm", network])
            for cleanup in cleanup_commands:
                try:
                    subprocess.run(cleanup, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=15, check=False)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            return ActionOutcome("Semantic broker started but health is unverified.", "ERROR", None,
                                 f"container lifecycle incomplete ({type(exc).__name__}); inspect Docker state")
        report = json.dumps({
            "status": "healthy", "project_root": str(project), "recipe_digest": recipe.digest,
            "container": container, "image": image, "network": "internal-only",
            "endpoint": f"http://127.0.0.1:{host_port}",
            "transport": "loopback-only host proxy to an internal Docker network",
            "mount_read_only": True, "cap_drop": "ALL", "no_new_privileges": True,
            "pids_limit": 128, "credentials_mounted": False,
        }, ensure_ascii=False, sort_keys=True, indent=2)
        try:
            BrokerRegistry().register(
                self.workspace, project, recipe_digest=recipe.digest, image=image,
                container=container, network=network, host_port=int(host_port),
                container_ip=container_ip, proxy_pid=proxy_pid)
        except (OSError, RuntimeError, TypeError, ValueError):
            if proxy_pid is not None and proxy_port is not None and container_ip is not None:
                _stop_proxy(proxy_pid, root_id, proxy_port, container_ip)
            for cleanup in ([docker, "rm", "--force", container],
                            [docker, "network", "rm", network]):
                try:
                    subprocess.run(cleanup, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=15, check=False)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            return ActionOutcome(
                "Semantic broker started but could not be registered.", "ERROR", None,
                "private broker inventory could not be written; container cleanup was requested")
        receipt = ActionReceipt(
            "rcpt_" + hashlib.sha256((build_request.digest + start_request.digest + report).encode()).hexdigest()[:16],
            "broker.build+broker.start", start_request.digest, "ALLOW", "SUCCESS",
            hashlib.sha256(report.encode("utf-8")).hexdigest())
        if not receipt.verify(start_request, report):
            return ActionOutcome("Semantic broker receipt failed verification.", "NOT_VERIFIABLE", None,
                                 "request/result digest did not match")
        if not self.gate.persist_receipt(start_request, receipt):
            return ActionOutcome("Semantic broker receipt could not be persisted.",
                                 "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable")
        return ActionOutcome(report, "ALLOW", receipt,
                             "reviewed Docker image built; isolated loopback broker passed /health")


class BrokerManagementOwner:
    """Run explicit start/health/logs/stop/remove actions for a registered broker."""

    def __init__(self, workspace: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore, docker_executable: str | None = None):
        self.workspace = workspace.expanduser().resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        docker = docker_executable or shutil.which("docker")
        if not docker:
            raise FileNotFoundError("Docker executable is unavailable")
        self.docker = str(Path(docker).expanduser().resolve(strict=True))
        self.registry = BrokerRegistry()
        self.gate = ProductActionGate(self.workspace, authority, owner_id="broker_management")

    def request_for(self, project_root: Path, operation: str) -> tuple[ActionRequest, dict[str, Any]]:
        action_id = {"health": "broker.health", "logs": "broker.logs",
                     "start": "broker.start", "stop": "broker.stop",
                     "remove": "broker.remove"}.get(operation)
        if action_id is None:
            raise ValueError("operation must be health, logs, stop or remove")
        project = _canonical_registered_project_path(self.workspace, project_root)
        item = self.registry.get(self.workspace, project)
        if item is None:
            raise FileNotFoundError("managed broker is not registered")
        parameters = {
            "operation": operation, "project_root": str(project),
            "root_id": self.registry.root_id(project),
            "container": item["container"], "network": item["network"],
            "image": item["image"], "recipe_digest": item["recipe_digest"],
            "host_port": item["host_port"], "executable": self.docker,
        }
        if operation == "start":
            parameters["managed_existing"] = True
        return ActionRequest(action_id, self.workspace, item["container"], parameters,
                             execution_owner="broker_management"), item

    def perform(self, project_root: Path, operation: str,
                approval: ActionApproval | None = None) -> ActionOutcome:
        try:
            request, item = self.request_for(project_root, operation)
        except (OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
            return ActionOutcome("Broker action denied.", "DENY", None,
                                 f"registered broker unavailable ({type(exc).__name__})")
        action_id = request.action_id
        _, decision = self.gate.authorize(
            request, approvals=self.approvals, approval=approval)
        if not decision.allowed:
            reason = "; ".join(item.reason for item in decision.checks if not item.passed)
            return ActionOutcome("Broker action denied.", "DENY", None, reason)
        try:
            result = self._operate(operation, Path(item["project_root"]), item)
            text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
        except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
            return ActionOutcome("Broker action failed.", "ERROR", None,
                                 f"{operation} did not complete ({type(exc).__name__})")
        receipt = ActionReceipt(
            "rcpt_" + hashlib.sha256((request.digest + text).encode()).hexdigest()[:16],
            action_id, request.digest, "ALLOW", "SUCCESS",
            hashlib.sha256(text.encode("utf-8")).hexdigest())
        if not receipt.verify(request, text):
            return ActionOutcome("Broker action receipt failed verification.", "NOT_VERIFIABLE", None,
                                 "request/result digest did not match")
        if not self.gate.persist_receipt(request, receipt):
            return ActionOutcome("Broker receipt could not be persisted.",
                                 "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable")
        return ActionOutcome(text, "ALLOW", receipt, f"registered broker {operation} completed")

    def _run(self, args: list[str], *, timeout: int = 15,
             output_limit: int = 32_768) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [self.docker, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=timeout, check=False, text=True)
        if len(result.stdout.encode("utf-8", errors="replace")) > output_limit:
            raise ValueError("Docker output exceeded the operation limit")
        return result

    def _assert_container_identity(self, item: dict[str, Any]) -> tuple[bool, bool]:
        result = self._run([
            "inspect", "--format",
            '{{json .Config.Labels}}|{{.Config.Image}}|{{.State.Running}}', item["container"]])
        if result.returncode != 0:
            daemon = self._run(["info"])
            if daemon.returncode != 0:
                raise RuntimeError("Docker daemon is unavailable")
            return False, False
        labels_raw, separator, remainder = result.stdout.strip().partition("|")
        if not separator:
            raise ValueError("Docker returned malformed broker identity")
        image, separator, running = remainder.rpartition("|")
        if not separator:
            raise ValueError("Docker returned malformed broker state")
        labels = json.loads(labels_raw)
        expected_root = self.registry.root_id(Path(item["project_root"]))
        if (not isinstance(labels, dict) or labels.get("isycode.managed") != "true"
                or labels.get("isycode.root") != expected_root or image != item["image"]):
            raise ValueError("container labels or image do not match the registered broker")
        return True, running.strip().casefold() == "true"

    def _assert_network_identity(self, item: dict[str, Any]) -> bool:
        result = self._run([
            "network", "inspect", "--format", "{{json .Labels}}|{{.Internal}}", item["network"]])
        if result.returncode != 0:
            daemon = self._run(["info"])
            if daemon.returncode != 0:
                raise RuntimeError("Docker daemon is unavailable")
            return False
        labels_raw, separator, internal = result.stdout.strip().partition("|")
        if not separator or internal.casefold() != "true":
            raise ValueError("broker network is not Docker-internal")
        labels = json.loads(labels_raw)
        expected_root = self.registry.root_id(Path(item["project_root"]))
        if (not isinstance(labels, dict) or labels.get("isycode.managed") != "true"
                or labels.get("isycode.root") != expected_root):
            raise ValueError("network labels do not match the registered broker")
        return True

    def _operate(self, operation: str, project: Path, item: dict[str, Any]) -> dict[str, Any]:
        if operation == "remove":
            # Verify both identities before any destructive Docker request.
            network_exists = self._assert_network_identity(item)
            exists, _ = self._assert_container_identity(item)
            if exists:
                container = self._run(["rm", "--force", item["container"]])
                if container.returncode != 0:
                    raise RuntimeError("managed broker container could not be removed")
            if item.get("transport") == "loopback_proxy":
                _stop_proxy(item.get("proxy_pid"), self.registry.root_id(project),
                            item["host_port"], item["container_ip"])
            if network_exists:
                network = self._run(["network", "rm", item["network"]])
                if network.returncode != 0:
                    self.registry.update_status(self.workspace, project, "unverified")
                    raise RuntimeError("container removed, but its network cleanup is unverified")
            self.registry.remove(self.workspace, project)
            return {"status": "removed", "project_root": str(project),
                    "container": item["container"], "network": item["network"],
                    "image_retained": item["image"],
                    "note": "Shared recipe images are retained to avoid removing another workspace's image."}

        network_exists = self._assert_network_identity(item)
        exists, running = self._assert_container_identity(item)
        if operation == "start":
            if not exists:
                raise RuntimeError("registered broker container no longer exists")
            if not network_exists:
                raise RuntimeError("registered broker network no longer exists")
            if not running:
                started = self._run(["start", item["container"]], timeout=20)
                if started.returncode != 0:
                    raise RuntimeError("registered broker did not start")
            if item.get("transport") == "loopback_proxy":
                _stop_proxy(item.get("proxy_pid"), self.registry.root_id(project),
                            item["host_port"], item["container_ip"])
                container_ip = _container_ip(self.docker, item["container"], item["network"])
                host_port, proxy_pid = _start_proxy(
                    self.registry.root_id(project), container_ip,
                    preferred_port=item["host_port"])
                item = self.registry.update_proxy(
                    self.workspace, project, host_port=host_port,
                    container_ip=container_ip, proxy_pid=proxy_pid)
                _wait_for_health(host_port)
            return self._operate("health", project, item)
        if operation == "stop":
            if exists and running:
                stopped = self._run(["stop", "--time", "10", item["container"]], timeout=20)
                if stopped.returncode != 0:
                    raise RuntimeError("registered broker did not stop")
            if item.get("transport") == "loopback_proxy":
                _stop_proxy(item.get("proxy_pid"), self.registry.root_id(project),
                            item["host_port"], item["container_ip"])
            self.registry.update_status(self.workspace, project, "stopped")
            return {"status": "stopped", "project_root": str(project),
                    "container": item["container"]}
        if operation == "health":
            if not exists or not running:
                if item.get("transport") == "loopback_proxy":
                    _stop_proxy(item.get("proxy_pid"), self.registry.root_id(project),
                                item["host_port"], item["container_ip"])
                self.registry.update_status(self.workspace, project, "stopped")
                return {"status": "stopped", "project_root": str(project),
                        "container": item["container"]}
            if item.get("transport") == "loopback_proxy":
                broker_id = self.registry.root_id(project)
                if not _proxy_process_matches(item["proxy_pid"], broker_id,
                                              item["host_port"], item["container_ip"]):
                    raise RuntimeError("managed loopback proxy is not running")
                current_ip = _container_ip(self.docker, item["container"], item["network"])
                if current_ip != item["container_ip"]:
                    raise RuntimeError("broker network address changed; restart the managed proxy")
                _wait_for_health(item["host_port"])
                host_port = item["host_port"]
            else:
                port = self._run(["port", item["container"], "8791/tcp"])
                prefix = "127.0.0.1:"
                port_text = port.stdout.strip()
                if port.returncode != 0 or not port_text.startswith(prefix):
                    raise RuntimeError("legacy broker is not published on loopback")
                host_port = port_text[len(prefix):].splitlines()[0]
                if not host_port.isdigit() or not 1 <= int(host_port) <= 65535:
                    raise RuntimeError("Docker returned an invalid port")
                _wait_for_health(int(host_port))
            self.registry.update_status(self.workspace, project, "healthy")
            return {"status": "healthy", "project_root": str(project),
                    "endpoint": f"http://127.0.0.1:{host_port}",
                    "container": item["container"], "network": "internal-only",
                    "mount_read_only": True}
        if operation == "logs":
            if not exists:
                raise RuntimeError("registered broker container no longer exists")
            result = self._run(["logs", "--tail", "200", "--timestamps", item["container"]],
                               timeout=15, output_limit=MAX_LOG_BYTES * 2)
            if result.returncode != 0:
                raise RuntimeError("Docker logs could not be read")
            logs = _redact_broker_logs(result.stdout)[-MAX_LOG_BYTES:]
            return {"status": "logs", "project_root": str(project),
                    "container": item["container"], "logs": logs,
                    "truncated": len(result.stdout.encode("utf-8", errors="replace")) > MAX_LOG_BYTES}
        raise ValueError("unsupported broker operation")


def _redact_broker_logs(value: str) -> str:
    redacted = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+",
                      r"\1[REDACTED]", value)
    redacted = re.sub(r"(?i)\b(?:sk|nvapi|isy)_[A-Za-z0-9._-]{12,}\b", "[REDACTED]", redacted)
    redacted = re.sub(r"(?i)\b(api[_-]?key|token|password|secret)(\s*[:=]\s*)[^\s,;]+",
                      r"\1\2[REDACTED]", redacted)
    return redacted


__all__ = ["BrokerPreviewOwner", "BrokerProvisionOwner", "BrokerRecipe",
           "BrokerRegistry", "BrokerManagementOwner", "load_reviewed_recipe"]
