"""Git worktree manager modeled after Orca's worktree panel.

Conservative by construction: listing never mutates, and ``remove_worktree``
refuses to delete a checkout whose preflight finds uncommitted, untracked or
unmerged work unless the caller explicitly passes ``force=True``.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from core.processes import ProcessFailure, capture_process


class WorktreeError(ValueError):
    """Raised when Git refuses an operation or preflight blocks removal."""


@dataclass(frozen=True)
class Worktree:
    """One record of ``git worktree list --porcelain``."""

    path: str
    head: str = ""
    branch: str | None = None  # short name (``main``), None when detached/bare
    bare: bool = False
    detached: bool = False
    locked: bool = False
    lock_reason: str = ""
    prunable: bool = False
    prunable_reason: str = ""

    @property
    def name(self) -> str:
        """Human label: branch when available, else the directory basename."""
        return self.branch or Path(self.path).name or self.path

    def to_dict(self) -> dict:
        return {
            "path": self.path, "head": self.head, "branch": self.branch, "name": self.name,
            "bare": self.bare, "detached": self.detached, "locked": self.locked,
            "lock_reason": self.lock_reason, "prunable": self.prunable,
            "prunable_reason": self.prunable_reason,
        }


@dataclass(frozen=True)
class PreflightReport:
    """Result of inspecting a worktree before removal."""

    path: str
    dirty: tuple[str, ...] = ()        # modified/staged/conflicted paths
    untracked: tuple[str, ...] = ()    # untracked files that would be lost
    ahead: int = 0                     # commits not reachable from any other branch
    unmerged_branches: tuple[str, ...] = ()  # branches whose tips only this worktree holds
    locked: bool = False
    lock_reason: str = ""
    exists: bool = True

    @property
    def safe(self) -> bool:
        return not (self.dirty or self.untracked or self.ahead or self.unmerged_branches)

    @property
    def blocking(self) -> bool:
        return self.locked

    def warnings(self) -> list[str]:
        """Ordered, human-readable reasons why removal is risky."""
        out: list[str] = []
        if not self.exists:
            return out
        if self.dirty:
            out.append(f"{len(self.dirty)} cambio(s) sin commitear: {', '.join(self.dirty[:5])}"
                       + (" …" if len(self.dirty) > 5 else ""))
        if self.untracked:
            out.append(f"{len(self.untracked)} archivo(s) sin seguimiento: {', '.join(self.untracked[:5])}"
                       + (" …" if len(self.untracked) > 5 else ""))
        if self.ahead:
            out.append(f"{self.ahead} commit(s) no integrados en ninguna otra rama")
        if self.unmerged_branches:
            out.append("rama(s) con commits exclusivos: " + ", ".join(self.unmerged_branches))
        return out


_REF_HEADS = re.compile(r"^refs/heads/(.+)$")


def parse_worktree_list(text: str) -> list[Worktree]:
    """Parse ``git worktree list --porcelain`` into :class:`Worktree` records.

    Grammar (one blank-line separated record per worktree)::

        worktree <path>
        HEAD <sha>
        branch refs/heads/<name>
        bare
        detached
        locked [reason]
        prunable [reason]
    """
    records: list[Worktree] = []
    current: dict | None = None

    def flush():
        nonlocal current
        if current is not None:
            records.append(Worktree(
                path=current.get("path", ""),
                head=current.get("head", ""),
                branch=current.get("branch"),
                bare=bool(current.get("bare")),
                detached=bool(current.get("detached")),
                locked=bool(current.get("locked")),
                lock_reason=current.get("lock_reason", ""),
                prunable=bool(current.get("prunable")),
                prunable_reason=current.get("prunable_reason", ""),
            ))
        current = None

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line.strip():
            flush()
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            flush()
            current = {"path": value}
        elif current is None:
            continue  # stray line before any record; ignore defensively
        elif key == "HEAD":
            current["head"] = value
        elif key == "branch":
            match = _REF_HEADS.match(value)
            current["branch"] = match.group(1) if match else value
        elif key == "bare":
            current["bare"] = True
        elif key == "detached":
            current["detached"] = True
        elif key == "locked":
            current["locked"] = True
            current["lock_reason"] = value
        elif key == "prunable":
            current["prunable"] = True
            current["prunable_reason"] = value
    flush()
    return records


class WorktreeManager:
    """Async, bounded wrapper around ``git worktree`` for one repository."""

    def __init__(self, repo: str | Path):
        self.repo = Path(repo).resolve()

    # --- process plumbing -------------------------------------------------

    def _env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
        return env

    async def _git(self, args: list[str], *, cwd: Path | None = None, allow_failure: bool = False,
                   timeout: float = 20) -> str:
        binary = shutil.which("git")
        if not binary:
            raise WorktreeError("Git no está instalado.")
        options = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "gc.auto=0"]
        try:
            result = await capture_process([binary, *options, *args], cwd=cwd or self.repo,
                                           env=self._env(), timeout=timeout)
        except TimeoutError:
            raise WorktreeError("La operación Git no terminó a tiempo. Revisa el tamaño del repositorio.") from None
        except ProcessFailure as exc:
            raise WorktreeError(f"Git produjo una salida excesiva ({exc}).") from None
        except (OSError, ValueError):
            raise WorktreeError("No se pudo ejecutar Git. Revisa la carpeta y sus permisos.") from None
        if result.returncode and not allow_failure:
            message = result.stderr.decode(errors="replace").strip().splitlines()
            raise WorktreeError(message[0] if message else "Git rechazó la operación de worktree.")
        return result.stdout.decode(errors="replace")

    async def _top_level(self) -> Path:
        top = (await self._git(["rev-parse", "--show-toplevel"], allow_failure=True)).strip()
        if not top:
            raise WorktreeError(f"{self.repo} no es un repositorio Git (ni está dentro de uno).")
        return Path(top).resolve()

    # --- listing ------------------------------------------------------------

    async def list_worktrees(self) -> list[Worktree]:
        """All worktrees (main checkout first) of the repository containing ``repo``."""
        await self._top_level()
        return parse_worktree_list(await self._git(["worktree", "list", "--porcelain"]))

    def list_worktrees_sync(self) -> list[Worktree]:
        return asyncio.run(self.list_worktrees())

    # --- create -------------------------------------------------------------

    async def add_worktree(self, path: str | Path, branch: str, *, create_branch: bool = True,
                           start_point: str | None = None) -> Worktree:
        """Add a worktree at ``path`` for ``branch``.

        ``create_branch=True`` passes ``-b`` so a missing branch is created from
        HEAD (or ``start_point``); ``False`` requires the branch to exist already.
        """
        path = Path(path).expanduser()
        if not path.is_absolute():
            path = self.repo.parent / path
        args = ["worktree", "add"]
        if create_branch:
            args += ["-b", branch]
        args.append(str(path))
        if create_branch:
            if start_point:
                args.append(start_point)
        else:
            args.append(branch)
        await self._git(args)
        for record in await self.list_worktrees():
            if Path(record.path).resolve() == path.resolve():
                return record
        return Worktree(path=str(path), branch=branch)

    # --- preflight ----------------------------------------------------------

    async def preflight_remove(self, worktree_path: str | Path) -> PreflightReport:
        """Inspect ``worktree_path`` and report everything that removal would destroy."""
        target = Path(worktree_path).expanduser()
        report = PreflightReport(path=str(target))
        if not target.exists():
            return PreflightReport(path=str(target), exists=False)
        records = await self.list_worktrees()
        record = next((r for r in records if Path(r.path).resolve() == target.resolve()), None)
        if record is None:
            raise WorktreeError(f"Git no reconoce {target} como worktree de {self.repo}.")
        if record.locked:
            report = PreflightReport(path=str(target), locked=True, lock_reason=record.lock_reason)
            return report
        if record.bare or record.detached:
            # Nothing to merge-check against; still surface dirty state below.
            pass
        status = await self._git(["status", "--porcelain=v1", "-z", "--untracked-files=all"],
                                 cwd=target, allow_failure=True)
        # ``-z`` emits ``XY<space>path`` records separated by NUL; renames and copies
        # (``R``/``C``) carry a second NUL-separated token with the original path, which
        # must be consumed or it would be mis-read as a record of its own.
        dirty: list[str] = []
        untracked: list[str] = []
        tokens = [t for t in status.split("\0") if t]
        index = 0
        while index < len(tokens):
            entry = tokens[index]
            index += 1
            code, name = entry[:2], entry[3:]
            if "R" in code or "C" in code:
                index += 1  # the source path token that follows a rename/copy
            if code == "??":
                untracked.append(name)
            elif code.strip(" !"):
                dirty.append(name)
        ahead = 0
        unmerged: tuple[str, ...] = ()
        if record.branch:
            ahead = await self._unmerged_count(record.branch)
        return PreflightReport(
            path=str(target), dirty=tuple(dirty), untracked=tuple(untracked), ahead=ahead,
            unmerged_branches=unmerged, locked=False,
        )

    async def _unmerged_count(self, branch: str) -> int:
        """Commits on ``branch`` reachable from no other local branch or remote."""
        refs = await self._git(["for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes"])
        others = [ref for ref in refs.split() if ref != f"refs/heads/{branch}"]
        if not others:
            base = await self._git(["rev-parse", branch], allow_failure=True)
            return 0 if not base.strip() else await self._count_commits([branch])
        out = await self._git(["rev-list", "--count", branch, "--not", *others], allow_failure=True)
        try:
            return int(out.strip() or 0)
        except ValueError:
            return 0

    async def _count_commits(self, ranges: list[str]) -> int:
        out = await self._git(["rev-list", "--count", *ranges], allow_failure=True)
        try:
            return int(out.strip() or 0)
        except ValueError:
            return 0

    # --- remove -------------------------------------------------------------

    async def remove_worktree(self, worktree_path: str | Path, *, force: bool = False) -> PreflightReport:
        """Remove a worktree after preflight; refuse when at-risk unless ``force``.

        Returns the preflight report that gated the removal.
        """
        report = await self.preflight_remove(worktree_path)
        if not report.exists:
            raise WorktreeError(f"El worktree {report.path} ya no existe.")
        if report.locked:
            raise WorktreeError(
                "El worktree está bloqueado" + (f" ({report.lock_reason})" if report.lock_reason else "") +
                ". Desbloquéalo antes de eliminarlo.")
        if not report.safe and not force:
            raise WorktreeError("Se conservó el worktree: " + " · ".join(report.warnings()))
        # ``git worktree remove`` refuses dirty trees unless forced; ``--force`` is passed only
        # when the caller explicitly accepted the preflight risk.
        await self._git(["worktree", "remove", *(["--force"] if force and not report.safe else []), report.path])
        return report


# ---------------------------------------------------------------------------
# Module-level synchronous API (the contract the rest of the IDE wires against).
# Each call owns a fresh event loop; prefer ``WorktreeManager`` from async code.
# ---------------------------------------------------------------------------

def list_worktrees(repo: str | Path) -> list[Worktree]:
    """All worktrees of ``repo`` (main checkout first). Raises :class:`WorktreeError` if not a repo."""
    return asyncio.run(WorktreeManager(repo).list_worktrees())


def add_worktree(repo: str | Path, path: str | Path, branch: str, create_branch: bool = True) -> Worktree:
    """Add a worktree at ``path`` for ``branch``; ``-b`` creates the branch when ``create_branch``."""
    return asyncio.run(WorktreeManager(repo).add_worktree(path, branch, create_branch=create_branch))


def preflight_remove(worktree_path: str | Path) -> PreflightReport:
    """Inspect ``worktree_path`` (any path inside a Git checkout) and report what removal would destroy.

    Never mutates anything. ``report.safe`` is True only when nothing is modified, untracked or
    unmerged; ``report.blocking`` is True for locked worktrees.
    """
    return asyncio.run(WorktreeManager(worktree_path).preflight_remove(worktree_path))


def remove_worktree(repo: str | Path, worktree_path: str | Path, force: bool = False) -> PreflightReport:
    """Remove ``worktree_path`` after preflight; refuses at-risk trees unless ``force``.

    Returns the :class:`PreflightReport` that gated the removal.
    """
    return asyncio.run(WorktreeManager(repo).remove_worktree(worktree_path, force=force))


__all__ = ["Worktree", "WorktreeManager", "WorktreeError", "PreflightReport", "parse_worktree_list",
           "list_worktrees", "add_worktree", "preflight_remove", "remove_worktree"]
