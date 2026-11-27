"""Regression tests for the adv-ux findings (Haiku pass, findings 5/6/7/9/11/12).

Each test pins the user-visible behaviour that was reported broken:

* F1 help wraps every shortcut description instead of cropping it, and the
  dialog border stays closed while the card sits above the composer.
* PageUp / PageDown with focus in the composer page the chat transcript;
  Home / End keep moving the text caret.
* Escape from the right rail returns to the composer and closes the rail when
  the hint promises "esc back"; the rail hint never leaks into the main column.
* The Idea box collapses on short / narrow terminals so it stops crowding chat.
* Modal screens dim the splash art behind the dialog instead of letting the
  block landscape bleed through the dialog border.
* Enter on the highlighted provider in /providers always opens that provider's
  model list, and Enter on a model row always applies it.
"""
import asyncio
import pathlib

import pytest
from textual.widgets import Button, Input, OptionList

from isycode.tui import PromptArea, SidePanel, TUIApp, plain_text
from isycode.tui_widgets import ChatArea
from test_daily_tui import configure


# ── Finding 11: PageUp / PageDown from the composer ──────────────────────────

def _mount_long_transcript(app, lines: int = 120) -> None:
    from textual.widgets import Static
    chat = app.query_one(ChatArea)
    # Raw widgets keep this test off the network and the provider owners.
    for index in range(lines):
        chat.mount(Static(f"línea {index}", classes="tui-test-line"), before=chat._tail)


def test_composer_pageup_pagedown_scroll_the_chat_not_the_caret(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            _mount_long_transcript(app)
            await pilot.pause()
            await pilot.pause()
            chat = app.query_one(ChatArea)
            prompt = app.query_one("#prompt-input", PromptArea)
            prompt.focus()
            prompt.insert("primera\nsegunda\ntercera linea")
            await pilot.pause()
            assert chat.max_scroll_y > 0, "the transcript must be scrollable for this test"
            chat.scroll_end(animate=False, immediate=True)
            await pilot.pause()
            bottom = chat.scroll_y
            caret_before = prompt.cursor_location

            await pilot.press("pageup")
            await pilot.pause()
            await pilot.pause()
            assert chat.scroll_y < bottom, (chat.scroll_y, bottom)
            assert prompt.cursor_location == caret_before, "page keys must not move the caret"
            assert app.focused is prompt, "paging keeps focus in the composer"
            up_position = chat.scroll_y

            await pilot.press("pagedown")
            await pilot.pause()
            await pilot.pause()
            assert chat.scroll_y > up_position, (chat.scroll_y, up_position)
            assert prompt.cursor_location == caret_before

            # Home / End still belong to the text caret.
            await pilot.press("home")
            await pilot.pause()
            assert prompt.cursor_location == (2, 0), prompt.cursor_location
            await pilot.press("end")
            await pilot.pause()
            assert prompt.cursor_location[1] == len(prompt.document.lines[2]), prompt.cursor_location

    asyncio.run(scenario())


# ── Finding 9: F1 help wraps and keeps its border ────────────────────────────

def _screen_cells(app):
    """One string per screen row, one character per terminal cell.

    Wide glyphs (CJK titles) occupy two cells; ``Strip.text`` would shorten the
    row and shift every column after it, so pad them here.
    """
    from rich.cells import cell_len
    rows = []
    for strip in app.screen._compositor.render_strips():
        row = strip.text
        if len(row) != strip.cell_length:
            out = []
            for char in row:
                out.append(char)
                if cell_len(char) == 2:
                    out.append(" ")
            row = "".join(out)
        rows.append(row)
    return rows


_screen_lines = _screen_cells


@pytest.mark.parametrize("locale", ["en", "es", "zh"])
@pytest.mark.parametrize("size", [(120, 40), (100, 36), (80, 24)])
def test_quick_help_wraps_every_row_and_keeps_a_closed_border(tmp_path, monkeypatch, locale, size):
    configure(tmp_path, monkeypatch)
    from isycode.user_defaults import UserDefaultsStore
    UserDefaultsStore().update(locale=locale)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            app.action_quick_help()
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            card = screen.query_one("#quick-help-card")
            # Every description fits its own box: no cropped sentence.
            for row in screen.query("HelpRow"):
                desc = row.query_one(".help-desc")
                assert desc.virtual_size.width <= desc.content_size.width, (
                    plain_text(row.query_one(".help-key")), plain_text(desc),
                    desc.virtual_size.width, desc.content_size.width)
            # The card never covers the composer or the command bar.
            prompt = app.screen_stack[0].query_one("#prompt-input", PromptArea)
            bar = app.screen_stack[0].query_one("#command-bar")
            overlap = max(0, min(card.region.bottom, prompt.region.bottom) - max(card.region.y, prompt.region.y))
            assert overlap == 0, (card.region, prompt.region)
            assert card.region.bottom <= prompt.region.y, (card.region, prompt.region)
            assert card.region.contains_region(screen.query_one("#help-close", Button).region)
            # The rendered border is a closed rectangle: both side rails appear on
            # every row of the card, and the bottom rail is one unbroken line.
            lines = _screen_lines(app)
            left, right = card.region.x, card.region.right - 1
            for y in range(card.region.y + 1, card.region.bottom - 1):
                assert lines[y][left] == "│", (y, repr(lines[y][left:left + 3]))
                assert lines[y][right] == "│", (y, repr(lines[y][right - 2:right + 1]))
            bottom = lines[card.region.bottom - 1][left:right + 1]
            assert bottom.startswith("└") and bottom.endswith("┘"), repr(bottom)
            assert "─" in bottom and bottom.strip("└┘─") == "", repr(bottom)
            await pilot.press("escape")
            await pilot.pause()
            assert not any(type(s).__name__ == "QuickHelpScreen" for s in app.screen_stack)
            # Composer and bar still exist untouched behind the modal.
            assert prompt.region.height >= 3 and bar.region.height >= 1

    asyncio.run(scenario())


def test_quick_help_rows_wrap_instead_of_cropping(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    from isycode.tui_screens_help import HelpRow

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            row = HelpRow("Shift+Enter / Ctrl+J", "Inserta un salto de línea en el compositor · una frase deliberadamente larga")
            await app.mount(row)
            await pilot.pause()
            desc = row.query_one(".help-desc")
            assert str(desc.styles.text_wrap) != "nowrap", desc.styles.text_wrap
            assert row.region.height >= 2, row.region

    asyncio.run(scenario())


# ── Finding 6: rail, Tab and Escape ───────────────────────────────────────────

def test_escape_from_the_rail_closes_it_and_returns_to_the_composer(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_toggle_sidebar()
            await pilot.pause()
            rail = app.query_one(SidePanel)
            assert rail.display
            chat_width_with_rail = app.query_one(ChatArea).region.width
            assert chat_width_with_rail < 120
            app.query_one("#show-overview", Button).focus()
            await pilot.pause()
            assert app._rail_visible is True
            await pilot.press("escape")
            await pilot.pause()
            await pilot.pause()
            prompt = app.query_one("#prompt-input", PromptArea)
            assert app.focused is prompt, type(app.focused).__name__
            assert rail.display is False, "Escape must close the rail that promises 'esc back'"
            assert app._rail_visible is False
            assert app.query_one(ChatArea).region.width > chat_width_with_rail
            # The rail hint is not painted over the main column once the rail is gone.
            hint = app.query_one("#rail-footer-hint")
            assert hint.region.width == 0 or not hint.display

    asyncio.run(scenario())


def test_tab_from_the_composer_never_enters_the_rail(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_toggle_sidebar()
            await pilot.pause()
            prompt = app.query_one("#prompt-input", PromptArea)
            prompt.focus()
            await pilot.pause()
            seen = []
            for _ in range(14):
                await pilot.press("tab")
                await pilot.pause()
                seen.append(type(app.focused).__name__)
                assert not isinstance(app.focused, SidePanel)
                node = app.focused
                while node is not None:
                    assert not isinstance(node, SidePanel), "Tab must not trap focus in the rail"
                    node = node.parent
            assert "PromptArea" in seen, seen
            # The rail only takes focus when the user asks for it (F6 / click).
            await pilot.press("f6")
            await pilot.pause()
            assert app._rail_view == "files"

    asyncio.run(scenario())


# ── Finding 7: Idea box on small terminals ────────────────────────────────────

@pytest.mark.parametrize("size", [(80, 24), (60, 20), (79, 40), (120, 23)])
def test_idea_box_collapses_on_small_terminals(tmp_path, monkeypatch, size):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await pilot.pause()
            idea = app.query_one("#idea-box")
            row = app.query_one("#idea-box-row")
            chat = app.query_one(ChatArea)
            assert idea.display is False, (size, idea.region)
            assert row.region.height <= 1, (size, row.region)
            assert chat.region.height >= size[1] - 10, (size, chat.region)

    asyncio.run(scenario())


def test_idea_box_comes_back_on_a_large_terminal(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.query_one("#idea-box").display is False
            await pilot.resize_terminal(120, 40)
            await pilot.pause()
            await pilot.pause()
            assert app.query_one("#idea-box").display is True
            await pilot.resize_terminal(60, 20)
            await pilot.pause()
            await pilot.pause()
            assert app.query_one("#idea-box").display is False

    asyncio.run(scenario())


# ── Finding 12: noisy background behind modals ───────────────────────────────

def test_onboarding_modal_dims_the_splash_behind_the_dialog(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        from isycode.tui_screens_grants import QuickStartScreen
        from isycode.tui_widgets import IdleBoard
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            board = app.query_one("#idle-board", IdleBoard)
            assert board.display, "the splash must be visible before the modal opens"
            screen = QuickStartScreen(tmp_path, provider_ready=False)
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()
            assert screen.query_one("#idle-board").display is False or screen.query_one("#idle-board").region.height == 0
            # The dimmed backdrop covers the whole terminal, so block art never
            # reaches the dialog border.
            from textual.color import Color
            backdrop = screen.styles.background
            assert backdrop is not None and backdrop.a > 0.9, backdrop
            card = screen.query_one(".isy-dialog")
            lines = _screen_lines(app)
            # Nothing but the dimmed backdrop is painted between the screen edge
            # and the dialog on the card's middle row.
            y = card.region.y + card.region.height // 2
            outside = lines[y][:card.region.x] + lines[y][card.region.right:]
            assert "▀" not in outside and "▀" not in outside, repr(outside)

    asyncio.run(scenario())


# ── Finding 5: Enter always activates the highlighted provider ───────────────

def test_providers_enter_opens_the_highlighted_provider_models(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        from isycode.tui_screens_harness import ModelChoice, ModelsScreen
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._open_provider_menu()
            await pilot.pause()
            await pilot.pause()
            options = app.query_one("#action-list", OptionList)
            assert app.focused is options
            target = next(i for i, e in enumerate(app._menu_filtered) if e.get("value") == "lmstudio")
            # Walk the list with the keyboard only.
            for _ in range(target):
                await pilot.press("down")
                await pilot.pause()
            assert options.highlighted == target, (options.highlighted, target)
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, ModelsScreen), type(app.screen).__name__
            assert app.screen.provider_scope == "lmstudio"
            # Enter again on the model list applies the highlighted model: the
            # model screen must put focus on a row, not on the search box, when
            # the user arrived with the keyboard.
            assert isinstance(app.focused, ModelChoice), type(app.focused).__name__
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            assert not isinstance(app.screen, ModelsScreen)
            import os
            assert os.environ["ISYCODE_PROVIDER"] == "lmstudio"

    asyncio.run(scenario())
