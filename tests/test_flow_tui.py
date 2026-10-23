"""Flow is selectable and every chat turn has its own recoverable file changes."""
import asyncio
import json

import pytest
from textual.widgets import OptionList

from isycode.localization import configure_locale as set_locale
from isycode.tui import TUIApp
from isycode.tui_screens_grants import WorkspaceModeScreen
from isycode.turn_journal import TurnJournal
from isycode.workspace_authority import WorkspaceAuthority
from test_daily_tui import configure


@pytest.mark.parametrize('locale', ['en', 'es', 'zh'])
@pytest.mark.parametrize('size', [(80, 24), (100, 30), (140, 40)])
def test_flow_can_be_selected_in_onboarding_and_settings(tmp_path, monkeypatch, capsys, locale, size):
    root = configure(tmp_path, monkeypatch)
    from isycode.user_defaults import UserDefaultsStore
    UserDefaultsStore().update(locale=locale)
    set_locale(locale)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=size) as pilot:
            await app.wait_for_ready()
            chosen = []
            app.push_screen(WorkspaceModeScreen(root), chosen.append)
            await pilot.pause()
            options = app.screen.query_one('#workspace-mode-options', OptionList)
            assert options.get_option_at_index(options.highlighted or 0).id == 'classic'
            assert options.get_option('flow')
            assert options.region.bottom <= size[1]
            import os
            capture = os.environ.get('FLOW_CAPTURE_DIR')
            if capture:
                app.save_screenshot(f'flow-onboarding-{locale}-{size[0]}x{size[1]}.svg', path=capture)
            await pilot.press('down', 'enter')
            await pilot.pause()
            assert chosen == ['flow']
            app._open_workflow_menu()
            assert {e['value'] for e in app._menu_entries if e.get('kind') == 'workspace_mode'} == {'classic', 'flow', 'security'}
            await pilot.pause()
            if capture:
                app.save_screenshot(f'flow-settings-{locale}-{size[0]}x{size[1]}.svg', path=capture)
            WorkspaceAuthority(root).set_mode('flow')
            app._update_workspace_identity_ui()
            assert 'Flow' in app._root_source_label()
            app._open_authority_menu()
            assert any('Flow' in e.get('label', '') for e in app._menu_entries)

    try:
        with capsys.disabled():
            asyncio.run(scenario())
    finally:
        set_locale('en')


def test_chat_turns_are_recorded_separately_and_undo_survives_reload(tmp_path, monkeypatch, capsys):
    root = configure(tmp_path, monkeypatch)
    WorkspaceAuthority(root).set_mode('flow')
    (root / 'one.txt').write_text('human before\n')
    rounds = 0
    turn_ids = []

    async def complete(provider, messages, **kwargs):
        nonlocal rounds
        active = TurnJournal.active(root)
        assert active is not None
        if rounds % 2 == 0:
            turn_ids.append(active.turn_id)
            name = 'one.txt' if rounds == 0 else 'two.txt'
            result = {'text': '', 'tool_calls': [{'id': f'write-{rounds}', 'type': 'function', 'function': {
                'name': 'workspace_write', 'arguments': json.dumps({'path': name, 'content': 'agent\n'})}}]}
        else:
            result = {'text': 'Done.', 'tool_calls': []}
        rounds += 1
        return result

    monkeypatch.setattr('isycode.tui.provider_complete', complete)

    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await app.wait_for_ready()
            await app._run_chat('edit one')
            assert TurnJournal.active(root) is None
            assert (root / 'one.txt').read_text() == 'agent\n'
            await app._run_chat('create two')
            assert TurnJournal.active(root) is None
            assert len(set(turn_ids)) == 2
            assert (root / 'two.txt').read_text() == 'agent\n'
        # Nothing in TUI memory identifies the last turn in this new instance.
        app = TUIApp()
        async with app.run_test() as pilot:
            await app.wait_for_ready()
            await app._undo_last_change()
            assert not (root / 'two.txt').exists()
            assert (root / 'one.txt').read_text() == 'agent\n'
            await app._undo_last_change()
            assert (root / 'one.txt').read_text() == 'human before\n'

    with capsys.disabled():
        asyncio.run(scenario())


@pytest.mark.parametrize('failure', ['storage', 'busy'])
def test_flow_journal_failure_stops_the_turn_before_provider_or_effects(tmp_path, monkeypatch, capsys, failure):
    root = configure(tmp_path, monkeypatch)
    WorkspaceAuthority(root).set_mode('flow')
    calls = []

    async def complete(*args, **kwargs):
        calls.append(1)
        return {'text': 'must not run', 'tool_calls': []}

    def broken(*args, **kwargs):
        raise OSError('disk full')

    monkeypatch.setattr('isycode.tui.provider_complete', complete)
    active = None
    if failure == 'busy':
        active = TurnJournal.begin(root)
    else:
        monkeypatch.setattr(TurnJournal, 'begin', broken)

    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await app.wait_for_ready()
            await app._run_chat('keep this prompt')
            assert not calls
            assert app.query_one('#prompt-input').text == 'keep this prompt'
            assert TurnJournal.active(root) is active

    try:
        with capsys.disabled():
            asyncio.run(scenario())
    finally:
        if active is not None:
            active.finish()


def test_cancel_waits_for_inflight_file_write_before_closing_turn(tmp_path, monkeypatch, capsys):
    import threading
    from isycode.workspace_write import WorkspaceWriteOwner
    root = configure(tmp_path, monkeypatch)
    WorkspaceAuthority(root).set_mode('flow')
    entered, release = threading.Event(), threading.Event()
    original = WorkspaceWriteOwner.apply

    def slow_write(owner, preview, approval):
        entered.set()
        if not release.wait(5):
            raise RuntimeError('test did not release writer')
        return original(owner, preview, approval)

    async def complete(provider, messages, **kwargs):
        return {'text': '', 'tool_calls': [{'id': 'write', 'type': 'function', 'function': {
            'name': 'workspace_write', 'arguments': json.dumps({'path': 'slow.txt', 'content': 'saved\n'})}}]}

    monkeypatch.setattr(WorkspaceWriteOwner, 'apply', slow_write)
    monkeypatch.setattr('isycode.tui.provider_complete', complete)

    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await app.wait_for_ready()
            task = asyncio.create_task(app._run_chat('write slowly'))
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                turn_id = TurnJournal.active(root).turn_id
                task.cancel()
                await asyncio.sleep(0.05)
                assert not task.done()
                assert TurnJournal.active(root) is not None
            finally:
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert TurnJournal.active(root) is None
            assert TurnJournal.load(root, turn_id).changes()[0]['path'] == 'slow.txt'
            await app._undo_last_change()
            assert not (root / 'slow.txt').exists()

    with capsys.disabled():
        asyncio.run(scenario())
