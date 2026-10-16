"""Decision content stays reviewable while explicit actions remain reachable."""
import asyncio
from pathlib import Path

import pytest
from textual.app import App
from textual.containers import VerticalScroll
from textual.document._document import Selection
from textual.widgets import Button, Input, OptionList, TextArea

from isycode.command_runner import CommandPreview
from isycode.security import ActionRequest
from isycode.tui_screens_approval import CommandApprovalScreen, LocalMCPConfirmScreen
from isycode.tui_screens_grants import (
    AddCredentialScreen, GrantProviderNetworkScreen, WorkspaceModeScreen,
)
from isycode.file_preview import FilePreviewScreen


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    for name, subdir in (("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "state"),
                         ("XDG_DATA_HOME", "data"), ("ISYCODE_STATE_HOME", "isycode")):
        monkeypatch.setenv(name, str(tmp_path / subdir))


class Host(App):
    def __init__(self, screen):
        super().__init__()
        self.dialog = screen
        self.results = []
        self.copied = []

    def on_mount(self):
        self.push_screen(self.dialog, self.results.append)

    async def _request_clipboard_copy(self, text, source):
        # External clipboard transport is intentionally a fixture boundary.
        self.copied.append((text, source))


def assert_visible(widget, size):
    region = widget.region
    assert region.width > 0 and region.height > 0
    assert region.x >= 0 and region.y >= 0
    assert region.right <= size[0] and region.bottom <= size[1], region


@pytest.mark.parametrize("size", [(80, 24), (100, 30), (140, 40)])
def test_long_command_review_scrolls_without_hiding_either_decision(tmp_path, size):
    # A clipped argv or a tall action row would make the exact final argument
    # unreadable or the explicit reject/run buttons inaccessible.
    argv = ("echo",) + tuple("argument_" + "x" * 70 for _ in range(30)) + ("FINAL_ARGUMENT",)
    request = ActionRequest("workspace.command.run", tmp_path, "/usr/bin/echo",
                            {"argv": list(argv)}, execution_owner="workspace_command")
    preview = CommandPreview(request, argv, "/usr/bin/echo", ".", 120, (), "tests")

    async def scenario():
        app = Host(CommandApprovalScreen(preview))
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            screen = app.screen
            body = screen.query_one(".isy-dialog-body", VerticalScroll)
            assert body.max_scroll_y > 0
            assert_visible(screen.query_one("#command-approval-reject"), size)
            assert_visible(screen.query_one("#command-approval-run"), size)
            assert screen.focused.id == "command-approval-reject"
            body.focus()
            for _ in range(100):
                if screen.focused is body:
                    break
                await pilot.pause(.05)
            assert screen.focused is body
            await pilot.press("end")
            for _ in range(100):
                if body.scroll_y > 0:
                    break
                await pilot.pause(.05)
            assert body.scroll_y > 0
            await pilot.click("#command-approval-run")
            await pilot.pause()
            assert app.results == [True]

    asyncio.run(scenario())


@pytest.mark.parametrize("decision, expected", [("enter", False), ("escape", False), ("y", True)])
def test_long_mcp_review_keeps_default_reject_and_explicit_approval(decision, expected):
    async def scenario():
        app = Host(LocalMCPConfirmScreen("Review one tool call", "scope " * 150,
                                         "payload\n" * 60, "Call once"))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert_visible(app.screen.query_one("#local-mcp-cancel"), (80, 24))
            assert_visible(app.screen.query_one("#local-mcp-approve"), (80, 24))
            await pilot.press(decision)
            await pilot.pause()
            assert app.results == [expected]
    asyncio.run(scenario())


def test_long_network_target_is_scrollable_and_cancel_does_not_grant():
    async def scenario():
        app = Host(GrantProviderNetworkScreen("Provider " * 35, "long-host.example/" * 60))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            body = app.screen.query_one(".isy-dialog-body", VerticalScroll)
            assert body.max_scroll_y > 0
            assert_visible(app.screen.query_one("#provider-network-cancel"), (80, 24))
            assert_visible(app.screen.query_one("#provider-network-confirm"), (80, 24))
            await pilot.press("enter")
            await pilot.pause()
            assert app.results == [False]
    asyncio.run(scenario())


def test_workspace_mode_continue_applies_focused_choice_without_implicit_change(tmp_path):
    async def scenario():
        app = Host(WorkspaceModeScreen(tmp_path))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.press("down")
            assert app.results == []
            assert_visible(app.screen.query_one("#workspace-mode-continue"), (80, 24))
            await pilot.click("#workspace-mode-continue")
            await pilot.pause()
            assert app.results == ["security"]
    asyncio.run(scenario())


def test_credential_form_keeps_save_cancel_visible_and_secret_masked():
    async def scenario():
        app = Host(AddCredentialScreen())
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert_visible(app.screen.query_one("#credential-save"), (80, 24))
            assert_visible(app.screen.query_one("#credential-cancel"), (80, 24))
            secret = app.screen.query_one("#credential-secret", Input)
            assert secret.password
            secret.value = "never-echo-this-key"
            await pilot.press("escape")
            await pilot.pause()
            assert app.results == [None]
    asyncio.run(scenario())


def test_file_preview_preserves_exact_selection_and_separate_whole_box_copy(tmp_path):
    text = "  one\tα  \n two β \n" + "long line " * 80

    async def scenario():
        app = Host(FilePreviewScreen(tmp_path / "notes.txt", text))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            for selector in ("#preview-copy", "#preview-copy-whole", "#preview-close"):
                assert_visible(app.screen.query_one(selector), (80, 24))
            editor = app.screen.query_one(TextArea)
            assert editor.read_only
            assert app.screen.query_one("#preview-copy", Button).disabled
            editor.selection = Selection((1, 6), (0, 2))
            await pilot.pause()
            await pilot.click("#preview-copy")
            await pilot.pause()
            assert app.copied == [("one\tα  \n two β", "selection")]
            await pilot.click("#preview-copy-whole")
            await pilot.pause()
            assert app.copied[-1] == (text, "content_box")
            await pilot.press("escape")
            await pilot.pause()
            assert app.results == [None]
    asyncio.run(scenario())


def test_write_review_keeps_long_changed_lines_and_all_actions_at_80_columns(tmp_path):
    from rich.console import Console
    from io import StringIO
    from isycode.tui_screens_approval import WriteApprovalScreen
    from isycode.workspace_write import WritePreview

    old = "old_value = " + "x" * 90 + "_OLD_END"
    new = "new_value = " + "y" * 90 + "_NEW_END"
    diff = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-" + old + "\n+" + new + "\n"
    request = ActionRequest("workspace.files.write", tmp_path, "app.py", {},
                            execution_owner="workspace_write")
    preview = WritePreview(request, "app.py", diff, False, new)

    async def scenario():
        app = Host(WriteApprovalScreen(preview, allow_session_trust=True))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            for selector in ("#write-approval-reject", "#write-approval-apply",
                             "#write-approval-session", "#write-approval-always"):
                assert_visible(app.screen.query_one(selector), (80, 24))
            rendered = app.screen.query_one("#write-approval-diff Static").content
            output = StringIO()
            Console(file=output, width=70, color_system=None).print(rendered)
            visible_text = output.getvalue()
            assert "_OLD_END" in visible_text and "_NEW_END" in visible_text
            await pilot.click("#write-approval-apply")
            await pilot.pause()
            assert app.results == [True]
    asyncio.run(scenario())
