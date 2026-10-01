import asyncio
import pytest
from isycode.tui import TUIApp
from test_daily_tui import configure

def test_openai_menu_has_separate_subscription_methods(tmp_path, monkeypatch, capsys):
    configure(tmp_path,monkeypatch)
    async def run():
        app=TUIApp()
        async with app.run_test() as p:
            await p.pause()
            app._select_menu_entry(app._entry('OpenAI','provider','openai'))
            assert app._menu_mode == 'provider_auth_methods'
            assert {'auth_api_key','auth_browser','auth_device'}.issubset({e['kind'] for e in app._menu_entries})
    with capsys.disabled(): asyncio.run(run())

@pytest.mark.parametrize('cancel',[False,True])
def test_native_subscription_login_and_cancel_never_save_challenge(tmp_path,monkeypatch,capsys,cancel):
    configure(tmp_path,monkeypatch)
    import isycode.provider_auth as auth
    executable=tmp_path/'codex';executable.write_text('#!/bin/sh\nexit 0\n');executable.chmod(0o700)
    monkeypatch.setenv('ISYCODE_CODEX_EXECUTABLE',str(executable))
    class Peer:
        def __init__(self,*a,**k): self.closed=False
        async def __aenter__(self): return self
        async def start_login(self,method): return {'method':method,'login_id':'private-id','url':'https://auth.openai.com/device','user_code':'PRIVATE-CODE'}
        async def wait_login(self,login_id):
            if cancel: await asyncio.Event().wait()
            await asyncio.sleep(.05);return True
        async def account(self): return {'authenticated':True,'method':'chatgpt','plan':'plus'}
        async def close(self): self.closed=True
    monkeypatch.setattr('isycode.codex_connector.CodexConnector',Peer)
    async def run():
        from isycode.tui import TailscaleConfirmScreen
        from isycode.provider_auth_screens import SubscriptionLoginScreen
        app=TUIApp()
        async with app.run_test(size=(80,24)) as p:
            await p.pause()
            task=asyncio.create_task(app._connect_chatgpt('device'))
            for _ in range(100):
                await p.pause(.01)
                if isinstance(app.screen,TailscaleConfirmScreen): break
            assert isinstance(app.screen,TailscaleConfirmScreen)
            await p.press('tab','enter')
            if cancel:
                for _ in range(100):
                    await p.pause(.01)
                    if isinstance(app.screen,SubscriptionLoginScreen): break
                assert isinstance(app.screen,SubscriptionLoginScreen)
                await p.press('escape')
            await asyncio.wait_for(task,10)
            from isycode.providers import selected_provider_name
            assert selected_provider_name() == ('openai' if cancel else 'chatgpt')
            assert all('PRIVATE-CODE' not in m['content'] for m in app._history)
            for path in (tmp_path/'state').rglob('*'):
                if path.is_file(): assert b'PRIVATE-CODE' not in path.read_bytes()
    with capsys.disabled(): asyncio.run(run())


def test_slash_catalog_cannot_spawn_connector_without_grants(tmp_path,monkeypatch,capsys):
    root=configure(tmp_path,monkeypatch)
    executable=tmp_path/'codex';executable.write_text('#!/bin/sh\nexit 0\n');executable.chmod(0o700)
    monkeypatch.setenv('ISYCODE_CODEX_EXECUTABLE',str(executable))
    monkeypatch.setenv('ISYCODE_PROVIDER','chatgpt')
    calls=[]
    monkeypatch.setattr('isycode.providers.Provider.models',lambda self: calls.append('unowned') or ['model'])
    async def run():
        app=TUIApp()
        async with app.run_test() as p:
            await p.pause()
            from isycode.workspace_authority import WorkspaceAuthority
            WorkspaceAuthority(root).set_grant('provider.request',enabled=False)
            _,command,arg=app._plugins.route('/provider models')
            await command.handler(app,arg)
            assert calls==[]
    with capsys.disabled(): asyncio.run(run())


def test_providers_opens_the_selector_and_provider_reports_saved_credentials(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr("isycode.tui.provider_credential_state",
                        lambda name: "saved" if name == "nvidia" else "missing")

    async def run():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            _, command, arg = app._plugins.route("/providers")
            await command.handler(app, arg)
            assert app._menu_mode == "providers"
            assert app._menu_title == "Providers · ISyCode chat"
            assert not any("Provider catalog" in str(child) for child in app.query_one("#chat").children)

            lines = []
            original = app._append
            app._append = lambda value, *_args, **_kwargs: lines.append(str(value))
            _, command, arg = app._plugins.route("/provider")
            await command.handler(app, arg)
            app._append = original
            assert any("nvidia" in line and "key saved in ISyCode vault" in line for line in lines)
            assert any("/providers to choose" in line for line in lines)

    with capsys.disabled():
        asyncio.run(run())
