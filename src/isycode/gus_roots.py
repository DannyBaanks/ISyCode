"""GUS's roots (ADR 0015): where it reads, where it edits, and who authorizes each.

GUS is offered in every workspace, but the three roots stay separate:

- the visible workspace the TUI was opened in (read-only for GUS unless it is
  also the target);
- the configured ISyCode checkout GUS edits, on a ``gus/*`` branch, through a
  dedicated authority in Security mode with explicit grants only;
- the machine scope it may read (ADR 0015, phase 2), never the user state.

The GUS conversation and its model calls have their own authority rooted in the
user state directory, so GUS talks even in a Security workspace or without a
target. Nothing here grants an action: grants are written explicitly and every
call still passes through IsySentinel, the owner, the journal and receipts.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from isycode.gus_role import is_isycode_checkout
from isycode.gus_session import GusState
from isycode.platform_storage import storage
from isycode.state_index import get_state_index
from isycode.workspace_authority import WorkspaceAuthority, known_provider_hosts
from isycode.workspace_trust import QUIET_FLOW_ACTIONS

SETTINGS_VERSION = 1
MAX_SETTINGS_BYTES = 64 * 1024
READ_SCOPE_MODES = frozenset({"machine", "home", "folders"})
MEMORY_MODES = frozenset({"explicit", "automatic"})
DEFAULT_SETTINGS = {
    "version": SETTINGS_VERSION,
    "read_scope": {"mode": "machine", "folders": []},
    "target": None,
    "memory_mode": "explicit",
    "consent_digest": "",
    "consent_at": "",
}
# Target grants: recoverable local work plus git review/commit, never push,
# credentials, sessions, provider, configuration or authority.
TARGET_GIT_ACTIONS = frozenset({"git.status", "git.diff", "git.commit", "git.branch.create"})


class GusRootsError(ValueError):
    """GUS's roots or settings cannot be used safely."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def running_checkout() -> Path | None:
    """The ISyCode checkout that is executing this app, if it is one."""
    try:
        candidate = Path(__file__).resolve().parents[2]
    except (OSError, RuntimeError):
        return None
    return candidate if is_isycode_checkout(candidate) else None


def scope_text(settings: dict[str, Any]) -> str:
    scope = settings.get("read_scope") or {}
    mode = scope.get("mode")
    if mode == "machine":
        return "/"
    if mode == "home":
        return str(Path.home())
    folders = scope.get("folders") or []
    return ", ".join(str(folder) for folder in folders) if folders else "-"


def scope_digest(settings: dict[str, Any]) -> str:
    scope = settings.get("read_scope") or {}
    folders = sorted(str(folder) for folder in scope.get("folders") or []
                     if isinstance(folder, str))
    return _digest(json.dumps({"mode": scope.get("mode"), "folders": folders},
                              sort_keys=True, separators=(",", ":")))


class GusSettingsStore:
    """Private, bounded user settings under ``<state>/gus/settings.json``."""

    def __init__(self, *, root: Path | None = None) -> None:
        self.directory = get_state_index().subsystem("gus", root=root)
        self.path = self.directory / "settings.json"

    def _ensure(self) -> None:
        storage.ensure_directory(self.directory.parent, repair=True)
        storage.ensure_directory(self.directory, repair=True)
        if (self.directory.is_symlink() or not self.directory.is_dir()
                or not storage.private(self.directory)):
            raise GusRootsError("GUS settings directory is unsafe")

    def read(self) -> dict[str, Any]:
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return json.loads(json.dumps(DEFAULT_SETTINGS))
        except OSError as exc:
            raise GusRootsError("GUS settings cannot be inspected") from exc
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_size > MAX_SETTINGS_BYTES):
            raise GusRootsError("GUS settings are not a bounded regular file")
        if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise GusRootsError("GUS settings are not private")
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GusRootsError("GUS settings are unreadable") from exc
        return self._validated(data)

    @staticmethod
    def _validated(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict) or data.get("version") != SETTINGS_VERSION:
            raise GusRootsError("GUS settings do not match this version")
        merged = json.loads(json.dumps(DEFAULT_SETTINGS))
        merged.update({key: data[key] for key in
                       ("target", "memory_mode", "consent_digest", "consent_at")
                       if key in data})
        scope = data.get("read_scope")
        if not isinstance(scope, dict) or scope.get("mode") not in READ_SCOPE_MODES:
            raise GusRootsError("GUS read scope is invalid")
        folders = scope.get("folders", [])
        if (not isinstance(folders, list) or len(folders) > 64
                or not all(isinstance(folder, str) and folder for folder in folders)):
            raise GusRootsError("GUS read scope folders are invalid")
        merged["read_scope"] = {"mode": scope["mode"], "folders": list(folders)}
        if merged["memory_mode"] not in MEMORY_MODES:
            raise GusRootsError("GUS memory mode is invalid")
        target = merged.get("target")
        if target is not None and not isinstance(target, str):
            raise GusRootsError("GUS target is invalid")
        if not isinstance(merged["consent_digest"], str) or not isinstance(merged["consent_at"], str):
            raise GusRootsError("GUS consent record is invalid")
        return merged

    def write(self, settings: dict[str, Any]) -> None:
        value = self._validated({**settings, "version": SETTINGS_VERSION})
        self._ensure()
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        if len(payload) > MAX_SETTINGS_BYTES:
            raise GusRootsError("GUS settings exceed their size limit")
        temporary = self.directory / (".gus-settings-" + os.urandom(8).hex() + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            view = memoryview(payload)
            while view:
                view = view[os.write(descriptor, view):]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.replace(temporary, self.path)
            if os.name == "posix":
                os.chmod(self.path, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()

    def consent(self, settings: dict[str, Any], *, at: str) -> dict[str, Any]:
        value = {**settings, "consent_digest": scope_digest(settings), "consent_at": at}
        self.write(value)
        return value

    def consented(self, settings: dict[str, Any]) -> bool:
        return (bool(settings.get("consent_digest"))
                and settings.get("consent_digest") == scope_digest(settings))


def configured_target(settings: dict[str, Any]) -> Path | None:
    """The saved target if it is still an ISyCode checkout, else the running one."""
    saved = settings.get("target")
    if isinstance(saved, str) and saved:
        try:
            candidate = Path(saved).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            candidate = None
        if candidate is not None and candidate.is_dir() and is_isycode_checkout(candidate):
            return candidate
    return running_checkout()


def validate_target(value: str) -> Path:
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise GusRootsError("the target must be a folder path")
    try:
        candidate = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise GusRootsError("the target folder does not exist") from exc
    if not candidate.is_dir() or not is_isycode_checkout(candidate):
        raise GusRootsError("the target is not an ISyCode checkout")
    if (candidate / ".git").is_symlink() or not (candidate / ".git").is_dir():
        raise GusRootsError("the target checkout has no real .git folder")
    return candidate


def configure_target_grants(authority: WorkspaceAuthority, target: Path) -> None:
    """Write the exact, auditable target grants. Nothing is implicit here."""
    from isycode.command_runner import sandbox_executable

    target = target.resolve(strict=True)
    authority.set_mode("security")
    for action in sorted(QUIET_FLOW_ACTIONS - {"workspace.command.run"}):
        authority.set_grant(action, enabled=True, path_prefixes=[target])
    sandbox = sandbox_executable()
    if sandbox:
        authority.set_grant("workspace.command.run", enabled=True, executables=[sandbox])
    for action in sorted(TARGET_GIT_ACTIONS):
        authority.set_grant(action, enabled=True)


class GusTargetAuthority(WorkspaceAuthority):
    """The authority that governs GUS's edits to its target checkout."""

    gus_target = True


class GusRoots:
    """One GUS session bound to a visible workspace, a target and user settings."""

    def __init__(self, visible: Path, *, settings: GusSettingsStore | None = None,
                 data: dict[str, Any] | None = None) -> None:
        try:
            self.visible = Path(visible).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise GusRootsError("the visible workspace cannot be resolved") from exc
        self.settings = settings or GusSettingsStore()
        self.data = data if data is not None else self.settings.read()
        self.target = configured_target(self.data)
        self._authority: GusTargetAuthority | None = None
        self._provider_authority: WorkspaceAuthority | None = None

    def consent_ready(self) -> bool:
        return self.settings.consented(self.data)

    def read_scope(self) -> dict[str, Any]:
        return dict(self.data.get("read_scope") or {})

    def memory_mode(self) -> str:
        return str(self.data.get("memory_mode") or "explicit")

    def authority(self) -> GusTargetAuthority:
        """The target authority; every call rewrites the audited grant file."""
        if self.target is None:
            raise GusRootsError("GUS has no editable ISyCode target")
        if self._authority is None:
            base = self.settings.directory / "target-authority" / _digest(str(self.target))[:32]
            authority = GusTargetAuthority(self.target, state_directory=base)
            configure_target_grants(authority, self.target)
            self._authority = authority
        return self._authority

    def provider_authority(self) -> WorkspaceAuthority:
        """The authority for GUS's model calls, rooted in the user state."""
        if self._provider_authority is None:
            base = self.settings.directory / "provider-authority"
            state = self.settings.directory.parent
            storage.ensure_directory(state, repair=True)
            authority = WorkspaceAuthority(state, state_directory=base)
            authority.set_mode("security")
            authority.set_grant("provider.request", enabled=True,
                                network_hosts=known_provider_hosts())
            self._provider_authority = authority
        return self._provider_authority

    def visible_state(self) -> GusState:
        return GusState(self.visible)

    def target_state(self) -> GusState | None:
        return None if self.target is None else GusState(self.target)

    def enabled(self) -> bool:
        try:
            return self.visible_state().enabled()
        except OSError:
            return False

    def target_ready(self) -> tuple[bool, str]:
        """Whether GUS may edit now: marker files, real git, clean tree, narrow root."""
        from isycode.workspace_setup import broad_workspace_reason

        target = self.target
        if target is None:
            return False, "GUS has no configured ISyCode checkout to edit"
        if not is_isycode_checkout(target):
            return False, "GUS's target is not an ISyCode checkout"
        if (target / ".git").is_symlink() or not (target / ".git").is_dir():
            return False, "GUS's target has no real .git folder"
        if broad_workspace_reason(target):
            return False, "GUS does not edit a broad folder"
        from isycode.git_owner import GitOwner
        try:
            owner = GitOwner(target, self.authority())
            state, reason = owner.worktree_state()
            if state == "unavailable":
                return False, "GUS's target cannot be inspected: " + reason
            if state == "changed":
                detail = f" ({reason})" if reason else ""
                return False, ("GUS edits only in a clean checkout; commit or discard changes first"
                               + detail)
        except (OSError, RuntimeError, ValueError) as exc:
            return False, f"GUS's target cannot be inspected: {type(exc).__name__}"
        return True, ""


__all__ = [
    "DEFAULT_SETTINGS", "GusRoots", "GusRootsError", "GusSettingsStore", "GusTargetAuthority",
    "MEMORY_MODES", "READ_SCOPE_MODES", "SETTINGS_VERSION", "TARGET_GIT_ACTIONS",
    "configure_target_grants", "configured_target", "running_checkout", "scope_digest",
    "scope_text", "validate_target",
]
