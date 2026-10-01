"""Exercise the complete TUI against the installed Textual dependency."""
import asyncio

from isycode.tui import PromptArea, TUIApp, WorkspaceModeScreen, WorkspaceSetupScreen


def test_tui_starts_in_a_temporary_security_workspace(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, WorkspaceSetupScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, WorkspaceModeScreen)
            await pilot.press("escape")
            await pilot.pause()
            prompt = app.query_one("#prompt-input", PromptArea)
            assert prompt.text == ""
            assert app.focused is prompt
            assert not (project / ".isyroot").exists()
            await pilot.press("f6")
            await pilot.pause()
            assert app.query_one("#files-view").display
            assert not app.query_one("#overview-view").display
            await pilot.press("shift+f6")
            await pilot.pause()
            assert app.query_one("#overview-view").display
            assert not app.query_one("#files-view").display

    # Textual redirects stdout itself; nested pytest capture can leave its
    # message pump waiting during asyncio shutdown.
    with capsys.disabled():
        asyncio.run(scenario())
