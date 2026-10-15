"""Integration menus keep exact reviews, invalid drafts and refusing actions."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.app import App
from textual.widgets import Button, TextArea, Static, Select

from isycode.tui_screens_mcp import (
    MCPArgumentsScreen, MCPInvocationConfirmScreen, GatewaySemanticQueryScreen,
    GatewaySemanticConfirmScreen, LSPQueryScreen, LSPConfirmScreen,
    BrokerProvisionConfirmScreen, BrokerManagementScreen, BrokerOperationConfirmScreen,
)


LONG_ROOT = Path("/workspace/" + "long-project-name/" * 12)


@pytest.mark.parametrize("size", [(80, 24), (140, 40)])
@pytest.mark.parametrize("factory", [
    lambda: MCPInvocationConfirmScreen("search", "Description " * 180, {"query": "[exact] " * 180}, "https://gateway.example"),
    lambda: GatewaySemanticConfirmScreen("https://gateway.example", "symbols/search", {"query": "EXACT " * 250}, "workspace-1"),
    lambda: LSPConfirmScreen(LONG_ROOT, "symbol " * 30),
    lambda: BrokerProvisionConfirmScreen(LONG_ROOT, SimpleNamespace(source_root=LONG_ROOT, digest="a" * 64, files=[(f"src/{i}.py", "b" * 64) for i in range(12)]), "local-image"),
    lambda: BrokerOperationConfirmScreen("stop", LONG_ROOT, "container-1"),
])
def test_long_confirmations_keep_cancel_visible_and_enter_rejects(factory, size):
    results = []
    async def scenario():
        app = App()
        async with app.run_test(size=size) as pilot:
            screen = factory()
            await app.push_screen(screen, results.append)
            await pilot.pause()
            for button in screen.query(Button):
                assert screen.region.contains_region(button.region)
                assert screen.query_one(".isy-dialog").region.contains_region(button.region)
            assert screen.focused is screen.query_one(Button)
            await pilot.press("enter")
            await pilot.pause()
            assert results == [False]
    asyncio.run(scenario())


def test_mcp_invalid_json_keeps_draft_then_returns_exact_object():
    results = []
    async def scenario():
        app = App()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = MCPArgumentsScreen({"name": "search", "description": "Description " * 200, "inputSchema": {"properties": {str(i): {"type": "string"} for i in range(30)}}})
            await app.push_screen(screen, results.append)
            await pilot.pause()
            editor = screen.query_one("#mcp-arguments-input", TextArea)
            assert editor.region.height >= 3
            editor.load_text("{ invalid json }")
            assert await pilot.click("#mcp-arguments-review")
            await pilot.pause()
            assert editor.text == "{ invalid json }" and results == []
            assert "Expecting" in str(screen.query_one("#mcp-arguments-error", Static).render())
            editor.load_text('{"query":"[exact]","limit":2}')
            await pilot.pause(0.4)
            assert await pilot.click("#mcp-arguments-review")
            await pilot.pause()
            assert results == [{"query": "[exact]", "limit": 2}]
    asyncio.run(scenario())


@pytest.mark.parametrize("factory,editor_id", [
    (lambda: GatewaySemanticQueryScreen("https://gateway.example", "workspace-1"), "semantic-payload"),
    (lambda: MCPArgumentsScreen({"name": "search", "inputSchema": {}}), "mcp-arguments-input"),
    (lambda: LSPQueryScreen(LONG_ROOT), None),
    (lambda: BrokerManagementScreen(LONG_ROOT, {"container": "container-1", "recipe_digest": "a" * 64}), None),
])
def test_forms_and_management_keep_actions_reachable(factory, editor_id):
    async def scenario():
        app = App()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = factory()
            await app.push_screen(screen)
            await pilot.pause()
            for button in screen.query(Button):
                assert screen.region.contains_region(button.region)
            if editor_id:
                assert screen.query_one("#" + editor_id).region.height >= 3
            await pilot.press("escape")
            assert app.screen is not screen
    asyncio.run(scenario())


def test_gateway_operation_overlay_closes_without_losing_json_draft():
    from isycode.tui import TUIApp
    class StyledHost(App):
        CSS_PATH = TUIApp.CSS_PATH
    async def scenario():
        app = StyledHost()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = GatewaySemanticQueryScreen("https://gateway.example", "workspace-1")
            await app.push_screen(screen)
            await pilot.pause()
            editor = screen.query_one("#semantic-payload", TextArea)
            draft = editor.text
            selector = screen.query_one("#semantic-operation", Select)
            await pilot.click("#semantic-operation SelectCurrent", offset=(3, 1))
            await pilot.pause()
            assert selector.expanded
            await pilot.press("escape")
            assert app.screen is screen and not selector.expanded
            assert editor.text == draft
            assert screen.region.contains_region(screen.query_one("#semantic-query-review").region)
            await pilot.press("escape")
    asyncio.run(scenario())
