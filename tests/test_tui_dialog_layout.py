"""Dialogs stay inside the main column and keep their copy readable.

A modal card used to be centered on the whole terminal, so it painted over the
right rail and clipped its labels. The onboarding copy also used to run past
the bottom of the card, cutting the sentence that explains what the choice
does. These tests pin the geometry that fixed both.
"""
import asyncio

import pytest
from textual.widgets import OptionList

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
            # The whole onboarding copy is visible: nothing is cut mid
            # sentence and the region does not need scrolling.
            assert copy.max_scroll_y == 0, copy.virtual_size
            assert copy.content_size.height >= 8
            # Choices and both actions stay on screen at 80x24.
            assert screen.region.contains_region(options.region)
            for button in screen.query("Button"):
                assert screen.region.contains_region(button.region)
            app.pop_screen()
            await pilot.pause()

    asyncio.run(scenario())
