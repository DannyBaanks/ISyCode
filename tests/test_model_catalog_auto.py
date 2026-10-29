import asyncio
from test_daily_tui import configure
from isycode.tui import TUIApp, ModelsScreen
from isycode.providers import Provider
from isycode import reasoning_options as reasoning


def test_open_models_discovers_concrete_catalog_and_model_effort(tmp_path,monkeypatch):
    configure(tmp_path,monkeypatch)
    calls=[]
    def models(provider):
        calls.append(provider.name)
        reasoning.record_catalog(provider.name,'concrete-model',{'supportedReasoningEfforts':[{'reasoningEffort':'low'},{'reasoningEffort':'high'}]})
        return ['concrete-model']
    monkeypatch.setattr(Provider,'models',models)
    async def run():
        app=TUIApp()
        async with app.run_test(size=(120,40)) as pilot:
            await pilot.pause()
            app._render_menu('branch','Models',app._branch_entries('models'))
            for _ in range(8):await pilot.pause(.1)
            assert calls==['openai']
            assert {'provider':'openai','model':'concrete-model'} in app._child_model_choices()
            assert isinstance(app.screen,ModelsScreen)
            choices=[entry['value'] for entry in app.screen.entries if entry['kind']=='model']
            assert 'openai|concrete-model' in choices
            assert 'openai|gpt-6-luna' not in choices
            app._open_reasoning_menu('openai','concrete-model')
            assert [e['value'].rsplit('|',1)[-1] for e in app._menu_entries]==['default','low','high']
    asyncio.run(run())


def test_expanding_another_provider_loads_its_catalog_without_switching(tmp_path,monkeypatch):
    configure(tmp_path,monkeypatch)
    from isycode.providers import selected_provider_name
    from textual.widgets import Collapsible
    monkeypatch.setenv('NVIDIA_NIM_API_KEY','test-not-real')
    calls=[]
    monkeypatch.setattr(Provider,'models',lambda p:calls.append(p.name) or [p.name+'-concrete'])
    async def run():
        app=TUIApp()
        async with app.run_test(size=(120,40)) as pilot:
            await pilot.pause()
            app._render_menu('branch','Models',app._branch_entries('models'))
            # The screen is rebuilt when a catalog load finishes; wait for conditions,
            # not fixed sleeps, so a slow runner cannot catch it half-built.
            async def until(condition):
                for _ in range(200):
                    await pilot.pause(.05)
                    try:
                        if condition():
                            return True
                    except Exception:
                        pass
                return False
            assert await until(lambda: calls==['openai'] and not getattr(app,'_account_models_loading',False)
                               and app.screen.query_one('#model-provider-nvidia',Collapsible) is not None)
            app.screen.query_one('#model-provider-nvidia',Collapsible).collapsed=False
            assert await until(lambda: 'nvidia|nvidia-concrete' in [e['value'] for e in app.screen.entries if e['kind']=='model']
                               and not app.screen.query_one('#model-provider-nvidia',Collapsible).collapsed)
            assert calls==['openai','nvidia']
            assert selected_provider_name()=='openai'
            assert not app.screen.query_one('#model-provider-nvidia',Collapsible).collapsed
            assert 'nvidia|nvidia-concrete' in [e['value'] for e in app.screen.entries if e['kind']=='model']
    asyncio.run(run())


def test_catalog_default_effort_is_model_specific(monkeypatch):
    monkeypatch.setattr(reasoning,'_CATALOG',{})
    monkeypatch.setattr(reasoning,'_CATALOG_DEFAULTS',{})
    monkeypatch.setattr(reasoning,'_SELECTIONS',{})
    monkeypatch.delenv('ISYCODE_REASONING_EFFORT',raising=False)
    monkeypatch.delenv('ISYMOTRON_REASONING_EFFORT',raising=False)
    reasoning.record_catalog('chatgpt','fixture',{'supportedReasoningEfforts':[{'reasoningEffort':'low'},{'reasoningEffort':'high'}],'defaultReasoningEffort':'high'})
    assert reasoning.effective_reasoning('chatgpt','fixture','medium')=='high'
    reasoning.select_reasoning('chatgpt','fixture','low')
    assert reasoning.effective_reasoning('chatgpt','fixture','medium')=='low'


def test_a_catalog_refresh_before_the_picker_mounts_does_not_stack_two_pickers(tmp_path, monkeypatch):
    """Regression: the push is deferred; a second render meanwhile must update it,
    not schedule another picker that later catalog loads would never reach."""
    configure(tmp_path, monkeypatch)
    from isycode.tui import ModelsScreen
    monkeypatch.setattr(Provider, 'models', lambda p: [])

    async def run():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            first = app._branch_entries('models')
            app._render_menu('branch', 'Models', first)
            later = first + [{'label': 'late row', 'kind': 'info', 'value': '', 'detail': ''}]
            app._render_menu('branch', 'Models', later)  # same tick, before the push ran
            for _ in range(10):
                await pilot.pause(.05)
            pickers = [screen for screen in app.screen_stack if isinstance(screen, ModelsScreen)]
            assert len(pickers) == 1
            assert pickers[0].entries == app._menu_entries  # the latest render reached it
    asyncio.run(run())
