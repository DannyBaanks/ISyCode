import asyncio
import pytest
from textual.widgets import Static
from isycode.tui import TUIApp, QuietScrollBar, plain_text
from test_daily_tui import configure


@pytest.mark.parametrize('size', [(80, 24), (100, 30), (120, 40), (140, 40)])
def test_status_flanks_idea_box_and_animation_stops(tmp_path, monkeypatch, size):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            activity = app.query_one('#activity-status', Static)
            usage = app.query_one('#usage-status', Static)
            idea = app.query_one('#idea-box', Static)
            prompt = app.query_one('#prompt-input')
            assert activity.region.right <= idea.region.x
            assert idea.region.right <= usage.region.x
            assert not activity.region.overlaps(prompt.region)
            assert not usage.region.overlaps(prompt.region)
            assert 'cost' not in plain_text(usage)
            assert 'req' not in plain_text(usage)
            gate = asyncio.Event()
            app._start_operation(gate.wait(), 'Chat working')
            app._animate_activity()
            first = plain_text(activity)
            app._animate_activity()
            assert plain_text(activity) != first
            gate.set()
            await pilot.pause()
            assert plain_text(activity) == 'Chat ready'
            app._animate_activity()
            assert plain_text(activity) == 'Chat ready'
            bar = app.query_one('#chat').vertical_scrollbar
            assert isinstance(bar, QuietScrollBar)
            bar._direction = 1
            bar._settle()
            assert bar._direction == 0
    asyncio.run(scenario())
