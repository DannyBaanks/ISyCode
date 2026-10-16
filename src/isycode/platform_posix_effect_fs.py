"""Descriptor-bound file effects used by staging and durable recovery."""
from __future__ import annotations

import hashlib
import os
import secrets
import stat
from pathlib import Path


def open_parent(root: Path, relative: str, *, create: bool = False) -> int:
    """Walk a relative parent from the root without following directory links."""
    parts = Path(relative).parts
    if (not parts or Path(relative).is_absolute()
            or any(part in {"", ".", ".."} for part in parts)):
        raise OSError("effect path escapes the workspace")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(root, flags)
    try:
        for part in parts[:-1]:
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o755, dir_fd=descriptor)
                os.fsync(descriptor)
                child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def read_at(parent: int, name: str) -> tuple[bytes, int] | None:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    try:
        descriptor = os.open(name, flags, dir_fd=parent)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("effect target is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read()
        return payload, stat.S_IMODE(info.st_mode)
    finally:
        os.close(descriptor)


def read_file(root: Path, relative: str) -> tuple[bytes, int] | None:
    try:
        parent = open_parent(root, relative)
    except FileNotFoundError:
        return None
    try:
        return read_at(parent, Path(relative).name)
    finally:
        os.close(parent)


def digest(current: tuple[bytes, int] | None) -> str | None:
    return None if current is None else hashlib.sha256(current[0]).hexdigest()


def apply_file(root: Path, relative: str, payload: bytes | None, *,
               expected: str | None, mode: int = 0o644,
               expected_mode: int | None = None) -> None:
    """Apply only a matching preimage; never open an existing temporary file.

    The final preimage check detects edits arriving after the plan snapshot.
    A simultaneous external writer after that check cannot be serialized by a
    userspace hash check; no universal filesystem compare-and-swap is claimed.
    """
    parent = open_parent(root, relative, create=payload is not None)
    name = Path(relative).name
    temporary = ".isycode-effect-" + secrets.token_hex(16) + ".tmp"
    created = False
    try:
        current = read_at(parent, name)
        if digest(current) != expected or (expected_mode is not None
                and current is not None and current[1] != expected_mode):
            raise OSError("effect preimage changed; user content was preserved")
        if payload is not None:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                 | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
            created = True
            try:
                view = memoryview(payload)
                while view:
                    view = view[os.write(descriptor, view):]
                os.fchmod(descriptor, mode)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        # Confirm the parent path still names the directory held by our handle.
        fresh_parent = open_parent(root, relative)
        try:
            old_info, fresh_info = os.fstat(parent), os.fstat(fresh_parent)
            if (old_info.st_dev, old_info.st_ino) != (fresh_info.st_dev, fresh_info.st_ino):
                raise OSError("effect parent changed; user content was preserved")
        finally:
            os.close(fresh_parent)
        if read_at(parent, name) != current:
            raise OSError("effect preimage changed; user content was preserved")
        if payload is None:
            if current is not None:
                os.unlink(name, dir_fd=parent)
        elif current is None:
            # Unlike replace, link refuses a concurrently-created destination.
            os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent,
                    follow_symlinks=False)
            os.unlink(temporary, dir_fd=parent)
            created = False
        else:
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            created = False
        os.fsync(parent)
        result = read_at(parent, name)
        if (result is not None if payload is None else
                result is None or result[0] != payload or result[1] != mode):
            raise OSError("effect result could not be verified")
    finally:
        if created:
            os.unlink(temporary, dir_fd=parent)
        os.close(parent)
