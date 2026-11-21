"""Native host paths and shell guidance for Flow's computer-wide tools.

Flow deliberately uses the host namespace, not the POSIX-only sandbox namespace.
Keep drive/UNC handling and the shell example in one place so the model is not
told to run Bash on a Windows computer where it may not exist.
"""
from __future__ import annotations

import os
import string
from pathlib import Path


def flow_path_prefixes(root: Path, *, windows: bool | None = None) -> tuple[str, ...]:
    """Roots covered by Flow's implicit file grants, including every fixed drive.

    POSIX has one filesystem root. Windows has independent drive roots: using
    only ``root.anchor`` silently limits Flow to the launch drive. Drive letters
    are discovered through the native API; a failure falls back to the current
    drive rather than pretending that another drive was covered.
    """
    roots = {str(root.anchor or os.sep)}
    native_windows = os.name == "nt" if windows is None else windows
    if native_windows:  # pragma: no cover - native Windows CI
        import ctypes

        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for index, letter in enumerate(string.ascii_uppercase):
            if mask & (1 << index):
                roots.add(f"{letter}:\\")
    resolved = set()
    for value in roots:
        if windows is True and os.name != "nt" and len(value) == 3 and value[1:] == ":\\":
            # A simulated Windows drive cannot be resolved by a POSIX pathlib;
            # native Windows takes the normal resolve() path below.
            resolved.add(value)
            continue
        try:
            resolved.add(str(Path(value).resolve(strict=False)))
        except (OSError, RuntimeError):
            resolved.add(value)
    return tuple(sorted(resolved, key=lambda item: (item.casefold(), item)))


def shell_example() -> str:
    """An argv example for the native shell, or direct execution if none exists."""
    if os.name == "nt":
        return '["powershell", "-NoProfile", "-Command", "..."]'
    return '["bash", "-c", "..."]'


def shell_name() -> str:
    return "PowerShell" if os.name == "nt" else "bash"


def stdin_description() -> str:
    return "NUL" if os.name == "nt" else "/dev/null"
