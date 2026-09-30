"""Read-only tool discovery through the native ISyCo Gateway MCP server."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from isycode.config import PROJECT_ROOT
from isycode.credentials import read_saved_secret
from isycode.gateway_client import GatewayClient


MCP_ROOT_ENV = "ISYCO_GATEWAY_MCP_ROOT"


class GatewayMCPUnavailable(RuntimeError):
    pass


def tool_schema_digest(tool: dict[str, Any]) -> str:
    """Fingerprint the displayed MCP tool schema for request binding."""
    name = tool.get("name")
    schema = tool.get("inputSchema", {})
    canonical = json.dumps({"name": name, "inputSchema": schema}, ensure_ascii=False,
                           sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _server_command() -> list[str]:
    configured_root = os.environ.get(MCP_ROOT_ENV, "").strip()
    candidates = [Path(configured_root).expanduser()] if configured_root else []
    # Support the two established sibling-checkout layouts without embedding a
    # machine-specific absolute path. An explicit env path always wins.
    candidates.extend([
        PROJECT_ROOT.parent / "bridge_core" / "capabilities" / "mcp_gateway",
        PROJECT_ROOT.parent.parent / "ISyCo" / "bridge_core" / "capabilities" / "mcp_gateway",
    ])
    for candidate in candidates:
        root = candidate.resolve()
        if not (root / "pyproject.toml").is_file() or not (root / "mcp_gateway_http.py").is_file():
            if configured_root and candidate == candidates[0]:
                raise GatewayMCPUnavailable(f"{MCP_ROOT_ENV} does not point to the Gateway MCP package")
            continue
        uvx = shutil.which("uvx")
        if not uvx:
            raise GatewayMCPUnavailable("Install uv (uvx) to run the Gateway MCP package")
        return [uvx, "--from", str(root), "isyco-gateway-mcp"]
    installed = shutil.which("isyco-gateway-mcp")
    if installed:
        return [installed]
    return []


async def discover_gateway_tools(timeout_s: float = 90.0) -> list[dict[str, Any]]:
    """Run initialize + tools/list over stdio without invoking any tool."""
    command = _server_command()
    if not command:
        raise GatewayMCPUnavailable(
            f"Install isyco-gateway-mcp or set {MCP_ROOT_ENV} to its package directory")

    inherited_names = (
        "PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
        "XDG_CACHE_HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "UV_CACHE_DIR",
    )
    environment = {name: os.environ[name] for name in inherited_names if name in os.environ}
    gateway_url = os.environ.get("GATEWAY_URL") or "http://127.0.0.1:8787"
    GatewayClient._validate_base_url(gateway_url)
    environment["GATEWAY_BASE_URL"] = gateway_url
    gateway_key = os.environ.get("GATEWAY_API_KEY", "")
    if not gateway_key:
        gateway_key = read_saved_secret("isyco-gateway", "mcp") or ""
    if gateway_key:
        environment["GATEWAY_API_KEY"] = gateway_key

    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=environment,
    )
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "isycode", "version": "0.1.0"},
        }},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    payload = "".join(json.dumps(item, separators=(",", ":")) + "\n"
                      for item in requests).encode("utf-8")
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(payload), timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise GatewayMCPUnavailable("Gateway MCP startup timed out") from exc
    if len(stdout) > 4_000_000:
        raise GatewayMCPUnavailable("Gateway MCP returned more than 4 MB of discovery data")
    if process.returncode not in {0, None} and not stdout:
        raise GatewayMCPUnavailable("Gateway MCP process exited before replying")

    initialize_response = None
    response = None
    for line in stdout.splitlines():
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(message, dict) and message.get("id") == 1:
            initialize_response = message
        elif isinstance(message, dict) and message.get("id") == 2:
            response = message
    if not isinstance(initialize_response, dict) or "result" not in initialize_response:
        raise GatewayMCPUnavailable("Gateway MCP initialization did not succeed")
    if not isinstance(response, dict):
        raise GatewayMCPUnavailable("Gateway MCP did not return a tools/list response")
    if "error" in response:
        raise GatewayMCPUnavailable("Gateway MCP rejected tools/list")
    tools = (response.get("result") or {}).get("tools")
    if not isinstance(tools, list):
        raise GatewayMCPUnavailable("Gateway MCP returned an invalid tool catalog")
    return [item for item in tools if isinstance(item, dict)
            and isinstance(item.get("name"), str)]


async def invoke_gateway_tool(name: str, arguments: dict[str, Any], *,
                              base_url: str | None = None,
                              timeout_s: float = 45.0) -> dict[str, Any]:
    """Invoke one explicitly selected Gateway MCP tool over a fresh stdio process.

    Callers must first pass the same immutable request through Workspace
    Authority and ISySentinel and obtain a one-use approval. Discovery never
    grants invocation. The Gateway independently authenticates and authorizes
    the request.
    """
    if not isinstance(name, str) or not name or len(name) > 160:
        raise ValueError("MCP tool name is invalid")
    if not isinstance(arguments, dict):
        raise ValueError("MCP tool arguments must be a JSON object")
    command = _server_command()
    if not command:
        raise GatewayMCPUnavailable(
            f"Install isyco-gateway-mcp or set {MCP_ROOT_ENV} to its package directory")

    inherited_names = (
        "PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
        "XDG_CACHE_HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "UV_CACHE_DIR",
    )
    environment = {key: os.environ[key] for key in inherited_names if key in os.environ}
    gateway_url = base_url or os.environ.get("GATEWAY_URL") or "http://127.0.0.1:8787"
    GatewayClient._validate_base_url(gateway_url)
    environment["GATEWAY_BASE_URL"] = gateway_url
    gateway_key = os.environ.get("GATEWAY_API_KEY", "")
    if not gateway_key:
        gateway_key = read_saved_secret("isyco-gateway", "mcp") or ""
    if gateway_key:
        environment["GATEWAY_API_KEY"] = gateway_key

    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=environment,
    )
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "isycode", "version": "0.1.0"},
        }},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": name, "arguments": arguments,
        }},
    ]
    payload = "".join(json.dumps(item, separators=(",", ":")) + "\n"
                      for item in requests).encode("utf-8")
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(payload), timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise GatewayMCPUnavailable("Gateway MCP tool call timed out") from exc
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    if len(stdout) > 4_000_000:
        raise GatewayMCPUnavailable("Gateway MCP returned more than 4 MB of tool output")
    if process.returncode not in {0, None} and not stdout:
        raise GatewayMCPUnavailable("Gateway MCP process exited before replying")

    initialize_response = None
    response = None
    for line in stdout.splitlines():
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(message, dict) and message.get("id") == 1:
            initialize_response = message
        elif isinstance(message, dict) and message.get("id") == 2:
            response = message
    if not isinstance(initialize_response, dict) or "result" not in initialize_response:
        raise GatewayMCPUnavailable("Gateway MCP initialization did not succeed")
    if not isinstance(response, dict):
        raise GatewayMCPUnavailable("Gateway MCP did not return a tools/call response")
    if "error" in response:
        raise GatewayMCPUnavailable("Gateway MCP rejected the tool call")
    result = response.get("result")
    if not isinstance(result, dict):
        raise GatewayMCPUnavailable("Gateway MCP returned an invalid tool result")
    return result
