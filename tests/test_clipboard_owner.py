"""Copy on select: owned, granted, journaled without the text, never from the model."""
import ast
from pathlib import Path

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.clipboard_owner import CLIPBOARD_TARGET, ClipboardOwner
from isycode.workspace_authority import WorkspaceAuthority

SOURCE = Path(__file__).resolve().parents[1] / "src" / "isycode" / "tui.py"


@pytest.fixture
def owner(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "project"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    written = []
    tool = tmp_path / "fake-copy"
    tool.write_text(f"#!/bin/sh\ncat > {tmp_path / 'clip.txt'}\n")
    tool.chmod(0o755)
    return (ClipboardOwner(root, authority, command_finder=lambda: [str(tool)]), authority,
            written, tmp_path / "clip.txt", root.resolve())


def test_copy_needs_the_grant(owner):
    clipboard, authority, written, clip, _ = owner
    outcome = clipboard.copy("hello", source="selection", terminal_write=written.append)
    assert outcome.decision == "DENY" and "grant" in outcome.reason
    assert written == [] and not clip.exists()


def test_copy_uses_the_system_tool_and_never_journals_the_text(owner):
    clipboard, authority, written, clip, root = owner
    authority.set_grant("clipboard.copy", enabled=True, targets=[CLIPBOARD_TARGET])
    secret_looking = "my selected text 12345"
    outcome = clipboard.copy(secret_looking, source="selection", terminal_write=written.append)
    assert outcome.decision == "ALLOW" and outcome.text == "fake-copy"
    assert clip.read_text() == secret_looking and written == [secret_looking]
    assert ActionAuditJournal(root).verify().receipts == 1
    journal = "".join(path.read_text(errors="ignore")
                      for path in Path(ActionAuditJournal(root).path).parent.rglob("*") if path.is_file())
    assert secret_looking not in journal


@pytest.mark.parametrize("text, source", [("", "selection"), ("x", "model"), ("x" * (1024 * 1024 + 1), "selection")])
def test_invalid_copies_are_refused(owner, text, source):
    clipboard, authority, written, _, _ = owner
    authority.set_grant("clipboard.copy", enabled=True, targets=[CLIPBOARD_TARGET])
    assert clipboard.copy(text, source=source, terminal_write=written.append).decision == "DENY"
    assert written == []


def _methods():
    found = {}
    for path in (SOURCE, *sorted(SOURCE.parent.glob("tui_app_*.py"))):
        source = path.read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name != "TUIApp" and not node.name.endswith("Mixin"):
                continue
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found[item.name] = ast.get_source_segment(source, item)
    return found


def test_every_copy_goes_through_the_owner_and_never_copies_the_key_field():
    methods = _methods()
    assert "_copy_through_owner" in methods["copy_to_clipboard"]
    assert "_copy_through_owner" in methods["on_text_selected"]
    helper = methods["_copy_through_owner"]
    assert helper.index('"#provider-key-input"') < helper.index("owner.copy(")
    assert "API keys are never copied" in helper
    # The model has no clipboard tool.
    assert "clipboard" not in methods["_dispatch_chat_tool"]
