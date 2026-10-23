"""What one Flow turn changed, recorded before each change so the turn can be undone.

The journal lives in private app state, outside the checkout. The first time a
turn touches a path it stores the exact preimage (bytes and permission bits, or
"absent"); every later change of that path only updates the hash the turn left.
Undo is not done here: ``WorkspaceWriteOwner`` restores through Authority,
IsySentinel, the effect ledger and the journal (``workspace.turn.undo``).

A full journal refuses the capture. Callers then keep the change from landing
quietly: a command's changes stay staged and nothing is promoted.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import threading
import time
from pathlib import Path
from typing import Any

from isycode.workspace_setup import state_root

TURN_ID = re.compile(r"turn_[0-9]{13}_[0-9a-f]{8}")
SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_TURN_PREIMAGE_BYTES = 256 * 1024 * 1024
MAX_TURN_PATHS = 4000
MAX_KEPT_TURNS = 20

_LOCK = threading.Lock()
_ACTIVE: dict[str, "TurnJournal"] = {}


class TurnJournalFull(ValueError):
    """The turn cannot record another preimage within its budget; nothing changes."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _root_key(root: Path) -> str:
    return str(Path(root).resolve())


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise OSError("turn journal directory is unsafe")
    if os.name == "posix":
        path.chmod(0o700)
    return path


def _write_private(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class TurnJournal:
    """Preimages and final hashes of the paths one turn changed."""

    def __init__(self, root: Path, turn_id: str, directory: Path) -> None:
        self.root = Path(root).resolve()
        self.turn_id = turn_id
        self.directory = directory
        self.entries: dict[str, dict[str, Any]] = {}
        self.preimage_bytes = 0
        self.started_at = 0.0
        self.finished = False
        self.undone = False

    # -- lifecycle -----------------------------------------------------
    @staticmethod
    def base_directory(root: Path, base: Path | None = None) -> Path:
        key = _sha(_root_key(root).encode("utf-8"))[:32]
        return Path(base or (state_root() / "turns")).expanduser() / key

    @classmethod
    def begin(cls, root: Path, *, base: Path | None = None) -> "TurnJournal":
        """Start recording a turn of ``root``; an unfinished earlier turn is closed."""
        turn_id = f"turn_{int(time.time() * 1000):013d}_{secrets.token_hex(4)}"
        directory = _private_dir(cls.base_directory(root, base) / turn_id)
        journal = cls(root, turn_id, directory)
        journal.started_at = time.time()
        journal._save()
        with _LOCK:
            previous = _ACTIVE.get(_root_key(root))
            _ACTIVE[_root_key(root)] = journal
        if previous is not None and previous is not journal:
            previous._close()
        journal._prune()
        return journal

    @classmethod
    def active(cls, root: Path) -> "TurnJournal | None":
        with _LOCK:
            return _ACTIVE.get(_root_key(root))

    @classmethod
    def load(cls, root: Path, turn_id: str, *, base: Path | None = None) -> "TurnJournal":
        if not isinstance(turn_id, str) or not TURN_ID.fullmatch(turn_id):
            raise ValueError("invalid turn id")
        directory = cls.base_directory(root, base) / turn_id
        manifest = directory / "manifest.json"
        info = manifest.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("turn manifest is not a regular file")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or data.get("turn_id") != turn_id
                or data.get("root") != _root_key(root) or not isinstance(data.get("entries"), dict)):
            raise ValueError("turn manifest does not match this workspace")
        journal = cls(root, turn_id, directory)
        journal.entries = data["entries"]
        journal.preimage_bytes = int(data.get("preimage_bytes", 0))
        journal.started_at = float(data.get("started_at", 0.0))
        journal.finished = bool(data.get("finished"))
        journal.undone = bool(data.get("undone"))
        return journal

    @classmethod
    def latest(cls, root: Path) -> "TurnJournal | None":
        """Newest nonempty, not-undone turn, also after a process restart.

        A corrupt newest record is an error: never silently undo an older turn.
        An interrupted process may leave finished=False; no in-process active
        turn exists after restart, so its verified preimages remain recoverable.
        """
        directory = cls.base_directory(root)
        if not directory.exists():
            return None
        candidates = sorted((p for p in directory.iterdir()
                             if TURN_ID.fullmatch(p.name)), reverse=True)
        for path in candidates:
            if path.is_symlink() or not path.is_dir():
                raise ValueError("turn journal directory is unsafe")
            journal = cls.load(root, path.name)
            if not journal.undone and journal.changes():
                return journal
        return None

    def finish(self) -> None:
        """The turn ended; its record stays for review and undo."""
        with _LOCK:
            if _ACTIVE.get(_root_key(self.root)) is self:
                del _ACTIVE[_root_key(self.root)]
        self._close()

    def _close(self) -> None:
        self.finished = True
        self._save()

    # -- recording -----------------------------------------------------
    def capture(self, relative: str, payload: bytes | None, mode: int | None = None) -> None:
        """Remember the state of ``relative`` before this turn first changed it."""
        if self.finished:
            raise TurnJournalFull("the turn is already finished")
        if relative in self.entries:
            return
        if len(self.entries) >= MAX_TURN_PATHS:
            raise TurnJournalFull("the turn changed too many files to undo")
        size = 0 if payload is None else len(payload)
        if self.preimage_bytes + size > MAX_TURN_PREIMAGE_BYTES:
            raise TurnJournalFull("the turn's undo budget is full")
        before = None
        if payload is not None:
            before = _sha(payload)
            blobs = _private_dir(self.directory / "blobs")
            blob = blobs / before
            if not blob.exists():
                _write_private(blob, payload)
        self.entries[relative] = {
            "order": len(self.entries), "before_sha256": before,
            "before_mode": None if mode is None else stat.S_IMODE(mode),
            "after_sha256": before, "after_mode": None if mode is None else stat.S_IMODE(mode),
        }
        self.preimage_bytes += size
        self._save()

    def note_after(self, relative: str, after_sha256: str | None) -> None:
        """The hash ``relative`` has after this turn's latest change (None: absent)."""
        entry = self.entries.get(relative)
        if entry is None:
            return
        entry["after_sha256"] = after_sha256
        entry["after_mode"] = (stat.S_IMODE((self.root / relative).lstat().st_mode)
                               if after_sha256 is not None else None)
        self._save()

    def mark_undone(self) -> None:
        self.undone = True
        self._save()

    # -- reading -------------------------------------------------------
    def read_before(self, relative: str) -> bytes | None:
        entry = self.entries[relative]
        digest = entry["before_sha256"]
        if digest is None:
            return None
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError("turn preimage digest is malformed")
        blob = self.directory / "blobs" / digest
        info = blob.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("turn preimage is not a regular file")
        payload = blob.read_bytes()
        if _sha(payload) != digest:
            raise ValueError("turn preimage does not match its digest")
        return payload

    def changes(self) -> list[dict[str, Any]]:
        """Paths whose state differs from before the turn, in capture order."""
        rows = []
        for path, entry in sorted(self.entries.items(), key=lambda item: item[1]["order"]):
            before, after = entry["before_sha256"], entry["after_sha256"]
            if before == after and entry.get("before_mode") == entry.get("after_mode"):
                continue
            kind = "created" if before is None else "deleted" if after is None else "modified"
            rows.append({"path": path, "kind": kind, **entry})
        return rows

    def summary(self) -> dict[str, int]:
        counts = {"created": 0, "modified": 0, "deleted": 0}
        for row in self.changes():
            counts[row["kind"]] += 1
        return counts

    # -- storage -------------------------------------------------------
    def _save(self) -> None:
        data = {"turn_id": self.turn_id, "root": _root_key(self.root), "entries": self.entries,
                "preimage_bytes": self.preimage_bytes, "started_at": self.started_at,
                "finished": self.finished, "undone": self.undone}
        _write_private(self.directory / "manifest.json",
                       json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8"))

    def _prune(self) -> None:
        parent = self.directory.parent
        turns = sorted(path for path in parent.iterdir()
                       if path.is_dir() and not path.is_symlink() and TURN_ID.fullmatch(path.name))
        for old in turns[:-MAX_KEPT_TURNS]:
            for child in sorted(old.rglob("*"), reverse=True):
                if child.is_symlink() or child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            old.rmdir()


__all__ = ["MAX_TURN_PREIMAGE_BYTES", "TURN_ID", "TurnJournal", "TurnJournalFull"]
