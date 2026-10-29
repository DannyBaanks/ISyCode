"""The integration tools: discovery is offered, every call is gated."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from isycode.action_runtime import GatewayMCPInvocationOwner
from isycode.integration_tools import (
    GATEWAY_TOOL_PREFIX, gateway_chat_tool_name, gateway_chat_tools,
    gateway_tool_target, l1_state_rows,
)


def _catalog() -> list[dict]:
    return [
        {"name": "drive_list_files",
         "description": "Lista archivos de Google Drive.",
         "inputSchema": {"type": "object",
                         "properties": {"folder_id": {"type": "string"}}}},
        {"name": "email_send", "description": "Envia un correo via Gmail.",
         "inputSchema": {"type": "object",
                         "properties": {"to": {"type": "string"},
                                         "body": {"type": "string"}},
                         "required": ["to", "body"]}},
    ]


def test_discovered_tools_become_namespaced_chat_tools():
    tools = gateway_chat_tools(_catalog())
    assert [tool["function"]["name"] for tool in tools] == [
        "gateway__drive_list_files", "gateway__email_send"]
    # The Gateway schema is preserved: the model must see the same contract.
    assert tools[1]["function"]["parameters"]["required"] == ["to", "body"]
    assert "mcp.invoke" in tools[0]["function"]["description"]


def test_chat_tool_name_round_trips_through_the_target():
    for tool in _catalog():
        chatted = gateway_chat_tool_name(tool["name"])
        assert chatted.startswith(GATEWAY_TOOL_PREFIX)
        assert gateway_tool_target(chatted) == tool["name"]


def test_unsafe_tool_names_are_namespaced_safely():
    assert gateway_chat_tool_name("drive list/files") == "gateway__drive_list_files"
    assert gateway_tool_target("gateway__drive_list_files") == "drive_list_files"


def test_target_rejects_a_name_outside_the_namespace():
    with pytest.raises(ValueError):
        gateway_tool_target("bridge_send")


def test_l1_state_reports_registered_and_granted_separately(tmp_path, monkeypatch):
    root = tmp_path / "l1"
    root.mkdir()
    (root / "registry.json").write_text(json.dumps({"tools": {
        "demo_one": {"version": "0.1.0", "capability": "read",
                     "effect_class": "READ", "gates_passed": ["validate"],
                     "registered": True, "granted": False},
        "demo_two": {"version": "0.2.0", "capability": "write",
                     "effect_class": "WRITE", "gates_passed": ["validate", "test"],
                     "registered": True, "granted": True},
    }}), encoding="utf-8")
    monkeypatch.setenv("ISYCODE_L1_ROOT", str(root))
    rows = {row["id"]: row for row in l1_state_rows()}
    assert rows["demo_one"]["usable"] is False
    assert rows["demo_two"]["usable"] is True
    # A stage is a fact, not a capability: the state never says "callable".
    assert "usable" in rows["demo_one"] and "callable" not in rows["demo_one"]


def test_l1_state_is_empty_without_a_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_L1_ROOT", str(tmp_path / "missing"))
    assert l1_state_rows() == []


def test_gateway_target_is_the_gateway_service():
    assert GatewayMCPInvocationOwner.target_for("http://127.0.0.1:8787") == (
        "isyco-gateway@127.0.0.1:8787")


def test_gateway_call_for_an_undiscovered_tool_is_refused_without_invoking(tmp_path, monkeypatch):
    from isycode.tui import TUIApp, plain_text
    from isycode.contracts import CatalogSnapshot
    from isycode.tui_app_tools import ToolMixin
    from test_daily_tui import configure

    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._gateway_mcp_snapshot = CatalogSnapshot(True, [], "ready", "")
            call = {"id": "call_1", "function": {
                "name": "gateway__email_send",
                "arguments": json.dumps({"to": "a@example.com", "body": "hi"})}}
            task = asyncio.create_task(app._dispatch_chat_tool(call))
            result = await asyncio.wait_for(task, 10)
            assert json.loads(result[1])["error"] == (
                "tool is absent from the discovered Gateway catalog")

    import asyncio
    asyncio.run(scenario())
