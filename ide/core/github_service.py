"""Official gh identity/catalog and explicit, conservative Git synchronization."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shlex
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

from core.ide_state import atomic_write, state_home, project_state, state_lock, async_state_lock
from core.processes import capture_process
from core.resident.store import utc_now


class GitHubError(ValueError):
    pass


def github_identity(url: str) -> str:
    """Never expose credentials or match repositories by directory basename."""
    if url.startswith("git@github.com:"):
        path = url.removeprefix("git@github.com:")
    else:
        parsed = urlsplit(url)
        if parsed.hostname != "github.com" or parsed.scheme not in {"https", "ssh"} or parsed.password or parsed.query or parsed.fragment:
            raise GitHubError("El remoto debe pertenecer a github.com sin credenciales en la URL.")
        if parsed.username and not (parsed.scheme == "ssh" and parsed.username == "git"):
            raise GitHubError("No se admiten credenciales en el remoto.")
        if parsed.port not in {None, 22, 443}:
            raise GitHubError("Puerto de remoto no soportado.")
        path = parsed.path.lstrip("/")
    path = path.removesuffix("/").removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path):
        raise GitHubError("La identidad del repositorio remoto no es válida.")
    return path


@dataclass(frozen=True)
class GitStatus:
    folder: str
    repo: str
    branch: str
    upstream: str
    remote: str
    remote_branch: str
    head: str
    target: str
    ahead: int | None
    behind: int | None
    local_changes: int
    staged: int
    unstaged: int
    untracked: int
    conflicts: bool
    shallow: bool
    checked: str | None
    fresh: bool
    state: str

    @property
    def can_update(self):
        return (self.fresh and self.state == "behind" and self.ahead == 0
                and self.local_changes == 0 and not self.conflicts and not self.shallow)


@dataclass(frozen=True)
class PullPreview:
    id: str
    status: GitStatus
    files: tuple[tuple[str, str], ...]
    created: str


class RepoLinkStore:
    def __init__(self):
        self.path = state_home() / "github-links.json"

    def list(self):
        if not self.path.exists():
            return []
        if self.path.is_symlink() or self.path.stat().st_size > 1_000_000:
            raise GitHubError("El registro de carpetas no es válido.")
        links = json.loads(self.path.read_text())
        if not isinstance(links, list) or any(
                not isinstance(x, dict) or not isinstance(x.get("repo"), str)
                or not isinstance(x.get("folder"), str) or not Path(x["folder"]).is_absolute()
                for x in links):
            raise GitHubError("El registro de carpetas no es válido.")
        for link in links:
            github_identity("https://github.com/" + link["repo"])
        return links

    def add(self, repo: str, folder: str):
        folder = str(Path(folder).resolve())
        with state_lock(self.path.with_suffix(".lock")):
            links = self.list()
            links = [x for x in links if x.get("folder") != folder]
            links.append({"repo": repo, "folder": folder})
            atomic_write(self.path, json.dumps(links, ensure_ascii=False, indent=2) + "\n")

    def unlink(self, folder):
        with state_lock(self.path.with_suffix(".lock")):
            links = [x for x in self.list() if x.get("folder") != str(Path(folder).resolve())]
            atomic_write(self.path, json.dumps(links, ensure_ascii=False, indent=2) + "\n")


class GitHubService:
    """Calls only fixed gh commands; no token export or global auth setup."""

    def __init__(self):
        self.links = RepoLinkStore()

    async def _gh(self, arguments):
        binary = shutil.which("gh")
        if not binary:
            raise GitHubError("gh no está instalado. Instala GitHub CLI e inicia sesión con gh auth login.")
        env = dict(os.environ, GH_HOST="github.com", GH_PROMPT_DISABLED="1", GH_PAGER="cat")
        try:
            output = await capture_process([binary, *arguments], env=env, timeout=40)
        except (OSError, TimeoutError, ValueError):
            raise GitHubError("No se pudo consultar GitHub. Revisa gh, la red y la sesión.") from None
        if output.returncode:
            raise GitHubError("GitHub rechazó la consulta. Revisa la sesión o los permisos con gh auth status.")
        try:
            return json.loads(output.stdout)
        except ValueError:
            raise GitHubError("La respuesta de GitHub no es válida.") from None

    async def catalog(self):
        account = await self._gh(["api", "--hostname", "github.com", "user"])
        login = account.get("login") if isinstance(account, dict) else None
        if not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login):
            raise GitHubError("No se pudo verificar la identidad activa de gh.")
        repos = []
        # Paginate the authenticated owner's catalog, including private repos.
        # Every response remains bounded; cancellation is handled per page.
        may_have_more = False
        for page in range(1, 101):
            batch = await self._gh(["api", "--hostname", "github.com",
                                    f"user/repos?affiliation=owner&per_page=100&page={page}"])
            if not isinstance(batch, list):
                raise GitHubError("No se pudo leer la lista de repositorios.")
            repos.extend(batch)
            if len(batch) < 100:
                break
        else:
            may_have_more = True
        verified = []
        for item in repos:
            if not isinstance(item, dict):
                continue
            try:
                identity = github_identity(item.get("html_url", ""))
            except (ValueError, TypeError):
                continue
            if identity.lower() != str(item.get("full_name", "")).lower():
                continue
            if identity.split("/", 1)[0].lower() != login.lower():
                continue
            verified.append({"name": identity, "url": "https://github.com/" + identity,
                             "private": bool(item.get("private")), "archived": bool(item.get("archived")),
                             "description": str(item.get("description") or "")[:1000]})
        return {"login": login, "host": "github.com", "verified": True, "checked": utc_now(),
                "repositories": verified, "limit": 10000, "may_have_more": may_have_more}

    async def repository_details(self, repo: str):
        """Bounded, read-only activity. Missing permission is not zero activity.

        Recheck the active account before every refresh; only its own repos are
        admitted. Do not return bodies, authentication data or arbitrary URLs.
        Activity is a recent sample, not an aggregate count or local Git truth.
        """
        repo = github_identity("https://github.com/" + repo)
        account = await self._gh(["api", "--hostname", "github.com", "user"])
        login = account.get("login") if isinstance(account, dict) else None
        if not isinstance(login, str) or login.casefold() != repo.split("/")[0].casefold():
            raise GitHubError("La cuenta activa de gh cambió o no es propietaria de este repositorio. Vuelve a cargar el catálogo.")
        prefix = "repos/" + repo
        metadata = await self._gh(["api", "--hostname", "github.com", prefix])
        if not isinstance(metadata, dict) or str(metadata.get("full_name", "")).casefold() != repo.casefold():
            raise GitHubError("GitHub no devolvió el repositorio seleccionado.")

        def text(value, limit=400):
            return " ".join(str(value or "").split())[:limit]

        def count(value):
            return value if type(value) is int and value >= 0 else None

        report = {"repo": repo, "checked": utc_now(), "description": text(metadata.get("description"), 1000),
                  "private": bool(metadata.get("private")), "archived": bool(metadata.get("archived")),
                  "branch": text(metadata.get("default_branch")), "language": text(metadata.get("language")),
                  "pushed": text(metadata.get("pushed_at")), "stars": count(metadata.get("stargazers_count")),
                  "forks": count(metadata.get("forks_count")), "sections": {}}

        async def section(kind, endpoint):
            try:
                raw = await self._gh(["api", "--hostname", "github.com", prefix + endpoint])
                if kind == "actions":
                    raw = raw.get("workflow_runs") if isinstance(raw, dict) else None
                if not isinstance(raw, list):
                    raise GitHubError("Respuesta de actividad no válida.")
                rows = []
                for item in raw[:30]:
                    if not isinstance(item, dict):
                        continue
                    if kind == "issues" and "pull_request" in item:
                        continue  # GitHub's issues endpoint also includes PRs.
                    if kind in {"pulls", "issues"}:
                        number = count(item.get("number"))
                        if not number:
                            continue
                        rows.append({"number": number, "title": text(item.get("title")),
                                     "author": text((item.get("user") or {}).get("login")) if isinstance(item.get("user"), dict) else "",
                                     "draft": bool(item.get("draft")), "updated": text(item.get("updated_at")),
                                     "url": f"https://github.com/{repo}/{'pull' if kind == 'pulls' else 'issues'}/{number}"})
                    elif kind == "commits":
                        sha = item.get("sha", "")
                        commit = item.get("commit")
                        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40,64}", sha) or not isinstance(commit, dict):
                            continue
                        author = commit.get("author") or {}
                        rows.append({"sha": sha, "title": text(str(commit.get("message") or "").split("\n")[0]),
                                     "author": text(author.get("name")) if isinstance(author, dict) else "",
                                     "updated": text(author.get("date")) if isinstance(author, dict) else "",
                                     "url": f"https://github.com/{repo}/commit/{sha}"})
                    else:
                        run = count(item.get("id"))
                        if not run:
                            continue
                        rows.append({"title": text(item.get("name")), "status": text(item.get("status")),
                                     "conclusion": text(item.get("conclusion")), "branch": text(item.get("head_branch")),
                                     "updated": text(item.get("updated_at")),
                                     "url": f"https://github.com/{repo}/actions/runs/{run}"})
                return kind, {"available": True, "rows": rows, "limited": len(raw) >= 30}
            except GitHubError:
                return kind, {"available": False, "rows": [], "error": "Sin datos: revisa la red o los permisos de gh."}

        sections = await asyncio.gather(
            section("pulls", "/pulls?state=open&sort=updated&direction=desc&per_page=30"),
            section("issues", "/issues?state=open&sort=updated&direction=desc&per_page=30"),
            section("commits", "/commits?per_page=30"),
            section("actions", "/actions/runs?per_page=30"))
        report["sections"] = dict(sections)
        return report


class GitSyncService:
    """No reset, stash, rebase, auto branch switching or repository-wide pull."""

    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self._last = None
        self._previews = {}

    def _env(self):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_TERMINAL_PROMPT="0", GH_HOST="github.com", GH_PROMPT_DISABLED="1")
        return env

    async def _git(self, arguments, *, allow_failure=False, network=False, limit=2_000_000):
        binary = shutil.which("git")
        if not binary:
            raise GitHubError("Git no está instalado.")
        options = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
                   "-c", "submodule.recurse=false", "-c", "gc.auto=0",
                   "-c", "protocol.file.allow=never", "-c", "protocol.ext.allow=never",
                   "-c", "http.followRedirects=false"]
        if network:
            gh = shutil.which("gh")
            if not gh:
                raise GitHubError("gh debe estar disponible para comprobar el remoto.")
            options += ["-c", "credential.helper=", "-c", "credential.helper=!" + shlex.quote(gh) + " auth git-credential"]
        try:
            result = await capture_process([binary, *options, *arguments], cwd=self.folder,
                                           env=self._env(), timeout=60 if network else 20, limit=limit)
        except (OSError, TimeoutError, ValueError):
            raise GitHubError("La operación Git no terminó. Revisa la carpeta, la red y sus permisos.") from None
        if result.returncode and not allow_failure:
            raise GitHubError("Git rechazó la operación. El IDE conserva el trabajo local; consulta la carpeta en el terminal manual.")
        return result

    async def _supported(self):
        top = (await self._git(["rev-parse", "--show-toplevel"])).stdout.decode().strip()
        if Path(top).resolve() != self.folder:
            raise GitHubError("Vincula la raíz del checkout o worktree, no una carpeta interna.")
        await self._no_filters()
        # URL rewriting can silently change the destination of a verified fetch.
        rewrites = await self._git(["config", "--get-regexp", r"^url\..*\.(insteadof|pushinsteadof)$"], allow_failure=True)
        if rewrites.returncode not in {0, 1} or rewrites.stdout:
            raise GitHubError("Hay reglas Git que reescriben URLs. La vista requiere un remoto directo de GitHub.")
        tracked_state = await self._git(["ls-files", "-z", "--", ".isycode-ide", ".isyvm"])
        if tracked_state.stdout:
            raise GitHubError("Este checkout versiona metadatos privados del host. Su sincronización requiere revisión manual.")

    async def _no_filters(self, revision=None):
        # Merely installing LFS registers global drivers for every repository.
        # Check effective attributes instead; check-attr does not run drivers.
        listing = await self._git(["ls-tree", "-r", "-z", "--name-only", revision] if revision
                                  else ["ls-files", "-z"])
        paths = [os.fsdecode(item) for item in listing.stdout.split(b"\0") if item]
        for offset in range(0, len(paths), 100):
            args = ["check-attr", "-z"]
            if revision:
                args += ["--source=" + revision]
            output = await self._git([*args, "filter", "--", *paths[offset:offset + 100]])
            parts = output.stdout.split(b"\0")
            if any(value not in {b"unspecified", b"unset"} for value in parts[2::3]):
                raise GitHubError("Este checkout usa filtros Git personalizados/LFS. Su sincronización requiere soporte adicional; usa el terminal manual.")

    async def inspect(self, *, refresh=False, expected_repo=None):
        await self._supported()
        branch_out = await self._git(["symbolic-ref", "--quiet", "--short", "HEAD"], allow_failure=True)
        branch = branch_out.stdout.decode().strip() if branch_out.returncode == 0 else ""
        head = (await self._git(["rev-parse", "--verify", "HEAD"])).stdout.decode().strip()
        # Host metadata is deliberately separate from source synchronization.
        dirty = await self._git(["status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none",
                                 "--", ".", ":(exclude).isycode-ide", ":(exclude).isyvm"])
        parts = [item for item in dirty.stdout.split(b"\0") if item]
        entries = []
        index = 0
        while index < len(parts):
            entry = parts[index]
            entries.append(entry)
            index += 2 if b"R" in entry[:2] or b"C" in entry[:2] else 1
        staged = sum(item[0:1] not in {b" ", b"?"} for item in entries)
        unstaged = sum(item[1:2] not in {b" ", b"?"} for item in entries)
        untracked = sum(item[:2] == b"??" for item in entries)
        conflicts = any(item[:2] in {b"DD", b"AU", b"UD", b"UA", b"DU", b"AA", b"UU"} for item in entries)
        shallow = (await self._git(["rev-parse", "--is-shallow-repository"])).stdout.strip() == b"true"
        upstream = upstream_ref = remote = remote_branch = repo = target = ""
        if branch:
            remote_out = await self._git(["config", "--get", f"branch.{branch}.remote"], allow_failure=True)
            merge_out = await self._git(["config", "--get", f"branch.{branch}.merge"], allow_failure=True)
            if remote_out.returncode == 0 and merge_out.returncode == 0:
                remote = remote_out.stdout.decode().strip()
                merge = merge_out.stdout.decode().strip()
                if remote == "." or not merge.startswith("refs/heads/") or "\n" in merge:
                    raise GitHubError("El upstream no apunta a una rama remota soportada.")
                remote_branch = merge.removeprefix("refs/heads/")
                upstream_out = await self._git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], allow_failure=True)
                upstream = upstream_out.stdout.decode().strip() if upstream_out.returncode == 0 else ""
                upstream_ref = (await self._git(["for-each-ref", "--format=%(upstream)", "refs/heads/" + branch])).stdout.decode().strip()
                if not upstream_ref.startswith("refs/remotes/"):
                    raise GitHubError("El upstream no tiene una referencia remota soportada.")
                await self._git(["check-ref-format", upstream_ref])
                url = (await self._git(["remote", "get-url", "--", remote])).stdout.decode().strip()
                repo = github_identity(url)
        if not repo:
            # Identity can still be linked on a branch without an upstream.
            origin = await self._git(["remote", "get-url", "origin"], allow_failure=True)
            if origin.returncode == 0:
                repo = github_identity(origin.stdout.decode().strip())
        if expected_repo and repo.lower() != expected_repo.lower():
            raise GitHubError("La carpeta ya no coincide con el repositorio vinculado o no tiene upstream.")
        if refresh:
            self._last = None  # A failed refresh must not leave a 'fresh' count.
            if not repo or not remote_branch:
                raise GitHubError("Selecciona una rama con upstream de GitHub antes de comprobarla.")
            account = await GitHubService()._gh(["api", "--hostname", "github.com", "user"])
            if not isinstance(account, dict) or str(account.get("login", "")).lower() != repo.split("/", 1)[0].lower():
                raise GitHubError("La cuenta activa de gh cambió. Vuelve a verificar la sesión y cargar sus repositorios.")
            # One explicit branch, no prune, force, tags, auto maintenance or FETCH_HEAD merge.
            await self._git(["fetch", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head",
                             "https://github.com/" + repo + ".git", "refs/heads/" + remote_branch + ":" + upstream_ref], network=True)
            # Resolve the remote head directly rather than guessing a tracking ref.
            listing = await self._git(["ls-remote", "--exit-code", "https://github.com/" + repo + ".git",
                                      "refs/heads/" + remote_branch], network=True)
            line = listing.stdout.decode().strip().split("\t")
            if len(line) != 2 or not re.fullmatch(r"[0-9a-f]{40,64}", line[0]):
                raise GitHubError("No se pudo identificar la rama actual de GitHub.")
            target = line[0]
            # A push between fetch and ls-remote may refer to an object not fetched.
            await self._git(["cat-file", "-e", target + "^{commit}"])
            self._last = {"repo": repo.lower(), "branch": branch, "remote_branch": remote_branch,
                          "target": target, "checked": utc_now()}
        elif self._last and self._last["repo"] == repo.lower() and self._last["branch"] == branch and self._last["remote_branch"] == remote_branch:
            target = self._last["target"]
        elif upstream:
            target_out = await self._git(["rev-parse", "--verify", "@{upstream}"], allow_failure=True)
            target = target_out.stdout.decode().strip() if target_out.returncode == 0 else ""
        fresh = bool(self._last and target == self._last["target"] and repo.lower() == self._last["repo"] and branch == self._last["branch"] and remote_branch == self._last["remote_branch"])
        ahead = behind = None
        if target and not shallow:
            counts = (await self._git(["rev-list", "--left-right", "--count", head + "..." + target])).stdout.split()
            ahead, behind = int(counts[0]), int(counts[1])
        state = ("detached" if not branch else "no_upstream" if not remote_branch else "shallow" if shallow
                 else "conflict" if conflicts else "unknown" if ahead is None else "diverged" if ahead and behind
                 else "ahead" if ahead else "behind" if behind else "equal")
        return GitStatus(str(self.folder), repo, branch, upstream, remote, remote_branch, head, target,
                         ahead, behind, len(entries), staged, unstaged, untracked, conflicts, shallow,
                         self._last["checked"] if fresh else None, fresh, state)

    async def link(self, expected_repo):
        status = await self.inspect(expected_repo=expected_repo)
        RepoLinkStore().add(status.repo, str(self.folder))
        return status

    async def preview_pull(self, expected_repo):
        status = await self.inspect(refresh=True, expected_repo=expected_repo)
        if not status.can_update:
            raise GitHubError("Pull requiere una rama solo atrasada, historia completa y carpeta sin cambios locales.")
        await self._no_filters(status.target)
        # Submodule updates are a separate operation, never an implicit recursion.
        for revision in (status.head, status.target):
            tree = await self._git(["ls-tree", "-r", revision])
            if any(line.startswith(b"160000 ") for line in tree.stdout.splitlines()):
                raise GitHubError("Este repositorio contiene submódulos; actualización manual requerida.")
        changes = await self._git(["diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-status", "-z", status.head, status.target])
        parts = [os.fsdecode(x) for x in changes.stdout.split(b"\0") if x]
        files = tuple(zip(parts[::2], parts[1::2]))
        if len(parts) % 2:
            raise GitHubError("No se pudo preparar el manifiesto de actualización.")
        if any(path == ".isycode-ide" or path.startswith(".isycode-ide/") or path == ".isyvm" or path.startswith(".isyvm/") for _, path in files):
            raise GitHubError("El remoto modifica metadatos privados del host. Actualización bloqueada.")
        self._preserve_local_additions(files)
        preview = PullPreview(uuid.uuid4().hex, status, files, utc_now())
        self._previews[preview.id] = preview
        return preview

    def _preserve_local_additions(self, files):
        # Git status excludes ignored data. An incoming addition must never
        # silently replace an existing ignored file, directory or symlink.
        for change, relative in files:
            if change != "A":
                continue
            path = self.folder / relative
            if os.path.lexists(path):
                raise GitHubError("El pull coincide con un archivo local/ignorado: " + relative + ". Conserva ese contenido antes de revisar otra actualización.")
            for parent in path.parents:
                if parent == self.folder:
                    break
                if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                    raise GitHubError("El pull atraviesa contenido local/ignorado: " + relative)

    async def apply_pull(self, preview_id, *, operator_approved=False):
        preview = self._previews.pop(preview_id, None)
        if preview is None or operator_approved is not True:
            raise GitHubError("Revisa y aprueba el manifiesto antes de actualizar.")
        # Serialize IDE updates across processes without modifying the checkout.
        key = hashlib.sha256(str(self.folder).encode()).hexdigest()
        async with async_state_lock(state_home() / "git-sync" / (key + ".lock")), async_state_lock(project_state(self.folder) / "workspace-edit.lock"):
            current = await self.inspect(refresh=True, expected_repo=preview.status.repo)
            if not current.can_update or current.head != preview.status.head or current.target != preview.status.target or current.branch != preview.status.branch:
                raise GitHubError("La base o el remoto cambiaron después del preview. Prepara otra revisión.")
            await self._no_filters(current.target)
            self._preserve_local_additions(preview.files)
            receipt_path = state_home() / "git-sync" / (preview.id + ".json")
            receipt = {"preview": preview.id, "created": utc_now(), "folder": str(self.folder),
                       "before": preview.status.head, "target": preview.status.target,
                       "files": preview.files, "branch": current.branch, "status": "applying"}
            atomic_write(receipt_path, json.dumps(receipt, indent=2) + "\n")
            try:
                await self._git(["merge", "--ff-only", "--no-edit", "--no-overwrite-ignore", preview.status.target])
                final = await self.inspect(expected_repo=preview.status.repo)
            except BaseException:
                # Preserve the transaction and checkout for manual inspection;
                # an interrupted native Git operation is never 'rolled back' by reset.
                receipt.update(status="review_required", finished=utc_now())
                atomic_write(receipt_path, json.dumps(receipt, indent=2) + "\n")
                raise
            receipt.update(after=final.head, finished=utc_now(),
                           status="updated" if final.head == preview.status.target and final.local_changes == 0 else "review_required")
            atomic_write(receipt_path, json.dumps(receipt, indent=2) + "\n")
            return final, receipt

    async def differences(self, status):
        current = await self.inspect(expected_repo=status.repo)
        if current.head != status.head or current.target != status.target:
            raise GitHubError("La comparación cambió. Comprueba el remoto otra vez.")
        if not status.target:
            raise GitHubError("Comprueba una rama con upstream antes de comparar.")
        result = await self._git(["diff", "--no-ext-diff", "--no-textconv", "--no-renames",
                                  status.head, status.target, "--", ".",
                                  ":(exclude).isycode-ide", ":(exclude).isyvm"])
        return result.stdout.decode("utf-8", errors="replace")

    async def incoming(self, status):
        if not status.target or status.behind is None:
            return []
        output = await self._git(["log", "--format=%h %s", "--max-count=20", status.head + ".." + status.target])
        return output.stdout.decode("utf-8", errors="replace").splitlines()
