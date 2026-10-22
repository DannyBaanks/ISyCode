"""Dialogs stay inside the main column and keep their copy readable.

A modal card used to be centered on the whole terminal, so it painted over the
right rail and clipped its labels. The onboarding copy also used to run past
the bottom of the card, cutting the sentence that explains what the choice
does. These tests pin the geometry that fixed both.
"""
import asyncio

import pytest
from textual.widgets import Button, OptionList

from isycode.tui import SidePanel, TUIApp
from isycode.tui_screens_grants import QuickStartScreen, WorkspaceModeScreen
from test_daily_tui import configure


def _overlap(first, second) -> int:
    """Columns shared by two regions."""
    return max(0, min(first.right, second.right) - max(first.x, second.x))


@pytest.mark.parametrize("screen_name", ["mode", "quick"])
@pytest.mark.parametrize("size", [(140, 40), (120, 40)])
def test_modal_card_never_covers_the_right_rail(tmp_path, monkeypatch, screen_name, size):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            if not app.query_one(SidePanel).display:
                app.action_toggle_sidebar()
                await pilot.pause()
            rail = app.query_one(SidePanel)
            assert rail.display, "the rail must be visible for this geometry"
            screen = (QuickStartScreen(tmp_path, provider_ready=False)
                      if screen_name == "quick" else WorkspaceModeScreen(tmp_path))
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()
            card = app.screen.query_one(".isy-dialog")
            assert _overlap(card.region, rail.region) == 0, (card.region, rail.region)
            # The dialog keeps a readable width instead of being squeezed.
            assert card.region.width >= 60, card.region
            app.pop_screen()
            await pilot.pause()

    asyncio.run(scenario())


@pytest.mark.parametrize("screen_name", ["mode", "quick"])
def test_onboarding_copy_fits_without_hiding_the_choice(tmp_path, monkeypatch, screen_name):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = (QuickStartScreen(tmp_path, provider_ready=False)
                      if screen_name == "quick" else WorkspaceModeScreen(tmp_path))
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()
            copy = screen.query_one("#quick-start-copy" if screen_name == "quick"
                                    else "#workspace-mode-copy")
            options = screen.query_one(OptionList)
            # The copy is bounded by its own card, never by the terminal: a
            # long workspace path wraps, so the region may scroll, but the
            # choices and the buttons stay inside the terminal.
            assert copy.styles.max_height.value == 11, copy.styles.max_height
            assert screen.region.contains_region(copy.region)
            assert screen.region.y + screen.region.height <= 24, screen.region
            # Choices and both actions stay on screen at 80x24.
            assert screen.region.contains_region(options.region)
            for button in screen.query("Button"):
                assert screen.region.contains_region(button.region)
            assert options.content_size.height >= 2
            app.pop_screen()
            await pilot.pause()

    asyncio.run(scenario())


@pytest.mark.parametrize("screen_name", ["mode", "quick"])
def test_onboarding_survives_a_very_long_workspace_path(tmp_path, monkeypatch, screen_name):
    """CI and Windows paths wrap to many more lines than a short temp name.

    A long path must not push the choices or the buttons out of an 80x24
    terminal: the copy scrolls inside its own card instead. The monkeypatch is
    the fixture, not a fresh instance: an unreverted patch leaks into the rest
    of the session and breaks the tests that run after this one.
    """

    async def scenario():
        root = tmp_path.joinpath(*["segment-" + "x" * 40 for _ in range(3)])
        root.mkdir(parents=True)
        configure(root, monkeypatch)
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = (QuickStartScreen(root, provider_ready=False)
                      if screen_name == "quick" else WorkspaceModeScreen(root))
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()
            copy = screen.query_one("#quick-start-copy" if screen_name == "quick"
                                    else "#workspace-mode-copy")
            options = screen.query_one(OptionList)
            assert copy.styles.max_height.value == 11
            assert screen.region.y + screen.region.height <= 24, screen.region
            assert screen.region.contains_region(options.region)
            assert screen.region.contains_region(copy.region)
            for button in screen.query(Button):
                assert screen.region.contains_region(button.region)
            app.pop_screen()
            await pilot.pause()

    asyncio.run(scenario())
