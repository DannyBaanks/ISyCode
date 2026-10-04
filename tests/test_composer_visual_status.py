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
            assert 'Chat ready' in plain_text(activity)
            asleep = plain_text(activity)
            app._animate_activity()
            assert plain_text(activity) == asleep
            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            from rich.cells import cell_len
            assert all(cell_len(row) <= activity.content_size.width
                       for row in plain_text(activity).splitlines())
            app._animate_activity()
            assert 'Chat ready' in plain_text(activity)
            app._set_activity('Draft kept')
            kept = plain_text(activity)
            assert 'Draft kept' in kept and 'z' in kept
            app._set_activity('Interrupted')
            stopped = plain_text(activity)
            assert stopped.splitlines()[-1].lstrip().startswith('Interrupted')
            assert 'transcript' not in stopped
            if activity.content_size.width >= 15:
                assert 'z' in stopped
            bar = app.query_one('#chat').vertical_scrollbar
            assert isinstance(bar, QuietScrollBar)
            bar._direction = 1
            bar._settle()
            assert bar._direction == 0
    asyncio.run(scenario())


def test_friendly_model_stays_visible_and_startup_does_not_repeat_path(tmp_path, monkeypatch):
    check_model = TUIApp._check_model
    configure(tmp_path, monkeypatch)
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "test-not-real")
    monkeypatch.setenv("ISYCODE_PROVIDER", "nvidia")
    monkeypatch.setenv("ISYCODE_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(180, 40)) as pilot:
            await pilot.pause()
            app._paint_idea_box()
            label = "Nemotron 3 Ultra 550b a55b / Default · NVIDIA NIM"
            assert "Idea box     " + label in plain_text(app.query_one('#idea-box'))
            assert str(app._workspace_root) not in app._idle_board_text().plain
            await check_model(app)
            assert label in app._model_line
            monkeypatch.setenv("ISYCODE_MODEL", "z-ai/glm-5.3")
            app._paint_idea_box()
            assert "GLM 5.3 / Default · NVIDIA NIM" in plain_text(app.query_one('#idea-box'))
    asyncio.run(scenario())


def test_scroll_thumb_tracks_position_and_remains_after_settle(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one('#chat').vertical_scrollbar
            bar.window_virtual_size = 1000
            bar.window_size = 20
            bar.position = 0
            top = bar.render().plain.splitlines()
            bar.position = 980
            bottom = bar.render().plain.splitlines()
            assert top.index('━━━') < bottom.index('━━━')
            assert top[0] == ' ▲ ' and bottom[-1] == ' ▼ '
            bar._settle()
            assert bar.render().plain.splitlines() == bottom
    asyncio.run(scenario())
