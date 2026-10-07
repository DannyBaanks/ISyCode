"""Every approval screen: y approves, n and Esc reject, Enter on the default button rejects."""
import ast
import asyncio
from pathlib import Path

import pytest
from textual.app import App

from isycode.command_runner import CommandPreview
from isycode.security import ActionRequest

SOURCE = Path(__file__).resolve().parents[1] / "src" / "isycode" / "tui.py"


def _screens(tmp_path):
    from isycode.tui import (CommandApprovalScreen, GrantProviderNetworkScreen,
                             GrantWorkspaceReadScreen, LocalMCPConfirmScreen, TailscaleConfirmScreen)

    request = ActionRequest("workspace.command.run", tmp_path, "/usr/bin/echo", {"argv": ["echo"]},
                            execution_owner="workspace_command")
    preview = CommandPreview(request, ("echo", "hi"), "/usr/bin/echo", ".", 120, ())
    return [lambda: CommandApprovalScreen(preview),
            lambda: TailscaleConfirmScreen("Allow?", "body", "Allow"),
            lambda: LocalMCPConfirmScreen("t", "b", "{}", "Call once"),
            lambda: GrantWorkspaceReadScreen(tmp_path),
            lambda: GrantProviderNetworkScreen("OpenAI API", "api.openai.com")]


@pytest.mark.parametrize("keys, expected", [("y", True), ("n", False), ("escape", False),
                                            ("enter", False)])
def test_keys_decide_every_approval_screen(tmp_path, keys, expected):
    for make in _screens(tmp_path):
        results = []

        class Host(App):
            def on_mount(self):
                self.push_screen(make(), results.append)

        async def scenario():
            async with Host().run_test() as pilot:
                await pilot.pause()
                await pilot.press(keys)
                await pilot.pause()

        asyncio.run(scenario())
        assert results == [expected], make


def test_every_boolean_approval_screen_uses_the_shared_keys():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    bases = {node.name: [ast.unparse(base) for base in node.bases]
             for node in module.body if isinstance(node, ast.ClassDef)}
    approvals = [name for name in ("WriteApprovalScreen", "CommandApprovalScreen",
                                   "CommitApprovalScreen", "LocalMCPConfirmScreen",
                                   "MCPInvocationConfirmScreen", "TailscaleConfirmScreen",
                                   "DeleteSessionScreen", "GlobalRecurringDefaultScreen",
                                   "GrantWorkspaceReadScreen", "GrantProviderNetworkScreen",
                                   "GrantMCPInvocationScreen", "GrantLSPProcessScreen",
                                   "BrokerPreviewGrantScreen")]
    assert all(bases[name] == ["ApprovalScreen"] for name in approvals)
