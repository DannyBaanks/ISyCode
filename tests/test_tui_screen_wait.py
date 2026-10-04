"""Approval screens must work from chat turns and slash commands (plain asyncio tasks)."""
import ast
import asyncio
from pathlib import Path

from textual.app import App
from textual.screen import ModalScreen
from textual.widgets import Static

SOURCE = Path(__file__).resolve().parents[1] / "src" / "isycode" / "tui.py"


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
    calls = set()
    plugins = ""
    for path in (SOURCE, *sorted(SOURCE.parent.glob("tui_app_*.py"))):
        source = path.read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name != "TUIApp" and not node.name.endswith("Mixin"):
                continue
            calls.update(item.func.attr for item in ast.walk(node)
                         if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute))
            if node.name == "TUIApp":
                plugins = ast.get_source_segment(source, next(
                    item for item in node.body if getattr(item, "name", "") == "_register_builtin_plugins"))
    assert "push_screen_wait" not in calls
    assert "push_screen_wait" not in plugins
