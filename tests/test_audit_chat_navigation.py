"""Regression witnesses for reading history while chat output grows."""
import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Static

from isycode.tui import ChatArea


class HistoryApp(App):
    def compose(self) -> ComposeResult:
        yield ChatArea(id="history")


def test_home_releases_tail_even_when_layout_callbacks_are_pending():
    async def scenario():
        app = HistoryApp()
        async with app.run_test(size=(80, 24)) as pilot:
            chat = app.query_one(ChatArea)
            await chat.mount(Static("history\n" * 80))
            await pilot.pause()
            assert chat.scroll_y == chat.max_scroll_y
            chat.focus()
            await pilot.press("home")
            await pilot.pause(1.1)
            assert chat.scroll_y < chat.max_scroll_y
            position = chat.scroll_y
            await chat.mount(Static("new output\n" * 20))
            chat.follow_tail()
            await pilot.pause()
            assert chat.scroll_y == position
            await pilot.press("end")
            await pilot.pause()
            assert chat.scroll_y == chat.max_scroll_y
    asyncio.run(scenario())
