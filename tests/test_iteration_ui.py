import asyncio
import json

import pytest
from test_daily_tui import configure
from isycode.tui import TUIApp, PromptArea
from isycode.iteration import IterationOwner
from isycode.workspace_authority import WorkspaceAuthority


def test_command_does_not_mount_user_message(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            mounted = []
            monkeypatch.setattr(app, '_mount_user_turn', lambda *a: mounted.append(a))
            monkeypatch.setattr(app, '_start_operation', lambda coroutine, label: coroutine.close())
            prompt = app.query_one('#prompt-input', PromptArea)
            app._accept_prompt(prompt, '/providers')
            assert mounted == []
            app._accept_prompt(prompt, 'ordinary message')
            assert mounted[0][0] == 'ordinary message'
    asyncio.run(scenario())


def test_iteration_three_model_ui_and_sessions_marker(tmp_path, monkeypatch):
    root = configure(tmp_path, monkeypatch)
    monkeypatch.setenv('NVIDIA_NIM_API_KEY', 'test-not-real')
    choices = [dict(provider='nvidia',model='fixture-a'), dict(provider='openai',model='fixture-b'), dict(provider='nvidia',model='fixture-c')]
    monkeypatch.setattr('isycode.providers.child_model_choices', lambda: choices)
    seen = []
    async def transport(provider, messages, **kwargs):
        if messages[-1]['role'] == 'user':
            task = json.loads(messages[-1]['content'])
            return {'text':'','tool_calls':[{'id':'read','function':{'name':'read_iteration','arguments':json.dumps({'ref':task['iteration_ref'],'after_seq':0,'through_seq':task['head_seq']})}}]}
        records = json.loads(messages[-1]['content'])
        seen.append((provider.model,len(records)))
        return {'text':'TOKEN_A=ui-proof' if provider.model=='fixture-a' else 'HUMAN_HANDOFF: TOKEN_A=ui-proof verified','tool_calls':[]}
    monkeypatch.setattr('isycode.iteration.provider_complete', transport)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(110,38)) as pilot:
            await pilot.pause()
            authority = WorkspaceAuthority(root)
            for action in ['session.create','session.resume']:
                authority.set_grant(action,enabled=True)
            authority.set_grant('provider.request',enabled=True,network_hosts=['integrate.api.nvidia.com','api.openai.com'])
            monkeypatch.setattr(app,'_sessions_enabled',lambda:True)
            selected = iter(choices)
            async def select(screen): return next(selected)
            monkeypatch.setattr(app,'_await_screen',select)
            app._loop_task = asyncio.current_task()  # Same command task must be allowed.
            await app._run_iteration_window('Test UI iteration')
            app._loop_task = None
            assert seen == [('fixture-a',1),('fixture-b',2),('fixture-c',3)]
            states = app._iteration_owner().list_sessions()
            assert len(states)==1 and states[0]['status']=='WAITING_FOR_HUMAN'
            await app._refresh_work_list()
            row = next(r for r in app._work_rows if r.get('session_kind')=='iterative')
            assert row['id']=='iteration:'+states[0]['iteration_session_id']
            await app._resume_chat_session(row['id'])
            assert app._iteration_owner().inspect(states[0]['iteration_session_id'])['head_seq']==4
    asyncio.run(scenario())


def test_iterative_row_can_be_deleted(tmp_path, monkeypatch):
    root = configure(tmp_path, monkeypatch)
    authority = WorkspaceAuthority(root)
    authority.set_grant('session.create', enabled=True)
    authority.set_grant('session.resume', enabled=True)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            monkeypatch.setattr(app, '_sessions_enabled', lambda: True)
            owner = app._iteration_owner()
            people = [dict(provider='nvidia', model='fixture-a', role='A'),
                      dict(provider='openai', model='fixture-b', role='B')]
            sid = owner.create_iteration('Erase me', people)
            kept = owner.create_iteration('Keep me', people)
            board = app.query_one('#work-list')
            board.display = True
            await pilot.pause()
            await app._refresh_work_list()
            await pilot.pause()
            listing = board.query_one('#work-conversations')
            index = next(i for i in range(listing.option_count)
                         if listing.get_option_at_index(i).id == 'iteration:' + sid)
            option = listing.get_option_at_index(index)
            assert option.prompt.plain.endswith('[×]')
            from rich.style import Style
            assert any(isinstance(span.style, Style)
                       and span.style.meta.get('delete_session') == 'iteration:' + sid
                       for span in option.prompt.spans)
            seen = []

            async def decline(screen):
                seen.append(screen.title_text)
                return False

            app._await_screen = decline
            listing.highlighted = index
            listing.focus()
            await pilot.press('ctrl+d')
            await pilot.pause()
            assert seen == ['Erase me']
            assert owner.inspect(sid)['title'] == 'Erase me'

            async def accept(screen):
                seen.append((screen.kind, screen.title_text))
                return True

            app._await_screen = accept
            await app._delete_iteration_session(sid)
            await pilot.pause()
            await app._refresh_work_list()
            assert seen[-1] == ('iteration', 'Erase me')
            with pytest.raises(FileNotFoundError):
                owner.inspect(sid)
            assert owner.inspect(kept)['title'] == 'Keep me'
            ids = {row['id'] for row in app._work_rows}
            assert 'iteration:' + sid not in ids
            assert 'iteration:' + kept in ids
    asyncio.run(scenario())
