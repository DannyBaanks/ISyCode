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
