"""Composition boundary for native locks and private state.

Availability is not authority. Callers retain their owner and policy checks.
"""
import os
import stat
from contextlib import contextmanager
from typing import Protocol
from pathlib import Path


class Storage(Protocol):
    def lock(self, fd: int, *, blocking: bool = True) -> None: ...
    def unlock(self, fd: int) -> None: ...
    def protect(self, path: Path) -> None: ...
    def private(self, path: Path, *, fd: int | None = None) -> bool: ...
    def private_child(self, path: Path, *, fd: int) -> bool: ...
    def ensure_directory(self, path: Path, *, repair: bool = False) -> None: ...
    def replace(self, source: Path, destination: Path) -> None: ...
    def sync_directory(self, path: Path) -> None: ...
    def delete_private(self, path: Path) -> None: ...


def _compose() -> Storage:
    if os.name == 'nt':
        from isycode.platform_windows_storage import WindowsStorage
        return WindowsStorage()
    if os.name == 'posix':
        from isycode.platform_posix_storage import PosixStorage
        return PosixStorage()
    raise RuntimeError('native private storage is unavailable on this platform')


storage = _compose()


@contextmanager
def held(path: Path):
    """Stable sidecar lock, including across replacement/rotation of data files."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
                 | getattr(os, 'O_BINARY', 0), 0o600)
    try:
        info, named = os.fstat(fd), path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                or not storage.private(path, fd=fd)):
            raise ValueError('private lock file is unsafe')
        storage.lock(fd)
        yield
    finally:
        os.close(fd)
