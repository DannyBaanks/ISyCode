from pathlib import Path
import asyncio

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


@pytest.mark.parametrize("picker_name", [
    "choose_context_file", "choose_workspace_file", "choose_workspace_directory",
])
def test_native_picker_direct_api_is_denied_until_an_execution_owner_is_connected(
        tmp_path: Path, picker_name: str):
    picker = getattr(file_picker, picker_name)

    with pytest.raises(file_picker.FilePickerUnavailable, match="execution owner"):
        asyncio.run(picker(tmp_path))

    assert not hasattr(file_picker, "_run_picker")
    assert "create_subprocess_exec" not in Path(file_picker.__file__).read_text(encoding="utf-8")
