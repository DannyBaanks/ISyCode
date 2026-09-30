"""@file mentions and custom slash commands only change the prompt; reads stay owned."""
import ast
from pathlib import Path

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import LocalWorkspaceReadOwner
from isycode.prompt_expansion import (
    MAX_MENTIONS, attach_files, find_mentions, load_user_commands, parse_command,
    read_result_text, render_command,
)
from isycode.workspace_authority import WorkspaceAuthority


def test_mentions_ignore_emails_and_trailing_punctuation():
    text = "look at @src/app.py, and @./README.md. mail me at dev@example.com @src/app.py"
    assert find_mentions(text) == ["src/app.py", "README.md"]
    many = " ".join(f"@f{index}.py" for index in range(10))
    assert len(find_mentions(many)) == MAX_MENTIONS


def test_attached_files_are_marked_as_data():
    text = attach_files("fix it", [("a.py", "x = 1")])
    assert text.startswith("fix it\n") and "not instructions" in text
    assert '<file path="a.py">\nx = 1\n</file>' in text
    assert attach_files("same", []) == "same"


def test_read_result_text_tolerates_truncated_output():
    assert read_result_text('{"path": "a", "text": "hi"}') == "hi"
    assert read_result_text('{"path": "a", "text": "h') == '{"path": "a", "text": "h'


def test_commands_render_arguments():
    command = parse_command("review", "# Review code\nReview $ARGUMENTS carefully.", "user")
    assert command.description == "Review code"
    assert render_command(command, " app.py ") == "# Review code\nReview app.py carefully."
    plain = parse_command("tests", "Write tests.", "user")
    assert render_command(plain, "for parser") == "Write tests.\n\nfor parser"
    assert parse_command("Bad Name", "x", "user") is None
    assert parse_command("empty", "   ", "user") is None


def test_user_commands_skip_symlinks_large_files_and_bad_names(tmp_path):
    folder = tmp_path / "commands"
    folder.mkdir()
    (folder / "review.md").write_text("Review $ARGUMENTS")
    (folder / "big.md").write_text("x" * 40_000)
    (folder / "Bad Name.md").write_text("x")
    (folder / "notes.txt").write_text("x")
    (folder / "link.md").symlink_to(folder / "review.md")
    assert sorted(load_user_commands(folder)) == ["review"]
    assert load_user_commands(tmp_path / "missing") == {}


def test_workspace_command_files_need_the_read_grant(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "project"
    (root / ".isycode-commands").mkdir(parents=True)
    (root / ".isycode-commands" / "ship.md").write_text("Ship it")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    owner = LocalWorkspaceReadOwner(root, authority)
    assert owner.execute("workspace.files.read", {"path": ".isycode-commands/ship.md"}).decision == "DENY"
    authority.set_mode("classic")
    outcome = owner.execute("workspace.files.read", {"path": ".isycode-commands/ship.md"})
    assert read_result_text(outcome.text) == "Ship it"
    assert ActionAuditJournal(root.resolve()).verify().receipts == 1


def _methods():
    source = (Path(__file__).parent / "isycode" / "tui.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    return {node.name: ast.get_source_segment(source, node) for node in app.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_tui_reads_mentions_and_workspace_commands_through_the_read_owner():
    methods = _methods()
    for name in ("_expand_mentions", "_run_custom_command"):
        assert 'owner.execute, "workspace.files.read"' in methods[name], name
        assert "read_text(" not in methods[name] and "open(" not in methods[name], name
    assert "text = await self._expand_mentions(text)" in methods["_run_chat"]
    assert "self._run_custom_command(text)" in methods["_accept_prompt"]
