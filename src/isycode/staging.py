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


class PromotionCancelled(Exception):
    """Promotion stopped at a checkpoint. Later files are not applied."""


@dataclass
class Staging:
    original: Path
    root: Path
    baseline: dict[str, tuple]
    scope: str = "."


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


def prepare_staging(original: Path, *, scope: str = ".") -> Staging:
    """Copy ``original`` to a new directory outside it. The original is not mounted writable."""
    source = original.resolve(strict=True)
    if (Path(scope).is_absolute() or ".." in Path(scope).parts
            or not _parents_are_real(source, source / scope)):
        raise StagingError("staging scope must be a real folder inside the workspace")
    selected = source / scope
    if not selected.is_dir() or selected.is_symlink():
        raise StagingError("staging scope is not an existing folder")
    size = _tree_bytes(selected)
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
        target = destination / scope
        target.mkdir(parents=True, exist_ok=True)
        _copy_tree(selected, target)
    except OSError as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise StagingError("workspace could not be copied into staging; command was not run") from exc
    return Staging(source, destination, _index(destination), scope)


def cleanup_staging(staging: Staging) -> None:
    if staging.root.name.startswith("isycode-stage-"):
        shutil.rmtree(staging.root, ignore_errors=True)


def measure_changes(staging: Staging) -> list[dict[str, str]]:
    """Paths whose staged bytes differ from the copy-time original."""
    current = _index(staging.root)
    changes: list[dict[str, str]] = []
    for relative in sorted(set(staging.baseline) | set(current)):
        if staging.scope != "." and not relative.startswith(staging.scope + "/"):
            continue
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
    live = _scoped_index(staging.original, staging.scope)
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


def promote_accounted(staging: Staging, changes: list[dict[str, str]], *,
                      ledger=None, crash_at: str | None = None,
                      operation_id: str | None = None, operations=None,
                      interrupt=None) -> tuple[list[str], list[str], dict]:
    """Reserve a finite effect, back up preimages, then promote. A crash rolls back.

    Directory entries are not part of the reservation. Empty directories are
    removed only after the ledger commit, so a crash before that commit still
    has the files to restore. ``crash_at`` is a test seam. ``interrupt`` is
    the cancel seam: it is called at the same steps and may raise
    ``PromotionCancelled``. The same ``operation_id`` is not applied twice.
    """
    from isycode.effect_ledger import CrashInjected, EffectCost, EffectLedger, LedgerDenied

    if operation_id is not None and operations is not None:
        replayed = _replay_operation(operations, operation_id, ledger, staging)
        if replayed is not None:
            return replayed

    live = _scoped_index(staging.original, staging.scope)
    staged_now = _index(staging.root)
    refused: list[str] = []
    eligible: list[tuple[str, str, tuple | None, tuple | None]] = []
    ordered = sorted(changes, key=lambda item: (item.get("kind") != "delete", item.get("path", "")))
    for change in ordered:
        relative = str(change.get("path", ""))
        kind = str(change.get("kind", ""))
        before = staging.baseline.get(relative)
        after = staged_now.get(relative)
        if _refused(relative, before, after) or live.get(relative) != before:
            refused.append(relative)
            continue
        if before is not None and before[0] == "dir":
            if _protected(relative):
                refused.append(relative)
            continue
        if kind not in {"add", "modify", "delete"}:
            refused.append(relative)
            continue
        if kind == "add" and (after is None or after[0] != "file"):
            refused.append(relative)
            continue
        if kind != "add" and (before is None or before[0] != "file"):
            refused.append(relative)
            continue
        eligible.append((relative, kind, before, after))
    if not eligible:
        _remove_empty_deleted_directories(staging, changes, refused)
        return [], refused, {"state": "idle"}

    plan: list[dict] = []
    churn = 0
    for relative, kind, before, after in eligible:
        preimage = before[1] if before is not None and before[0] == "file" else None
        target = after[1] if after is not None and after[0] == "file" else None
        if kind == "delete":
            file_churn = _nbytes(staging.original, relative)
        elif kind == "add":
            file_churn = _nbytes(staging.root, relative)
        else:
            file_churn = _nbytes(staging.original, relative) + _nbytes(staging.root, relative)
        churn += file_churn
        plan.append({"path": relative, "kind": kind, "preimage": preimage,
                     "target": target, "churn": file_churn,
                     "preimage_mode": None if before is None else before[2],
                     "target_mode": None if after is None else after[2]})
    book = ledger or EffectLedger(staging.original)
    _crash(crash_at, "before-reserve")
    with book.exclusive():
        result = _promote_reserved(book, staging, changes, refused, plan, churn, crash_at,
                                   operation_id, operations, interrupt)
    if result[2].get("state") == "committed":
        _remove_empty_deleted_directories(staging, changes, refused)
    return result


def _replay_operation(operations, operation_id: str, ledger, staging: Staging):
    """Return the one recorded effect, or raise when the response was lost."""
    from isycode.effect_ledger import EffectLedger, LedgerDenied

    try:
        existing = operations.lookup(operation_id)
    except Exception as exc:
        raise LedgerDenied("promotion is uncertain; the operation journal is unreadable",
                           effect_state="uncertain") from exc
    if existing is None:
        return None
    if existing.phase == "receipt":
        return list(existing.applied), list(existing.refused), {"state": "committed", "reconciled": True}
    if existing.phase not in {"effected", "uncertain"}:
        return None
    book = ledger or EffectLedger(staging.original)
    try:
        outcome = book.reconcile()
    except LedgerDenied:
        outcome = "UNCERTAIN"
    if outcome == "COMMITTED":
        operations.mark_receipt(operation_id, result="committed",
                                applied=existing.applied, refused=existing.refused)
        return list(existing.applied), list(existing.refused), {"state": "committed", "reconciled": True}
    if existing.phase != "uncertain":
        operations.mark_uncertain(operation_id, "promotion response was lost")
    info = book.status()
    raise LedgerDenied(
        "promotion is uncertain; "
        f"ledger has {info['unique_paths']} paths, {info['delete_ops']} deletes "
        f"and {info['churn_bytes']} churn bytes",
        effect_state="uncertain")


def _promote_reserved(book, staging: Staging, changes: list[dict[str, str]], refused: list[str],
                      plan: list[dict], churn: int, crash_at: str | None,
                      operation_id: str | None = None, operations=None, interrupt=None):
    from isycode.effect_ledger import CrashInjected, EffectCost, LedgerDenied

    reservation = book.reserve(EffectCost(tuple(item["path"] for item in plan),
                                          sum(item["kind"] == "delete" for item in plan), churn))
    _checkpoint(crash_at, interrupt, "after-reserve")
    started = False
    committed = False
    applied: list[str] = []
    try:
        for item in plan:
            if item["preimage"] is None:
                continue
            source = _lexical(staging.original, item["path"])
            if source is None or not source.is_file() or source.is_symlink():
                raise LedgerDenied("preimage disappeared before backup")
            payload = source.read_bytes()
            if hashlib.sha256(payload).hexdigest() != item["preimage"]:
                raise LedgerDenied("preimage changed before backup")
            book.backup_file(reservation, item["path"], payload)
        _checkpoint(crash_at, interrupt, "after-backup")
        book.store_plan(reservation, plan)
        _checkpoint(crash_at, interrupt, "after-plan")
        for index, item in enumerate(plan):
            _checkpoint(crash_at, interrupt, f"before-apply:{index}")
            if index == 0 and operation_id is not None and operations is not None:
                record, claimed = operations.claim_effect(
                    operation_id, kind="promote",
                    applied=[entry["path"] for entry in plan], refused=list(refused))
                if not claimed:
                    if record.phase == "receipt":
                        try:
                            book.abort(reservation)
                        except LedgerDenied:
                            pass
                        return list(record.applied), list(record.refused), {
                            "state": "committed", "reconciled": True}
                    raise LedgerDenied("promotion is uncertain; reconcile before repeating",
                                       effect_state="uncertain")
            started = True
            book.mark_applying(reservation, item["path"])
            _checkpoint(crash_at, interrupt, f"after-mark-applying:{index}")
            _apply(staging, item["path"], item["kind"])
            _checkpoint(crash_at, interrupt, f"after-apply:{index}")
            book.mark_applied(reservation, item["path"])
            applied.append(item["path"])
            _checkpoint(crash_at, interrupt, f"after-mark-applied:{index}")
        _checkpoint(crash_at, interrupt, "before-commit")
        book.commit(reservation, applied_paths=tuple(applied),
                    deletes=sum(item["kind"] == "delete" for item in plan), churn_bytes=churn)
        committed = True
        if operation_id is not None and operations is not None:
            operations.mark_receipt(operation_id, result="committed",
                                    applied=applied, refused=list(refused))
        _checkpoint(crash_at, interrupt, "after-commit")
    except PromotionCancelled:
        if not committed and started:
            try:
                outcome = book.reconcile()
            except LedgerDenied:
                outcome = "UNCERTAIN"
            if operation_id is not None and operations is not None:
                if outcome == "COMMITTED":
                    operations.mark_receipt(operation_id, result="committed",
                                            applied=applied, refused=list(refused))
                else:
                    operations.mark_uncertain(operation_id, "cancelled during promotion")
        elif not committed:
            try:
                book.abort(reservation)
            except LedgerDenied:
                pass
        raise
    except CrashInjected:
        raise
    except (LedgerDenied, OSError) as exc:
        if not committed and started:
            outcome = book.reconcile()
            if outcome == "COMMITTED":
                return applied, refused, {"state": "committed"}
            if outcome == "UNCERTAIN":
                info = book.status()
                raise LedgerDenied(
                    "promotion is uncertain; "
                    f"ledger has {info['unique_paths']} paths, {info['delete_ops']} deletes "
                    f"and {info['churn_bytes']} churn bytes",
                    effect_state="uncertain") from exc
        elif not committed:
            try:
                book.abort(reservation)
            except LedgerDenied:
                pass
        message = str(exc).strip() or type(exc).__name__
        raise LedgerDenied(f"promotion stopped; the workspace was not changed ({message[:200]})") from exc
    return applied, refused, {"state": "committed"}


def _crash(crash_at: str | None, step: str) -> None:
    if crash_at == step:
        from isycode.effect_ledger import CrashInjected
        raise CrashInjected(step)


def _checkpoint(crash_at: str | None, interrupt, step: str) -> None:
    _crash(crash_at, step)
    if interrupt is not None:
        interrupt(step)


def _nbytes(root: Path, relative: str) -> int:
    from isycode.effect_ledger import LedgerDenied
    path = _lexical(root, relative)
    if path is None:
        raise LedgerDenied("effect path escapes the workspace")
    try:
        info = path.lstat()
    except OSError as exc:
        raise LedgerDenied("effect path cannot be measured") from exc
    if not stat.S_ISREG(info.st_mode):
        raise LedgerDenied("effect path is not a regular file")
    return info.st_size


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
    from isycode.effect_fs import apply_file, read_file

    if staging.scope != "." and not relative.startswith(staging.scope + "/"):
        raise OSError("effect path is outside the selected staging scope")
    before = staging.baseline.get(relative)
    if _protected(relative) or (before is not None and before[0] != "file"):
        raise OSError("effect path is protected or not a regular file")
    after = None if kind == "delete" else read_file(staging.root, relative)
    if kind != "delete" and after is None:
        raise OSError("staged path is not a regular file")
    apply_file(staging.original, relative, None if after is None else after[0],
               expected=None if before is None else before[1],
               mode=0o644 if after is None else after[1],
               expected_mode=None if before is None else before[2])


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


def _scoped_index(root: Path, scope: str) -> dict[str, tuple]:
    if scope == ".":
        return _index(root)
    if not _parents_are_real(root, root / scope):
        raise StagingError("selected folder changed before promotion")
    return {scope + "/" + path: value for path, value in _index(root / scope).items()}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
