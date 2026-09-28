"""Native Linux file selection for explicit context-file import."""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path


class FilePickerUnavailable(RuntimeError):
    """No supported desktop file chooser is available in this session."""


def build_linux_file_picker_command(executable: str, initial_directory: Path) -> list[str]:
    """Build a shell-free chooser command for the supported Linux desktops."""
    name = Path(executable).name.casefold()
    if name == "zenity":
        return [
            executable,
            "--file-selection",
            "--title=Choose AGENTS.md or AGENT.md",
            "--filename=" + str(initial_directory.expanduser()) + "/",
            "--file-filter=Agent instructions | AGENTS.md AGENT.md",
        ]
    if name == "kdialog":
        return [
            executable,
            "--title", "Choose AGENTS.md or AGENT.md",
            "--getopenfilename", str(initial_directory.expanduser()),
            "AGENTS.md AGENT.md",
        ]
    raise ValueError(f"unsupported Linux file picker: {name}")


def build_linux_workspace_picker_command(executable: str, initial_directory: Path,
                                         *, title: str, pattern: str = "*") -> list[str]:
    """Build a native open-file dialog without requiring a typed path."""
    name = Path(executable).name.casefold()
    if name == "zenity":
        return [
            executable, "--file-selection", f"--title={title}",
            "--filename=" + str(initial_directory.expanduser()) + "/",
            f"--file-filter=Workspace files | {pattern}",
        ]
    if name == "kdialog":
        return [executable, "--title", title, "--getopenfilename",
                str(initial_directory.expanduser()), pattern]
    raise ValueError(f"unsupported Linux file picker: {name}")


def build_linux_directory_picker_command(executable: str, initial_directory: Path,
                                         *, title: str) -> list[str]:
    """Build a native directory chooser; callers must still enforce authority."""
    name = Path(executable).name.casefold()
    if name == "zenity":
        return [executable, "--file-selection", "--directory", f"--title={title}",
                "--filename=" + str(initial_directory.expanduser()) + "/"]
    if name == "kdialog":
        return [executable, "--title", title, "--getexistingdirectory",
                str(initial_directory.expanduser())]
    raise ValueError(f"unsupported Linux directory picker: {name}")


async def choose_context_file(initial_directory: Path, *, timeout: float = 300.0) -> Path | None:
    """Open Zenity/KDialog and return the selected path, or None on cancel."""
    if not sys.platform.startswith("linux"):
        raise FilePickerUnavailable("The native context-file picker is currently Linux-only.")
    executable = shutil.which("zenity") or shutil.which("kdialog")
    if executable is None:
        raise FilePickerUnavailable(
            "Install Zenity or KDialog to choose a file from the desktop browser.")
    directory = initial_directory.expanduser().resolve()
    if not directory.is_dir():
        directory = Path.home()
    command = build_linux_file_picker_command(executable, directory)
    return await _run_picker(command, timeout=timeout)


async def choose_workspace_file(initial_directory: Path, *, title: str = "Choose a workspace file",
                                pattern: str = "*", timeout: float = 300.0) -> Path | None:
    """Open the Linux file browser for a user-selected workspace file."""
    if not sys.platform.startswith("linux"):
        raise FilePickerUnavailable("The native file picker is currently Linux-only.")
    executable = shutil.which("zenity") or shutil.which("kdialog")
    if executable is None:
        raise FilePickerUnavailable(
            "Install Zenity or KDialog to choose a file from the desktop browser.")
    directory = initial_directory.expanduser().resolve()
    if not directory.is_dir():
        directory = Path.home()
    command = build_linux_workspace_picker_command(
        executable, directory, title=title[:120], pattern=pattern[:120])
    return await _run_picker(command, timeout=timeout)


async def choose_workspace_directory(initial_directory: Path, *, title: str = "Choose a workspace folder",
                                     timeout: float = 300.0) -> Path | None:
    """Open Linux's directory browser; a picker selection is not a grant."""
    if not sys.platform.startswith("linux"):
        raise FilePickerUnavailable("The native directory picker is currently Linux-only.")
    executable = shutil.which("zenity") or shutil.which("kdialog")
    if executable is None:
        raise FilePickerUnavailable("Install Zenity or KDialog to choose a workspace folder.")
    directory = initial_directory.expanduser().resolve()
    if not directory.is_dir():
        directory = Path.home()
    command = build_linux_directory_picker_command(executable, directory, title=title[:120])
    return await _run_picker(command, timeout=timeout)


async def _run_picker(command: list[str], *, timeout: float) -> Path | None:
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        if "process" in locals() and process.returncode is None:
            process.kill()
            await process.wait()
        raise FilePickerUnavailable("The file chooser did not respond before its timeout.") from exc
    except OSError as exc:
        raise FilePickerUnavailable("Could not open the Linux file chooser.") from exc

    if process.returncode == 1:
        return None
    if process.returncode != 0:
        raise FilePickerUnavailable("The Linux file chooser could not complete.")
    selected = os.fsdecode(output.rstrip(b"\r\n"))
    if not selected:
        return None
    return Path(selected)
