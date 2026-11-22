"""Exact copy, reduced-motion and keyboard regressions found on PR 112."""
import asyncio
from types import SimpleNamespace

from rich.text import Text
from textual.app import App
from textual.containers import Vertical

from isycode.file_preview import FilePreviewScreen
from isycode.tui import TUIApp
from isycode.tui_copy import CopyMenuScreen
from isycode.tui_widgets import (
    CommandOutputCard, ExpandableBox, SelectableText, ToolActivityGroup,
)
from test_daily_tui import configure


def test_wide_character_mouse_copy_keeps_exact_cells():
    copied = []

    class Host(App):
        def compose(self):
            yield SelectableText(Text("界ab"), id="body")

        async def _request_clipboard_copy(self, text, source):
            copied.append((text, source))

    async def scenario():
        async with Host().run_test(size=(80, 24)) as pilot:
            body = pilot.app.query_one("#body")
            await pilot.mouse_down(body, offset=(0, 0))
            await pilot.hover(body, offset=(3, 0))
            await pilot.mouse_up(body, offset=(3, 0))
            await pilot.press("ctrl+c")
            await pilot.pause()
            assert copied == [("界a", "selection")], copied

    asyncio.run(scenario())


def test_double_click_does_not_borrow_another_boxs_selection():
    class Host(App):
        def compose(self):
            with Vertical():
                yield SelectableText(Text("one"), id="first")
                yield SelectableText(Text("two"), id="second")

    async def scenario():
        async with Host().run_test(size=(80, 24)) as pilot:
            first = pilot.app.query_one("#first")
            second = pilot.app.query_one("#second")
            await pilot.mouse_down(first, offset=(0, 0))
            await pilot.hover(first, offset=(3, 0))
            await pilot.mouse_up(first, offset=(3, 0))
            assert first.screen.selections
            await pilot.click(second, times=2)
            await pilot.pause()
            assert isinstance(pilot.app.screen, CopyMenuScreen)
            assert pilot.app.screen.selected == "", repr(pilot.app.screen.selected)

    asyncio.run(scenario())


def test_reduced_motion_disables_command_spinner():
    class Host(App):
        _reduced_motion = True

        def compose(self):
            yield CommandOutputCard("echo test")

    async def scenario():
        async with Host().run_test(size=(80, 24)) as pilot:
            card = pilot.app.query_one(CommandOutputCard)
            await pilot.pause()
            assert card._spinner_timer is None
            before = (card._spinner_idx, str(card.border_subtitle))
            card._tick_spinner()
            assert (card._spinner_idx, str(card.border_subtitle)) == before

    asyncio.run(scenario())


def test_tool_group_spinner_starts_for_initial_running_leaf():
    class Host(App):
        _reduced_motion = False

        def compose(self):
            leaf = ExpandableBox(SelectableText("output"), title="read", collapsed=False)
            yield ToolActivityGroup("workspace_read", leaf, "workspace_read")

    async def scenario():
        async with Host().run_test(size=(80, 24)) as pilot:
            group = pilot.app.query_one(ToolActivityGroup)
            await pilot.pause()
            assert group._running_leaves
            assert group._spinner_timer is not None

    asyncio.run(scenario())


def test_reduced_motion_disables_tool_group_spinner():
    class Host(App):
        _reduced_motion = True

        def compose(self):
            leaf = ExpandableBox(SelectableText("output"), title="read", collapsed=False)
            yield ToolActivityGroup("workspace_read", leaf, "workspace_read")

    async def scenario():
        async with Host().run_test(size=(80, 24)) as pilot:
            group = pilot.app.query_one(ToolActivityGroup)
            await pilot.pause()
            group._check_spinner()
            assert group._spinner_timer is None
            before = (group._spinner_idx, str(group.title))
            group._tick_spinner()
            assert (group._spinner_idx, str(group.title)) == before

    asyncio.run(scenario())


def test_motion_toggle_syncs_existing_spinners(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            chat = app.query_one("ChatArea")
            card = CommandOutputCard("echo test")
            leaf = ExpandableBox(SelectableText("output"), title="read", collapsed=False)
            group = ToolActivityGroup("workspace_read", leaf, "workspace_read")
            await chat.mount(card, group)
            await pilot.pause()
            assert card._spinner_timer is not None
            assert group._spinner_timer is not None
            app._reduced_motion = False
            app._menu_motion_toggle({})
            assert app._reduced_motion is True
            assert card._spinner_timer is None and group._spinner_timer is None
            app._menu_motion_toggle({})
            assert app._reduced_motion is False
            assert card._spinner_timer is not None and group._spinner_timer is not None

    asyncio.run(scenario())


def test_f2_opens_copy_menu_for_focused_readonly_modal_preview(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            app.push_screen(FilePreviewScreen("notes.txt", "one\ntwo\n"))
            await pilot.pause()
            assert isinstance(app.screen, FilePreviewScreen)
            assert app.screen.focused is app.screen.query_one("#preview-text")
            await pilot.press("f2")
            await pilot.pause()
            assert isinstance(app.screen, CopyMenuScreen), type(app.screen).__name__

    asyncio.run(scenario())


def test_image_attachment_toast_names_the_real_review_shortcut(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    class Owner:
        def __init__(self, *args):
            pass

        def paste(self):
            import base64
            png = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1sAAAAASUVORK5CYII="
            )
            return SimpleNamespace(decision="ALLOW", reason=""), "image/png", png

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            messages = []
            app.notify = lambda message, **kwargs: messages.append(str(message))

            async def approve(*args):
                return True

            app._await_screen = approve
            monkeypatch.setattr("isycode.tui.ClipboardOwner", Owner)
            prompt = app.query_one("#prompt-input")
            await app._request_clipboard_paste(prompt)
            assert any("Ctrl+Shift+P reviews attachments" in message for message in messages), messages

    asyncio.run(scenario())
