"""First-run recurrence choice and external per-workspace session locations."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path


def state_root() -> Path:
    override = os.environ.get("ISYCODE_STATE_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "ISyCode"
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "isycode"


def broad_workspace_reason(directory: Path) -> str | None:
    """Explain why a marker here would become the root of unrelated projects.

    Workspace discovery walks up to the nearest `.isyroot`, so a marker in the
    home directory, one of its ancestors, the temporary directory, or a mount
    point makes that broad directory the shared root (grants, sessions and
    receipts) of every descendant folder without its own marker.
    """
    try:
        path = directory.expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return "the directory cannot be resolved"
    if path == Path(path.anchor):
        return "it is the filesystem root"
    try:
        home = Path.home().resolve(strict=True)
    except (OSError, RuntimeError, KeyError):
        home = None
    if home is not None and (path == home or path in home.parents):
        return "it is your home directory or contains it"
    try:
        if path == Path(tempfile.gettempdir()).resolve(strict=True):
            return "it is the shared temporary directory"
    except (OSError, RuntimeError):
        pass
    if os.path.ismount(path):
        return "it is a mount point"
    return None


def shared_root_warning(workspace_root: Path, root_source: str,
                        launch_dir: Path) -> str | None:
    """Warn when an existing marker makes a broad directory the active root.

    Markers created before the broad-directory guard, or by hand, still make
    every descendant without its own `.isyroot` share one identity. The marker
    is honoured (it is an explicit identity), but the sharing must be visible.
    """
    if root_source != "isyroot":
        return None
    reason = broad_workspace_reason(workspace_root)
    if reason is None:
        return None
    shared = "" if launch_dir == workspace_root else f" for {launch_dir}"
    return (f"Workspace root {workspace_root}{shared}: {reason}. Folders below it without "
            "their own .isyroot share its grants and sessions. Create an empty .isyroot in "
            "the project folder to give it its own workspace.")


def new_workspace_choice(launch_dir: Path, saved_choice: bool | None,
                         global_default: str) -> bool | None:
    """Decide recurrence for a folder with no `.isyroot`; None means ask.

    A saved per-folder choice wins. The user-wide default only preselects a
    choice for ordinary project folders: it never creates a marker by itself
    in a broad directory, where the user must see the path and decide.
    """
    if saved_choice is not None:
        return saved_choice
    if global_default == "temporary":
        return False
    if global_default == "recurring" and broad_workspace_reason(launch_dir) is None:
        return True
    return None


class WorkspaceSetupStore:
    """Store onboarding decisions outside workspaces; marker creation is opt-in."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or state_root()).expanduser()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("ISyCode state root must be a real directory, not a symlink")
        self.root = self.root.resolve(strict=True)
        if os.name == "posix":
            self.root.chmod(0o700)
        self.preferences_path = self.root / "workspace-setup.json"

    @staticmethod
    def _key(launch_dir: Path) -> str:
        return str(launch_dir.expanduser().resolve(strict=True))

    def _load(self) -> dict[str, bool]:
        try:
            info = self.preferences_path.lstat()
        except FileNotFoundError:
            return {}
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("workspace setup preferences are not a regular file")
        if info.st_size > 256_000:
            raise ValueError("workspace setup preferences exceed the size limit")
        data = json.loads(self.preferences_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("choices", {}), dict):
            raise ValueError("workspace setup preferences are malformed")
        return {key: value for key, value in data.get("choices", {}).items()
                if isinstance(key, str) and isinstance(value, bool)}

    def recurrent_choice(self, launch_dir: Path) -> bool | None:
        return self._load().get(self._key(launch_dir))

    def choose_recurrent(self, launch_dir: Path, accepted: bool) -> None:
        launch = launch_dir.expanduser().resolve(strict=True)
        if not launch.is_dir():
            raise ValueError("recurring workspace must be an existing directory")
        if accepted:
            marker = launch / ".isyroot"
            try:
                metadata = marker.lstat()
            except FileNotFoundError:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(marker, flags, 0o600)
                os.close(descriptor)
            else:
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != 0:
                    raise ValueError("existing .isyroot must be an empty regular file")

        choices = self._load()
        choices[str(launch)] = bool(accepted)
        payload = json.dumps({"version": 1, "choices": choices}, indent=2)
        fd, temporary = tempfile.mkstemp(prefix=".workspace-setup-", dir=self.root)
        try:
            if os.name == "posix":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.preferences_path)
            if os.name == "posix":
                self.preferences_path.chmod(0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def sessions_root(self, workspace_root: Path) -> Path:
        canonical = workspace_root.expanduser().resolve(strict=True)
        digest = hashlib.sha256(str(canonical).encode("utf-8")).hexdigest()[:24]
        return self.root / "isyrcodesessions" / digest
