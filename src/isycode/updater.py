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
from urllib.parse import unquote, urlsplit


OFFICIAL_REPOSITORY = "https://github.com/DannyBaanks/ISyCode.git"
GENERATED_COVERAGE_SNAPSHOT = "docs/security/m15-authority-coverage.json"
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
                 discover_source_checkout: bool = True,
                 confirm=None):
        self.source_root = (Path(source_root).resolve() if source_root is not None else
                            self.discover_checkout() if discover_source_checkout else None)
        self.data_home = Path(data_home) if data_home is not None else None
        self.command_runner = command_runner
        self.allow_local_remotes = allow_local_remotes
        self.official_repository = official_repository
        # Asked before anything beyond a clean fast-forward (backing up local
        # changes in a stash, or creating a merge commit). None means "no".
        self.confirm = confirm

    def _confirmed(self, question: str, details: tuple[str, ...] = ()) -> bool:
        if self.confirm is None:
            return False
        try:
            return self.confirm(question, details) is True
        except (EOFError, KeyboardInterrupt):
            return False

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
                   "-c", "protocol.allow=never", "-c", "protocol.https.allow=always"]
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
        try:
            official = urlsplit(self.official_repository)
            path = unquote(parsed.path)
            official_path = unquote(official.path)
        except (AttributeError, ValueError):
            return False
        # Bind both owner and repository to the configured official source; a
        # matching final component alone lets any GitHub user impersonate ISyCode.
        if (official.scheme != "https" or official.hostname != "github.com"
                or not official_path or official.username or official.password):
            return False
        def canonical(value: str) -> str:
            return value.rstrip("/").removesuffix(".git").casefold()

        return canonical(path) == canonical(official_path)

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

    def _merge_preview(self) -> tuple[str, list[str]]:
        """Preflight a merge without touching the index or working tree."""
        result = self._git("merge-tree", "--write-tree", "HEAD", "FETCH_HEAD", check=False)
        if result.returncode == 0:
            return "clean", []
        if result.returncode != 1:
            return "error", []
        paths: list[str] = []
        for line in result.stdout.splitlines():
            match = re.search(r"Merge conflict in (.+)$", line)
            if match:
                path = self._clean_line(match.group(1))
                if path and path not in paths:
                    paths.append(path)
        return "conflict", paths[:30]

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
            status = self._git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
            dirty_paths = [self._clean_line(item[3:]) for item in status.split("\0") if item]
            ignored_paths = self._ignored_paths()
            collisions = [incoming for incoming in incoming_paths
                          if any(self._overlap(incoming, ignored) for ignored in ignored_paths)]
            if behind == 0:
                lines = ["ISyCode ya está actualizado; no hay commits remotos nuevos."]
                if dirty_paths:
                    lines.append(
                        f"Se conservaron {len(dirty_paths)} cambio(s) local(es) sin modificar."
                    )
                return UpdateReport("current", tuple(lines))
            if dirty_paths or collisions:
                if (dirty_paths and not collisions and not check_only and self._confirmed(
                        f"Tienes {len(dirty_paths)} cambio(s) local(es). ¿Guardarlos en un git stash, "
                        "actualizar y volver a aplicarlos?", tuple(f"Local: {p}" for p in dirty_paths[:30]))):
                    saved = self._stash_local_changes()
                    if isinstance(saved, UpdateReport):
                        return saved
                    stash_oid = saved
                    integrated = self._update_checkout(root, check_only=False)
                    restored = self._restore_local_changes(stash_oid)
                    if restored is not None:
                        return UpdateReport(restored.status,
                                            (*integrated.lines, *restored.lines))
                    return integrated
                lines = [
                    f"Hay {len(dirty_paths)} cambio(s) local(es); no se actualizó el checkout."
                ]
                if behind:
                    lines.append(
                        f"El remoto todavía tiene {behind} commit(s) pendiente(s); "
                        "guarda o confirma tus cambios locales y vuelve a ejecutar el comando."
                    )
                lines.extend(f"Local: {p}" for p in dirty_paths[:30])
                lines.extend(f"Archivo ignorado que coincide con la actualización: {p}" for p in collisions[:30])
                lines.extend(f"Actualizaciones remotas: {self._clean_line(line)}" for line in commits[:12])
                lines.extend(self._clean_line(line) for line in summary[:12])
                return UpdateReport("dirty", tuple(lines))
            details = [f"Actualizaciones disponibles: {behind} commit(s)."]
            details.extend(self._clean_line(line) for line in commits[:12])
            details.extend(self._clean_line(line) for line in summary[:12])
            review = "git diff --stat HEAD FETCH_HEAD"
            details.append(f"Revisa el cambio con: {review}")
            diverged = ahead > 0 and behind > 0
            if diverged:
                local_commits = self._git("log", "--format=%h %s", "FETCH_HEAD..HEAD").stdout.splitlines()
                lines = [f"Historial divergente: {ahead} commit(s) local(es) y {behind} remoto(s)."]
                lines.append("Commits locales:")
                lines.extend(self._clean_line(line) for line in local_commits[:10])
                lines.append("Commits remotos:")
                lines.extend(self._clean_line(line) for line in commits[:10])
                lines.extend(self._clean_line(line) for line in summary[:12])
                state, conflicts = self._merge_preview()
                if state == "error":
                    lines.append("Falló la previsualización previa; la rama y los archivos se conservaron.")
                    lines.append("Revisa Git y vuelve a ejecutar isycode actualizar.")
                    return UpdateReport("blocked", tuple(lines))
                if state == "conflict":
                    if conflicts == [GENERATED_COVERAGE_SNAPSHOT]:
                        lines.append(
                            "El único conflicto es el snapshot de cobertura generado; "
                            "puede regenerarse desde el código integrado."
                        )
                        if check_only:
                            lines.append("La comprobación no integró ni regeneró archivos.")
                            return UpdateReport("available", tuple(lines))
                        if not self._confirmed("Tu rama y la remota divergieron. ¿Crear un commit de merge?",
                                               tuple(lines)):
                            return self._merge_declined(lines)
                        merged = self._merge_and_regenerate_coverage(root)
                        if merged is not None:
                            return UpdateReport(merged.status, (*lines, *merged.lines))
                        sync = self._sync_environment(root)
                        if sync is not None:
                            return sync
                        return UpdateReport(
                            "updated",
                            ("ISyCode actualizado; se conservaron ambas historias y se regeneró el snapshot.", *lines),
                        )
                    lines.append("Git detectó conflictos; no se integró nada y se conservaron la rama y los archivos.")
                    lines.extend(f"Conflicto: {path}" for path in conflicts)
                    if not conflicts:
                        lines.append("Git no pudo identificar las rutas en conflicto; revisa el merge manualmente.")
                    lines.append("Resuelve los conflictos y vuelve a ejecutar isycode actualizar.")
                    return UpdateReport("blocked", tuple(lines))
                lines.append("La previsualización confirma que ambas historias se pueden integrar sin conflictos.")
                if check_only:
                    lines.append("No se integró nada porque esta es una comprobación.")
                    return UpdateReport("available", tuple(lines))
                if not self._confirmed("Tu rama y la remota divergieron. ¿Crear un commit de merge?",
                                       tuple(lines)):
                    return self._merge_declined(lines)
                merge = self._git("merge", "--no-edit", "--no-ff", "FETCH_HEAD", check=False)
                if merge.returncode:
                    return UpdateReport("error", (
                        "Git no completó la integración después de la previsualización.",
                        "No se reescribieron commits; revisa git status antes de continuar.",
                    ))
                sync = self._sync_environment(root)
                if sync is not None:
                    return sync
                return UpdateReport("updated", ("ISyCode actualizado; se conservaron ambas historias.", *lines))
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

    @staticmethod
    def _merge_declined(lines: list[str]) -> UpdateReport:
        return UpdateReport("blocked", (*lines,
            "No se integró nada: el merge necesita tu confirmación.",
            "Ejecuta isycode actualizar en una terminal y responde «s», o integra con git merge."))

    def _stash_local_changes(self) -> str | UpdateReport:
        """Back up staged-safe dirty work before merging; never absorb an existing index."""
        staged = self._git("diff", "--cached", "--quiet", check=False)
        if staged.returncode != 0:
            return UpdateReport("dirty", (
                "Hay cambios preparados en el índice; se conservaron y no se actualizó el checkout.",
                "Confirma o retira esos cambios preparados y vuelve a ejecutar isycode actualizar.",
            ))
        before = self._git("rev-parse", "--verify", "refs/stash", check=False)
        before_oid = before.stdout.strip() if before.returncode == 0 else ""
        added = self._git("add", "--all", check=False)
        if added.returncode:
            self._git("reset", "--mixed", "HEAD", check=False)
            return UpdateReport("error", (
                "No se pudieron preparar temporalmente los cambios locales; se conservaron los archivos.",
            ))
        saved = self._git("stash", "push", "--include-untracked", "-m",
                          "isycode actualizar: respaldo temporal", check=False)
        after = self._git("rev-parse", "--verify", "refs/stash", check=False)
        after_oid = after.stdout.strip() if after.returncode == 0 else ""
        if saved.returncode or not after_oid or after_oid == before_oid:
            self._git("reset", "--mixed", "HEAD", check=False)
            return UpdateReport("error", (
                "No se pudo crear un respaldo Git de los cambios locales; se conservaron los archivos.",
            ))
        return after_oid

    def _restore_local_changes(self, stash_oid: str) -> UpdateReport | None:
        restored = self._git("stash", "apply", stash_oid, check=False)
        if restored.returncode:
            unresolved = self._git("ls-files", "--unmerged", "-z", check=False)
            if unresolved.returncode == 0 and not unresolved.stdout:
                restored = self._git("stash", "apply", stash_oid, check=False)
        if restored.returncode == 0:
            return None
        unresolved = self._git("ls-files", "--unmerged", "-z", check=False)
        paths = []
        for record in unresolved.stdout.split("\0"):
            if "\t" in record:
                path = self._clean_line(record.split("\t", 1)[1])
                if path not in paths:
                    paths.append(path)
        if paths == [GENERATED_COVERAGE_SNAPSHOT] and self._regenerate_coverage_snapshot():
            return None
        lines = [
            "El código remoto se integró; algunos cambios locales necesitan resolución manual.",
            f"Respaldo completo conservado en Git stash {stash_oid[:12]}.",
        ]
        lines.extend(f"Conflicto: {path}" for path in paths[:30])
        if not paths:
            lines.append("La restauración no terminó; recupera los cambios con git stash apply "
                         f"{stash_oid[:12]}.")
        return UpdateReport("updated-conflicts", tuple(lines))

    def _regenerate_coverage_snapshot(self) -> bool:
        root = self.source_root
        if root is None:
            return False
        snapshot = root / GENERATED_COVERAGE_SNAPSHOT
        try:
            if not stat.S_ISREG(snapshot.lstat().st_mode):
                return False
        except OSError:
            return False
        python = root / ".venv" / "bin" / "python"
        if not python.is_file():
            python = Path(sys.executable)
        generator = "\n".join((
            "import json, os, stat, tempfile",
            "from pathlib import Path",
            "from isycode.action_coverage import authority_coverage_snapshot",
            f"p = Path({GENERATED_COVERAGE_SNAPSHOT!r})",
            "if not stat.S_ISDIR(p.parent.parent.lstat().st_mode) or not stat.S_ISDIR(p.parent.lstat().st_mode): raise ValueError('snapshot parent is not a directory')",
            "info = p.lstat()",
            "if not stat.S_ISREG(info.st_mode): raise ValueError('snapshot is not a regular file')",
            "fd, temporary = tempfile.mkstemp(prefix='.' + p.name + '.', suffix='.tmp', dir=p.parent)",
            "try:",
            "    with os.fdopen(fd, 'w', encoding='utf-8', newline='\\n') as stream:",
            "        stream.write(json.dumps(authority_coverage_snapshot(), ensure_ascii=False, indent=2) + '\\n')",
            "    os.chmod(temporary, stat.S_IMODE(info.st_mode))",
            "    os.replace(temporary, p)",
            "finally:",
            "    try: os.unlink(temporary)",
            "    except FileNotFoundError: pass",
        ))
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(filter(
            None, (str(root / "src"), str(root), env.get("PYTHONPATH", ""))))
        try:
            generated = self.command_runner(
                [str(python), "-c", generator], cwd=str(root), env=env,
                text=True, capture_output=True, timeout=120, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if generated.returncode:
            return False
        staged = self._git("add", "--", GENERATED_COVERAGE_SNAPSHOT, check=False)
        if staged.returncode:
            return False
        unresolved = self._git("diff", "--name-only", "--diff-filter=U", "-z", check=False)
        return unresolved.returncode == 0 and not unresolved.stdout

    def _merge_and_regenerate_coverage(self, root: Path) -> UpdateReport | None:
        """Resolve only the canonical generated coverage report during a merge."""
        self._git("merge", "--no-edit", "--no-ff", "--no-commit", "FETCH_HEAD", check=False)
        merge_head = self._git("rev-parse", "--verify", "MERGE_HEAD", check=False)
        if merge_head.returncode:
            return UpdateReport("error", (
                "Git no dejó activa la integración regenerable; no se tocaron archivos para resolver el conflicto.",
            ))

        unresolved = self._git("diff", "--name-only", "--diff-filter=U", "-z", check=False)
        unresolved_paths = [p for p in unresolved.stdout.split("\0") if p]
        if unresolved.returncode or unresolved_paths != [GENERATED_COVERAGE_SNAPSHOT]:
            return self._abort_generated_merge("blocked", (
                "El merge produjo conflictos distintos a la previsualización; se abortó sin resolverlos.",
                *(f"Conflicto: {path}" for path in unresolved_paths[:30]),
            ))

        python = root / ".venv" / "bin" / "python"
        if not python.is_file():
            python = Path(sys.executable)
        generator = "\n".join((
            "import json, os, stat, tempfile",
            "from pathlib import Path",
            "from isycode.action_coverage import authority_coverage_snapshot",
            f"p = Path({GENERATED_COVERAGE_SNAPSHOT!r})",
            "if not stat.S_ISDIR(p.parent.parent.lstat().st_mode) or not stat.S_ISDIR(p.parent.lstat().st_mode): raise ValueError('snapshot parent is not a directory')",
            "info = p.lstat()",
            "if not stat.S_ISREG(info.st_mode): raise ValueError('snapshot is not a regular file')",
            "fd, temporary = tempfile.mkstemp(prefix='.' + p.name + '.', suffix='.tmp', dir=p.parent)",
            "try:",
            "    with os.fdopen(fd, 'w', encoding='utf-8', newline='\\n') as stream:",
            "        stream.write(json.dumps(authority_coverage_snapshot(), ensure_ascii=False, indent=2) + '\\n')",
            "    os.chmod(temporary, stat.S_IMODE(info.st_mode))",
            "    os.replace(temporary, p)",
            "finally:",
            "    try:",
            "        os.unlink(temporary)",
            "    except FileNotFoundError:",
            "        pass",
        ))
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(filter(
            None, (str(root / "src"), str(root), env.get("PYTHONPATH", ""))))
        try:
            regenerated = self.command_runner(
                [str(python), "-c", generator], cwd=str(root), env=env,
                text=True, capture_output=True, timeout=120, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            regenerated = None
        if regenerated is None or regenerated.returncode:
            return self._abort_generated_merge("error", (
                "No se pudo regenerar el snapshot oficial de cobertura.",
            ))

        staged = self._git("add", "--", GENERATED_COVERAGE_SNAPSHOT, check=False)
        if staged.returncode:
            return self._abort_generated_merge("error", (
                "No se pudo registrar el snapshot regenerado.",
            ))
        committed = self._git("commit", "--no-edit", check=False)
        if committed.returncode:
            return self._abort_generated_merge("error", (
                "No se pudo completar el commit de integración.",
            ))
        return None

    def _abort_generated_merge(self, status: str, lines: tuple[str, ...]) -> UpdateReport:
        aborted = self._git("merge", "--abort", check=False)
        if aborted.returncode:
            return UpdateReport("error", (*lines,
                "Git no pudo abortar el merge; revisa `git status` antes de continuar."))
        return UpdateReport(status, (*lines,
            "Se abortó el merge; HEAD, índice y archivos volvieron al estado previo."))

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
