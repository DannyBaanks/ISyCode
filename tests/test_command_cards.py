import asyncio
import json
from types import SimpleNamespace

import pytest
from textual.app import App
from textual.widgets import Button

from isycode.tui import CommandApprovalScreen, CommandOutputCard, TUIApp
from test_command_runner_tui import _preview
from test_daily_tui import configure


@pytest.mark.parametrize('size', [(80, 24), (120, 40)])
def test_command_card_has_two_preview_rows_and_preserves_full_output(size):
    class Host(App):
        def compose(self):
            yield CommandOutputCard('python3 check.py --long-argument=' + 'x' * 150)

    async def scenario():
        async with Host().run_test(size=size) as pilot:
            card = pilot.app.query_one(CommandOutputCard)
            card.append_output('first marker\n' + 'wide ' * 100 + '\nlast marker\n')
            card.finish('exit code 1', receipt='test-receipt', truncated=True)
            await pilot.pause()
            assert card.content_size.height == 2
            assert card.region.right <= size[0]
            assert 'first marker' not in card._body.selection_text
            assert 'last marker' in card._body.selection_text
            card.focus()
            await pilot.press('enter')
            await pilot.pause()
            assert card.expanded
            assert 'first marker' in card._body.selection_text
            assert 'test-receipt' in card._body.selection_text
            assert 'not retained' in card._body.selection_text
            await pilot.press('space')
            await pilot.pause()
            assert not card.expanded
            assert card.content_size.height == 2
            await pilot.click(card)
            await pilot.pause()
            assert not card.expanded
            await pilot.click(card)
            await pilot.pause()
            assert card.expanded
            await pilot.press('space')
            await pilot.pause()
            assert not card.expanded
            await pilot.click(card._body, offset=(2, 0))
            await pilot.pause()
            assert not card.expanded
            await pilot.click(card._body, offset=(4, 0))
            await pilot.pause()
            assert card.expanded
    asyncio.run(scenario())


def test_command_owner_output_is_grouped_and_returned_unchanged(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    result = {'output': 'first\nsecond\nthird\n', 'exit_code': 0,
              'timed_out': False, 'output_truncated': False}
    response = json.dumps(result)

    class Owner:
        def __init__(self, *args):
            pass
        def prepare(self, *args, **kwargs):
            return _preview(tmp_path)
        async def run(self, preview, approval, on_output):
            on_output('first\nsec')
            on_output('ond\nthird\n')
            return SimpleNamespace(decision='ALLOW', text=response,
                                   receipt=SimpleNamespace(receipt_id='verified-test'), reason='')

    monkeypatch.setattr('isycode.tui_app_workspace.CommandRunOwner', Owner)
    monkeypatch.setattr(TUIApp, '_command_tool_enabled', lambda self: True)
    monkeypatch.setattr(TUIApp, '_request_is_quiet', lambda *args: False)
    async def approve(*args):
        return True
    monkeypatch.setattr(TUIApp, '_await_screen', approve)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert await app._run_workspace_command({'argv': ['echo', 'hi there']}) == response
            await pilot.pause()
            cards = list(app.query(CommandOutputCard))
            assert len(cards) == 1
            assert cards[0].output == result['output']
            assert cards[0].status == 'exit code 0'
            assert cards[0].receipt == 'verified-test'
            from unittest.mock import Mock
            app._search_console('first', Mock())
            await pilot.pause()
            assert cards[0].expanded
            assert app._console_search_hits
    with capsys.disabled():
        asyncio.run(scenario())


def test_command_choice_tiles_fit_and_reject_is_focused(tmp_path):
    class Host(App):
        def on_mount(self):
            self.push_screen(CommandApprovalScreen(_preview(tmp_path)))
    async def scenario():
        async with Host().run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            reject = screen.query_one('#command-approval-reject', Button)
            run = screen.query_one('#command-approval-run', Button)
            assert screen.focused is reject
            assert reject.region.height == run.region.height == 5
            assert screen.region.contains_region(run.region)
            assert not reject.region.overlaps(run.region)
    asyncio.run(scenario())


def test_harness_counter_boxes_update_without_touching_todo():
    from isycode.tui import MultiHarnessScreen, plain_text
    from isycode.harness_graph import CATALOG_IDS
    class Host(App):
        def on_mount(self):
            self.push_screen(MultiHarnessScreen())
    async def scenario():
        async with Host().run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            screen.update_snapshot([{'harness_id': CATALOG_IDS[0], 'checking': False,
                                     'unlocked': True, 'settings': []}], 7)
            await pilot.pause()
            folders = screen.query_one('#harness-folders-count')
            sessions = screen.query_one('#harness-sessions-count')
            assert '1/' in plain_text(folders)
            assert '7' in plain_text(sessions)
            assert folders.region.height == sessions.region.height == 3
            assert not folders.region.overlaps(sessions.region)
            assert screen.region.contains_region(sessions.region)
    asyncio.run(scenario())
