"""Approval screens must work from chat turns and slash commands (plain asyncio tasks)."""
import ast
import asyncio
from pathlib import Path

from textual.app import App
from textual.screen import ModalScreen
from textual.widgets import Static

SOURCE = Path(__file__).parent / "isycode" / "tui.py"


def test_await_screen_works_outside_a_textual_worker():
    from isycode.tui import TUIApp

    class AutoDismiss(ModalScreen[bool]):
        def compose(self):
            yield Static("approve?")

        def on_mount(self):
            self.dismiss(True)

    result = {}

    class Host(App):
        _await_screen = TUIApp._await_screen

        def on_mount(self):
            async def operation():
                result["value"] = await self._await_screen(AutoDismiss())
            asyncio.get_running_loop().create_task(operation())

    async def scenario():
        async with Host().run_test() as pilot:
            for _ in range(20):
                await pilot.pause()

    asyncio.run(scenario())
    assert result == {"value": True}


def test_tui_app_never_calls_push_screen_wait():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    calls = {node.func.attr for node in ast.walk(app)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "push_screen_wait" not in calls
    plugins = ast.get_source_segment(SOURCE.read_text(encoding="utf-8"), next(
        node for node in app.body if getattr(node, "name", "") == "_register_builtin_plugins"))
    assert "push_screen_wait" not in plugins
