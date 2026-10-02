from pathlib import Path
import asyncio

import pytest

from isycode import file_picker
from isycode.file_picker import (ContextFilePickerOwner, build_linux_file_picker_command,
                                 choose_context_file)


def test_zenity_picker_opens_native_markdown_and_text_filter(tmp_path: Path):
    command = build_linux_file_picker_command("/usr/bin/zenity", tmp_path)

    assert command[:3] == ["/usr/bin/zenity", "--file-selection", "--title=Elegir archivo de contexto"]
    assert "--file-filter=Context documents | *.md *.txt" in command


def test_kdialog_picker_starts_at_launch_directory(tmp_path: Path):
    command = build_linux_file_picker_command("/usr/bin/kdialog", tmp_path)

    assert command == [
        "/usr/bin/kdialog", "--title", "Elegir archivo de contexto",
        "--getopenfilename", str(tmp_path), "*.md *.txt",
    ]


def test_unknown_picker_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="unsupported"):
        build_linux_file_picker_command("/usr/bin/file-dialog", tmp_path)


def test_context_owner_accepts_only_plain_markdown_or_text_in_workspace(tmp_path, monkeypatch):
    from isycode.file_picker import FilePickerUnavailable
    root = tmp_path / "workspace"
    root.mkdir()
    selected = root / "AGENTS.md"
    selected.write_text("context")
    owner = ContextFilePickerOwner(root)
    async def select(_root):
        return selected
    monkeypatch.setattr("isycode.file_picker.choose_context_file", select)

    async def choose():
        return await owner.choose()
    assert asyncio.run(choose()) == selected

    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    async def select_outside(_root):
        return outside
    monkeypatch.setattr("isycode.file_picker.choose_context_file", select_outside)
    with pytest.raises(FilePickerUnavailable, match="this workspace or a direct sibling project"):
        asyncio.run(choose())

    binaryish = root / "notes.pdf"
    binaryish.write_text("not allowed")
    async def select_binaryish(_root):
        return binaryish
    monkeypatch.setattr("isycode.file_picker.choose_context_file", select_binaryish)
    with pytest.raises(FilePickerUnavailable, match="this workspace or a direct sibling project"):
        asyncio.run(choose())


def test_context_picker_runs_only_fixed_native_chooser_argv(tmp_path, monkeypatch):
    selected = tmp_path / "AGENTS.md"
    calls = []
    async def fake_run(argv, timeout):
        calls.append((argv, timeout))
        return selected
    monkeypatch.setattr("isycode.file_picker._run_picker", fake_run)
    monkeypatch.setattr("isycode.file_picker.sys.platform", "linux")
    monkeypatch.setattr("isycode.file_picker.shutil.which", lambda name: "/usr/bin/zenity" if name == "zenity" else None)
    assert asyncio.run(file_picker.choose_context_file(tmp_path)) == selected
    assert calls[0][0][0] == "/usr/bin/zenity"
    assert calls[0][1] == 300.0
