"""Local MCP servers over stdio, started and called behind Authority and IsySentinel.

Servers come only from the user's own config file
(``~/.config/isycode/mcp.json``), never from the workspace, because starting
one runs a program with the user's privileges. Starting a server needs a
``mcp.local.start`` grant for its exact executable plus a fresh approval of
the exact command; every tool call needs a ``mcp.local.invoke`` grant for that
server plus a fresh approval of the exact arguments. Servers run with a
minimal environment in the workspace folder and stop when ISyCode exits.
Their tool descriptions and results are untrusted data.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from isycode.action_runtime import (
    MCP_ENV_NAME_RE as ENV_NAME_RE, MCP_SERVER_NAME_RE as SERVER_NAME_RE,
    MCP_TOOL_NAME_RE as TOOL_NAME_RE, ActionOutcome, ActionReceipt, ProductActionGate,
    command_argv_valid,
)
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority

OWNER_ID = "mcp_local"
MAX_CONFIG_BYTES = 64 * 1024
MAX_SERVERS = 20
MAX_TOOLS_PER_SERVER = 64
MAX_LINE_BYTES = 2**63 - 1  # Do not truncate large endpoint results before chat sees them.
START_TIMEOUT_S = 30
CALL_TIMEOUT_S = 120
PROTOCOL_VERSION = "2025-06-18"
BASE_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "SHELL")
PLAYWRIGHT_COMMAND = ("npx", "-y", "@playwright/mcp@0.0.83")
PLAYWRIGHT_READ_TOOL = "browser_snapshot"


def process_environment(config_env: tuple[tuple[str, str], ...]) -> dict[str, str]:
    """Fixed base environment plus the keys the user wrote in mcp.json.

    Provider keys and the rest of the host environment are not copied. A value
    is present only when that mcp.json entry names it.
    """
    env = {key: os.environ[key] for key in BASE_ENV_KEYS if key in os.environ}
    env.update(dict(config_env))
    return env


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "isycode" / "mcp.json"


@dataclass(frozen=True)
class ServerConfig:
    name: str
    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...] = ()

    @property
    def digest(self) -> str:
        # Env values may be secrets: only their names and a digest are bound.
        material = json.dumps([self.name, self.argv, self.env], ensure_ascii=False)
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


def load_config(path: Path | None = None) -> dict[str, ServerConfig]:
    """``{"servers": {"name": {"command": ["prog", "arg"], "env": {"KEY": "value"}}}}``."""
    path = path or config_path()
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {}
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CONFIG_BYTES:
        raise ValueError(f"{path} must be a regular file under 64 KiB")
    if os.name == "posix" and info.st_mode & 0o022:
        raise ValueError(f"{path} must not be writable by other users")
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data.get("servers") if isinstance(data, dict) else None
    if not isinstance(servers, dict) or len(servers) > MAX_SERVERS:
        raise ValueError('mcp.json needs a "servers" object with at most 20 entries')
    result = {}
    for name, entry in servers.items():
        command = entry.get("command") if isinstance(entry, dict) else None
        env = entry.get("env", {}) if isinstance(entry, dict) else None
        argv = tuple(command) if isinstance(command, list) else None
        if (not isinstance(name, str) or not SERVER_NAME_RE.match(name)
                or not command_argv_valid(argv) or not isinstance(env, dict)
                or not all(isinstance(k, str) and ENV_NAME_RE.match(k) and isinstance(v, str)
                           and "\x00" not in v for k, v in env.items())):
            raise ValueError(f"MCP server {name!r} has an invalid name, command or env")
        result[name] = ServerConfig(name, argv, tuple(sorted(env.items())))
    return result


def resolve_executable(argv0: str) -> str:
    found = shutil.which(argv0) if "/" not in argv0 else argv0
    if not found:
        raise ValueError(f"{argv0!r} was not found on PATH")
    resolved = Path(found).expanduser().resolve(strict=True)
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ValueError(f"{argv0!r} is not an executable file")
    return str(resolved)


def function_name(server: str, tool: str) -> str:
    """Provider-safe function name: only letters, digits, "_" and "-", at most 64 chars."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", f"mcp__{server}__{tool}")[:64]


def visible_tools(config: ServerConfig, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Limit the pinned Playwright preset to a read-only current-page snapshot."""
    if config.argv != PLAYWRIGHT_COMMAND:
        return tools
    result = []
    for tool in tools:
        if tool.get("name") == PLAYWRIGHT_READ_TOOL:
            result.append({**tool, "description": (
                "Read the current page in the visible Playwright browser. "
                "Open the page yourself first; this action cannot navigate, click, or enter data. "
                "The snapshot is filtered and treated as untrusted content." )})
    return result


@dataclass
class MCPSession:
    config: ServerConfig
    process: asyncio.subprocess.Process
    tools: list[dict[str, Any]] = field(default_factory=list)
    next_id: int = 1
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def request(self, method: str, params: dict | None, timeout: float) -> Any:
        async with self.lock:
            request_id = self.next_id
            self.next_id += 1
            await self._send({"jsonrpc": "2.0", "id": request_id, "method": method,
                              "params": params or {}})
            return await asyncio.wait_for(self._receive(request_id), timeout=timeout)

    async def notify(self, method: str) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": {}})

    async def _send(self, message: dict) -> None:
        if self.process.stdin is None or self.process.returncode is not None:
            raise RuntimeError("MCP server is not running")
        self.process.stdin.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
        await self.process.stdin.drain()

    async def _receive(self, request_id: int) -> Any:
        while True:
            line = await self.process.stdout.readline()
            if not line:
                raise RuntimeError("MCP server closed its output")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue  # servers may log noise on stdout
            if not isinstance(message, dict):
                continue
            if "method" in message and "id" in message:
                # Server-to-client requests (ping, roots, sampling): answer
                # ping, refuse everything else. No capability is offered.
                reply = ({"jsonrpc": "2.0", "id": message["id"], "result": {}}
                         if message["method"] == "ping" else
                         {"jsonrpc": "2.0", "id": message["id"],
                          "error": {"code": -32601, "message": "not supported by ISyCode"}})
                await self._send(reply)
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"] if isinstance(message["error"], dict) else {}
                raise RuntimeError(f"MCP error: {str(error.get('message', 'unknown'))[:200]}")
            return message.get("result")

    async def stop(self) -> None:
        if self.process.returncode is not None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, AttributeError):
            self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=3)
        except asyncio.TimeoutError:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, AttributeError):
                self.process.kill()
            await self.process.wait()


@dataclass(frozen=True)
class StartPreview:
    request: ActionRequest
    config: ServerConfig


@dataclass(frozen=True)
class CallPreview:
    request: ActionRequest
    server: str
    tool: str
    arguments: dict


class LocalMCPOwner:
    """The only execution owner for mcp.local.start and mcp.local.invoke."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.gate = ProductActionGate(self.root, authority, owner_id=OWNER_ID)
        self.sessions: dict[str, MCPSession] = {}

    # ── start ────────────────────────────────────────────────────

    def prepare_start(self, name: str, configs: dict[str, ServerConfig] | None = None) -> StartPreview:
        configs = load_config() if configs is None else configs
        config = configs.get(name)
        if config is None:
            raise ValueError(f"no MCP server named {name!r} in {config_path()}")
        request = ActionRequest(
            "mcp.local.start", self.root, name,
            {"server": name, "argv": config.argv, "executable": resolve_executable(config.argv[0]),
             "cwd": str(self.root), "env_keys": tuple(key for key, _ in config.env),
             "config_sha256": config.digest},
            execution_owner="mcp_local")
        return StartPreview(request, config)

    async def start(self, preview: StartPreview, approval: ActionApproval | None) -> ActionOutcome:
        request, config = preview.request, preview.config
        name = config.name
        if name in self.sessions and self.sessions[name].process.returncode is None:
            return ActionOutcome("MCP server already running.", "DENY", None, "server is already running")
        try:
            executable = resolve_executable(config.argv[0])
        except (OSError, ValueError) as exc:
            return ActionOutcome("MCP server denied.", "DENY", None, str(exc)[:200])
        if executable != request.parameters["executable"]:
            return ActionOutcome("MCP server denied.", "DENY", None,
                                 "the executable changed after review")
        _, decision = self.gate.authorize(request, approvals=self.approvals, approval=approval)
        if not decision.allowed:
            return ActionOutcome("MCP server denied.", "DENY", None,
                                 "; ".join(c.reason for c in decision.checks if not c.passed))
        env = process_environment(config.env)
        try:
            process = await asyncio.create_subprocess_exec(
                executable, *config.argv[1:], cwd=self.root, env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=MAX_LINE_BYTES,
                start_new_session=True)
        except OSError as exc:
            return ActionOutcome("MCP server could not start.", "ERROR", None, type(exc).__name__)
        session = MCPSession(config, process)
        try:
            await session.request("initialize", {
                "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                "clientInfo": {"name": "isycode", "version": "0.1.0"}}, START_TIMEOUT_S)
            await session.notify("notifications/initialized")
            listed = await session.request("tools/list", {}, START_TIMEOUT_S)
        except (asyncio.TimeoutError, RuntimeError, OSError, ValueError) as exc:
            await session.stop()
            return ActionOutcome("MCP server handshake failed.", "ERROR", None,
                                 f"{type(exc).__name__}: {str(exc)[:160]}")
        tools = []
        for tool in (listed or {}).get("tools", [])[:MAX_TOOLS_PER_SERVER]:
            if (isinstance(tool, dict) and isinstance(tool.get("name"), str)
                    and TOOL_NAME_RE.match(tool["name"])):
                schema = tool.get("inputSchema")
                tools.append({"name": tool["name"],
                              "description": str(tool.get("description", ""))[:1000],
                              "inputSchema": schema if isinstance(schema, dict) else
                              {"type": "object", "properties": {}}})
        tools = visible_tools(config, tools)
        session.tools = tools
        outcome = self._finish(request, {"server": name, "tools": [tool["name"] for tool in tools]},
                               f"{name} started with {len(tools)} tools")
        if outcome.decision == "ALLOW":
            self.sessions[name] = session
        else:
            await session.stop()
        return outcome

    # ── tools ────────────────────────────────────────────────────

    def chat_tools(self) -> list[dict]:
        """Running servers' tools as function definitions (descriptions are untrusted)."""
        tools = []
        seen: set[str] = set()
        for name, session in self.sessions.items():
            if session.process.returncode is not None:
                continue
            for tool in session.tools:
                function = function_name(name, tool["name"])
                if function in seen:
                    continue  # truncated names that collide are not offered
                seen.add(function)
                tools.append({"type": "function", "function": {
                    "name": function,
                    "description": (f"[MCP server {name}; untrusted description] "
                                    + tool["description"])[:1000],
                    "parameters": tool["inputSchema"]}})
        return tools

    def resolve_function(self, function: str) -> tuple[str, str] | None:
        for name, session in self.sessions.items():
            for tool in session.tools:
                if function_name(name, tool["name"]) == function:
                    return name, tool["name"]
        return None

    def prepare_call(self, server: str, tool: str, arguments: Any) -> CallPreview:
        session = self.sessions.get(server)
        if session is None or session.process.returncode is not None:
            raise ValueError(f"MCP server {server!r} is not running")
        if tool not in {item["name"] for item in session.tools}:
            raise ValueError(f"{server} has no tool named {tool!r}")
        if not isinstance(arguments, dict):
            raise ValueError("MCP tool arguments must be a JSON object")
        encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        if len(encoded) > 64 * 1024:
            raise ValueError("MCP tool arguments exceed 64 KiB")
        request = ActionRequest(
            "mcp.local.invoke", self.root, server,
            {"server": server, "tool": tool, "config_sha256": session.config.digest,
             "arguments_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest()},
            execution_owner="mcp_local")
        return CallPreview(request, server, tool, json.loads(encoded))

    async def call(self, preview: CallPreview, approval: ActionApproval | None) -> ActionOutcome:
        session = self.sessions.get(preview.server)
        if session is None or session.process.returncode is not None:
            return ActionOutcome("MCP call denied.", "DENY", None, "server is not running")
        if session.config.digest != preview.request.parameters["config_sha256"]:
            return ActionOutcome("MCP call denied.", "DENY", None, "server changed after review")
        _, decision = self.gate.authorize(preview.request, approvals=self.approvals,
                                          approval=approval)
        if not decision.allowed:
            return ActionOutcome("MCP call denied.", "DENY", None,
                                 "; ".join(c.reason for c in decision.checks if not c.passed))
        try:
            result = await session.request("tools/call", {"name": preview.tool,
                                                          "arguments": preview.arguments},
                                           CALL_TIMEOUT_S)
        except (asyncio.TimeoutError, RuntimeError, OSError) as exc:
            return ActionOutcome("MCP call failed.", "ERROR", None,
                                 f"{type(exc).__name__}: {str(exc)[:160]}")
        parts = []
        for item in (result or {}).get("content", []) if isinstance(result, dict) else []:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, dict):
                parts.append(f"[{item.get('type', 'content')} omitted]")
        text = "\n".join(parts)
        is_error = bool(result.get("isError")) if isinstance(result, dict) else False
        if (session.config.argv == PLAYWRIGHT_COMMAND
                and preview.tool == PLAYWRIGHT_READ_TOOL):
            from isycode.browser_read import filter_accessibility_snapshot
            if is_error:
                data = {"server": preview.server, "tool": preview.tool,
                        "text": "", "input_chars": len(text), "filtered_chars": 0,
                        "truncated": False, "untrusted": True,
                        "browser_read": True, "is_error": True}
            else:
                data = {"server": preview.server, "tool": preview.tool,
                        **filter_accessibility_snapshot(text),
                        "browser_read": True, "is_error": False}
        else:
            data = {"server": preview.server, "tool": preview.tool, "text": text,
                    "truncated": False, "is_error": is_error}
        return self._finish(preview.request, data,
                            f"{preview.server}.{preview.tool} returned")

    async def stop(self, name: str) -> bool:
        session = self.sessions.pop(name, None)
        if session is None:
            return False
        await session.stop()
        return True

    async def stop_all(self) -> None:
        for name in list(self.sessions):
            await self.stop(name)

    def _finish(self, request: ActionRequest, result: dict, reason: str) -> ActionOutcome:
        text = json.dumps(result, ensure_ascii=False, sort_keys=True)
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), request.action_id, request.digest,
                                "ALLOW", "SUCCESS", hashlib.sha256(text.encode("utf-8")).hexdigest())
        if not receipt.verify(request, text) or not self.gate.persist_receipt(request, receipt):
            return ActionOutcome("MCP receipt could not be persisted.", "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable")
        return ActionOutcome(text, "ALLOW", receipt, reason)


__all__ = ["CallPreview", "LocalMCPOwner", "ServerConfig", "StartPreview", "config_path",
           "function_name", "load_config", "resolve_executable", "PLAYWRIGHT_COMMAND",
           "PLAYWRIGHT_READ_TOOL", "visible_tools"]
