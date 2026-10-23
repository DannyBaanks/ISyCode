"""ISyCode's L0 for GUS (ADR 0013): the kernel GUS never changes, and its fingerprint.

L0 is the mechanism that keeps every other change safe: IsySentinel, Workspace
Authority and approvals, the journal and effect ledger, staging and the
sandboxes, every execution owner, the approval screens, GUS's own limits, the
coverage auditor, the ADRs, AGENTS.md and CI. GUS works only in L1, everything
else. A GUS turn may not write, move or delete an L0 path, and a generation
that touches one is rejected; L0 changes are Danny's (ADR 0013, decision L1).

The list is explicit, never inferred: a file is in it or it is not. One rule is
checked by a test instead of listed by hand: every module that defines an
execution owner (a class named ``...Owner``) is L0.

The fingerprint is a SHA-256 per L0 file, taken before a GUS turn and compared
after it. It is a hash check, not a filesystem lock (ADR 0013, "no demostrado").
"""
from __future__ import annotations

import hashlib
import os
import posixpath
from dataclasses import dataclass
from pathlib import Path

L0_FILES = (
    # GUS's own limits and the gates that hold them.
    "src/isycode/gus_l0.py",
    "src/isycode/gus_role.py",
    "src/isycode/agents/gus.md",
    "src/isycode/gus_slot.py",
    "src/isycode/gus_context_pack.py",
    "src/isycode/gus_session.py",
    "tests/test_gus_l0.py",
    "tests/test_gus_role.py",
    # IsySentinel, the action registry and the destructive-action firewall.
    "src/isycode/isysentinel.py",
    "src/isycode/security.py",
    "src/isycode/safety.py",
    "src/isycode/actions.py",
    "src/isycode/action_runtime.py",
    "src/isycode/effect_policy.py",
    "src/isycode/sensitive_paths.py",
    "src/isycode/terminal_safety.py",
    "src/isycode/egress.py",
    # Workspace Authority, approvals and trust.
    "src/isycode/authority.py",
    "src/isycode/workspace_authority.py",
    "src/isycode/approvals.py",
    "src/isycode/workspace_trust.py",
    "src/isycode/receipts.py",
    # Journal, effect ledger, verified file effects and Flow's undo.
    "src/isycode/action_audit.py",
    "src/isycode/effect_ledger.py",
    "src/isycode/effect_fs.py",
    "src/isycode/platform_posix_effect_fs.py",
    "src/isycode/platform_windows_effect_fs.py",
    "src/isycode/winfs.py",
    "src/isycode/turn_journal.py",
    # Staging and the platform sandboxes.
    "src/isycode/command_runner.py",
    "src/isycode/staging.py",
    "src/isycode/platform_sandbox.py",
    "src/isycode/platform_posix_sandbox.py",
    "src/isycode/platform_windows_sandbox.py",
    "src/isycode/platform_windows_sandbox_process.py",
    "src/isycode/platform_windows_sandbox_recovery.py",
    "src/isycode/platform_windows_sandbox_registry.py",
    "src/isycode/platform_windows_sandbox_resources.py",
    "src/isycode/platform_windows_sandbox_volume.py",
    "src/isycode/platform_windows_sandbox_volume_api.py",
    # Execution owners (the test requires every module defining one).
    "src/isycode/bridge_coordination.py",
    "src/isycode/bridge_presence.py",
    "src/isycode/broker.py",
    "src/isycode/clipboard_owner.py",
    "src/isycode/credential_owner.py",
    "src/isycode/credentials.py",
    "src/isycode/file_picker.py",
    "src/isycode/git_owner.py",
    "src/isycode/platform_git.py",
    "src/isycode/platform_windows_git.py",
    "src/isycode/grok_auth.py",
    "src/isycode/iteration.py",
    "src/isycode/mcp_local.py",
    "src/isycode/mobile_host.py",
    "src/isycode/provider_auth.py",
    "src/isycode/publish.py",
    "src/isycode/session_owner.py",
    "src/isycode/tailscale_install.py",
    "src/isycode/tailscale_login.py",
    "src/isycode/tailscale_read.py",
    "src/isycode/tailscale_serve.py",
    "src/isycode/web_fetch.py",
    "src/isycode/workspace_config_owner.py",
    "src/isycode/workspace_memory.py",
    "src/isycode/workspace_pack.py",
    "src/isycode/workspace_write.py",
    # Approval screens.
    "src/isycode/tui_screens_approval.py",
    "src/isycode/tui_screens_grants.py",
    "src/isycode/folder_screens.py",
    # The coverage auditor and its pinned snapshot.
    "src/isycode/action_coverage.py",
    "tests/test_action_coverage.py",
    # Repository rules and packaging.
    "AGENTS.md",
    "pyproject.toml",
)
L0_DIRECTORIES = (
    "docs/decisions",
    "docs/security",
    ".github/workflows",
)
L0_RULE = (
    "These files are ISyCode's L0, the kernel that keeps every other change safe. You never "
    "change them: a write, move or delete of an L0 path in a GUS turn is refused, and a "
    "generation that touches one is rejected. Plan your changes around L0; if a request needs "
    "an L0 change, say so and leave it to Danny.")

_SKIPPED_NAMES = frozenset({"__pycache__", ".DS_Store"})


def _key(path: str) -> str:
    # Case-folded so a case-insensitive filesystem cannot reach L0 by spelling.
    return path.casefold()


_L0_FILE_KEYS = frozenset(_key(path) for path in L0_FILES)
_L0_DIRECTORY_KEYS = tuple(_key(path) for path in L0_DIRECTORIES)
# Every folder above an L0 entry, and the repository root itself.
_L0_ANCESTOR_KEYS = frozenset(
    _key("/".join(parts[:depth]))
    for path in L0_FILES + L0_DIRECTORIES
    for parts in [path.split("/")]
    for depth in range(1, len(parts))
) | {"."}


def repository_path(path: str) -> str | None:
    """A repository-relative POSIX path, or ``None`` when it leaves the repository."""
    text = str(path).replace("\\", "/").strip()
    if not text or text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        return None
    normal = posixpath.normpath(text)
    if normal == ".." or normal.startswith("../"):
        return None
    return normal


def touches_l0(path: str) -> bool:
    """True for an L0 file, anything inside an L0 directory, or a folder holding L0.

    Moving or deleting ``src/isycode`` touches L0 as surely as editing
    ``security.py``. A path outside the repository is not L0; Workspace
    Authority already refuses it.
    """
    normal = repository_path(path)
    if normal is None:
        return False
    key = _key(normal)
    if key in _L0_FILE_KEYS or key in _L0_ANCESTOR_KEYS:
        return True
    return any(key == directory or key.startswith(directory + "/") for directory in _L0_DIRECTORY_KEYS)


def _digest(path: Path) -> str | None:
    try:
        if path.is_symlink():
            # A file swapped for a link is a change even if the target matches.
            return "link:" + hashlib.sha256(os.readlink(path).encode("utf-8", "surrogateescape")).hexdigest()
        # A Windows checkout carries CRLF; the same L0 has the same fingerprint everywhere.
        return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    except FileNotFoundError:
        return None


def _directory_files(root: Path, directory: str) -> list[str]:
    base = root / directory
    found = []
    for current, folders, files in os.walk(base, followlinks=False):
        folders[:] = sorted(name for name in folders if name not in _SKIPPED_NAMES)
        for name in sorted(files):
            if name not in _SKIPPED_NAMES:
                found.append(Path(current, name).relative_to(root).as_posix())
    return found


@dataclass(frozen=True)
class L0Fingerprint:
    entries: tuple[tuple[str, str | None], ...]

    @property
    def digest(self) -> str:
        lines = "".join(f"{path}\0{value or '-'}\n" for path, value in self.entries)
        return hashlib.sha256(lines.encode("utf-8")).hexdigest()

    def changed(self, other: "L0Fingerprint") -> list[str]:
        """L0 paths that differ, appeared or disappeared between two fingerprints."""
        mine, theirs = dict(self.entries), dict(other.entries)
        return sorted(path for path in mine.keys() | theirs.keys() if mine.get(path) != theirs.get(path))


def fingerprint(root: Path) -> L0Fingerprint:
    root = Path(root)
    paths = list(L0_FILES)
    for directory in L0_DIRECTORIES:
        paths.extend(_directory_files(root, directory))
    return L0Fingerprint(tuple((path, _digest(root / path)) for path in sorted(set(paths))))


def manifest_text(current: L0Fingerprint) -> str:
    """The L0 section of GUS's fixed context: the rule, the paths and the fingerprint."""
    listed = "\n".join(f"- {path}" for path in L0_FILES)
    folders = "\n".join(f"- {path}/ (everything inside)" for path in L0_DIRECTORIES)
    return (f"--- ISyCode L0 (fingerprint {current.digest[:16]}) ---\n{L0_RULE}\n"
            f"Folders that contain L0 files are L0 too (moving or deleting them touches L0).\n"
            f"{listed}\n{folders}")


__all__ = ["L0Fingerprint", "L0_DIRECTORIES", "L0_FILES", "L0_RULE", "fingerprint",
           "manifest_text", "repository_path", "touches_l0"]
