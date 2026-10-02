import asyncio
import json
import pytest

def test_recent_models_keep_provider_identity_and_multiple_models(tmp_path,monkeypatch):
    from isycode.providers import save_provider_selection, recent_models
    monkeypatch.setenv('ISYCODE_STATE_HOME',str(tmp_path/'state'))
    save_provider_selection('openai','same');save_provider_selection('nvidia','same');save_provider_selection('openai','other')
    assert recent_models()[:3]==[{'provider':'openai','model':'other'},{'provider':'nvidia','model':'same'},{'provider':'openai','model':'same'}]
    save_provider_selection('openai','same')
    assert len(recent_models())==3 and recent_models()[0]=={'provider':'openai','model':'same'}

def test_child_loop_executes_tools_and_denies_recursive_delegation():
    from isycode.subagents import run_child
    class Provider:name='nvidia';model='child-model'
    calls=[];tools=[]
    async def complete(messages):
        calls.append(list(messages))
        if len(calls)==1:return {'text':'checking','tool_calls':[{'id':'one','function':{'name':'workspace_read','arguments':'{}'}}]}
        return {'text':'done','tool_calls':[]}
    async def dispatch(call):tools.append(call);return call['id'],'verified read'
    result=asyncio.run(run_child(Provider(), 'inspect parser', [{'role':'system','content':'boundary'}], ['workspace_read'], complete, dispatch))
    assert result['status']=='completed' and result['provider']=='nvidia' and result['model']=='child-model'
    assert len(tools)==1 and calls[1][-1]['content']=='verified read'
    recursive_calls=[]
    async def recursive(messages):
        recursive_calls.append(True)
        if len(recursive_calls)==1:
            return {'text':'','tool_calls':[{'id':'loop','function':{'name':'delegate_task','arguments':'{}'}}]}
        return {'text':'done','tool_calls':[]}
    tools.clear()
    recursive_tools=[]
    async def dispatch_recursive(call):
        recursive_tools.append(call)
        return await dispatch(call)
    result=asyncio.run(run_child(Provider(),'task',[],['workspace_read'],recursive,dispatch_recursive))
    assert result['status']=='completed' and tools==[]
    assert len(recursive_calls)==2
    assert recursive_tools==[]
    with pytest.raises(ValueError):asyncio.run(run_child(Provider(),'',[],[],complete,dispatch))

@pytest.mark.parametrize('deny_network',[False,True])
def test_native_cross_provider_child_edits_with_existing_diff_approval(tmp_path,monkeypatch,capsys,deny_network):
    from test_daily_tui import configure
    from isycode.tui import TUIApp,WriteApprovalScreen
    from isycode.providers import save_provider_selection,selected_provider_name,selected_model_name
    from isycode.subagent_screen import SubagentModelScreen
    from isycode.workspace_authority import WorkspaceAuthority
    from isycode.action_audit import ActionAuditJournal
    root=configure(tmp_path,monkeypatch);(root/'app.py').write_text('value = 1\n')
    monkeypatch.setenv('NVIDIA_NIM_API_KEY','child-key-not-real')
    save_provider_selection('nvidia','child-model')
    seen=[]
    async def complete(provider,messages,**kwargs):
        seen.append((provider.name,provider.model,provider.base_url,list(messages)))
        assert all(tool['function']['name']!='delegate_task' for tool in kwargs['tools'])
        if len(seen)==1:
            return {'text':'','tool_calls':[{'id':'child-edit','type':'function','function':{'name':'workspace_edit','arguments':json.dumps({'path':'app.py','old_text':'value = 1','new_text':'value = 2'})}}]}
        assert json.loads(messages[-1]['content'])['status']=='written'
        return {'text':'Edit verified.','tool_calls':[]}
    monkeypatch.setattr('isycode.tui.provider_complete',complete)
    async def scenario():
        app=TUIApp()
        async with app.run_test(size=(100,32)) as pilot:
            await pilot.pause()
            authority=WorkspaceAuthority(root)
            if deny_network:authority.set_mode('security')
            authority.set_grant('provider.request',enabled=not deny_network,network_hosts=['integrate.api.nvidia.com'])
            task=asyncio.create_task(app._run_subagent('Change app.py value to 2.'))
            for _ in range(100):
                await pilot.pause(.01)
                if isinstance(app.screen,SubagentModelScreen):break
            assert isinstance(app.screen,SubagentModelScreen)
            await app.screen.ready.wait()
            await pilot.pause(.1)
            await pilot.click('#child-launch')
            if not deny_network:
                for _ in range(100):
                    await pilot.pause(.01)
                    if isinstance(app.screen,WriteApprovalScreen):break
                assert isinstance(app.screen,WriteApprovalScreen)
                assert (root/'app.py').read_text()=='value = 1\n'
                await pilot.press('tab','enter')
            result=await asyncio.wait_for(task,10)
            assert selected_provider_name()=='openai' and selected_model_name()=='gpt-6-luna'
            assert not app._subagent_running
            if deny_network:
                assert result['status']=='blocked' and seen==[] and (root/'app.py').read_text()=='value = 1\n'
            else:
                assert result['status']=='completed' and len(seen)==2 and seen[0][:3]==('nvidia','child-model','https://integrate.api.nvidia.com/v1')
                assert (root/'app.py').read_text()=='value = 2\n'
                assert ActionAuditJournal(root).verify().status=='PASS'
    with capsys.disabled():asyncio.run(scenario())

def test_native_child_cancel_never_sends_or_changes_main_model(tmp_path,monkeypatch,capsys):
    from test_daily_tui import configure
    from isycode.tui import TUIApp
    from isycode.providers import save_provider_selection
    from isycode.subagent_screen import SubagentModelScreen
    configure(tmp_path,monkeypatch);save_provider_selection('openai','registered')
    async def forbidden(*a,**k):raise AssertionError('cancel sent a provider request')
    monkeypatch.setattr('isycode.tui.provider_complete',forbidden)
    async def scenario():
        app=TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause();task=asyncio.create_task(app._run_subagent('inspect'))
            for _ in range(100):
                await pilot.pause(.01)
                if isinstance(app.screen,SubagentModelScreen):break
            await pilot.press('escape')
            assert await asyncio.wait_for(task,5)=={'status':'cancelled'}
            assert not app._subagent_running
    with capsys.disabled():asyncio.run(scenario())

def test_escape_cancels_launched_native_child_and_transport(tmp_path,monkeypatch,capsys):
    from test_daily_tui import configure
    from isycode.tui import TUIApp
    from isycode.providers import save_provider_selection
    from isycode.subagent_screen import SubagentModelScreen
    configure(tmp_path,monkeypatch);save_provider_selection('openai','registered')
    entered=asyncio.Event();stopped=[]
    async def block(*args,**kwargs):
        entered.set()
        try:await asyncio.Event().wait()
        finally:stopped.append(True)
    monkeypatch.setattr('isycode.tui.provider_complete',block)
    async def scenario():
        app=TUIApp()
        async with app.run_test(size=(100,32)) as pilot:
            await pilot.pause();app._start_operation(app._run_subagent('inspect'),'Child')
            task=app._loop_task
            for _ in range(100):
                await pilot.pause(.01)
                if isinstance(app.screen,SubagentModelScreen):break
            await app.screen.ready.wait();await pilot.pause(.1);await pilot.click('#child-launch')
            await asyncio.wait_for(entered.wait(),5)
            await pilot.press('escape')
            with pytest.raises(asyncio.CancelledError):await asyncio.wait_for(task,5)
            assert stopped==[True] and not app._subagent_running and app._subagent_task is None
    with capsys.disabled():asyncio.run(scenario())
