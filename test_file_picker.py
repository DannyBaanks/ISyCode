from pathlib import Path
import asyncio
from types import SimpleNamespace

import pytest

from isycode import file_picker
from isycode.file_picker import build_linux_file_picker_command, choose_context_file


def test_zenity_picker_opens_native_agent_markdown_filter(tmp_path: Path):
    command = build_linux_file_picker_command("/usr/bin/zenity", tmp_path)

    assert command[:3] == ["/usr/bin/zenity", "--file-selection", "--title=Choose AGENTS.md or AGENT.md"]
    assert "--file-filter=Agent instructions | AGENTS.md AGENT.md" in command


def test_kdialog_picker_starts_at_launch_directory(tmp_path: Path):
    command = build_linux_file_picker_command("/usr/bin/kdialog", tmp_path)

    assert command == [
        "/usr/bin/kdialog", "--title", "Choose AGENTS.md or AGENT.md",
        "--getopenfilename", str(tmp_path), "AGENTS.md AGENT.md",
    ]


def test_unknown_picker_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="unsupported"):
        build_linux_file_picker_command("/usr/bin/file-dialog", tmp_path)


def test_native_picker_returns_selected_file_without_shell(monkeypatch, tmp_path: Path):
    selected = tmp_path / "AGENTS.md"
    calls = []

    async def communicate():
        return str(selected).encode(), None

    async def create_process(*command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, communicate=communicate)

    monkeypatch.setattr(file_picker.sys, "platform", "linux")
    monkeypatch.setattr(
        file_picker.shutil, "which",
        lambda name: "/usr/bin/zenity" if name == "zenity" else None)
    monkeypatch.setattr(file_picker.asyncio, "create_subprocess_exec", create_process)

    result = asyncio.run(choose_context_file(tmp_path))

    assert result == selected
    assert calls[0][0][0:2] == ("/usr/bin/zenity", "--file-selection")
    assert "shell" not in calls[0][1]
