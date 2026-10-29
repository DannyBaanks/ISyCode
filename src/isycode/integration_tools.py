"""The integration tools the assistant may propose, from the ones ISyCode has.

The Gateway MCP catalog (Drive, Gmail, GitHub, semantic search and workspace
files) is discovered through the documented MCP server, then offered to the
model as ordinary chat tools. Discovery never grants invocation: every call
still needs the `mcp.invoke` grant, ISySentinel and a one-use approval, and
the user reviews the exact tool and arguments first.

The OpenISy catalog and the L1 pipeline are read-only here: they report what
exists, never create, activate or execute anything.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

GATEWAY_TOOL_PREFIX = "gateway__"

# Integration tools that need no execution owner: they report local state.
OPENISY_CATALOG_TOOL_NAME = "openisy_catalog"
L1_STATE_TOOL_NAME = "l1_state"


def gateway_chat_tool_name(tool_name: str) -> str:
    """Namespaced chat tool name for one Gateway MCP tool."""
    safe = "".join(char if char.isalnum() or char in "_-." else "_" for char in tool_name)
    return f"{GATEWAY_TOOL_PREFIX}{safe}"[:160]


def gateway_tool_target(chatted_name: str) -> str:
    """The MCP tool name behind a namespaced chat tool name."""
    if not chatted_name.startswith(GATEWAY_TOOL_PREFIX):
        raise ValueError("not a Gateway chat tool")
    return chatted_name[len(GATEWAY_TOOL_PREFIX):]


def gateway_chat_tools(discovered_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn a discovered Gateway MCP catalog into chat tool schemas."""
    schemas: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool in discovered_tools:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            continue
        chatted = gateway_chat_tool_name(name)
        if chatted in seen:
            continue
        seen.add(chatted)
        description = tool.get("description")
        if not isinstance(description, str) or not description.strip():
            description = f"Gateway tool {name}."
        description = (
            f"{description.strip()} Calls the ISyCo Gateway through its MCP server; the "
            "user reviews the exact call before it runs and `mcp.invoke` must be granted.")
        schema = tool.get("inputSchema")
        parameters = schema if isinstance(schema, dict) else {
            "type": "object", "properties": {}}
        schemas.append({"type": "function", "function": {
            "name": chatted,
            "description": description[:1024],
            "parameters": parameters,
        }})
    return schemas


OPENISY_CATALOG_TOOL = {
    "type": "function",
    "function": {
        "name": OPENISY_CATALOG_TOOL_NAME,
        "description": (
            "Report which ISyCode integrations are available right now: the OpenISy "
            "catalog state, MCP servers, skills and the provider catalog. Read-only; "
            "it starts nothing and grants nothing."),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

L1_STATE_TOOL = {
    "type": "function",
    "function": {
        "name": L1_STATE_TOOL_NAME,
        "description": (
            "List the model-authored L1 tools with their gate state and whether each "
            "one is registered or granted. Read-only: a tool listed here is not "
            "callable until the L1 pipeline and the authority both allow it."),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

INTEGRATION_TOOL_NAMES = frozenset({OPENISY_CATALOG_TOOL_NAME, L1_STATE_TOOL_NAME,
                                     GATEWAY_TOOL_PREFIX})


def l1_state_rows() -> list[dict[str, Any]]:
    """Read the L1 registry without staging, validating or running anything."""
    root = Path(os.environ.get("ISYCODE_L1_ROOT")
                or os.path.expanduser("~/.isycode/l1"))
    registry = root / "registry.json"
    if root.is_symlink() or registry.is_symlink() or not registry.is_file():
        return []
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    tools = data.get("tools") if isinstance(data, dict) else None
    if not isinstance(tools, dict):
        return []
    rows: list[dict[str, Any]] = []
    for tool_id, entry in sorted(tools.items()):
        if not isinstance(entry, dict):
            continue
        rows.append({
            "id": str(tool_id)[:64],
            "version": str(entry.get("version", ""))[:24],
            "capability": str(entry.get("capability", ""))[:64],
            "effect_class": str(entry.get("effect_class", ""))[:32],
            "gates": [str(name)[:32] for name in entry.get("gates_passed", [])
                      if isinstance(name, str)][:12],
            "registered": entry.get("registered") is True,
            "granted": entry.get("granted") is True,
            "usable": bool(entry.get("registered") is True
                           and entry.get("granted") is True),
        })
    return rows
