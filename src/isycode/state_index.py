"""Single authority for ISyCode state path resolution (F-10).

Every durable state path derives from one root. The root honors
``ISYCODE_STATE_HOME`` first, then the platform convention (``LOCALAPPDATA``
on Windows; ``XDG_STATE_HOME`` or ``~/.local/state`` elsewhere). The digest
helpers preserve the historical shapes each store already wrote — resolved
vs raw workspace paths, 16/24/32 hex characters — because unifying them
would orphan existing user state.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


def _digest(text: str, length: int) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


class StateIndex:
    """Resolve every state path from a single, overridable root."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root).expanduser() if root is not None else self.default_root()

    @staticmethod
    def default_root() -> Path:
        override = os.environ.get("ISYCODE_STATE_HOME")
        if override:
            return Path(override).expanduser()
        if os.name == "nt":
            return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "ISyCode"
        return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "isycode"

    def state_root(self) -> Path:
        return self._root

    def subsystem(self, name: str, *, root: Path | None = None) -> Path:
        base = Path(root).expanduser() if root is not None else self._root
        return base / name

    def workspace_digest(self, workspace_root: Path, *, length: int = 32,
                         resolve: bool = False) -> str:
        target = (Path(workspace_root).expanduser().resolve(strict=True)
                  if resolve else Path(workspace_root))
        return _digest(str(target), length)

    def workspace_state(self, workspace_root: Path, parent: Path, *,
                        length: int = 32, resolve: bool = False) -> Path:
        return parent / self.workspace_digest(workspace_root, length=length, resolve=resolve)

    def journal_directory(self, *, state_directory: Path | None = None) -> Path:
        return Path(state_directory or (self._root / "action-audit")).expanduser()

    def journal_path(self, workspace_root: Path, *,
                     state_directory: Path | None = None) -> Path:
        root_id = self.workspace_digest(workspace_root, length=32, resolve=True)
        return self.journal_directory(state_directory=state_directory) / f"actions-{root_id}.jsonl"

    def trust_directory(self, *, root: Path | None = None) -> Path:
        return Path(root or self._root) / "workspace-trust"

    def trust_path(self, workspace_root: Path, *, root: Path | None = None) -> Path:
        digest = self.workspace_digest(workspace_root, length=32)
        return self.trust_directory(root=root) / f"trust-{digest}.json"

    def sessions_path(self, workspace_root: Path, *, root: Path | None = None) -> Path:
        canonical_digest = self.workspace_digest(workspace_root, length=24, resolve=True)
        return Path(root or self._root) / "isyrcodesessions" / canonical_digest


_cached: StateIndex | None = None
_cached_key: tuple[str | None, ...] = ()


def get_state_index() -> StateIndex:
    """Process-wide StateIndex; rebuilds when any state-path env input changes.

    Tests monkeypatch these variables per test, so the cache key covers every
    environment input ``default_root`` reads, not only ``ISYCODE_STATE_HOME``.
    """
    global _cached, _cached_key
    key = (os.environ.get("ISYCODE_STATE_HOME"), os.environ.get("XDG_STATE_HOME"),
           os.environ.get("LOCALAPPDATA"), os.environ.get("HOME"),
           os.environ.get("USERPROFILE"))
    if _cached is None or key != _cached_key:
        _cached = StateIndex()
        _cached_key = key
    return _cached
