import asyncio
import pytest
from textual.widgets import Collapsible
from textual.widgets._collapsible import CollapsibleTitle
from isycode.harness_graph import CATALOG_IDS
from isycode.tui import MultiHarnessScreen, TUIApp
from test_daily_tui import configure


@pytest.mark.parametrize('size', [(80, 24), (120, 40)])
def test_harness_list_opens_collapsed_and_preserves_each_expansion(tmp_path, monkeypatch, size):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=size) as pilot:
            screen = MultiHarnessScreen()
            app.push_screen(screen)
            await pilot.pause()
            sections = list(screen.query('.harness-section'))
            assert len(sections) == len(CATALOG_IDS)
            assert all(section.collapsed for section in sections)
            first = sections[0]
            first.query_one(CollapsibleTitle).focus()
            await pilot.press('enter')
            await pilot.pause()
            assert not first.collapsed
            assert all(section.collapsed for section in sections[1:])
            screen.update_snapshot([
                {'harness_id': harness_id, 'checking': False, 'unlocked': True,
                 'settings': [], 'version_line': 'fixture'}
                for harness_id in CATALOG_IDS
            ], 4)
            await pilot.pause()
            assert not first.collapsed
            assert 'ready' in first.title
            assert all(section.collapsed for section in sections[1:])
            first.query_one(CollapsibleTitle).focus()
            await pilot.press('enter')
            await pilot.pause()
            assert first.collapsed
            close = screen.query_one('#harness-close')
            assert screen.query_one('#harness-card').region.contains_region(close.region)
            await pilot.press('escape')
            await pilot.pause()
            assert app.screen is not screen
    asyncio.run(scenario())
