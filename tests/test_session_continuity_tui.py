from isycode.tui import plain_text
import asyncio
import json

import pytest

from isycode.providers import ProviderError
from isycode.tui import TUIApp
from isycode.user_defaults import UserDefaultsStore
from test_daily_tui import configure


def test_tool_context_survives_next_turn_and_restart_without_replay(tmp_path, monkeypatch, capsys):
    root = configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace='recurring')
    (root / 'first.py').write_text('unique_read_result = 42\n')
    requests = []
    async def complete(provider, messages, **kwargs):
        requests.append(json.dumps(messages))
        if len(requests) == 1:
            return {'text': 'Read it.', 'tool_calls': [{'id': 'r', 'function': {
                'name': 'workspace_read', 'arguments': '{"path":"first.py"}'}}],
                'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}
        return {'text': 'Done.', 'tool_calls': [],
                'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}
    monkeypatch.setattr('isycode.tui.provider_complete', complete)
    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await app._run_chat('Read first.py.')
            sid = app._active_chat_session_id
            assert sid
            await app._run_chat('What did you read?')
            assert 'unique_read_result' in requests[-1]
            stored = app._chat_session_owner.resume(sid)[1]
            assert stored.state['tool_history'][0]['name'] == 'workspace_read'
        resumed = TUIApp()
        async with resumed.run_test() as pilot:
            await pilot.pause()
            await resumed._resume_chat_session(sid)
            before = len(requests)
            assert len(resumed._tool_history) == 1
            assert len(requests) == before
            assert resumed._usage.to_state()['requests'] == 3
            await resumed._run_chat('Continue from what you read.')
            assert 'unique_read_result' in requests[-1]
            assert 'untrusted' in requests[-1].lower()
            assert len(resumed._tool_history) == 1
    with capsys.disabled():
        asyncio.run(scenario())


def test_interrupted_turn_preserves_completed_tool_context(tmp_path, monkeypatch, capsys):
    root = configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace='recurring')
    (root / 'first.py').write_text('completed_tool_marker\n')
    calls = []
    async def complete(provider, messages, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            return {'text': '', 'tool_calls': [{'id': 'r', 'function': {
                'name': 'workspace_read', 'arguments': '{"path":"first.py"}'}}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
        raise ProviderError('failure', status=503)
    monkeypatch.setattr('isycode.tui.provider_complete', complete)
    from isycode import continuity_recovery

    async def no_wait(delay):
        return None

    monkeypatch.setattr(continuity_recovery, 'wait_fixed', no_wait)
    retries = continuity_recovery.POLICIES['PROVIDER'].max_attempts
    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await app._run_chat('Read and explain.')
            session = app._chat_session_owner.resume(app._active_chat_session_id)[1]
            assert session.messages == []
            assert 'completed_tool_marker' in session.state['tool_history'][0]['result']
            # The read ran once; the 503 step was re-sent (each attempt is a request).
            assert len(calls) == 2 + retries
            assert session.state['usage']['unknown_requests'] == 1 + retries
    with capsys.disabled():
        asyncio.run(scenario())


def test_usage_and_legacy_budget_do_not_impose_local_chat_caps(tmp_path, monkeypatch, capsys):
    root = configure(tmp_path, monkeypatch)
    (root / 'first.py').write_text('value = 1\n')
    UserDefaultsStore().update(chat_token_budget=10000)
    calls = []
    async def complete(provider, messages, **kwargs):
        calls.append(kwargs['max_tokens'])
        if len(calls) == 1:
            return {'text': 'Reading.', 'tool_calls': [{'id': 'r', 'function': {
                'name': 'workspace_read', 'arguments': '{"path":"first.py"}'}}],
                'usage': {'prompt_tokens': 9000, 'completion_tokens': 1000}}
        return {'text': 'Done.', 'tool_calls': [],
                'usage': {'prompt_tokens': 9000, 'completion_tokens': 1000}}
    monkeypatch.setattr('isycode.tui.provider_complete', complete)
    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await app._run_chat('Read it.')
            assert calls == [None, None]
            assert len(app._tool_history) == 1
            await app._run_chat('Continue.')
            assert calls == [None, None, None]
            assert 'usage unknown' not in app._usage_status_text().lower()
            assert '30000' in app._usage_status_text().replace(',', '')
    with capsys.disabled():
        asyncio.run(scenario())


def test_usage_status_shows_estimated_context_and_unknown_cost(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app._history = [{"role": "user", "content": "x" * 400}]
            text = app._usage_status_text().lower()
            # The default model may now get its window from the models.dev
            # snapshot; either way the locally estimated count keeps its "~".
            assert "ctx ~100" in text
            assert "cost" not in text
            assert "req" not in text
            assert "$0" not in text
    with capsys.disabled():
        asyncio.run(scenario())


def test_budget_defaults_are_validated_and_legacy_settings_load(tmp_path):
    store = UserDefaultsStore(tmp_path)
    assert store.load()['chat_token_budget'] == 0
    store.update(chat_token_budget=10000)
    store.update(answer_tokens=4096)
    assert store.load()['chat_token_budget'] == 10000
    for invalid in (True, -1, 123, '10000'):
        with pytest.raises(ValueError):
            store.update(chat_token_budget=invalid)


def test_usage_and_budget_fit_the_standard_terminal_width(tmp_path, monkeypatch, capsys):
    from textual.widgets import Static
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app._usage.record(None)
            app._refresh_usage()
            text = plain_text(app.query_one('#usage-status', Static))
            assert len(text) <= 80
            assert '+?' in text
    with capsys.disabled():
        asyncio.run(scenario())


def test_unreadable_legacy_budget_settings_do_not_block_provider_requests(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    calls = []
    async def complete(provider, messages, **kwargs):
        calls.append(True)
        return {'text': 'Answer.', 'tool_calls': []}
    monkeypatch.setattr('isycode.tui.provider_complete', complete)
    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            UserDefaultsStore().path.write_text('invalid JSON')
            await app._run_chat('Explain this.')
            assert calls == [True]
    with capsys.disabled():
        asyncio.run(scenario())


def test_chat_does_not_automatically_compact_long_history(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(chat_token_budget=10000)
    requests = []
    async def complete(provider, messages, **kwargs):
        requests.append(messages)
        return {'text': 'Old history summary.', 'tool_calls': [],
                'usage': {'prompt_tokens': 9900, 'completion_tokens': 100}}
    monkeypatch.setattr('isycode.tui.provider_complete', complete)
    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app._history = [{'role': role, 'content': 'x' * 15000}
                            for role in ('user', 'assistant') * 6]
            await app._run_chat('Continue.')
            assert len(requests) == 1
            assert app._conversation_summary == ''
            assert any(message.get('content') == 'Continue.' for message in requests[0])
            assert any(message.get('content') == 'x' * 15000 for message in requests[0])
            assert app._usage.to_state()['input_tokens'] == 9900
    with capsys.disabled():
        asyncio.run(scenario())


def test_failed_explicit_compaction_saves_unknown_consumption(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace='recurring')
    async def fail(provider, messages, **kwargs):
        raise ProviderError('not available', status=503)
    monkeypatch.setattr('isycode.tui.provider_complete', fail)
    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app._history = [{'role': 'user', 'content': 'Old conversation.'},
                            {'role': 'assistant', 'content': 'Old answer.'}] * 4
            await app._compact_conversation()
            assert app._active_chat_session_id
            state = app._chat_session_owner.resume(app._active_chat_session_id)[1].state
            assert state['usage']['unknown_requests'] == 1
    with capsys.disabled():
        asyncio.run(scenario())


def test_compact_uses_small_slot_and_user_instructions(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    from isycode.providers import save_model_slot
    save_model_slot('small', 'openai', 'gpt-small-fixture')
    calls = []

    async def complete(provider, messages, **kwargs):
        calls.append((provider.name, provider.model, messages))
        return {'text': 'Compact summary.', 'tool_calls': [],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}

    monkeypatch.setattr('isycode.tui.provider_complete', complete)

    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app._history = [
                {'role': 'user', 'content': 'Old conversation.'},
                {'role': 'assistant', 'content': 'Old answer.'},
            ] * 4
            await app._compact_conversation('Keep failing tests and exact paths.')
            assert calls[0][0:2] == ('openai', 'gpt-small-fixture')
            assert 'Keep failing tests and exact paths.' in calls[0][2][0]['content']
            assert app._conversation_summary == 'Compact summary.'

    with capsys.disabled():
        asyncio.run(scenario())


def test_cancellation_retains_unverified_threaded_tool_attempt(tmp_path, monkeypatch, capsys):
    import threading
    root = configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace='recurring')
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    async def complete(provider, messages, **kwargs):
        return {'text': '', 'tool_calls': [{'id': 'w', 'function': {
            'name': 'workspace_read', 'arguments': '{"path":"changed.txt"}'}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
    def delayed_owner_result():
        started.set()
        assert release.wait(5)
        (root / 'changed.txt').write_text('late effect')
        finished.set()
        return 'w', '{"written":true}'
    async def dispatch(self, call):
        return await asyncio.to_thread(delayed_owner_result)
    monkeypatch.setattr('isycode.tui.provider_complete', complete)
    monkeypatch.setattr(TUIApp, '_dispatch_chat_tool', dispatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            task = asyncio.create_task(app._run_chat('Do a slow operation.'))
            try:
                assert await asyncio.to_thread(started.wait, 5)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                session = app._chat_session_owner.resume(app._active_chat_session_id)[1]
                note = session.state['tool_history'][0]['result']
                assert 'unverified' in note.lower()
                assert 'written' not in note
            finally:
                release.set()
                await asyncio.to_thread(finished.wait, 5)
            assert (root / 'changed.txt').read_text() == 'late effect'
    with capsys.disabled():
        asyncio.run(scenario())


def test_cancelled_compaction_persists_unknown_usage(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace='recurring', chat_token_budget=10000)
    started = asyncio.Event()
    async def complete(provider, messages, **kwargs):
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr('isycode.tui.provider_complete', complete)
    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app._persist_chat_message('user', 'Old conversation.')
            app._history = [{'role': 'user', 'content': 'Old conversation.'},
                            {'role': 'assistant', 'content': 'Old answer.'}] * 4
            task = asyncio.create_task(app._compact_conversation())
            await asyncio.wait_for(started.wait(), 5)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            state = app._chat_session_owner.resume(app._active_chat_session_id)[1].state
            assert state['usage']['unknown_requests'] == 1
    with capsys.disabled():
        asyncio.run(scenario())


def test_cancel_after_applied_edit_retains_unverified_note(tmp_path, monkeypatch, capsys):
    root = configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace='recurring')
    (root / 'a.py').write_text('value = 1\n')
    async def complete(provider, messages, **kwargs):
        return {'text': '', 'tool_calls': [{'id': 'w', 'function': {
            'name': 'workspace_edit', 'arguments': json.dumps({
                'path': 'a.py', 'old_text': 'value = 1', 'new_text': 'value = 2'})}}],
            'usage': {'prompt_tokens': 2, 'completion_tokens': 1}}
    monkeypatch.setattr('isycode.tui.provider_complete', complete)
    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            async def approve(screen):
                return True
            app._await_screen = approve
            reached = asyncio.Event()
            async def diagnostics(*args):
                reached.set()
                await asyncio.Event().wait()
            app._post_edit_diagnostics = diagnostics
            task = asyncio.create_task(app._run_chat('Edit a.py.'))
            await asyncio.wait_for(reached.wait(), 5)
            assert (root / 'a.py').read_text() == 'value = 2\n'
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            session = app._chat_session_owner.resume(app._active_chat_session_id)[1]
            assert session.messages == []
            assert 'unverified' in session.state['tool_history'][0]['result'].lower()
    with capsys.disabled():
        asyncio.run(scenario())
