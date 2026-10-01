"""Conservative self-update support for ISyCode source checkouts."""
from __future__ import annotations

import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


OFFICIAL_REPOSITORY = "https://github.com/DannyBaanks/ISyCode.git"
_DANGEROUS_CONFIG = re.compile(
    r"(^|\.)(filter|diff|merge)\..*\.(clean|smudge|process|textconv|command|driver)$"
    r"|(^|\.)(core\.fsmonitor|core\.hookspath|core\.sshcommand|credential\.helper)$"
    r"|(^|\.)(include|includeif)\."
    r"|(^|\.)(remote\..*\.(uploadpack|receivepack|vcs))$"
    r"|(^|\.)(url\..*\.insteadof|http\..*\.extraheader)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class UpdateReport:
    status: str
    lines: tuple[str, ...]


class SelfUpdater:
    """Inspect and fast-forward a clean checkout without shelling out to user hooks."""

    def __init__(self, source_root: Path | str | None = None, *, data_home: Path | str | None = None,
                 command_runner=subprocess.run, allow_local_remotes: bool = False,
                 official_repository: str = OFFICIAL_REPOSITORY,
                 discover_source_checkout: bool = True):
        self.source_root = (Path(source_root).resolve() if source_root is not None else
                            self.discover_checkout() if discover_source_checkout else None)
        self.data_home = Path(data_home) if data_home is not None else None
        self.command_runner = command_runner
        self.allow_local_remotes = allow_local_remotes
        self.official_repository = official_repository

    @staticmethod
    def discover_checkout(package_file: Path | str | None = None) -> Path | None:
        start = Path(package_file or __file__).resolve()
        for candidate in (start.parent, *start.parents):
            if (candidate / "pyproject.toml").is_file() and (
                    (candidate / ".git").exists() or (candidate / ".git").is_file()):
                return candidate
        return None

    @staticmethod
    def _git_path() -> str:
        for candidate in ("/usr/local/bin/git", "/usr/bin/git", "/bin/git"):
            if Path(candidate).is_file() and os.access(candidate, os.X_OK):
                return candidate
        return shutil.which("git") or "git"

    def _env(self) -> dict[str, str]:
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(Path.home()),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_ATTR_NOSYSTEM": "1",
        }
        return env

    def _git(self, *args: str, cwd: Path | None = None, check: bool = True,
             local_file_protocol: bool = False):
        options = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                   "-c", "diff.external=", "-c", "credential.helper=",
                   "-c", "protocol.allow=never"]
        if local_file_protocol:
            options.extend(["-c", "protocol.file.allow=always"])
        try:
            result = self.command_runner(
                [self._git_path(), *options, *args],
                cwd=str(cwd or self.source_root),
                env=self._env(),
                text=True,
                capture_output=True,
                timeout=90,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError("No se pudo ejecutar Git de forma segura.")
        if check and result.returncode:
            raise RuntimeError("Falló una operación Git; no se modificó el checkout.")
        return result

    def _config_keys_safe(self) -> bool:
        root = self.source_root
        if root is None:
            return False
        git_dir_result = self._git("rev-parse", "--absolute-git-dir", check=False)
        if git_dir_result.returncode:
            return False
        git_dir = Path(git_dir_result.stdout.strip())
        common_result = self._git("rev-parse", "--git-common-dir", check=False)
        if common_result.returncode:
            return False
        common_dir = Path(common_result.stdout.strip())
        if not common_dir.is_absolute():
            common_dir = (root / common_dir).resolve()
        config_paths = [common_dir / "config", git_dir / "config.worktree"]
        for config in config_paths:
            if not config.is_file():
                continue
            result = self._git("config", "--file", str(config), "--no-includes",
                               "--name-only", "--list", "-z", check=False)
            if result.returncode:
                return False
            keys = [key.casefold() for key in result.stdout.split("\0") if key]
            if any(_DANGEROUS_CONFIG.search(key) for key in keys):
                return False
        return True

    def _remote_allowed(self, url: str) -> bool:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            return False
        if self.allow_local_remotes and not parsed.scheme:
            return True
        if (parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username
                or parsed.password or port not in (None, 443) or parsed.query or parsed.fragment):
            return False
        return Path(parsed.path).name.removesuffix(".git").casefold() == "isycode"

    @staticmethod
    def _clean_line(value: str) -> str:
        return "".join(ch if ch >= " " and ch != "\x7f" else " " for ch in value).strip()

    def _incoming_details(self) -> tuple[str, list[str], list[str], list[str]]:
        counts = self._git("rev-list", "--left-right", "--count", "HEAD...FETCH_HEAD").stdout.split()
        ahead, behind = (int(counts[0]), int(counts[1]))
        commits = self._git("log", "--format=%h %s", "HEAD..FETCH_HEAD").stdout.splitlines()
        summary = self._git("diff", "--stat", "HEAD...FETCH_HEAD").stdout.splitlines()
        paths = [p for p in self._git("diff", "--name-only", "-z", "HEAD...FETCH_HEAD").stdout.split("\0") if p]
        return f"{ahead} {behind}", commits, summary, paths

    def _ignored_paths(self) -> list[str]:
        result = self._git("ls-files", "--others", "--ignored", "--directory",
                           "--exclude-standard", "-z", check=False)
        return [p.rstrip("/") for p in result.stdout.split("\0") if p]

    @staticmethod
    def _overlap(path: str, ignored: str) -> bool:
        return path == ignored or path.startswith(ignored + "/") or ignored.startswith(path + "/")

    def run(self, check_only: bool = False) -> UpdateReport:
        root = self.source_root
        if root is None:
            return self._bootstrap(check_only)
        if not root.is_dir():
            return UpdateReport("blocked", ("No se encontró un checkout de ISyCode.",))
        return self._update_checkout(root, check_only)

    def _update_checkout(self, root: Path, check_only: bool) -> UpdateReport:
        self.source_root = root.resolve()
        if not (root / ".git").exists() and not (root / ".git").is_file():
            return UpdateReport("blocked", ("La carpeta actual no es un checkout Git administrado.",))
        try:
            if not self._config_keys_safe():
                return UpdateReport("blocked", ("Configuración local de Git con filtros o ejecutables: revisión manual requerida.",))
            branch = self._git("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
            if branch.returncode:
                return UpdateReport("blocked", ("HEAD separado; cambia a una rama antes de actualizar.",))
            branch_name = branch.stdout.strip()
            upstream = self._git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", check=False)
            if upstream.returncode:
                return UpdateReport("blocked", (
                    "Esta rama no tiene upstream configurado.",
                    f"Configúralo con: git branch --set-upstream-to=origin/{shlex.quote(branch_name)} {shlex.quote(branch_name)}",
                ))
            upstream_name = upstream.stdout.strip()
            remote_name, separator, remote_branch = upstream_name.partition("/")
            if not separator or not remote_name or not remote_branch or remote_branch.startswith("/"):
                return UpdateReport("blocked", ("La referencia upstream no es válida.",))
            remote = self._git("remote", "get-url", remote_name, check=False)
            if remote.returncode or not self._remote_allowed(remote.stdout.strip()):
                return UpdateReport("blocked", ("El remoto configurado no es un repositorio ISyCode de GitHub permitido.",))
            fetch = self._git("fetch", "--no-tags", "--no-recurse-submodules", remote_name,
                              f"refs/heads/{remote_branch}", check=False,
                              local_file_protocol=self.allow_local_remotes)
            if fetch.returncode:
                return UpdateReport("error", ("Falló el fetch; revisa la conexión y la disponibilidad del remoto.",))
            counts, commits, summary, incoming_paths = self._incoming_details()
            ahead, behind = (int(value) for value in counts.split())
            if ahead and behind:
                return UpdateReport("blocked", ("La rama local y la remota divergieron; no se reescribió historial.",))
            status = self._git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
            dirty_paths = [self._clean_line(item[3:]) for item in status.split("\0") if item]
            ignored_paths = self._ignored_paths()
            collisions = [incoming for incoming in incoming_paths
                          if any(self._overlap(incoming, ignored) for ignored in ignored_paths)]
            if behind == 0:
                return UpdateReport("current", ("ISyCode ya está actualizado.",))
            details = [f"Actualizaciones disponibles: {behind} commit(s)."]
            details.extend(self._clean_line(line) for line in commits[:12])
            details.extend(self._clean_line(line) for line in summary[:12])
            review = "git diff --stat HEAD FETCH_HEAD"
            details.append(f"Revisa el cambio con: {review}")
            if dirty_paths or collisions:
                lines = ["Hay cambios locales; no se actualizó el checkout."]
                lines.extend(f"Local: {p}" for p in dirty_paths[:30])
                lines.extend(f"Archivo ignorado que coincide con la actualización: {p}" for p in collisions[:30])
                lines.extend(details)
                return UpdateReport("dirty", tuple(lines))
            if check_only:
                return UpdateReport("available", tuple(details))
            merge = self._git("merge", "--ff-only", "--no-edit", "FETCH_HEAD", check=False)
            if merge.returncode:
                return UpdateReport("error", ("Git rechazó el avance rápido; tu rama y archivos se conservaron.",))
            sync = self._sync_environment(root)
            if sync is not None:
                return sync
            return UpdateReport("updated", ("ISyCode actualizado correctamente.", *details))
        except RuntimeError as exc:
            return UpdateReport("error", (str(exc),))

    def _data_root(self) -> Path:
        if self.data_home is not None:
            base = self.data_home
        else:
            xdg = os.environ.get("XDG_DATA_HOME", "")
            base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".local" / "share"
        return base / "isycode"

    def _bootstrap(self, check_only: bool) -> UpdateReport:
        destination = self._data_root() / "source"
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink():
                return UpdateReport("blocked", (f"Se conservó el enlace existente: {destination}",))
            if not ((destination / ".git").exists() or (destination / ".git").is_file()):
                return UpdateReport("blocked", (
                    f"Se conservó la carpeta existente: {destination}",
                    "Muévela manualmente a otra ubicación para instalar ISyCode ahí.",
                ))
            self.source_root = destination.resolve()
            report = self._update_checkout(self.source_root, check_only)
            if check_only or report.status not in {"updated", "current"}:
                return report
            sync = self._sync_environment(self.source_root)
            if sync is not None:
                return sync
            return self._manage_launcher(self.source_root, report)

        if check_only:
            result = self._git("ls-remote", "--symref", self.official_repository, "HEAD",
                               cwd=Path.cwd(), check=False,
                               local_file_protocol=self.allow_local_remotes)
            if result.returncode:
                return UpdateReport("error", ("No se pudo consultar el repositorio oficial; revisa la conexión.",))
            match = re.search(r"^ref:\s+refs/heads/(\S+)\s+HEAD$", result.stdout, re.MULTILINE)
            branch = match.group(1) if match else "rama predeterminada"
            return UpdateReport("available", (f"Repositorio oficial disponible ({branch}).",
                                               "La comprobación no clonó ni instaló archivos."))

        parent = destination.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".isycode-source-", dir=parent))
            shutil.rmtree(staging)
            clone = self._git("clone", "--", self.official_repository, str(staging),
                              cwd=parent, check=False, local_file_protocol=self.allow_local_remotes)
            if clone.returncode:
                shutil.rmtree(staging, ignore_errors=True)
                return UpdateReport("error", ("No se pudo clonar ISyCode. Revisa la conexión y vuelve a intentar.",))
            if destination.exists() or destination.is_symlink():
                shutil.rmtree(staging, ignore_errors=True)
                return UpdateReport("blocked", (f"Se preservó la carpeta que apareció durante la instalación: {destination}",))
            os.rename(staging, destination)
        except (OSError, RuntimeError):
            return UpdateReport("error", ("No se pudo preparar la carpeta de datos de ISyCode.",))
        self.source_root = destination.resolve()
        sync = self._sync_environment(destination)
        if sync is not None:
            return sync
        return self._manage_launcher(destination, UpdateReport("updated", (
            f"Código descargado en {destination}.",
            "ISyCode se instaló en un entorno virtual aislado.",
        )))

    def _sync_environment(self, root: Path) -> UpdateReport | None:
        if not (root / "pyproject.toml").is_file():
            return None
        environment_python = root / ".venv" / "bin" / "python"
        try:
            if not environment_python.is_file():
                created = self.command_runner([sys.executable, "-m", "venv", str(root / ".venv")],
                                              cwd=str(root), env=os.environ.copy(),
                                              text=True, capture_output=True, timeout=180, check=False)
                if created.returncode:
                    return UpdateReport("error", ("No se pudo crear el entorno virtual; el checkout se conservó.",))
            installed = self.command_runner(
                [str(environment_python), "-m", "pip", "install", "--upgrade", "-e", str(root)],
                cwd=str(root), env=os.environ.copy(), text=True, capture_output=True,
                timeout=900, check=False,
            )
            if installed.returncode:
                return UpdateReport("error", (
                    "El código quedó actualizado, pero no se pudieron sincronizar sus dependencias.",
                    f"Reintenta: {environment_python} -m pip install --upgrade -e {shlex.quote(str(root))}",
                ))
        except (OSError, subprocess.TimeoutExpired):
            return UpdateReport("error", ("No se pudo sincronizar el entorno virtual de ISyCode.",))
        return None

    @staticmethod
    def _is_generated_pip_launcher(path: Path) -> bool:
        try:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != os.geteuid() or info.st_size > 8192):
                return False
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return False
        normalized = text.replace("\r\n", "\n")
        if not normalized.startswith("#!") or len(normalized.splitlines()) > 12:
            return False
        lines = normalized.splitlines()
        interpreter = Path(lines[0][2:]).name.casefold() if lines[0].startswith("#!") else ""
        if (not re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", interpreter)
                or any("\x00" in line for line in lines)):
            return False
        body = "\n".join(lines[1:]) + "\n"
        prefixes = ("", "# -*- coding: utf-8 -*-\n")
        for prefix in prefixes:
            for re_import in ("", "import re\n"):
                candidate = (prefix + re_import + "import sys\n"
                             "from isycode.launcher import main\n"
                             "if __name__ == '__main__':\n")
                for argv_line in (
                    "",
                    "    sys.argv[0] = re.sub(r'(-script\\.pyw?|\\.exe)?$', '', sys.argv[0])\n",
                ):
                    if body == candidate + argv_line + "    sys.exit(main())\n":
                        return not argv_line or bool(re_import)
        return False

    def _manage_launcher(self, root: Path, report: UpdateReport) -> UpdateReport:
        bin_dir = Path.home() / ".local" / "bin"
        command = bin_dir / "isycode"
        launcher = root / "scripts" / "isycode"
        try:
            bin_dir.mkdir(parents=True, exist_ok=True)
            if command.is_symlink() and command.resolve() == launcher.resolve():
                return report
            if command.exists() or command.is_symlink():
                if not self._is_generated_pip_launcher(command):
                    return UpdateReport(report.status, (*report.lines,
                        f"Se conservó el comando existente. El launcher preparado está en: {launcher}",
                        f"Para usarlo directamente: {launcher}",
                    ))
            temporary = bin_dir / f".isycode-link-{os.getpid()}"
            if temporary.exists() or temporary.is_symlink():
                return UpdateReport("blocked", (*report.lines, "No se reemplazó un archivo temporal existente."))
            temporary.symlink_to(launcher)
            if command.exists() or command.is_symlink():
                if not self._is_generated_pip_launcher(command):
                    temporary.unlink()
                    return UpdateReport(report.status, (*report.lines,
                        f"Se conservó el comando existente. El launcher preparado está en: {launcher}"))
            os.replace(temporary, command)
        except OSError:
            return UpdateReport(report.status, (*report.lines,
                f"No se pudo enlazar el comando; launcher preparado: {launcher}",
                f"Enlázalo manualmente en {command}.",
            ))
        lines = [*report.lines, f"Comando disponible: {command}"]
        if str(bin_dir) not in os.environ.get("PATH", "").split(os.pathsep):
            lines.append(f"Añádelo al PATH: export PATH={shlex.quote(str(bin_dir))}:$PATH")
        return UpdateReport(report.status, tuple(lines))
