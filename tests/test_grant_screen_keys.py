"""Grant screens take y/n like every other approval; Esc and the default button still refuse."""
import ast
import asyncio
from pathlib import Path

import pytest
from textual.app import App

SURFACE = Path(__file__).resolve().parents[1] / "src" / "isycode"
GRANT_SCREENS = ("GlobalRecurringDefaultScreen", "GrantWorkspaceReadScreen",
                 "GrantProviderNetworkScreen", "GrantMCPInvocationScreen",
                 "GrantLSPProcessScreen", "BrokerPreviewGrantScreen")


def test_grant_screens_share_the_approval_keys():
    bases = {}
    for path in sorted(SURFACE.glob("tui*.py")):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef):
                bases[node.name] = [ast.unparse(base) for base in node.bases]
    assert {name: bases[name] for name in GRANT_SCREENS} == {
        name: ["ApprovalScreen"] for name in GRANT_SCREENS}


@pytest.mark.parametrize("keys, expected", [("y", True), ("n", False), ("escape", False),
                                            ("enter", False)])
def test_keys_decide_grant_screens(tmp_path, keys, expected):
    from isycode.tui import GrantProviderNetworkScreen, GrantWorkspaceReadScreen

    for make in (lambda: GrantWorkspaceReadScreen(tmp_path),
                 lambda: GrantProviderNetworkScreen("OpenAI API", "api.openai.com")):
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
