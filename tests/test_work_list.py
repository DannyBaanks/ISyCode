"""The local work list is not a multi-agent supervisor."""
import asyncio
import json
from datetime import datetime

import pytest

from isycode.chat_sessions import ChatSessionStore
from isycode.work_list import fit_heading
from isycode.session_owner import ChatSessionOwner
from isycode.tui import TUIApp, plain_text
from isycode.user_defaults import UserDefaultsStore
from isycode.workspace_authority import WorkspaceAuthority
from test_daily_tui import configure


def test_owned_messages_get_real_local_time_and_export_keeps_it(tmp_path, monkeypatch):
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    root = tmp_path / 'project'; root.mkdir()
    auth = WorkspaceAuthority(root); auth.set_mode('classic')
    owner = ChatSessionOwner(root, auth, tmp_path / 'sessions')
    before = datetime.now().astimezone()
    outcome, sid = owner.record(None, 'user', 'hello')
    after = datetime.now().astimezone()
    assert outcome.decision == 'ALLOW'
    message = owner.resume(sid)[1].messages[0]
    recorded = datetime.fromisoformat(message['sent_at'])
    assert before.replace(microsecond=0) <= recorded <= after
    exported = json.loads(owner.export(sid)[1])
    assert exported['messages'][0]['sent_at'] == message['sent_at']
    imported = owner.store.parse_import(json.dumps(exported))
    assert imported.messages[0]['sent_at'] == message['sent_at']
    legacy = owner.store.create('old')
    legacy.messages = [{'role': 'user', 'content': 'old'}]
    owner.store.save(legacy)
    assert 'sent_at' not in owner.store.load(legacy.session_id).messages[0]
    stamp = '2026-10-02T17:06:00-06:00'
    kept, kept_id = owner.record(None, 'user', 'stamped', sent_at=stamp)
    assert kept.decision == 'ALLOW'
    assert owner.resume(kept_id)[1].messages[0]['sent_at'] == stamp
    replaced, replaced_id = owner.record(None, 'user', 'naive', sent_at='2026-10-02T17:06:00')
    assert replaced.decision == 'ALLOW'
    naive = owner.resume(replaced_id)[1].messages[0]['sent_at']
    assert naive != '2026-10-02T17:06:00'
    assert datetime.fromisoformat(naive).tzinfo is not None


def test_work_heading_keeps_the_counts_when_the_path_is_long():
    path = '/home/danny/Development/ISyCo Git/a-very-long-workspace-name'
    heading = fit_heading(path, '2 idle', 36)
    assert heading.endswith('2 idle')
    assert '…' in heading
    assert fit_heading(path, '2 idle', 200) == f'{path}    2 idle'


def test_sessions_panel_switches_here_and_blocks_during_generation(tmp_path, monkeypatch, capsys):
    root = configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace='recurring')
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            owner = app._chat_session_owner
            _, first = owner.record(None, 'user', 'First task')
            _, second = owner.record(None, 'user', 'Second task')
            await app._show_chat_sessions()
            await pilot.pause()
            panel = app.query_one('#work-list')
            assert panel.display and not app._menu_mode
            assert not app.query_one('#chat').display
            assert app.screen.id == '_default'
            labels = ' '.join(str(option.prompt) for option in app.query_one('#work-conversations')._options)
            assert 'Idle' in labels and 'First task' in labels and 'Second task' in labels
            assert 'now' in labels
            await app._resume_chat_session(first)
            assert app._active_chat_session_id == first
            stop = asyncio.Event()
            task = asyncio.create_task(stop.wait()); app._loop_task = task
            try:
                await app._resume_chat_session(second)
                assert app._active_chat_session_id == first
                app._start_new_conversation()
                assert app._active_chat_session_id == first
                assert app._conversation_status() == 'generating'
            finally:
                task.cancel(); await asyncio.gather(task, return_exceptions=True); app._loop_task = None
            await app._resume_chat_session(second)
            assert app._active_chat_session_id == second
            app._start_new_conversation()
            await pilot.pause()
            assert app._active_chat_session_id not in {first, second, None}
            assert app._conversation_status() == 'idle'
            assert 'sent_at' not in json.dumps(app._history)
    with capsys.disabled():
        asyncio.run(scenario())
