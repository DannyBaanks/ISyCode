"""Narrow native file selection for user-selected workspace context."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import stat
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
            "--title=Elegir archivo de contexto",
            "--filename=" + str(initial_directory.expanduser()) + "/",
            "--file-filter=Context documents | *.md *.txt",
        ]
    if name == "kdialog":
        return [
            executable,
            "--title", "Elegir archivo de contexto",
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
            raise FilePickerUnavailable("Instala Zenity o KDE Dialog para elegir un archivo de contexto.")
        argv = build_linux_file_picker_command(executable, initial_directory)
        return await _run_picker(argv, timeout)
    raise FilePickerUnavailable("No native context-file picker is available on this platform.")


async def choose_sibling_workspace_folder(main_directory: Path, *,
                                          timeout: float = 300.0) -> Path | None:
    """Open the OS folder chooser at the workspace parent.

    The result is only a candidate. SiblingFolderPickerOwner and
    WorkspaceFolders.add both validate the exact sibling boundary before any
    workspace grants are written.
    """
    main = main_directory.expanduser().resolve(strict=True)
    if not main.is_dir():
        raise FilePickerUnavailable("The current workspace folder is unavailable.")
    initial_directory = main.parent
    if os.name == "nt":
        return await asyncio.to_thread(_choose_windows_directory, initial_directory)
    if sys.platform.startswith("linux"):
        executable = None
        for name in ("zenity", "kdialog"):
            executable = shutil.which(name)
            if executable:
                break
        if executable is None:
            raise FilePickerUnavailable(
                "Install Zenity or KDE Dialog to choose a sibling project folder.")
        argv = build_linux_directory_picker_command(
            executable, initial_directory, title="Choose sibling project folder")
        return await _run_picker(argv, timeout)
    raise FilePickerUnavailable("No native folder picker is available on this platform.")


async def choose_harness_folder(initial_directory: Path, *, title: str,
                                timeout: float = 300.0) -> Path | None:
    """Open one native folder chooser for Multi Harness. Grants nothing."""
    initial_directory = initial_directory.expanduser().resolve(strict=True)
    if not initial_directory.is_dir():
        raise FilePickerUnavailable("The initial folder is unavailable.")
    if os.name == "nt":
        try:
            return await asyncio.to_thread(
                _choose_windows_directory, initial_directory, title=title)
        except FilePickerUnavailable as exc:
            raise FilePickerUnavailable(f"Folder selection for {title.removeprefix('Choose the folder for ')} failed.") from exc
    if sys.platform.startswith("linux"):
        executable = next((found for name in ("zenity", "kdialog")
                           if (found := shutil.which(name))), None)
        if executable is None:
            harness = title.removeprefix("Choose the folder for ")
            raise FilePickerUnavailable(f"Folder selection for {harness} failed.")
        argv = build_linux_directory_picker_command(executable, initial_directory, title=title)
        try:
            return await _run_picker(argv, timeout)
        except FilePickerUnavailable as exc:
            harness = title.removeprefix("Choose the folder for ")
            raise FilePickerUnavailable(f"Folder selection for {harness} failed.") from exc
    harness = title.removeprefix("Choose the folder for ")
    raise FilePickerUnavailable(f"Folder selection for {harness} failed.")


def _choose_windows_directory(initial_directory: Path, *,
                              title: str = "Choose sibling project folder") -> Path | None:
    """Use Windows' native folder chooser without launching a shell."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
            selected = filedialog.askdirectory(
                title=title,
                initialdir=str(initial_directory), mustexist=True)
        finally:
            root.destroy()
    except (ImportError, OSError, RuntimeError) as exc:
        raise FilePickerUnavailable("Windows native folder picker is unavailable.") from exc
    return Path(selected) if selected else None


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
    """Own a user chooser and constrain the result to this or a sibling project."""

    def __init__(self, workspace_root: Path):
        self.root = workspace_root.expanduser().resolve(strict=True)

    async def choose(self) -> Path | None:
        selected = await choose_context_file(self.root.parent)
        if selected is None:
            return None
        return self.validate(selected)

    def validate(self, selected: Path) -> Path:
        """Return a safe Markdown/text document in this or a direct sibling root."""
        try:
            lexical = Path(os.path.abspath(selected.expanduser()))
            project_root = self._project_root(lexical)
            relative = lexical.relative_to(project_root)
            current = project_root
            for part in relative.parts:
                current = current / part
                if current.is_symlink():
                    raise ValueError
            resolved = lexical.resolve(strict=True)
            relative = resolved.relative_to(project_root)
            if (not resolved.is_file() or resolved.suffix.casefold() not in {".md", ".txt"}
                    or any(part.startswith(".") or part.casefold() in {
                               ".git", ".isycode", ".ssh", ".aws", ".gnupg",
                           }
                           for part in relative.parts)):
                raise ValueError
        except (OSError, RuntimeError, ValueError) as exc:
            raise FilePickerUnavailable(
                "Choose a visible .md or .txt file in this workspace or a direct sibling project.") from exc
        return resolved

    def project_root_for(self, selected: Path) -> Path:
        """Resolve the project root after the same path checks used by validate()."""
        safe_file = self.validate(selected)
        return self._project_root(safe_file)

    def _project_root(self, selected: Path) -> Path:
        lexical = Path(os.path.abspath(selected.expanduser()))
        if lexical == self.root or self.root in lexical.parents:
            return self.root
        if lexical.parent == self.root.parent:
            # A selected sibling root itself is not a document.
            raise ValueError
        for parent in lexical.parents:
            if parent.parent == self.root.parent and parent != self.root:
                if parent.name.startswith(".") or parent.is_symlink():
                    raise ValueError
                return parent.resolve(strict=True)
        raise ValueError


class SiblingFolderPickerOwner:
    """Constrain the native chooser result to one real direct sibling directory."""

    def __init__(self, main_directory: Path):
        self.main = main_directory.expanduser().resolve(strict=True)
        if not self.main.is_dir():
            raise FilePickerUnavailable("The current workspace folder is unavailable.")

    async def choose(self) -> Path | None:
        selected = await choose_sibling_workspace_folder(self.main)
        if selected is None:
            return None
        try:
            lexical = Path(os.path.abspath(selected.expanduser()))
            info = lexical.lstat()
            resolved = lexical.resolve(strict=True)
            if (not stat.S_ISDIR(info.st_mode) or lexical.parent != self.main.parent
                    or lexical == self.main or resolved != lexical
                    or lexical.name.startswith(".")):
                raise ValueError
        except (OSError, RuntimeError, ValueError) as exc:
            raise FilePickerUnavailable(
                "Choose a visible, real project folder directly beside this workspace.") from exc
        return lexical


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
