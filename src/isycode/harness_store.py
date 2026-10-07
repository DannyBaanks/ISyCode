"""Private user state for explicit Multi Harness folder picks."""
from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path

from isycode.harness_graph import CATALOG_IDS
from isycode.workspace_setup import state_root


class HarnessStore:
    def __init__(self) -> None:
        self.directory = state_root() / "multi-harness"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            info = self.directory.lstat()
        except OSError as exc:
            raise ValueError("Multi Harness state directory is unavailable") from exc
        if not stat.S_ISDIR(info.st_mode) or self.directory.is_symlink():
            raise ValueError("Multi Harness state directory must be a real directory")
        if os.name == "posix":
            self.directory.chmod(0o700)
        self.roots_path = self.directory / "roots.json"

    def roots(self) -> dict[str, Path]:
        try:
            info = self.roots_path.lstat()
        except FileNotFoundError:
            return {}
        if (not stat.S_ISREG(info.st_mode) or self.roots_path.is_symlink()
                or info.st_size > 64 * 1024):
            raise ValueError("Multi Harness roots file is unsafe")
        if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Multi Harness roots file must be private")
        try:
            data = json.loads(self.roots_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Multi Harness roots file is malformed") from exc
        raw = data.get("roots") if isinstance(data, dict) and data.get("version") == 1 else None
        if not isinstance(raw, dict):
            raise ValueError("Multi Harness roots file is malformed")
        if any(key not in CATALOG_IDS for key in raw):
            raise ValueError("Multi Harness roots file contains an unknown harness id")
        result: dict[str, Path] = {}
        for harness_id, value in raw.items():
            if not isinstance(value, str):
                raise ValueError("Multi Harness root paths must be strings")
            path = Path(value)
            if not path.is_absolute():
                raise ValueError("Multi Harness root paths must be absolute")
            result[harness_id] = path
        return result

    def set_root(self, harness_id: str, root: Path) -> None:
        if harness_id not in CATALOG_IDS:
            raise ValueError("unknown harness id")
        canonical = Path(root).expanduser().resolve(strict=True)
        if not canonical.is_dir():
            raise ValueError("picked harness root must be an existing directory")
        roots = self.roots()
        roots[harness_id] = canonical
        payload = {
            "version": 1,
            "roots": {key: str(value) for key, value in roots.items()},
        }
        temporary = self.directory / (".roots-" + secrets.token_hex(8) + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.roots_path)
            if os.name == "posix":
                self.roots_path.chmod(0o600)
        finally:
            if temporary.exists():
                temporary.unlink()


__all__ = ["HarnessStore"]
