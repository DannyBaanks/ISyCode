"""The real TUI meets a second continuity (another process) of its open conversation."""
import asyncio
import json
import pytest

from isycode.tui import TUIApp
from isycode.tui_screens_sessions import SessionDivergedScreen
from isycode.user_defaults import UserDefaultsStore
from session_peer_client import PeerProcess
from test_daily_tui import configure


@pytest.fixture
def tui_env(tmp_path, monkeypatch):
    root = configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace='recurring')

    async def complete(provider, messages, **kwargs):
        return {'text': 'ok', 'tool_calls': [], 'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}

    monkeypatch.setattr('isycode.tui.provider_complete', complete)
    return root


async def _until(pilot, predicate, timeout=10.0):
    for _ in range(int(timeout / 0.05)):
        await pilot.pause(0.05)
        if predicate():
            return True
    return False


async def _click(pilot, selector: str) -> None:
    """Click a dialog button once the overlay really has it under the pointer.

    Pilot.click returns False when the widget is not under the pointer yet: on a
    slow runner the dialog is in the DOM before its layout is, and a click that
    misses leaves the dialog open while the test moves on.
    """
    for _ in range(int(10.0 / 0.05)):
        if await pilot.click(selector):
            return
        await pilot.pause(0.05)
    raise AssertionError(f"{selector} never came under the pointer")


def _run(tui_env, choice, check):
    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await app.wait_for_ready()
            await app._run_chat('Refactoriza el parser')
            sid = app._active_chat_session_id
            owner = app._chat_session_owner
            peer = PeerProcess(app._workspace_root, owner.store.root)
            try:
                assert peer(op='resume', sid=sid)['decision'] == 'ALLOW'
                assert peer(op='record', sid=sid, role='user', content='B: borra el parser',
                            state={'conversation_summary': 'resumen de B'})['decision'] == 'ALLOW'
            finally:
                peer.close()
            other_window = owner.store._read_bytes(sid)
            app.run_worker(app._run_chat('A: agrega tests'))
            # Pushed is not mounted: wait for the dialog's buttons before clicking one.
            assert await _until(pilot, lambda: isinstance(app.screen, SessionDivergedScreen)
                                and bool(app.screen.query('#diverged-reload')))
            assert owner.store._read_bytes(sid) == other_window  # nothing merged
            if choice == 'reload':
                await _click(pilot, '#diverged-reload')
                assert await _until(pilot, lambda: not isinstance(app.screen, SessionDivergedScreen))
                await pilot.press('y')  # confirm discarding what exists only here
            elif choice == 'fork':
                await _click(pilot, '#diverged-fork')
            else:
                await pilot.press('escape')
            assert await _until(pilot, lambda: app.screen is app.screen_stack[0])
            await _until(pilot, lambda: app._chat_turn_task is None or app._chat_turn_task.done(), 5)
            await pilot.pause(0.3)
            check(app, owner, sid, other_window)

    asyncio.run(scenario())


def test_fork_keeps_the_other_window_and_saves_mine_apart(tui_env, capsys):
    def check(app, owner, sid, other_window):
        assert owner.store._read_bytes(sid) == other_window
        new = app._active_chat_session_id
        assert new and new != sid
        mine = [m['content'] for m in owner.store.load(new).messages]
        assert 'A: agrega tests' in mine and 'B: borra el parser' not in mine
        assert owner.store.load(new).title.startswith('Fork:')

    with capsys.disabled():
        _run(tui_env, 'fork', check)


def test_reload_shows_exactly_the_saved_version(tui_env, capsys):
    def check(app, owner, sid, other_window):
        # Re-based on the saved version, this window may save on top of it again
        # (draft, usage); what the other window wrote must still be exactly there.
        other_messages = [m['content'] for m in json.loads(other_window)['messages']]
        assert [m['content'] for m in owner.store.load(sid).messages] == other_messages
        assert 'A: agrega tests' not in other_messages
        assert app._active_chat_session_id == sid
        saved = owner.store.load(sid)
        assert [m['content'] for m in app._history] == [m['content'] for m in saved.messages]
        assert app._conversation_summary == 'resumen de B'
        assert not owner.is_diverged(sid)

    with capsys.disabled():
        _run(tui_env, 'reload', check)


def test_continue_without_saving_never_writes_the_saved_conversation(tui_env, capsys):
    def check(app, owner, sid, other_window):
        assert owner.is_diverged(sid)
        app._persist_chat_message('user', 'A: otro turno')
        app._save_draft()
        assert owner.store._read_bytes(sid) == other_window
        assert any('A: agrega tests' == m['content'] for m in app._history)  # kept in memory

    with capsys.disabled():
        _run(tui_env, 'unsaved', check)
