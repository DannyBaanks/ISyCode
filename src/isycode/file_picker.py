"""Narrow native file selection for user-selected workspace context."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import sys


class FilePickerUnavailable(RuntimeError):
    """No supported desktop file chooser is available in this session."""


def build_linux_file_picker_command(executable: str, initial_directory: Path) -> list[str]:
    """Build a shell-free chooser command for the supported Linux desktops."""
    name = Path(executable).name.casefold()
    if name == "zenity":
        return [
            executable,
            "--file-selection",
            "--title=Choose context file",
            "--filename=" + str(initial_directory.expanduser()) + "/",
            "--file-filter=Context documents | *.md *.txt",
        ]
    if name == "kdialog":
        return [
            executable,
            "--title", "Choose context file",
            "--getopenfilename", str(initial_directory.expanduser()),
            "*.md *.txt",
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
    """Open one native chooser, returning only a selected .md/.txt path.

    This chooser never reads file contents. ContextFilePickerOwner applies the
    workspace boundary, then LocalWorkspaceReadOwner reads the selected text.
    """
    initial_directory = initial_directory.expanduser().resolve(strict=True)
    if not initial_directory.is_dir():
        raise FilePickerUnavailable("The workspace folder is unavailable.")
    if os.name == "nt":
        # Tk's Windows backend uses the native Common Item Dialog. No shell or
        # user-derived command text is involved.
        return await asyncio.to_thread(_choose_windows_file, initial_directory)
    if sys.platform.startswith("linux"):
        executable = None
        for name in ("zenity", "kdialog"):
            executable = shutil.which(name)
            if executable:
                break
        if executable is None:
            raise FilePickerUnavailable("Install Zenity or KDE Dialog to choose a context file.")
        argv = build_linux_file_picker_command(executable, initial_directory)
        return await _run_picker(argv, timeout)
    raise FilePickerUnavailable("No native context-file picker is available on this platform.")


def _choose_windows_file(initial_directory: Path) -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
            selected = filedialog.askopenfilename(
                title="Choose context file", initialdir=str(initial_directory),
                filetypes=(("Markdown and text", "*.md *.txt"), ("All files", "*.*")))
        finally:
            root.destroy()
    except (ImportError, OSError, RuntimeError) as exc:
        raise FilePickerUnavailable("Windows native file picker is unavailable.") from exc
    return Path(selected) if selected else None


async def _run_picker(argv: list[str], timeout: float) -> Path | None:
    if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > 600:
        raise ValueError("file picker timeout is outside the allowed range")
    process = None
    try:
        desktop_environment = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()),
                               "LANG": os.environ.get("LANG", "C.UTF-8")}
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR",
                     "DBUS_SESSION_BUS_ADDRESS", "XAUTHORITY"):
            value = os.environ.get(name)
            if value:
                desktop_environment[name] = value
        process = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env=desktop_environment)
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        raise FilePickerUnavailable("Context-file selection timed out.") from exc
    except asyncio.CancelledError:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        raise
    except OSError as exc:
        raise FilePickerUnavailable("Could not open the native context-file picker.") from exc
    if process.returncode != 0:
        return None
    try:
        selected = output.decode("utf-8").strip()
    except UnicodeError as exc:
        raise FilePickerUnavailable("The selected path is not valid UTF-8.") from exc
    return Path(selected) if selected else None


class ContextFilePickerOwner:
    """Own the explicit chooser gesture and constrain its result to one document."""

    def __init__(self, workspace_root: Path):
        self.root = workspace_root.expanduser().resolve(strict=True)

    async def choose(self) -> Path | None:
        selected = await choose_context_file(self.root)
        if selected is None:
            return None
        try:
            lexical = Path(os.path.abspath(selected.expanduser()))
            relative = lexical.relative_to(self.root)
            current = self.root
            for part in relative.parts:
                current = current / part
                if current.is_symlink():
                    raise ValueError
            resolved = lexical.resolve(strict=True)
            relative = resolved.relative_to(self.root)
            if (not resolved.is_file() or resolved.suffix.casefold() not in {".md", ".txt"}
                    or any(part.casefold() in {".git", ".isycode", ".ssh", ".aws", ".gnupg"}
                           for part in relative.parts)):
                raise ValueError
        except (OSError, RuntimeError, ValueError) as exc:
            raise FilePickerUnavailable("Choose a .md or .txt file inside this workspace.") from exc
        return resolved


async def choose_workspace_file(initial_directory: Path, *, title: str = "Choose a workspace file",
                                pattern: str = "*", timeout: float = 300.0) -> Path | None:
    """Fail closed until a Workspace Authority and approval owner is wired."""
    del initial_directory, title, pattern, timeout
    raise FilePickerUnavailable(
        "Native file picking is blocked in Secure until an execution owner is connected.")


async def choose_workspace_directory(initial_directory: Path, *, title: str = "Choose a workspace folder",
                                     timeout: float = 300.0) -> Path | None:
    """Fail closed until a Workspace Authority and approval owner is wired."""
    del initial_directory, title, timeout
    raise FilePickerUnavailable(
        "Native file picking is blocked in Secure until an execution owner is connected.")
