"""Handle-verified Windows preimages and recovery effects.

Same-user directory rename races remain the documented VerifiedFS limitation.
No universal filesystem compare-and-swap or hardware power-loss claim.
"""
import hashlib
import os
import secrets
import stat
from pathlib import Path
from isycode.winfs import VerifiedFS


def _target(root, relative):
    path = Path(relative)
    if (not path.parts or path.is_absolute() or path.drive
            or '\\' in relative or '\0' in relative or ':' in relative
            or any(part in {'.', '..'} for part in relative.split('/'))):
        raise OSError('effect path escapes the workspace')
    target = root / path
    VerifiedFS(root).check_chain(target)
    return target


def read_file(root: Path, relative: str):
    target = _target(root, relative)
    fs = VerifiedFS(root)
    try:
        fd = fs.open_read(target)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError('effect target is not a regular file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            return stream.read(), stat.S_IMODE(info.st_mode)
    finally:
        os.close(fd)


def _digest(current):
    return None if current is None else hashlib.sha256(current[0]).hexdigest()


def apply_file(root: Path, relative: str, payload: bytes | None, *,
               expected: str | None, mode: int = 0o644, expected_mode: int | None = None):
    target = _target(root, relative)
    fs = VerifiedFS(root)
    current = read_file(root, relative)
    if _digest(current) != expected or (expected_mode is not None
            and current is not None and current[1] != expected_mode):
        raise OSError('effect preimage changed; user content was preserved')
    if payload is None:
        if current is not None:
            if read_file(root, relative) != current:
                raise OSError('effect preimage changed')
            fs.remove(target)
    else:
        create = tuple(Path(*target.parent.relative_to(root).parts[:i]).as_posix()
                       for i in range(1, len(target.parent.relative_to(root).parts) + 1))
        fs.ensure_folders(target.parent, create)
        if current is None:
            # Exclusive hard-link creation refuses a concurrently-created target.
            temporary = target.parent / ('.isycode-effect-' + secrets.token_hex(16) + '.tmp')
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY, 0o600)
                try:
                    fs._verify_fd(fd, temporary)
                    with os.fdopen(fd, 'wb', closefd=False) as stream:
                        stream.write(payload)
                        stream.flush()
                        os.fsync(fd)
                finally:
                    os.close(fd)
                fs.check_chain(target.parent)
                os.link(temporary, target, follow_symlinks=False)
            finally:
                if temporary.exists():
                    temporary.unlink()
        else:
            def current_reader():
                observed = read_file(root, relative)
                if observed != current:
                    raise OSError('effect preimage changed; user content was preserved')
                return observed[0]
            fs.replace(target, payload, current[0], current_reader)
        # Windows mode only represents the read-only flag, not POSIX privacy.
        target.chmod(mode)
    result = read_file(root, relative)
    if (result is not None if payload is None else
            result is None or result[0] != payload):
        raise OSError('effect result could not be verified')
