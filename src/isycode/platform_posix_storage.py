"""POSIX implementation of private-state storage contracts."""
import fcntl
import os
import stat
from pathlib import Path
from isycode.winfs import is_link


class PosixStorage:
    def delete_private(self, path: Path) -> None:
        if is_link(path):
            raise OSError('private artifact cannot be a link')
        if not self.private(path.parent):
            raise ValueError('private state directory is unsafe')
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                self.lock(fd, blocking=False)
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not self.private(path, fd=fd):
                    raise ValueError('unsafe private artifact')
                os.unlink(path.name, dir_fd=directory)
            finally:
                os.close(fd)
        finally:
            os.close(directory)

    def replace(self, source: Path, destination: Path) -> None:
        os.replace(source, destination)

    def sync_directory(self, path: Path) -> None:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def lock(self, fd: int, *, blocking: bool = True) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))

    def unlock(self, fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)

    def protect(self, path: Path) -> None:
        if is_link(path):
            raise ValueError('private state cannot be a link')
        path.chmod(0o700 if path.is_dir() else 0o600)

    def private(self, path: Path, *, fd: int | None = None) -> bool:
        try:
            if any(is_link(part) for part in (path, *path.parents)):
                return False
            info = os.fstat(fd) if fd is not None else path.lstat()
            return info.st_uid == os.getuid() and not info.st_mode & 0o077
        except OSError:
            return False

    def private_child(self, path: Path, *, fd: int) -> bool:
        # Legacy transcripts may be mode 0644. A private parent prevents
        # unprivileged traversal on POSIX; do not rewrite their data or mode.
        try:
            info, named = os.fstat(fd), path.lstat()
            return (self.private(path.parent) and not is_link(path)
                    and stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and info.st_uid == os.getuid()
                    and (info.st_dev, info.st_ino) == (named.st_dev, named.st_ino))
        except OSError:
            return False

    def ensure_directory(self, path: Path, *, repair: bool = False) -> None:
        if any(is_link(part) for part in (path, *path.parents)):
            raise ValueError('private state cannot traverse links')
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if repair and not is_link(path) and path.stat().st_uid == os.getuid():
            self.protect(path)
        if not path.is_dir() or not self.private(path):
            raise ValueError('private state directory is unsafe')
