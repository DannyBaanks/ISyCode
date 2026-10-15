"""Accepted gestures, exact copy ranges and compact TUI regressions."""
import asyncio

import pytest
from rich.markdown import Markdown
from rich.text import Text
from textual.app import App
from textual.geometry import Offset
from textual.selection import Selection
from textual.widgets import Button, Input, OptionList, TextArea

from isycode.tui import TUIApp, PromptArea, Banner
from isycode.tui_copy import CopyMenuScreen, extract_range
from isycode.tui_widgets import ExpandableBox, BoxTitle, SelectableText, ThoughtBlock
from test_daily_tui import configure


@pytest.mark.parametrize("source,start,end,expected", [
    ("  uno  \ndos\ntres\n", (2, 0), (3, 1), "uno  \ndos"),
    ("uno\ndos\ntres\n", (0, 0), (0, 2), "uno\ndos\n"),
    ("\tα界 = 2  \n", (8, 0), (16, 0), "α界 = 2  "),
    ("abc\ndef", (2, 0), (2, 0), ""),
])
def test_exact_logical_ranges(source, start, end, expected):
    selection = Selection.from_offsets(Offset(*end), Offset(*start))
    assert extract_range(source, selection) == expected


def test_drag_two_lines_and_reverse_drag_copy_only_marked_text():
    copied = []
    class Host(App):
        def compose(self):
            yield SelectableText(Text("uno\ndos\ntres\n"), id="body")
        async def _request_clipboard_copy(self, text, source):
            copied.append((text, source))
    async def scenario():
        async with Host().run_test(size=(80, 24)) as pilot:
            body = pilot.app.query_one("#body")
            for start, end in [((0, 0), (2, 1)), ((2, 1), (0, 0))]:
                await pilot.mouse_down(body, offset=start)
                await pilot.hover(body, offset=end)
                await pilot.mouse_up(body, offset=end)
                await pilot.pause()
                assert copied == []
                assert body.screen.selections
                await pilot.press("ctrl+c")
                await pilot.pause()
                assert copied.pop() == ("uno\ndos", "selection")
    asyncio.run(scenario())


def test_markdown_selection_tracks_soft_wrap_and_preserves_code_whitespace():
    copied = []
    source = "```py\n\tx = 2  \n\n```\n\n" + "word " * 40
    class Host(App):
        def compose(self):
            yield SelectableText(Markdown(source), selection_text=source, id="body")
        async def _request_clipboard_copy(self, text, source):
            copied.append((text, source))
    async def scenario():
        async with Host().run_test(size=(30, 24)) as pilot:
            body = pilot.app.query_one("#body")
            await pilot.pause()
            assert body._selection_plain.startswith("\tx = 2  \n\n")
            # Select a soft-wrapped portion with the real compositor's offsets.
            await pilot.mouse_down(body, offset=(0, 4))
            await pilot.hover(body, offset=(5, 5))
            await pilot.mouse_up(body, offset=(5, 5))
            await pilot.press("ctrl+c")
            await pilot.pause()
            assert copied and copied[0][0] == "word " * 7 + "w"
            assert "\n" not in copied[0][0]
    asyncio.run(scenario())


def test_space_only_expansion_copy_menu_snapshot_cancel_and_empty_selection():
    copied = []
    class Host(App):
        def compose(self):
            yield ExpandableBox(SelectableText(Text("one\ntwo\n")), title="Result", collapsed=False)
        async def _request_clipboard_copy(self, text, source):
            copied.append((text, source))
    async def scenario():
        async with Host().run_test(size=(80, 24)) as pilot:
            box = pilot.app.query_one(ExpandableBox)
            title = box.query_one(BoxTitle)
            title.focus()
            await pilot.press("enter")
            assert not box.collapsed
            await pilot.press("space")
            assert box.collapsed
            await pilot.click(title, times=2)
            await pilot.pause()
            assert isinstance(pilot.app.screen, CopyMenuScreen)
            assert box.collapsed and copied == []
            assert pilot.app.screen.query_one("#copy-selection", Button).disabled
            await pilot.press("escape")
            title.focus()
            await pilot.press("space")
            body = box.query_one(SelectableText)
            await pilot.mouse_down(body, offset=(0, 0))
            await pilot.hover(body, offset=(2, 0))
            await pilot.mouse_up(body, offset=(2, 0))
            saved = dict(body.screen.selections)
            await pilot.click(title, times=2)
            await pilot.pause()
            assert pilot.app.screen.selected == "one"
            await pilot.press("escape")
            assert body.screen.selections == saved
            await pilot.click(title, times=2)
            await pilot.click("#copy-selection")
            await pilot.pause()
            assert copied == [("one", "selection")]
            body.screen.selections = {}
            await pilot.click(title, times=2)
            await pilot.click("#copy-whole")
            await pilot.pause()
            assert copied[-1] == ("one\ntwo\n", "content_box")
    asyncio.run(scenario())


def test_space_in_editable_field_does_not_expand_parent():
    class Host(App):
        def compose(self):
            yield ExpandableBox(TextArea("hello"), title="Input", collapsed=False)
    async def scenario():
        async with Host().run_test() as pilot:
            field = pilot.app.query_one(TextArea)
            field.focus()
            await pilot.press("space")
            assert field.text == " hello"
            assert not pilot.app.query_one(ExpandableBox).collapsed
    asyncio.run(scenario())


def test_readonly_double_click_preserves_marked_range_until_copy_or_cancel():
    from isycode.tui_copy import CopyTextArea
    from textual.document._document import Selection as AreaSelection
    copied = []
    class Host(App):
        def compose(self):
            yield CopyTextArea("one\ntwo\nthree\n", read_only=True)
        async def _request_clipboard_copy(self, text, source):
            copied.append((text, source))
    async def scenario():
        async with Host().run_test() as pilot:
            field = pilot.app.query_one(CopyTextArea)
            selected = AreaSelection((0, 0), (2, 0))
            field.selection = selected
            await pilot.click(field, offset=(2, 1), times=2)
            assert isinstance(pilot.app.screen, CopyMenuScreen)
            assert pilot.app.screen.selected == "one\ntwo\n" and copied == []
            await pilot.press("escape")
            assert field.selection == selected
            await pilot.click(field, offset=(2, 1), times=2)
            await pilot.click("#copy-selection", offset=(2, 1))
            await pilot.pause()
            assert copied == [("one\ntwo\n", "selection")]
    asyncio.run(scenario())


@pytest.mark.parametrize("reduced", [False, True])
def test_real_thinking_motion_and_timers_stop_on_completion_and_unmount(reduced):
    class Host(App):
        _reduced_motion = reduced
        def compose(self):
            yield ThoughtBlock()
    async def scenario():
        async with Host().run_test() as pilot:
            block = pilot.app.query_one(ThoughtBlock)
            block._started_at -= 1.1
            block._update_elapsed_title()
            assert str(block.title).startswith("◇" if reduced else "◆")
            block.collapse_to(2)
            assert block._elapsed_timer is None
            stable = block.title
            block._update_elapsed_title()
            assert block.title == stable
            await block.remove()
            assert block._elapsed_timer is None and block._marquee_timer is None
    asyncio.run(scenario())


@pytest.mark.parametrize("screen_name", ["QuickStartScreen", "WorkspaceModeScreen", "WorkspaceSetupScreen"])
def test_long_onboarding_keeps_choices_visible_at_80x24(tmp_path, monkeypatch, screen_name):
    configure(tmp_path, monkeypatch)
    from isycode import tui
    root = tmp_path / ("project-" + "x" * 220)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            cls = getattr(tui, screen_name)
            screen = cls(root, provider_ready=False) if screen_name == "QuickStartScreen" else cls(root)
            app.push_screen(screen)
            await pilot.pause()
            options = screen.query_one(OptionList)
            assert screen.region.contains_region(options.region)
            assert options.content_region.height >= 2
            copy = screen.query_one("OnboardingCopy")
            copy.focus()
            await pilot.press("end")
            await pilot.pause()
            assert copy.scroll_y > 0
            for button in screen.query(Button):
                assert screen.region.contains_region(button.region)
            await pilot.press("escape")
    asyncio.run(scenario())


def test_settings_reachable_categories_search_motion_and_new_chat_focus(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    from isycode.user_defaults import UserDefaultsStore
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.action_focus_files()
            await pilot.pause()
            settings = app.query_one("#settings-button")
            assert app.screen.region.contains_region(settings.region)
            assert await pilot.click(settings)
            await pilot.pause()
            categories = app.query_one("#settings-categories", OptionList)
            assert categories.display and categories.option_count == 4
            categories.highlighted = 1
            await pilot.pause()
            assert all(e["category_id"] == "Preferences" for e in app._menu_filtered)
            search = app.query_one("#action-search", Input)
            search.value = "provider"
            await pilot.pause()
            assert any("provider" in e["label"].casefold() for e in app._menu_filtered)
            search.value = ""
            app._select_menu_entry(next(e for e in app._menu_entries if e["kind"] == "motion_toggle"))
            assert app._reduced_motion and UserDefaultsStore().load()["reduced_motion"]
            await pilot.press("escape")
            app._start_new_conversation()
            await pilot.pause()
            assert app.screen.focused is app.query_one(PromptArea)
            await pilot.press("a", "b", "c")
            assert app.query_one(PromptArea).text == "abc"
    asyncio.run(scenario())


def test_mode_banner_updates_without_resize(tmp_path, monkeypatch):
    root = configure(tmp_path, monkeypatch)
    from isycode.workspace_authority import WorkspaceAuthority
    from isycode.tui import plain_text
    async def approve(*args):
        return True
    async def no_trust(*args, **kwargs):
        return None
    monkeypatch.setattr(TUIApp, "_await_screen", approve)
    monkeypatch.setattr(TUIApp, "_offer_quiet_trust", no_trust)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            for mode in ("security", "classic"):
                await app._change_workspace_mode(mode)
                app._close_menu()
                await pilot.pause()
                assert WorkspaceAuthority(root).mode() == mode
                assert mode.title() in plain_text(app.query_one(Banner))
    asyncio.run(scenario())
