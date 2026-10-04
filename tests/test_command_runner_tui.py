"""TUI wiring for sandboxed commands: Reject by default, tool offered only when granted."""
import ast
import asyncio
from pathlib import Path

from textual.app import App

from isycode.command_runner import CommandPreview
from isycode.security import ActionRequest


def _preview(tmp_path: Path) -> CommandPreview:
    request = ActionRequest("workspace.command.run", tmp_path, "/usr/bin/echo", {"argv": ["echo"]},
                            execution_owner="workspace_command")
    return CommandPreview(request, ("echo", "hi there"), "/usr/bin/echo", ".", 120,
                          ((".env", False),))


def test_command_screen_rejects_by_default_and_runs_only_on_the_button(tmp_path):
    from isycode.tui import CommandApprovalScreen

    results = []

    class Host(App):
        def on_mount(self):
            self.push_screen(CommandApprovalScreen(_preview(tmp_path)), results.append)

    async def scenario(action):
        async with Host().run_test() as pilot:
            await pilot.pause()
            await action(pilot)
            await pilot.pause()

    asyncio.run(scenario(lambda pilot: pilot.press("escape")))
    asyncio.run(scenario(lambda pilot: pilot.press("enter")))
    asyncio.run(scenario(lambda pilot: pilot.click("#command-approval-run")))
    assert results == [False, False, True]


def _methods():
    package = Path(__file__).resolve().parents[1] / "src" / "isycode"
    found = {}
    for path in (package / "tui.py", *sorted(package.glob("tui_app_*.py"))):
        source = path.read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name != "TUIApp" and not node.name.endswith("Mixin"):
                continue
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found[item.name] = ast.get_source_segment(source, item)
    return found


def test_command_tool_is_offered_only_with_an_effective_sandbox_grant():
    methods = _methods()
    assert "effective_policy()" in methods["_command_tool_enabled"]
    assert "sandbox_executable()" in methods["_command_tool_enabled"]
    run_chat = methods["_run_chat"]
    assert "command_active = tools_active and self._command_tool_enabled()" in run_chat
    assert "if command_active:\n                chat_tools = chat_tools + [COMMAND_TOOL]" in run_chat


def test_every_command_goes_through_the_approval_screen_and_the_owner():
    body = _methods()["_run_workspace_command"]
    assert body.index("CommandApprovalScreen(preview)") < body.index("self._action_approvals.issue")
    assert body.index("self._action_approvals.issue") < body.index("owner.run(preview, approval, on_output=show_output)")
    assert "create_subprocess" not in body and "subprocess." not in body
