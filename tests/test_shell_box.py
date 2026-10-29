import asyncio
from types import SimpleNamespace
from isycode.tui import TUIApp, ShellBox, ShellProcessesScreen
from isycode.command_runner import CommandRunOwner
from test_daily_tui import configure

def test_background_returns_before_completion_and_stop_keeps_chat_alive(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr(TUIApp, "_command_tool_enabled", lambda self: True)
    monkeypatch.setattr(TUIApp, "_request_is_quiet", lambda *args: True)
    monkeypatch.setattr(CommandRunOwner, "prepare", lambda *args, **kwargs: SimpleNamespace(argv=("echo", "fixture"), request=object(), timeout_s=120))
    async def scenario():
        started, stopped = asyncio.Event(), asyncio.Event()
        async def run(self, preview, approval, on_output):
            on_output("live output\n")
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                stopped.set()
                raise
        monkeypatch.setattr(CommandRunOwner, "run", run)
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            result = await app._run_workspace_command({"argv": ["echo", "fixture"], "background": True})
            assert 'process-1' in result
            await asyncio.wait_for(started.wait(), 3)
            await pilot.press("ctrl+s")
            assert app.query_one("#shell-box", ShellBox).display
            app._open_shell_box()
            await pilot.pause()
            assert isinstance(app.screen, ShellProcessesScreen)
            app.screen._selected_job = "process-1"
            app.screen.refresh_jobs()
            await pilot.click("#shell-stop")
            await asyncio.wait_for(stopped.wait(), 3)
            await pilot.pause()
            assert app._shell_jobs["process-1"]["status"] == "cancelled"
            await pilot.press("escape", "ctrl+s")
            assert app.query_one("#idea-box").display
    asyncio.run(scenario())
