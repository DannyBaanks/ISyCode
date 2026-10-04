import asyncio
from isycode.tui import TUIApp, ThoughtBlock, BoxTitle, plain_text
from test_daily_tui import configure


def test_thinking_preview_full_and_hidden_states_are_local_to_focus(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            block, chat = app._mount_thought()
            await pilot.pause()
            block.set_text('First line\nSecond line')
            assert plain_text(block._body) == 'First line\nSecond line'
            assert not str(block.border_subtitle)
            block.set_text('First line\nSecond line\nThird line\nFourth line')
            assert plain_text(block._body) == 'First line\nSecond line'
            assert 'expand' in str(block.border_subtitle)
            app.query_one('#prompt-input').focus()
            await pilot.press('space')
            assert plain_text(block._body) == 'First line\nSecond line'
            block.focus()
            await pilot.press('space')
            await pilot.pause()
            assert 'Fourth line' in plain_text(block._body)
            assert 'collapse' in str(block.border_subtitle)
            await pilot.press('space')
            assert plain_text(block._body) == 'First line\nSecond line'
            block.collapse_to(6)
            await pilot.pause()
            assert block.collapsed
            assert 'thought for 6s     First line Second line' in str(block.title)
            block.query_one(BoxTitle).focus()
            await pilot.press('enter')
            await pilot.pause()
            assert not block.collapsed
            assert 'Fourth line' in plain_text(block._body)
            rail = app.query_one('#rail-lsp')
            initial = rail.collapsed
            rail.query_one(BoxTitle).focus()
            await pilot.press('space')
            await pilot.pause()
            assert rail.collapsed != initial
            assert not block.collapsed
    asyncio.run(scenario())


def test_completed_marquee_is_optional_bounces_and_setting_is_saved(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            block, _ = app._mount_thought()
            await pilot.pause()
            block.set_text('A long completed reasoning note with different words. ' * 8)
            block.collapse_to(6)
            assert not block._marquee_enabled
            block.toggle_marquee()
            block._marquee_timer.pause()
            start = str(block.title)
            block._marquee_tick()
            assert str(block.title) != start
            block._marquee_offset = 10000
            block._marquee_tick()
            assert block._marquee_direction == -1
            block.toggle_marquee()
            fixed = str(block.title)
            block._marquee_tick()
            assert str(block.title) == fixed
            assert fixed.startswith('thought for 6s     ')
            app._select_menu_entry({'kind': 'marquee_toggle', 'value': '', 'label': 'toggle'})
            from isycode.user_defaults import UserDefaultsStore
            assert UserDefaultsStore().load()['compact_marquee'] is True
            assert block._marquee_enabled
    asyncio.run(scenario())
