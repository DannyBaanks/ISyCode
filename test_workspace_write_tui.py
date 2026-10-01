"""TUI mediation for proposed file writes: offered only when granted, diff first."""
import ast
import asyncio
from pathlib import Path

from isycode.security import ActionRequest
from isycode.workspace_write import WritePreview

SOURCE = Path(__file__).parent / "isycode" / "tui.py"


def _methods():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    return {node.name: node for node in app.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _segment(name):
    return ast.get_source_segment(SOURCE.read_text(encoding="utf-8"), _methods()[name])


def test_write_tool_is_offered_only_when_the_write_grant_is_on():
    run_chat = _segment("_run_chat")
    assert "write_active = tools_active and self._workspace_write_tool_enabled()" in run_chat
    assert "CHAT_WORKSPACE_TOOLS + [EDIT_TOOL, WRITE_TOOL] if write_active" in run_chat
    assert "tools=chat_tools" in run_chat


def test_write_dispatch_rechecks_the_grant_shows_the_diff_and_uses_the_owner():
    dispatch = _segment("_dispatch_write_tool")
    assert dispatch.index("_workspace_write_tool_enabled()") < dispatch.index("owner.preview")
    assert dispatch.index("WriteApprovalScreen(preview") < dispatch.index("owner.apply")
    assert "rejected_by_user" in dispatch
    for forbidden in ("write_text", "write_bytes", "open(", "os.replace"):
        assert forbidden not in dispatch


def test_approval_screen_rejects_by_default_and_applies_only_on_the_button(tmp_path):
    from textual.app import App
    from isycode.tui import WriteApprovalScreen

    request = ActionRequest("workspace.files.write", tmp_path, str(tmp_path / "a.txt"), {},
                            execution_owner="workspace_write")
    preview = WritePreview(request, "a.txt", "--- a/a.txt\n+++ b/a.txt\n-x\n+y\n", False, "y\n")
    results = []

    class Host(App):
        def on_mount(self):
            self.push_screen(WriteApprovalScreen(preview), results.append)

    async def scenario(keys):
        async with Host().run_test() as pilot:
            await pilot.pause()
            for key in keys:
                await pilot.press(key)
            await pilot.pause()

    asyncio.run(scenario(["escape"]))
    asyncio.run(scenario(["enter"]))   # focus starts on Reject
    asyncio.run(scenario(["tab", "enter"]))
    assert results == [False, False, True]
