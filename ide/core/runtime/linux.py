"""Linux commands: mandatory namespaces, bounded tmpfs, no host execution fallback."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from core.command_grants import CommandIdentity
from core.ide_state import atomic_write
from core.ide_state import project_state
from core.resident.store import utc_now
from core.processes import capture_process
from .base import BaseRuntime, ExecutionResult


PROFILE = "linux-offline-tmpfs-v1"
EXCLUDE = {".git", ".isyvm", ".isycode-ide", ".venv", "venv", ".venv_linux", "node_modules",
           "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", "dist", "build",
           "target", "zig-out", ".zig-cache", "zig-cache", ".ssh", ".aws", ".gnupg"}
MAX_SINGLE_FILE_BYTES = 10_000_000   # Skip individual >10 MB artifacts/blobs instead of aborting snapshot
MAX_SNAPSHOT_BYTES = 128_000_000     # 128 MB total snapshot ceiling
MAX_SNAPSHOT_FILES = 15_000          # 15,000 files ceiling
SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".keystore"}
SECRET_NAMES = {"auth.json", "credentials.json", "credentials", "secrets.json", "secrets.yaml", "secrets.yml", "token.json", "tokens.json"}


class CommandError(ValueError):
    pass


def trusted_binary(name):
    for directory in ("/usr/bin", "/bin"):
        candidate = Path(directory, name).resolve()
        if not candidate.is_file():
            continue
        info = candidate.stat()
        if info.st_uid != 0 or info.st_mode & 0o022 or info.st_mode & stat.S_ISUID:
            continue
        if os.access(candidate, os.X_OK):
            return str(candidate)
    raise CommandError("LINUX_RUNTIME_MISSING: se necesitan binarios del sistema bwrap, prlimit y python3 sin setuid")


def installation_status():
    try:
        return {"installed": os.name == "posix" and Path("/proc/self/ns/user").exists(),
                "bwrap": trusted_binary("bwrap"), "prlimit": trusted_binary("prlimit"),
                "python": trusted_binary("python3"), "capabilities": "NOT_DEMONSTRATED"}
    except (ValueError, OSError):
        return {"installed": False, "capabilities": "NOT_DEMONSTRATED"}


def sha_file(path):
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 512_000_000:
            raise CommandError("EXECUTABLE_UNSUPPORTED: no se puede identificar este binario")
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class CommandRequest:
    id: str
    identity: CommandIdentity
    sandbox_executable: str
    timeout: int
    launcher: tuple[str, str, str]
    broker_sha256: str


class LinuxCommandRuntime(BaseRuntime):
    def __init__(self, working_dir):
        super().__init__(Path(working_dir).resolve())
        self.broker = Path(__file__).with_name("linux_runner.py")
        self._checked = None

    def prepare(self, arguments):
        argv = arguments.get("argv")
        if not isinstance(argv, list) or not argv or len(argv) > 128 or any(not isinstance(arg, str) or "\0" in arg for arg in argv):
            raise CommandError("ARGV_REQUIRED: proporciona una lista de argumentos sin shell automático")
        if sum(len(arg.encode()) for arg in argv) > 65536 or not argv[0]:
            raise CommandError("ARGV_LIMIT: los argumentos superan el límite")
        raw_cwd = arguments.get("cwd", ".")
        if raw_cwd is None:
            raw_cwd = "."
        if not isinstance(raw_cwd, str):
            raise CommandError("CWD_REQUIRED: usa una carpeta relativa del proyecto")
        cwd = raw_cwd.strip() or "."
        if Path(cwd).is_absolute():
            raise CommandError("CWD_REQUIRED: usa una carpeta relativa del proyecto")
        candidate = self.working_dir / cwd
        normalized = candidate.resolve()
        try:
            relative = normalized.relative_to(self.working_dir)
        except ValueError:
            raise CommandError("CWD_OUTSIDE: la carpeta sale del proyecto") from None
        if normalized != Path(os.path.abspath(candidate)) or not normalized.is_dir() or any(part.startswith(".") or part in EXCLUDE for part in relative.parts):
            raise CommandError("CWD_UNSUPPORTED: carpeta no disponible en la copia aislada")
        requested = Path(argv[0])
        user_local = self._user_local_dir()
        search_path = "/usr/bin:/bin:/usr/local/bin"
        if user_local is not None:
            search_path = f"{search_path}:{user_local / 'bin'}"
        if requested.is_absolute():
            executable = requested.resolve()
        elif "/" in argv[0]:
            executable = (normalized / requested).resolve()
        else:
            found = shutil.which(argv[0], path=search_path)
            if not found:
                raise CommandError("EXECUTABLE_MISSING: el ejecutable no está en el perfil del sistema ni en ~/.local/bin")
            executable = Path(found).resolve()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise CommandError("EXECUTABLE_MISSING: el ejecutable no está disponible")
        try:
            project_executable = executable.relative_to(self.working_dir)
        except ValueError:
            project_executable = None
        if project_executable is not None:
            if any(part.startswith(".") or part in EXCLUDE for part in project_executable.parts) or executable.stat().st_nlink != 1:
                raise CommandError("EXECUTABLE_UNSUPPORTED: el ejecutable no se puede incluir en la copia")
            sandbox_executable = "/work/" + str(project_executable)
        elif executable.is_relative_to("/usr") and executable.stat().st_uid == 0 and not executable.stat().st_mode & 0o022:
            sandbox_executable = str(executable)
        elif (
            user_local is not None
            and executable.is_relative_to(user_local)
            and executable.stat().st_uid == os.getuid()
            and not executable.stat().st_mode & 0o022
        ):
            sandbox_executable = str(executable)
        else:
            raise CommandError("EXECUTABLE_UNSUPPORTED: usa un ejecutable del sistema, ~/.local/bin o del proyecto copiado")
        timeout = arguments.get("timeout", 60)
        if type(timeout) is not int or timeout < 1:
            raise CommandError("TIMEOUT_LIMIT: el tiempo debe ser un entero positivo (máximo 120 segundos)")
        if timeout > 120:
            timeout = 120
        status = installation_status()
        if not status["installed"]:
            raise CommandError("LINUX_RUNTIME_MISSING: el perfil Linux no está instalado; no hay fallback al host")
        launcher = (status["bwrap"], status["prlimit"], status["python"])
        broker_hash = sha_file(self.broker)
        profile = hashlib.sha256(json.dumps({"name": PROFILE, "broker": broker_hash, "runtime": sha_file(__file__),
                                             "launcher": [(p, sha_file(p)) for p in launcher]}, sort_keys=True).encode()).hexdigest()
        identity = CommandIdentity(str(self.working_dir), str(executable), sha_file(executable), tuple(argv), str(relative), profile)
        return CommandRequest(uuid.uuid4().hex, identity, sandbox_executable, timeout, launcher, broker_hash)

    @staticmethod
    def _user_local_dir() -> Path | None:
        for candidate in (Path("/home/danny/.local"), Path.home() / ".local"):
            try:
                resolved = candidate.resolve()
                if resolved.is_dir() and resolved.stat().st_uid == os.getuid():
                    return resolved
            except OSError:
                continue
        return None

    def _options(self, request, input_dir, config):
        bwrap, prlimit, python = request.launcher
        # RLIMIT_NPROC counts all threads of the host UID, even inside a PID
        # namespace. 128 denies launches on an ordinary desktop already above
        # that count. This is an absolute UID ceiling, not a cgroup task quota.
        args = [prlimit, "--as=1073741824", "--cpu=90", "--fsize=20971520", "--nofile=128", "--nproc=4096", "--core=0", "--",
                bwrap, "--unshare-user", "--unshare-ipc", "--unshare-pid", "--unshare-net", "--unshare-uts", "--unshare-cgroup",
                "--disable-userns", "--new-session", "--die-with-parent", "--cap-drop", "ALL"]
        for path in ("/usr", "/bin", "/lib", "/lib64", "/sbin"):
            if Path(path).exists():
                args += ["--ro-bind", path, path]
        user_local = self._user_local_dir()
        sandbox_path = "/usr/bin:/bin:/usr/local/bin"
        if user_local is not None:
            args += ["--ro-bind", str(user_local), str(user_local)]
            sandbox_path = f"{sandbox_path}:{user_local / 'bin'}"
        args += ["--proc", "/proc", "--dev", "/dev", "--dir", "/etc", "--dir", "/home",
                 "--size", "16777216", "--tmpfs", "/home/agent", "--size", "33554432", "--tmpfs", "/tmp",
                 "--size", "201326592", "--tmpfs", "/work", "--ro-bind", str(input_dir), "/input",
                 "--ro-bind", str(self.broker), "/broker.py", "--ro-bind", str(config), "/launch.json"]
        cache = Path("/etc/ld.so.cache")
        if cache.is_file():
            args += ["--ro-bind", str(cache), str(cache)]
        args += ["--remount-ro", "/dev", "--remount-ro", "/proc", "--remount-ro", "/",
                 "--clearenv", "--setenv", "PATH", sandbox_path, "--setenv", "HOME", "/home/agent",
                 "--setenv", "LANG", "C.UTF-8", "--setenv", "PYTHONNOUSERSITE", "1",
                 "--setenv", "PYTHONDONTWRITEBYTECODE", "1", "--chdir", "/work", "--", python, "/broker.py"]
        return args

    def _copy(self, destination):
        files, total, count = {}, 0, 0
        for directory, dirs, names, fd in os.fwalk(self.working_dir, follow_symlinks=False):
            relative_dir = Path(directory).relative_to(self.working_dir)
            dirs[:] = [name for name in dirs if not name.startswith(".") and name not in EXCLUDE
                       and not stat.S_ISLNK(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode)]
            target_dir = destination / relative_dir
            target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            for name in names:
                if name.startswith(".") or name in EXCLUDE or name.casefold() in SECRET_NAMES or Path(name).suffix.lower() in SECRET_SUFFIXES:
                    continue
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    continue
                if info.st_size > MAX_SINGLE_FILE_BYTES:
                    continue
                handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(handle, "rb") as stream:
                    actual = os.fstat(stream.fileno())
                    if not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1:
                        raise CommandError("SNAPSHOT_CHANGED: cambió un archivo durante la copia")
                    if actual.st_size > MAX_SINGLE_FILE_BYTES:
                        continue
                    raw = stream.read(MAX_SINGLE_FILE_BYTES + 1)
                if len(raw) > MAX_SINGLE_FILE_BYTES:
                    continue
                total += len(raw)
                count += 1
                if total > MAX_SNAPSHOT_BYTES or count > MAX_SNAPSHOT_FILES:
                    raise CommandError(f"SNAPSHOT_LIMIT: la copia admite {MAX_SNAPSHOT_BYTES // 1_000_000} MB y {MAX_SNAPSHOT_FILES} archivos")
                mode = stat.S_IMODE(actual.st_mode) & 0o777
                target = target_dir / name
                target.write_bytes(raw)
                target.chmod(mode)
                files[str(relative_dir / name)] = {"sha256": hashlib.sha256(raw).hexdigest(), "mode": mode}
        return files

    async def check_capabilities(self, request):
        if self._checked == request.identity.profile:
            return
        with tempfile.TemporaryDirectory(prefix="isycode-capability-") as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            config = root / "launch.json"
            atomic_write(config, json.dumps({"request": request.id, "argv": [trusted_binary("true")], "cwd": ".",
                                             "timeout": 5, "files": {}, "exclude": sorted(EXCLUDE)}))
            try:
                output = await capture_process(self._options(request, source, config), env={"PATH": "/usr/bin:/bin"}, timeout=12)
                report = json.loads(output.stdout)
            except (OSError, ValueError, TimeoutError):
                raise CommandError("LINUX_CAPABILITY_UNAVAILABLE: no se pudo crear el perfil aislado; revisa namespaces/AppArmor/bwrap. No se ejecutó el comando en el host.") from None
            if output.returncode or not isinstance(report, dict) or report.get("request") != request.id or report.get("returncode") != 0:
                raise CommandError("LINUX_CAPABILITY_UNAVAILABLE: el perfil obligatorio fue rechazado; no hay fallback al host")
            self._checked = request.identity.profile

    async def run_request(self, request, *, authorize=None):
        if authorize is None:
            raise CommandError("AUTHORITY_REQUIRED: falta la revalidación del host")
        current = self.prepare({"argv": list(request.identity.argv), "cwd": request.identity.cwd, "timeout": request.timeout})
        if current.identity != request.identity or current.broker_sha256 != request.broker_sha256:
            raise CommandError("COMMAND_IDENTITY_CHANGED: el ejecutable o perfil cambió desde la aprobación")
        await self.check_capabilities(request)
        with tempfile.TemporaryDirectory(prefix="isycode-command-") as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            files = self._copy(source)
            if self.working_dir.resolve() != self.working_dir:
                raise CommandError("SNAPSHOT_CHANGED: cambió la ruta del proyecto")
            if request.sandbox_executable.startswith("/work/"):
                record = files.get(request.sandbox_executable.removeprefix("/work/"))
                if not record or record["sha256"] != request.identity.executable_sha256:
                    raise CommandError("COMMAND_IDENTITY_CHANGED: el ejecutable copiado no coincide con el aprobado")
            if sha_file(request.identity.executable) != request.identity.executable_sha256 or sha_file(self.broker) != request.broker_sha256:
                raise CommandError("COMMAND_IDENTITY_CHANGED: cambió el ejecutable o broker")
            if authorize() is not True:
                raise CommandError("COMMAND_AUTHORITY_CHANGED: cambió la política, herramienta o permiso antes de ejecutar")
            config = root / "launch.json"
            atomic_write(config, json.dumps({"request": request.id,
                                             "argv": [request.sandbox_executable, *request.identity.argv[1:]],
                                             "cwd": request.identity.cwd, "timeout": request.timeout,
                                             "files": files, "exclude": sorted(EXCLUDE)}))
            receipt_path = project_state(self.working_dir) / "commands" / (request.id + ".json")
            receipt = {"request": request.id, "created": utc_now(), "identity": {
                "argv": list(request.identity.argv), "cwd": request.identity.cwd,
                "executable": request.identity.executable, "executable_sha256": request.identity.executable_sha256,
                "profile": PROFILE, "profile_sha256": request.identity.profile}, "status": "running"}
            atomic_write(receipt_path, json.dumps(receipt, indent=2) + "\n")
            try:
                output = await capture_process(self._options(request, source, config), env={"PATH": "/usr/bin:/bin"},
                                               timeout=request.timeout + 15, limit=32_000_000)
                report = json.loads(output.stdout)
            except BaseException:
                receipt.update(status="interrupted", finished=utc_now())
                atomic_write(receipt_path, json.dumps(receipt, indent=2) + "\n")
                raise
            try:
                return self._decode_report(request, output, report, files, receipt_path, receipt)
            except (ValueError, TypeError, KeyError):
                receipt.update(status="invalid_receipt", finished=utc_now())
                atomic_write(receipt_path, json.dumps(receipt, indent=2) + "\n")
                raise CommandError("COMMAND_INTERRUPTED: la ejecución no produjo un recibo válido; la carpeta original se conserva") from None

    def _decode_report(self, request, output, report, files, receipt_path, receipt):
        if output.returncode or not isinstance(report, dict) or report.get("request") != request.id or "error" in report:
            raise CommandError("COMMAND_FAILED: el proceso aislado no terminó con un recibo válido; la carpeta original se conserva")
        if type(report.get("returncode")) is not int or not isinstance(report.get("stdout"), str) or not isinstance(report.get("stderr"), str):
            raise CommandError("COMMAND_PROTOCOL_INVALID: recibo no válido")
        changes = report.get("changes")
        if not isinstance(changes, dict) or len(changes) > 100 or not isinstance(report.get("unsupported"), list):
            raise CommandError("COMMAND_PROTOCOL_INVALID: manifiesto no válido")
        if len(report["unsupported"]) > 5000 or not all(isinstance(item, str) and len(item) <= 4096 for item in report["unsupported"]):
            raise CommandError("COMMAND_PROTOCOL_INVALID: cambios no soportados inválidos")
        decoded, size = {}, 0
        for path, encoded in changes.items():
            if not isinstance(path, str) or not path or len(path) > 4096 or not isinstance(encoded, str) or Path(path).is_absolute() or ".." in Path(path).parts or any(part.startswith(".") or part in EXCLUDE for part in Path(path).parts):
                raise CommandError("COMMAND_PATH_INVALID: ruta de salida no soportada")
            if Path(path).suffix.lower() in SECRET_SUFFIXES or Path(path).name.casefold() in SECRET_NAMES:
                raise CommandError("COMMAND_SECRET_PATH: la salida modifica una ruta excluida")
            raw = base64.b64decode(encoded, validate=True)
            size += len(raw)
            if len(raw) > 2_000_000 or size > 10_000_000:
                raise CommandError("CHANGESET_LIMIT: la salida supera el límite")
            decoded[path] = raw.decode("utf-8")
        receipt.update(status="finished", finished=utc_now(), returncode=report["returncode"],
                       stdout=report["stdout"], stderr=report["stderr"], changes=list(decoded),
                       unsupported=report["unsupported"], verification="NOT_DEMONSTRATED")
        atomic_write(receipt_path, json.dumps(receipt, indent=2) + "\n")
        return {"returncode": report["returncode"], "stdout": report["stdout"], "stderr": report["stderr"],
                "changes": decoded, "unsupported": report["unsupported"],
                "bases": {path: record["sha256"] for path, record in files.items()},
                "request": request.id, "profile": PROFILE, "profile_sha256": request.identity.profile}

    async def execute(self, tool_call):
        return ExecutionResult(False, stderr="Usa la autoridad común y una aprobación de comando.", returncode=1, error_code="APPROVAL_REQUIRED")

    async def verify(self, result):
        return {"status": "NOT_DEMONSTRATED", "reason": "Una ejecución aislada no demuestra corrección."}
