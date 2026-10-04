import asyncio
import pytest
from isycode.tui import TUIApp
from test_daily_tui import configure


@pytest.mark.parametrize('size', [(80, 24), (120, 40)])
def test_prompt_grows_to_five_content_rows_then_scrolls_and_shrinks(tmp_path, monkeypatch, size):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            prompt = app.query_one('#prompt-input')
            assert prompt.content_size.height == 1
            prompt.load_text('one\ntwo\nthree')
            await pilot.pause()
            assert prompt.content_size.height == 3
            prompt.load_text('\n'.join(f'line {i}' for i in range(12)))
            prompt.move_cursor((11, 7))
            await pilot.pause()
            assert prompt.content_size.height == 5
            assert prompt.max_scroll_y > 0
            assert prompt.scroll_y > 0
            assert not prompt.region.overlaps(app.query_one('#idea-box').region)
            prompt.load_text('word ' * 100)
            await pilot.pause()
            assert prompt.content_size.height == 5
            assert prompt.max_scroll_y > 0
            prompt.load_text('')
            await pilot.pause()
            assert prompt.content_size.height == 1
    asyncio.run(scenario())
