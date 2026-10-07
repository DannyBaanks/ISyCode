import asyncio
from isycode.tui import TUIApp,PromptArea
from test_daily_tui import configure

def test_slash_filters_inline_keeps_focus_and_never_opens_settings(tmp_path,monkeypatch,capsys):
    configure(tmp_path,monkeypatch)
    async def run():
        app=TUIApp()
        async with app.run_test(size=(80,24)) as p:
            await p.pause();prompt=app.query_one(PromptArea)
            await p.press('/')
            assert not app.query_one('#action-menu').display
            assert app.query_one('#slash-suggestions').display and app.focused is prompt
            await p.press('p','r','o')
            assert all(e['value'].startswith('pro') for e in app._slash_matches)
            await p.press('enter');await p.pause()
            assert prompt.text.startswith('/provider') and prompt.text.endswith(' ')
            assert not app.query_one('#slash-suggestions').display
            assert app._loop_task is None
            prompt.load_text('/');await p.pause();await p.press('escape')
            assert prompt.text=='/' and not app.query_one('#slash-suggestions').display
            app._open_settings_menu();await p.pause()
            assert app.query_one('#action-menu').display
    with capsys.disabled(): asyncio.run(run())


def test_plain_text_and_command_arguments_do_not_show_suggestions(tmp_path,monkeypatch,capsys):
    configure(tmp_path,monkeypatch)
    async def run():
        app=TUIApp()
        async with app.run_test() as p:
            await p.pause();prompt=app.query_one(PromptArea)
            for text in ('hello /','/run echo hello','/not-a-command','hello'):
                prompt.load_text(text);await p.pause()
                assert not app.query_one('#slash-suggestions').display
    with capsys.disabled(): asyncio.run(run())


def test_ctrl_p_opens_the_command_palette_from_a_focused_composer(tmp_path,monkeypatch,capsys):
    # The composer once bound ctrl+p to paste review, which shadowed the
    # app-wide "Ctrl+P commands" shortcut the footer advertises.
    configure(tmp_path,monkeypatch)
    async def run():
        app=TUIApp()
        async with app.run_test(size=(100,40)) as p:
            await p.pause();prompt=app.query_one(PromptArea)
            assert app.focused is prompt
            await p.press('ctrl+p');await p.pause()
            assert app.query_one('#slash-suggestions').display
            assert app._slash_matches and app.focused is prompt
            await p.press('escape');await p.pause()
            assert not app.query_one('#slash-suggestions').display
    with capsys.disabled(): asyncio.run(run())
