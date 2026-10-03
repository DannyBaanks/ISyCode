import asyncio
import pytest
from isycode.tui import TUIApp, IdeaNoteScreen, plain_text
from test_daily_tui import configure


@pytest.mark.parametrize('size', [(80, 24), (120, 40)])
def test_full_idea_note_opens_updates_and_closes_without_resizing_box(tmp_path, monkeypatch, size):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            box = app.query_one('#idea-box')
            region = box.region
            app._idea_box = 'A long note. ' * 100
            app._paint_idea_box()
            await pilot.pause()
            assert box.region.width == region.width
            region = box.region
            assert 'Space' in str(box.border_title)
            box.focus()
            await pilot.press('space')
            await pilot.pause()
            assert isinstance(app.screen, IdeaNoteScreen)
            assert plain_text(app.screen.query_one('#idea-note-content')) == app._idea_box
            app._idea_box = 'Live updated note ' * 100
            app._paint_idea_box()
            await pilot.pause()
            assert plain_text(app.screen.query_one('#idea-note-content')) == app._idea_box
            await pilot.press('escape')
            await pilot.pause()
            assert not isinstance(app.screen, IdeaNoteScreen)
            assert box.region == region
            _, command, _ = app._plugins.route('/idea')
            await command.handler(app, '')
            await pilot.pause()
            assert isinstance(app.screen, IdeaNoteScreen)
            await pilot.click('#idea-note-close')
            await pilot.pause()
            assert not isinstance(app.screen, IdeaNoteScreen)
    asyncio.run(scenario())
