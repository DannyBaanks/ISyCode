"""Optional native fast path for the private action journal (libisyjournal, Zig).

The library lives next to its source in ``isycode/native/`` and is loaded at
run time with ctypes. Its contract is fail-closed toward the Python code that
already exists: when the library is missing, has another ABI version, is
disabled with ``ISYCODE_NATIVE_JOURNAL=0``, or reports anything but a clean
result, callers use the pure-Python path unchanged.

    python -m isycode.native_journal build     # needs zig 0.16 on PATH
    python -m isycode.native_journal status
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

ABI_VERSION = 1
OK, NOT_CANONICAL, BAD_CHAIN, BAD_INPUT = 0, 1, 2, 3

NATIVE_DIR = Path(__file__).resolve().parent / "native"
_LIB_NAMES = {"linux": "libisyjournal.so", "darwin": "libisyjournal.dylib"}


def library_path() -> Path | None:
    name = _LIB_NAMES.get(sys.platform)
    return NATIVE_DIR / name if name else None


class NativeJournal:
    """Thin ctypes wrapper; every call releases the GIL while it runs."""

    def __init__(self, lib: ctypes.CDLL, path: Path):
        self.path = path
        self._write = lib.isyj_write_fsync
        self._write.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t]
        self._write.restype = ctypes.c_int
        self._verify = lib.isyj_verify_chain
        self._verify.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p,
                                 ctypes.POINTER(ctypes.c_uint64),
                                 ctypes.POINTER(ctypes.c_uint64)]
        self._verify.restype = ctypes.c_int

    def write_fsync(self, fd: int, data: bytes) -> None:
        """Write all of ``data`` to ``fd`` and fsync it, or raise OSError."""
        if self._write(fd, data, len(data)) != 0:
            code = ctypes.get_errno() or 5  # EIO when libc left errno unset
            raise OSError(code, os.strerror(code))

    def verify_chain(self, data: bytes, previous: str) -> tuple[int, str, int, int]:
        """(status, last digest, records verified, 1-based bad line)."""
        prev = ctypes.create_string_buffer(previous.encode("ascii"), 64)
        records = ctypes.c_uint64(0)
        bad = ctypes.c_uint64(0)
        status = self._verify(data, len(data), prev, ctypes.byref(records), ctypes.byref(bad))
        return status, prev.raw[:64].decode("ascii"), records.value, bad.value


_lock = threading.Lock()
_loaded: NativeJournal | None = None
_tried = False


def load() -> NativeJournal | None:
    """The native journal helpers, or None when the Python path must be used."""
    global _loaded, _tried
    if os.environ.get("ISYCODE_NATIVE_JOURNAL", "1").strip() == "0":
        return None
    with _lock:
        if _tried:
            return _loaded
        _tried = True
        path = library_path()
        if os.name != "posix" or path is None or not path.is_file():
            return None
        try:
            lib = ctypes.CDLL(str(path), use_errno=True)
            version = lib.isyj_abi_version
            version.restype = ctypes.c_int
            if version() != ABI_VERSION:
                return None
            _loaded = NativeJournal(lib, path)
        except (OSError, AttributeError):
            _loaded = None
        return _loaded


def _reset_for_tests() -> None:
    global _loaded, _tried
    with _lock:
        _loaded, _tried = None, False


def build(optimize: str = "ReleaseSafe") -> Path:
    """Build libisyjournal with zig and place it where ``load`` looks."""
    target = library_path()
    if target is None:
        raise RuntimeError(f"no native journal build for platform {sys.platform}")
    zig = shutil.which("zig")
    if zig is None:
        raise RuntimeError("zig 0.16 is not on PATH")
    subprocess.run([zig, "build", f"-Doptimize={optimize}"], cwd=NATIVE_DIR, check=True)
    built = NATIVE_DIR / "zig-out" / "lib" / target.name
    tmp = target.with_suffix(target.suffix + ".tmp")
    shutil.copyfile(built, tmp)
    os.replace(tmp, target)
    _reset_for_tests()
    return target


def _main(argv: list[str]) -> int:
    command = argv[0] if argv else "status"
    if command == "build":
        print(build())
        return 0
    if command == "status":
        native = load()
        print(f"native journal: {'on ' + str(native.path) if native else 'off (Python path)'}")
        return 0
    print("usage: python -m isycode.native_journal [build|status]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
