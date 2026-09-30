"""Native Linux file selection for explicit context-file import."""
from __future__ import annotations

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
    """Fail closed until a Workspace Authority and approval owner is wired."""
    del initial_directory, timeout
    raise FilePickerUnavailable(
        "Native file picking is blocked in Secure until an execution owner is connected.")


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
