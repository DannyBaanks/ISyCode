"""No-link paths for private Hive coordination (not workspace authorization)."""
from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from pathlib import Path


def checked_path(root: Path, path: Path) -> Path:
    root = root.absolute()
    path = path.absolute()
    relative = path.relative_to(root)
    if '..' in relative.parts:
        raise ValueError('Hive path traversal')
    for component in (root, *root.parents):
        if component.is_symlink() or getattr(component, "is_junction", lambda: False)():
            raise ValueError('Hive root traverses a symbolic link')
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise ValueError('Hive path traverses a symbolic link')
    return path


@contextmanager
def directory(root: Path, path: Path):
    """Pin directory descriptors on POSIX to prevent parent-link swaps."""
    checked_path(root, path)
    if os.name == 'nt':
        yield None
        return
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(root, flags)
    try:
        for part in path.absolute().relative_to(root.absolute()).parts:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def read_message(root: Path, path: Path, limit: int = 2000000) -> str:
    checked_path(root, path)
    with directory(root, path.parent) as parent:
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        fd = os.open(path if parent is None else path.name, flags, **({} if parent is None else {'dir_fd': parent}))
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('Hive messages must be regular files')
            raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Oversized Hive message')
    return raw.decode('utf-8')


def create_message(root: Path, path: Path, text: str) -> bool:
    """Exclusive delivery preserves an existing message instead of overwriting it."""
    checked_path(root, path)
    with directory(root, path.parent) as parent:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        try:
            fd = os.open(path if parent is None else path.name, flags, 0o600,
                         **({} if parent is None else {'dir_fd': parent}))
        except FileExistsError:
            return False
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
    return True
