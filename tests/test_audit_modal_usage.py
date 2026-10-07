"""Background usage updates must not look for main widgets in a modal."""
import asyncio

from textual.screen import ModalScreen
from textual.widgets import Static

from isycode.tui import TUIApp, plain_text


class UsageApp(TUIApp):
    def on_mount(self):
        # Exercise the real layout without optional integrations or onboarding.
        pass


def test_usage_refresh_does_not_crash_with_an_active_modal(tmp_path, monkeypatch):
    async def no_startup(self):
        pass
    monkeypatch.setattr(TUIApp, "_startup_workspace", no_startup)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))

    async def scenario():
        app = UsageApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            main = app.screen
            await app.push_screen(ModalScreen())
            await pilot.pause()
            assert app.screen is not main
            app._refresh_usage()
            assert "tok" in plain_text(main.query_one("#usage-status", Static))
            app.pop_screen()
    asyncio.run(scenario())
