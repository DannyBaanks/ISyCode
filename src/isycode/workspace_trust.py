"""Human trust for one workspace root. This is not a grant and not a tool.

A Classic preset still asks before each edit and each command until a person
confirms this root. The record lives outside the checkout and matches the
resolved path together with its device and inode. A moved folder, a copy, a
replaced directory, a broad folder, or an unreadable policy does not inherit
it. Security mode never consults it. The model has no action that writes it.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from isycode.actions import ACTION_BY_ID
from isycode.effect_ledger import LIMITS_VERSION
from isycode.effect_policy import POLICY_VERSION
from isycode.workspace_setup import broad_workspace_reason, state_root

TRUST_VERSION = 1
PROFILE_VERSION = 1
ACCEPT_PHRASE = "trust this workspace"
MAX_RECORD_BYTES = 16 * 1024

# Ordinary local work after onboarding. Commits, secrets, credentials,
# provider calls, config, and authority changes stay outside on purpose.
QUIET_CLASSIC_ACTIONS = frozenset({
    "workspace.files.list",
    "workspace.files.read",
    "workspace.files.search",
    "workspace.context.inject",
    "workspace.files.write",
    "workspace.files.restore",
    "workspace.files.delete",
    "workspace.files.move",
    "workspace.command.run",
})


def onboarding_brief(*, root: Path, mode: str, provider: str,
                     sends_workspace_context: bool) -> str:
    """Short explanation shown before a person trusts one root."""
    context = ("File context from this folder can be sent to that provider."
               if sends_workspace_context else
               "This confirmation does not send the folder contents by itself.")
    return (
        f"Workspace root: {root}\n"
        f"Mode: {mode}\n"
        f"Provider: {provider}\n"
        f"{context}\n"
        "Trusting this folder lets Classic read and search it, and make recoverable "
        "edits, creates, moves and deletes inside the effect budget, and run isolated "
        "sandboxed tests, without a question for each one. Commits, secrets, authority "
        "changes, new network destinations and anything without a sandbox still ask or "
        "stay off. A revoked permission still wins. This is not a permanent approval "
        "for every tool, and it does not turn Security on or off."
    )


def modal_required(authority, request) -> bool:
    """True when this request still needs its own human approval."""
    spec = ACTION_BY_ID.get(getattr(request, "action_id", ""))
    if spec is None or not spec.approval_required:
        return False
    return not quiet_classic(authority, request)


def quiet_classic(authority, request) -> bool:
    """Whether a trusted Classic root covers this one request.

    Any error, mismatch, or missing sandbox says no. Callers then keep the
    per-action approval. This function does not grant, consume, or execute.
    """
    try:
        action_id = request.action_id
        if action_id not in QUIET_CLASSIC_ACTIONS:
            return False
        if request.workspace_root != authority.root:
            return False
        if authority.mode() != "classic":
            return False
        if action_id == "workspace.command.run":
            from isycode.command_runner import sandbox_executable
            if not sandbox_executable():
                return False
        return WorkspaceTrust().trusted(authority)
    except Exception:
        return False


class WorkspaceTrust:
    """Durable trust decision stored beside the effect ledger, not in the tree."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or state_root())
        self.directory = self.root / "workspace-trust"

    def trusted(self, authority) -> bool:
        record = self._matching(authority)
        return bool(record and record.get("decision") == "trusted")

    def declined(self, authority) -> bool:
        record = self._matching(authority)
        return bool(record and record.get("decision") == "declined")

    def needs_onboarding(self, authority) -> bool:
        """Ask once. A saved trust or a saved decline is not asked again."""
        try:
            if authority.mode() != "classic":
                return False
            if broad_workspace_reason(authority.root):
                return False
            if not self._policy_current(authority):
                return False
            if not self._outside(authority.root):
                return False
            return not self.trusted(authority) and not self.declined(authority)
        except Exception:
            return False

    def accept(self, authority, phrase: str) -> None:
        if phrase != ACCEPT_PHRASE:
            raise ValueError("trust phrase does not match")
        self._write_decision(authority, "trusted")

    def decline(self, authority) -> None:
        self._write_decision(authority, "declined")

    def _write_decision(self, authority, decision: str) -> None:
        if authority.mode() != "classic":
            raise ValueError("only a Classic workspace can record this decision")
        if broad_workspace_reason(authority.root):
            raise ValueError("a broad directory cannot receive the quiet profile")
        if not self._policy_current(authority):
            raise ValueError("workspace policy is not current")
        if not self._outside(authority.root):
            raise ValueError("trust records must stay outside the workspace")
        info = authority.root.stat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("workspace root must be a real directory")
        record = {
            "version": TRUST_VERSION,
            "profile_version": PROFILE_VERSION,
            "policy_version": POLICY_VERSION,
            "limits_version": LIMITS_VERSION,
            "decision": decision,
            "workspace_path": str(authority.root),
            "device": int(info.st_dev),
            "inode": int(info.st_ino),
        }
        self._ensure_dir()
        self._atomic_write(self._path_for(authority.root), record)

    def _matching(self, authority) -> dict[str, Any] | None:
        try:
            if not self._directory_is_real():
                return None
            if broad_workspace_reason(authority.root):
                return None
            if not self._outside(authority.root):
                return None
            if not self._policy_current(authority):
                return None
            record = self._read(authority.root)
            if record is None:
                return None
            info = authority.root.stat()
            if (record.get("version") != TRUST_VERSION
                    or record.get("profile_version") != PROFILE_VERSION
                    or record.get("policy_version") != POLICY_VERSION
                    or record.get("limits_version") != LIMITS_VERSION
                    or record.get("decision") not in {"trusted", "declined"}
                    or record.get("workspace_path") != str(authority.root)
                    or record.get("device") != int(info.st_dev)
                    or record.get("inode") != int(info.st_ino)
                    or not stat.S_ISDIR(info.st_mode)):
                return None
            return record
        except Exception:
            return None

    @staticmethod
    def _policy_current(authority) -> bool:
        policy = authority.policy()
        return (isinstance(policy, dict)
                and policy.get("version") == getattr(authority, "VERSION", None)
                and policy.get("workspace_root") == str(authority.root))

    def _outside(self, workspace: Path) -> bool:
        try:
            root = workspace.resolve(strict=True)
            directory = self.directory
            if directory.exists():
                directory = directory.resolve(strict=True)
            else:
                parent = self.root
                if parent.exists():
                    parent = parent.resolve(strict=True)
                directory = parent / directory.name
        except (OSError, RuntimeError):
            return False
        return directory != root and root not in directory.parents and directory not in root.parents

    def _path_for(self, workspace: Path) -> Path:
        digest = hashlib.sha256(str(workspace).encode("utf-8")).hexdigest()[:32]
        return self.directory / f"trust-{digest}.json"

    def _directory_is_real(self) -> bool:
        if not self.directory.exists() and not self.directory.is_symlink():
            return True
        try:
            info = self.directory.lstat()
        except OSError:
            return False
        return stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)

    def _ensure_dir(self) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("trust state root must be a real directory")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise ValueError("trust directory must be a real directory")
        if os.name == "posix":
            self.directory.chmod(0o700)

    def _read(self, workspace: Path) -> dict[str, Any] | None:
        """Return a record, or None. Never rewrite a bad file into trust."""
        path = self._path_for(workspace)
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        except OSError:
            return None
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_nlink != 1 or info.st_size > MAX_RECORD_BYTES):
            return None
        if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(path, flags)
            try:
                opened = os.fstat(descriptor)
                if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                        or opened.st_dev != info.st_dev or opened.st_ino != info.st_ino
                        or opened.st_size > MAX_RECORD_BYTES):
                    return None
                payload = os.read(descriptor, MAX_RECORD_BYTES + 1)
            finally:
                os.close(descriptor)
        except OSError:
            return None
        if len(payload) > MAX_RECORD_BYTES:
            return None
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return data

    def _atomic_write(self, path: Path, record: dict[str, Any]) -> None:
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2)
        if len(payload.encode("utf-8")) > MAX_RECORD_BYTES:
            raise ValueError("trust record exceeds its size limit")
        temporary = self.directory / (".trust-" + os.urandom(8).hex() + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            view = memoryview(payload.encode("utf-8"))
            while view:
                view = view[os.write(descriptor, view):]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.replace(temporary, path)
            if os.name == "posix":
                os.chmod(path, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()


__all__ = [
    "ACCEPT_PHRASE", "PROFILE_VERSION", "QUIET_CLASSIC_ACTIONS", "TRUST_VERSION",
    "WorkspaceTrust", "modal_required", "onboarding_brief", "quiet_classic",
]
