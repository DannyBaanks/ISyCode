"""Durable effect ledger outside the workspace.

This is not ``safety.Budget``. Every limit below is finite. A missing limit
does not mean unlimited, and a new process, a renamed folder or a clock change
does not open a fresh balance. The model has no action that resets it.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from isycode.workspace_setup import state_root

LEDGER_VERSION = 1
LIMITS_VERSION = 1
MAX_PATHS_PER_OPERATION = 4000
MAX_DELETES_PER_OPERATION = 2000
MAX_CHURN_PER_OPERATION = 32 * 1024 * 1024
MAX_UNIQUE_PATHS = 20000
MAX_DELETE_OPS = 10000
MAX_CHURN_BYTES = 256 * 1024 * 1024
RESET_PHRASE = "reset effect ledger"


class LedgerDenied(Exception):
    """The mutation must not start, or it was rolled back. ``effect_state`` is denied or uncertain."""

    def __init__(self, message: str = "", *, effect_state: str = "denied"):
        super().__init__(message)
        self.effect_state = effect_state


class CrashInjected(Exception):
    """Test seam. Production never raises it."""


@dataclass(frozen=True)
class EffectCost:
    paths: tuple[str, ...]
    deletes: int
    churn_bytes: int

    def __post_init__(self) -> None:
        if self.deletes < 0 or self.churn_bytes < 0:
            raise LedgerDenied("effect cost is negative")
        if any(not _relative_ok(path) for path in self.paths):
            raise LedgerDenied("effect path escapes the workspace")


def workspace_identity(root: Path) -> str:
    """Stable across rename and path alias. A new directory is a new identity."""
    info = root.resolve(strict=True).stat()
    return f"{info.st_dev}-{info.st_ino}"


class EffectLedger:
    def __init__(self, root: Path, *, state_directory: Path | None = None):
        self.root = root.resolve(strict=True)
        self.identity = workspace_identity(self.root)
        base = Path(state_directory) if state_directory is not None else state_root() / "effect-ledger"
        self.directory = base
        self.path = base / f"{self.identity}.json"
        self.lock_path = base / f"{self.identity}.lock"
        self.backup_root = base / "preimages" / self.identity
        self._depth = 0
        self._descriptor: int | None = None

    def exclusive(self):
        """Hold the ledger lock across reserve, backup, apply and commit.

        Another process blocks here. If the holder dies, the kernel drops the
        lock and the next caller reconciles whatever was left behind.
        """
        return _Exclusive(self)

    def status(self) -> dict:
        state = self._locked(lambda current: current)
        return {
            "unique_paths": len(state["unique_paths"]),
            "delete_ops": state["delete_ops"],
            "churn_bytes": state["churn_bytes"],
            "uncertain": state["uncertain"],
            "open": state["reservation"] is not None,
        }

    def reserve(self, cost: EffectCost) -> str:
        def op(state: dict) -> str:
            self._reconcile(state)
            if state["uncertain"]:
                raise LedgerDenied(self._denied_text(state, "a previous effect is uncertain"))
            if state["reservation"] is not None:
                raise LedgerDenied(self._denied_text(state, "a promotion is unfinished"))
            self._check(state, cost)
            reservation_id = "rsv_" + hashlib.sha256(os.urandom(16)).hexdigest()[:16]
            state["reservation"] = {
                "id": reservation_id,
                "state": "PREPARED",
                "paths": list(cost.paths),
                "deletes": cost.deletes,
                "churn_bytes": cost.churn_bytes,
                "plan": [],
                "applied": [],
                "applying": None,
            }
            return reservation_id
        return self._locked(op)

    def store_plan(self, reservation_id: str, plan: list[dict]) -> None:
        def op(state: dict) -> None:
            reservation = self._open(state, reservation_id)
            if reservation["state"] != "PREPARED" or reservation["plan"]:
                raise LedgerDenied("the promotion plan was already stored")
            reservation["plan"] = plan
        self._locked(op)

    def mark_applying(self, reservation_id: str, relative: str) -> None:
        def op(state: dict) -> None:
            reservation = self._open(state, reservation_id)
            reservation["state"] = "APPLYING"
            reservation["applying"] = relative
        self._locked(op)

    def mark_applied(self, reservation_id: str, relative: str) -> None:
        def op(state: dict) -> None:
            reservation = self._open(state, reservation_id)
            if reservation["applying"] != relative:
                raise LedgerDenied("promotion step is out of order")
            reservation["applied"].append(relative)
            reservation["applying"] = None
        self._locked(op)

    def commit(self, reservation_id: str, *, applied_paths: tuple[str, ...],
               deletes: int, churn_bytes: int) -> None:
        def op(state: dict) -> None:
            reservation = self._open(state, reservation_id)
            if reservation["applying"] is not None:
                raise LedgerDenied("a file is still being applied")
            if set(applied_paths) - set(reservation["paths"]):
                raise LedgerDenied("commit names a path that was not reserved")
            if deletes > reservation["deletes"] or churn_bytes > reservation["churn_bytes"]:
                state["uncertain"] = "commit exceeded the reservation"
                state["reservation"] = None
                raise LedgerDenied(self._denied_text(state, "commit exceeded the reservation"))
            self._charge(state, applied_paths, deletes, churn_bytes)
            state["reservation"] = None
        self._locked(op)

    def abort(self, reservation_id: str) -> None:
        def op(state: dict) -> None:
            reservation = self._open(state, reservation_id)
            if reservation["applied"] or reservation["applying"]:
                state["uncertain"] = "aborted after a file changed"
                raise LedgerDenied(self._denied_text(state, "aborted after a file changed"))
            state["reservation"] = None
        self._locked(op)

    def reconcile(self) -> str:
        def op(state: dict) -> str:
            return self._reconcile(state)
        return self._locked(op)

    def user_reset(self, phrase: str) -> None:
        """Clear the ledger. Not an action, not a tool, and the phrase is the whole check."""
        if phrase != RESET_PHRASE:
            raise LedgerDenied("the effect ledger was not reset")

        def op(state: dict) -> None:
            fresh = self._fresh()
            state.clear()
            state.update(fresh)
        self._locked(op)

    def backup_file(self, reservation_id: str, relative: str, payload: bytes) -> None:
        if not _relative_ok(relative) or not _relative_ok(reservation_id):
            raise LedgerDenied("backup path escapes the workspace")
        folder = self.backup_root / reservation_id
        _mkdir_real(self.directory)
        _mkdir_real(self.backup_root)
        _mkdir_real(folder)
        target = folder / relative
        _mkdir_real(target.parent)
        temporary = target.with_name(target.name + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            view = memoryview(payload)
            while view:
                view = view[os.write(descriptor, view):]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, target)
        if os.name == "posix":
            os.chmod(target, 0o600)
        directory = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def read_backup(self, reservation_id: str, relative: str) -> bytes:
        path = self.backup_root / reservation_id / relative
        if not path.is_file() or path.is_symlink():
            raise LedgerDenied("preimage backup is missing")
        return path.read_bytes()

    def _reconcile(self, state: dict) -> str:
        reservation = state["reservation"]
        if not reservation:
            return "IDLE"
        plan = {item["path"]: item for item in reservation.get("plan", [])}
        applied = list(reservation.get("applied", []))
        applying = reservation.get("applying")
        if applying:
            kind = self._classify(reservation["id"], applying, plan.get(applying))
            if kind == "uncertain":
                state["uncertain"] = f"bytes for {applying} match neither the preimage nor the target"
                return "UNCERTAIN"
            if kind == "target":
                applied.append(applying)
            reservation["applying"] = None
            reservation["applied"] = applied
        if applied and len(applied) == len(reservation.get("plan") or []) and not reservation.get("applying"):
            deletes = sum(1 for item in reservation["plan"] if item["path"] in applied and item["kind"] == "delete")
            churn = sum(item["churn"] for item in reservation["plan"] if item["path"] in applied)
            self._charge(state, tuple(applied), deletes, churn)
            state["reservation"] = None
            return "COMMITTED"
        for relative in applied:
            item = plan.get(relative)
            if item is None or self._restore(reservation["id"], relative, item) == "uncertain":
                state["uncertain"] = f"cannot restore {relative} without guessing"
                state["reservation"]["applied"] = applied
                return "UNCERTAIN"
        state["reservation"] = None
        return "ROLLED_BACK"

    def _classify(self, reservation_id: str, relative: str, item: dict | None) -> str:
        if item is None:
            return "uncertain"
        current = _file_sha(self.root / relative)
        if current == item["target"]:
            return "target"
        if current == item["preimage"]:
            return "preimage"
        return "uncertain"

    def _restore(self, reservation_id: str, relative: str, item: dict) -> str:
        destination = self.root / relative
        current = _file_sha(destination)
        if current == item["preimage"]:
            return "preimage"
        if current != item["target"]:
            return "uncertain"
        parent = destination.parent
        if not _parents_are_real(self.root, parent):
            return "uncertain"
        if item["preimage"] is None:
            if destination.is_symlink() or (destination.exists() and not destination.is_file()):
                return "uncertain"
            if destination.is_file():
                destination.unlink()
            return "restored"
        parent.mkdir(parents=True, exist_ok=True)
        temporary = parent / f".isycode-restore-{destination.name}"
        try:
            payload = self.read_backup(reservation_id, relative)
        except LedgerDenied:
            return "uncertain"
        if hashlib.sha256(payload).hexdigest() != item["preimage"]:
            return "uncertain"
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            view = memoryview(payload)
            while view:
                view = view[os.write(descriptor, view):]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, destination)
        return "restored"

    def _check(self, state: dict, cost: EffectCost) -> None:
        if len(cost.paths) > MAX_PATHS_PER_OPERATION:
            raise LedgerDenied(self._denied_text(state, "too many paths in one effect"))
        if cost.deletes > MAX_DELETES_PER_OPERATION:
            raise LedgerDenied(self._denied_text(state, "too many deletes in one effect"))
        if cost.churn_bytes > MAX_CHURN_PER_OPERATION:
            raise LedgerDenied(self._denied_text(state, "too many bytes in one effect"))
        projected_paths = len(set(state["unique_paths"]) | set(cost.paths))
        if projected_paths > MAX_UNIQUE_PATHS:
            raise LedgerDenied(self._denied_text(state, "workspace path limit reached"))
        if state["delete_ops"] + cost.deletes > MAX_DELETE_OPS:
            raise LedgerDenied(self._denied_text(state, "workspace delete limit reached"))
        if state["churn_bytes"] + cost.churn_bytes > MAX_CHURN_BYTES:
            raise LedgerDenied(self._denied_text(state, "workspace byte limit reached"))

    def _charge(self, state: dict, paths: tuple[str, ...], deletes: int, churn_bytes: int) -> None:
        unique = list(dict.fromkeys([*state["unique_paths"], *paths]))
        state["unique_paths"] = unique
        state["delete_ops"] += deletes
        state["churn_bytes"] += churn_bytes

    def _denied_text(self, state: dict, reason: str) -> str:
        return (f"{reason}; ledger has {len(state['unique_paths'])} paths, "
                f"{state['delete_ops']} deletes and {state['churn_bytes']} churn bytes")

    def _open(self, state: dict, reservation_id: str) -> dict:
        reservation = state.get("reservation")
        if not reservation or reservation.get("id") != reservation_id:
            raise LedgerDenied("effect reservation is not open")
        return reservation

    def _fresh(self) -> dict:
        return {
            "version": LEDGER_VERSION,
            "limits_version": LIMITS_VERSION,
            "identity": self.identity,
            "unique_paths": [],
            "delete_ops": 0,
            "churn_bytes": 0,
            "uncertain": None,
            "touched_at": 0,
            "reservation": None,
        }

    def _acquire(self) -> None:
        if self._depth:
            self._depth += 1
            return
        try:
            import fcntl
        except ImportError as exc:  # pragma: no cover - POSIX only
            raise LedgerDenied("effect ledger lock is unavailable") from exc
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.directory.is_symlink():
            raise LedgerDenied("effect ledger directory is a symlink")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.lock_path, flags, 0o600)
        try:
            if os.name == "posix":
                os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except Exception:
            os.close(descriptor)
            raise
        self._descriptor = descriptor
        self._depth = 1

    def _release(self) -> None:
        if self._depth == 0:
            return
        self._depth -= 1
        if self._depth:
            return
        descriptor = self._descriptor
        self._descriptor = None
        if descriptor is None:
            return
        try:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def _locked(self, function):
        self._acquire()
        try:
            state = self._read()
            error: Exception | None = None
            result = None
            try:
                result = function(state)
            except Exception as exc:
                error = exc
            try:
                self._write(state)
            except Exception as exc:
                if error is not None:
                    raise exc from error
                raise
            if error is not None:
                raise error
            return result
        finally:
            self._release()

    def _read(self) -> dict:
        if not self.path.exists():
            return self._fresh()
        if self.path.is_symlink() or not self.path.is_file():
            raise LedgerDenied("effect ledger is not a regular file; mutations are stopped")
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LedgerDenied("effect ledger is unreadable; mutations are stopped") from exc
        if not isinstance(loaded, dict) or loaded.get("version") != LEDGER_VERSION:
            raise LedgerDenied("effect ledger version is unusable; mutations are stopped")
        if loaded.get("identity") != self.identity:
            raise LedgerDenied("effect ledger identity does not match this directory")
        for key in ("unique_paths", "delete_ops", "churn_bytes", "uncertain", "reservation"):
            if key not in loaded:
                raise LedgerDenied("effect ledger is incomplete; mutations are stopped")
        if not isinstance(loaded["unique_paths"], list):
            raise LedgerDenied("effect ledger paths are unusable; mutations are stopped")
        return loaded

    def _write(self, state: dict) -> None:
        payload = json.dumps(state, ensure_ascii=False, sort_keys=True).encode("utf-8")
        temporary = self.path.with_name(self.path.name + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                             | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, self.path)
        if os.name == "posix":
            os.chmod(self.path, 0o600)
        directory = os.open(self.directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


class _Exclusive:
    def __init__(self, ledger: EffectLedger):
        self.ledger = ledger

    def __enter__(self) -> EffectLedger:
        self.ledger._acquire()
        return self.ledger

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.ledger._release()
        return False


def _relative_ok(relative: str) -> bool:
    if not isinstance(relative, str) or not relative or relative.startswith(("/", "\\")):
        return False
    if "\\" in relative or "\0" in relative:
        return False
    parts = Path(relative).parts
    return bool(parts) and all(part not in {"", ".", ".."} and "/" not in part for part in parts)


def _parents_are_real(root: Path, parent: Path) -> bool:
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


def _mkdir_real(path: Path) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise LedgerDenied("effect ledger directory is a symlink")
        return
    _mkdir_real(path.parent)
    path.mkdir(mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise LedgerDenied("effect ledger directory is a symlink")


def _file_sha(path: Path) -> str | None:
    try:
        if not path.exists() or path.is_symlink() or not path.is_file():
            if path.exists():
                return "not-a-file"
            return None
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return "unreadable"
    return digest.hexdigest()


__all__ = [
    "MAX_CHURN_BYTES", "MAX_CHURN_PER_OPERATION", "MAX_DELETE_OPS", "MAX_DELETES_PER_OPERATION",
    "MAX_PATHS_PER_OPERATION", "MAX_UNIQUE_PATHS", "RESET_PHRASE", "CrashInjected", "EffectCost",
    "EffectLedger", "LedgerDenied", "workspace_identity",
]
