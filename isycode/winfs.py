"""Path-verified workspace file I/O for platforms without ``dir_fd`` / ``O_NOFOLLOW`` (Windows).

POSIX owners walk directories with descriptors and never follow links. Windows
has neither, so this module:

- refuses any path whose components (from the workspace root) include a
  symlink or junction (any reparse point);
- after opening a file, asks the OS for the handle's final path and requires it
  to be inside the workspace and to be the same file as the path — this closes
  the race for reads, because the check is on what was actually opened;
- for writes, verifies the new temporary file's final path, re-checks the
  folder chain right before the atomic ``os.replace`` and reads the result back
  through a verified open.

Residual risk (documented): a local process that can already rename folders
inside the workspace could swap a folder for a junction in the instant between
the last check and ``os.replace``. Reads are not affected.
"""
from __future__ import annotations

import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_OPEN_EXTRA = getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0) | getattr(os, "O_CLOEXEC", 0)


def use_verified_fs() -> bool:
    """True where descriptor-relative, no-follow opens are unavailable."""
    return os.name == "nt" or os.open not in os.supports_dir_fd


def _windows_final_path(fd: int) -> str:  # pragma: no cover - Windows only
    import ctypes
    import msvcrt
    from ctypes import wintypes

    handle = msvcrt.get_osfhandle(fd)
    get_final = ctypes.windll.kernel32.GetFinalPathNameByHandleW
    get_final.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    get_final.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_final(handle, buffer, len(buffer), 0)
    if not 0 < length < len(buffer):
        raise OSError("the final path of an opened file is unavailable")
    path = buffer.value
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    return path[4:] if path.startswith("\\\\?\\") else path


def default_final_path(fd: int) -> str:
    if os.name == "nt":  # pragma: no cover - Windows only
        return _windows_final_path(fd)
    link = f"/proc/self/fd/{fd}"
    if not os.path.exists(link):
        raise OSError("the final path of an opened file is unavailable")
    return os.readlink(link)


def is_link(path: Path) -> bool:
    """Symlink or any other reparse point (junctions included)."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    return (stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT))


@dataclass(frozen=True)
class Entry:
    """The part of os.DirEntry the read owner uses, with links already removed."""

    name: str
    directory: bool
    regular: bool

    def is_dir(self, follow_symlinks: bool = True) -> bool:
        return self.directory

    def is_file(self, follow_symlinks: bool = True) -> bool:
        return self.regular

    def is_symlink(self) -> bool:
        return False


class VerifiedFS:
    def __init__(self, root: Path, final_path: Callable[[int], str] | None = None):
        self.root = Path(os.path.realpath(root))
        self._final_path = final_path or default_final_path
        self._root_key = os.path.normcase(str(self.root))

    def _inside(self, real: str) -> bool:
        key = os.path.normcase(os.path.realpath(real) if os.name != "nt" else real)
        return key == self._root_key or key.startswith(self._root_key.rstrip(os.sep) + os.sep)

    def check_chain(self, path: Path) -> None:
        current = self.root
        for part in Path(path).relative_to(self.root).parts:
            current = current / part
            if is_link(current):
                raise OSError("symlinks and junctions are not followed inside the workspace")

    def _verify_fd(self, fd: int, path: Path) -> None:
        if not self._inside(self._final_path(fd)):
            raise OSError("the opened file resolved outside the workspace")
        opened, named = os.fstat(fd), os.lstat(path)
        if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise OSError("the file changed while it was being opened")

    def open_read(self, path: Path) -> int:
        self.check_chain(path)
        fd = os.open(path, os.O_RDONLY | _OPEN_EXTRA)
        try:
            self._verify_fd(fd, path)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def list_dir(self, directory: Path) -> list[Entry]:
        self.check_chain(directory)
        if not self._inside(os.path.realpath(directory)):
            raise OSError("the folder resolved outside the workspace")
        entries = []
        with os.scandir(directory) as iterator:
            for item in iterator:
                try:
                    info = item.stat(follow_symlinks=False)
                except OSError:
                    continue
                if (stat.S_ISLNK(info.st_mode)
                        or getattr(info, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT):
                    continue
                entries.append(Entry(item.name, stat.S_ISDIR(info.st_mode), stat.S_ISREG(info.st_mode)))
        # A folder swapped for a junction during the listing is refused.
        self.check_chain(directory)
        return entries

    def read_file(self, path: Path, limit: int) -> bytes | None:
        """Bytes of a regular file up to ``limit``; None if it does not exist."""
        try:
            fd = self.open_read(path)
        except FileNotFoundError:
            return None
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("only regular files can be used")
            data = os.read(fd, limit + 1)
        finally:
            os.close(fd)
        if len(data) > limit:
            raise ValueError(f"the file exceeds the {limit // 1024} KiB limit")
        return data

    def ensure_folders(self, directory: Path, create: tuple[str, ...]) -> None:
        current = self.root
        walked = Path()
        for part in Path(directory).relative_to(self.root).parts:
            current, walked = current / part, walked / part
            if is_link(current):
                raise OSError("symlinks and junctions are not followed inside the workspace")
            if not current.exists():
                if walked.as_posix() not in create:
                    raise FileNotFoundError(str(walked))
                os.mkdir(current)
        self.check_chain(directory)

    def replace(self, target: Path, data: bytes, before: bytes | None,
                current_reader: Callable[[], bytes | None]) -> None:
        """Atomically replace ``target`` if ``current_reader()`` still returns ``before``."""
        if current_reader() != before:
            raise ValueError("the file changed during approval; nothing was written")
        temporary = target.parent / f".{target.name}.isycode-{secrets.token_hex(6)}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _OPEN_EXTRA, 0o600)
        created = True
        try:
            try:
                if not self._inside(self._final_path(fd)):
                    raise OSError("the target folder resolved outside the workspace")
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view):]
                os.fsync(fd)
            finally:
                os.close(fd)
            self.check_chain(target.parent)
            if is_link(target):
                raise OSError("symlinks and junctions are not followed inside the workspace")
            os.replace(temporary, target)
            created = False
        finally:
            if created:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
        if self.read_file(target, max(len(data), 1)) != data:
            raise OSError("the written file could not be verified inside the workspace")

    def move(self, source: Path, destination: Path, create: tuple[str, ...]) -> None:
        """Hard-link then unlink so an existing destination is never replaced."""
        self.ensure_folders(destination.parent, create)
        fd = self.open_read(source)
        os.close(fd)
        self.check_chain(destination.parent)
        os.link(source, destination, follow_symlinks=False)
        try:
            fd = self.open_read(destination)
            os.close(fd)
            self.check_chain(source)
        except BaseException:
            os.unlink(destination)
            raise
        os.unlink(source)

    def remove(self, target: Path) -> None:
        self.check_chain(target)
        os.unlink(target)


__all__ = ["Entry", "VerifiedFS", "default_final_path", "is_link", "use_verified_fs"]
