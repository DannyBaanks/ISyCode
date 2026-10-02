"""Independent staging for one workspace mutation.

Bubblewrap 0.9.0 has no overlay mount, and a user-namespace overlay was not
available on this host. The backend is a byte copy. Hardlinks are not shared
with the original, and promotion is a later step: until it runs, the user
tree stays as it was. There is no unsandboxed fallback.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from isycode.action_runtime import WorkspaceReadSystembility

MAX_STAGE_BYTES = 512 * 1024 * 1024
FREE_MARGIN_BYTES = 64 * 1024 * 1024


class StagingError(OSError):
    """The workspace cannot be staged. Nothing was run on the host."""


@dataclass
class Staging:
    original: Path
    root: Path
    baseline: dict[str, tuple]


def spill_bytes(payload: bytes) -> Path:
    """Store approved bytes outside the workspace, before any user-file replace."""
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("staged bytes must be a byte string")
    folder = Path(tempfile.mkdtemp(prefix="isycode-spill-"))
    target = folder / "bytes"
    target.write_bytes(payload)
    return target


def remove_spill(path: Path) -> None:
    folder = path.parent
    if folder.name.startswith("isycode-spill-"):
        shutil.rmtree(folder, ignore_errors=True)


def prepare_staging(original: Path) -> Staging:
    """Copy ``original`` to a new directory outside it. The original is not mounted writable."""
    source = original.resolve(strict=True)
    size = _tree_bytes(source)
    if size > MAX_STAGE_BYTES:
        raise StagingError("workspace is larger than the staging budget; command was not run")
    usage = shutil.disk_usage(tempfile.gettempdir())
    if usage.free < size * 2 + FREE_MARGIN_BYTES:
        raise StagingError("not enough free space to stage the workspace; command was not run")
    destination = Path(tempfile.mkdtemp(prefix="isycode-stage-"))
    try:
        destination.relative_to(source)
    except ValueError:
        pass
    else:
        shutil.rmtree(destination, ignore_errors=True)
        raise StagingError("staging directory must sit outside the workspace")
    try:
        _copy_tree(source, destination)
    except OSError as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise StagingError("workspace could not be copied into staging; command was not run") from exc
    return Staging(source, destination, _index(source))


def cleanup_staging(staging: Staging) -> None:
    if staging.root.name.startswith("isycode-stage-"):
        shutil.rmtree(staging.root, ignore_errors=True)


def measure_changes(staging: Staging) -> list[dict[str, str]]:
    """Paths whose staged bytes differ from the copy-time original."""
    current = _index(staging.root)
    changes: list[dict[str, str]] = []
    for relative in sorted(set(staging.baseline) | set(current)):
        if staging.baseline.get(relative) == current.get(relative):
            continue
        if relative not in current:
            kind = "delete"
        elif relative not in staging.baseline:
            kind = "add"
        else:
            kind = "modify"
        changes.append({"path": relative, "kind": kind})
    return changes


def promote_changes(staging: Staging, changes: list[dict[str, str]]) -> tuple[list[str], list[str]]:
    """Apply a measured diff. Protected paths and human conflicts are left untouched."""
    applied: list[str] = []
    refused: list[str] = []
    live = _index(staging.original)
    staged_now = _index(staging.root)
    ordered = sorted(changes, key=lambda item: (item.get("kind") != "delete", item.get("path", "")))
    for change in ordered:
        relative = str(change.get("path", ""))
        kind = str(change.get("kind", ""))
        if _refused(relative, staging.baseline.get(relative), staged_now.get(relative)):
            refused.append(relative)
            continue
        if live.get(relative) != staging.baseline.get(relative):
            refused.append(relative)
            continue
        try:
            _apply(staging, relative, kind)
        except OSError:
            refused.append(relative)
            continue
        applied.append(relative)
    _remove_empty_deleted_directories(staging, changes, refused)
    return applied, refused


def _refused(relative: str, before: tuple | None, after: tuple | None) -> bool:
    if _protected(relative):
        return True
    if before is not None and before[0] == "symlink":
        return True
    if after is not None and after[0] == "symlink":
        return True
    return False


def _protected(relative: str) -> bool:
    parts = Path(relative).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return True
    if parts[0] in {".git", ".isyroot", ".isycode"}:
        return True
    return any(WorkspaceReadSystembility.is_sensitive_name(part) for part in parts)


def _apply(staging: Staging, relative: str, kind: str) -> None:
    destination = _lexical(staging.original, relative)
    source = _lexical(staging.root, relative)
    if destination is None or (kind != "delete" and source is None):
        raise OSError("path escapes the workspace")
    if kind == "delete":
        if destination.is_file() and not destination.is_symlink():
            destination.unlink()
        return
    if source is None or not source.is_file() or source.is_symlink():
        raise OSError("staged path is not a regular file")
    parent = destination.parent
    if not _parents_are_real(staging.original, parent):
        raise OSError("a parent path is a symlink")
    parent.mkdir(parents=True, exist_ok=True)
    temporary = parent / f".isycode-promote-{destination.name}"
    shutil.copy2(source, temporary, follow_symlinks=False)
    os.replace(temporary, destination)


def _parents_are_real(root: Path, parent: Path) -> bool:
    """Walk the lexical path. A resolved path would follow a swapped-in symlink."""
    try:
        relative = parent.relative_to(root)
    except ValueError:
        return False
    walked = root
    for part in relative.parts:
        walked = walked / part
        if walked.is_symlink():
            return False
        if walked.exists() and not walked.is_dir():
            return False
    return True


def _remove_empty_deleted_directories(staging: Staging, changes: list[dict[str, str]],
                                      refused: list[str]) -> None:
    refused_set = set(refused)
    directories = sorted(
        (item["path"] for item in changes
         if item.get("kind") == "delete" and item.get("path") not in refused_set
         and staging.baseline.get(item["path"], (None,))[0] == "dir"),
        key=len, reverse=True)
    for relative in directories:
        if _protected(relative):
            continue
        target = _lexical(staging.original, relative)
        try:
            if target is not None and target.is_dir() and not any(target.iterdir()):
                target.rmdir()
        except OSError:
            continue


def _lexical(root: Path, relative: str) -> Path | None:
    parts = Path(relative).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    return root / relative


def _tree_bytes(root: Path) -> int:
    total = 0
    for path in _walk_files(root):
        try:
            total += path.stat(follow_symlinks=False).st_size
        except OSError:
            continue
        if total > MAX_STAGE_BYTES:
            return total
    return total


def _copy_tree(source: Path, destination: Path) -> None:
    for entry in os.scandir(source):
        target = destination / entry.name
        if entry.is_symlink():
            os.symlink(os.readlink(entry.path), target)
            continue
        if entry.is_dir(follow_symlinks=False):
            target.mkdir()
            _copy_tree(Path(entry.path), target)
            continue
        if entry.is_file(follow_symlinks=False):
            shutil.copy2(entry.path, target, follow_symlinks=False)


def _walk_files(root: Path):
    for entry in os.scandir(root):
        if entry.is_symlink():
            continue
        if entry.is_dir(follow_symlinks=False):
            yield from _walk_files(Path(entry.path))
        elif entry.is_file(follow_symlinks=False):
            yield Path(entry.path)


def _index(root: Path) -> dict[str, tuple]:
    found: dict[str, tuple] = {}

    def walk(current: Path) -> None:
        for entry in os.scandir(current):
            relative = Path(entry.path).relative_to(root).as_posix()
            if entry.is_symlink():
                found[relative] = ("symlink", os.readlink(entry.path))
                continue
            if entry.is_dir(follow_symlinks=False):
                found[relative] = ("dir",)
                walk(Path(entry.path))
                continue
            if entry.is_file(follow_symlinks=False):
                found[relative] = ("file", _sha(Path(entry.path)),
                                   stat.S_IMODE(entry.stat(follow_symlinks=False).st_mode))

    walk(root)
    return found


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
