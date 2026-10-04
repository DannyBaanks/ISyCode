import asyncio
from rich.console import Console
from isycode.tui import TUIApp
from isycode.work_list import WorkList, SessionDetails, SessionMessageScreen, quoted_preview
from test_daily_tui import configure


def test_quotes_fit_wrapped_lines_without_losing_full_message():
    preview = quoted_preview("a sentence " * 400, Console(), 25, 3)
    assert len(preview.plain.splitlines()) <= 3
    assert preview.plain.startswith("“") and preview.plain.endswith("…”")
    assert all(len(line) <= 25 for line in preview.plain.splitlines())


def test_details_expand_only_when_focused_and_preserve_exact_message(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    # The session timer captures this method at mount and would replace the fixture.
    monkeypatch.setattr(TUIApp, "_paint_work_status", lambda self: None)
    message = "Long message\n" * 200
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(160, 40)) as pilot:
            await app._show_chat_sessions()
            board = app.query_one(WorkList)
            board.show_rows([{"id": "fixture", "title": "Long", "status": "idle", "detail": message}])
            listing = board.query_one("#work-conversations")
            listing.highlighted = None
            listing.highlighted = next(
                index for index, option in enumerate(listing._options) if option.id == "fixture")
            await pilot.pause()
            panel = board.query_one(SessionDetails)
            assert "…”" in str(panel.render())
            assert panel.full_message == message
            assert "Enter / Space" in str(panel.render())
            await pilot.click(panel, offset=(3, 1))
            await pilot.pause()
            assert getattr(panel, "_activate_key", None) == "message"
            assert not isinstance(app.screen, SessionMessageScreen)
            # A different cell on the same panel still opens. Textual only
            # reports a double-click when both presses share one cell.
            await pilot.click(panel, offset=(6, 1))
            await pilot.pause()
            assert isinstance(app.screen, SessionMessageScreen)
            assert app.screen.message == message
            scroll = app.screen.query_one("#session-message-scroll")
            assert scroll.max_scroll_y > 0
            await pilot.press("escape")
            await pilot.pause()
            assert board.display
            panel.focus()
            await pilot.press("space")
            await pilot.pause()
            assert isinstance(app.screen, SessionMessageScreen)
    asyncio.run(scenario())
