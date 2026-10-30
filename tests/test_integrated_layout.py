import asyncio

import pytest

from isycode.tui import PromptArea, SidePanel, TUIApp, plain_text
from test_daily_tui import configure


@pytest.mark.parametrize('size', [(80, 24), (120, 40)])
def test_composer_and_idea_note_fit_beside_sidebar(tmp_path, monkeypatch, capsys, size):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            if not app.query_one(SidePanel).display:
                app.action_toggle_sidebar()
                await pilot.pause()
            rail = app.query_one(SidePanel)
            composer = app.query_one('#composer')
            prompt = app.query_one(PromptArea)
            box = app.query_one('#idea-box')
            assert not composer.region.overlaps(rail.region)
            assert prompt.content_size.height == 1
            assert abs(box.region.width - prompt.region.width * .6) <= 1
            assert abs(box.region.center[0] - prompt.region.center[0]) <= 1
            assert box.region.bottom == prompt.region.y
            settings = app.query_one('#settings-button')
            assert composer.region.contains_region(settings.region)
            # With the rail open below 100 columns the model button yields so
            # the bar stays inside the composer; the model shows in the idea
            # box title instead.
            # The bar is measured: the model yields first, then the mode chip.
            shown = [b for b in app.query('#command-bar Button') if b.display]
            assert all(composer.region.contains_region(b.region) for b in shown)
            assert not any(a.region.overlaps(b.region) for a in shown for b in shown if a is not b)
            if size[0] >= 100:
                assert app.query_one('#mode-button').display
            app._idea_box = 'Reading the parser; next: verify the fix.'
            app._paint_idea_box()
            assert 'Reading the parser' in plain_text(box)
            gate = asyncio.Event()
            app._start_operation(gate.wait(), 'Chat · working')
            await pilot.pause()
            assert 'Thinking' in plain_text(box)
            gate.set()
            await pilot.pause()
            assert 'Thinking' not in plain_text(box)

    with capsys.disabled():
        asyncio.run(scenario())


def test_opening_narrow_sidebar_hides_model_button_before_refresh(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        # At 100 columns the closed-rail bar still fits Model, GUS and the mode
        # chip; at 80 the GUS button displaces the model first, so the sidebar
        # toggle would no longer prove the pre-refresh prediction.
        async with app.run_test(size=(100, 24)) as pilot:
            await pilot.pause()
            rail = app.query_one(SidePanel)
            if rail.display:
                app.action_toggle_sidebar()
                await pilot.pause()
            assert not rail.display
            model_button = app.query_one('#model-button')
            assert model_button.display
            assert app.query_one('#gus-button').display

            app.action_toggle_sidebar()

            assert rail.display
            assert not model_button.display

    asyncio.run(scenario())


def test_history_restores_draft_and_multiline_keyboard_editing(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            prompt = app.query_one(PromptArea)
            app._prompt_history = ['first request', 'second request']
            prompt.load_text('unfinished draft')
            prompt.focus()
            await pilot.press('up')
            assert prompt.text == 'second request'
            await pilot.press('up')
            assert prompt.text == 'first request'
            await pilot.press('down', 'down')
            assert prompt.text == 'unfinished draft'
            await pilot.press('ctrl+j')
            assert '\n' in prompt.text
            assert app._loop_task is None

    with capsys.disabled():
        asyncio.run(scenario())
