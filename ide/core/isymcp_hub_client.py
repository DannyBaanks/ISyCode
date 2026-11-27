"""Native async stdio JSON-RPC client for ISyMCP Hub (`isymcp-hub connect`).

Allows ISyCode IDE's agent and composite motors to discover, describe, and
execute tools exposed by any MCP server registered in the local ISyMCP Hub.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

_DEFAULT_HUB_CANDIDATES = (
    Path("/home/danny/.codex-web-http/bin/isymcp-hub"),
    Path.home() / ".codex-web-http" / "bin" / "isymcp-hub",
    Path.home() / ".local" / "bin" / "isymcp-hub",
)

_SUMMARY_CACHE: tuple[float, dict[str, Any]] | None = None
_SUMMARY_TTL_SECONDS = 45.0


def resolve_hub_command() -> list[str] | None:
    """Resolve the `isymcp-hub connect` command from ~/.config/isycode/mcp.json or defaults."""
    real_home = Path("/home/danny") if Path("/home/danny/.config/isycode/mcp.json").is_file() else Path.home()
    cfg_path = real_home / ".config" / "isycode" / "mcp.json"
    if cfg_path.is_file():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            servers = data.get("mcpServers") or data.get("servers") or {}
            spec = servers.get("isymcp-hub")
            if isinstance(spec, dict) and not spec.get("disabled"):
                cmd = spec.get("command")
                if isinstance(cmd, list) and cmd and Path(cmd[0]).is_file():
                    return [str(x) for x in cmd]
                if isinstance(cmd, str) and Path(cmd).is_file():
                    args = spec.get("args") or ["connect"]
                    return [cmd, *[str(a) for a in args]]
        except Exception:
            pass
    for candidate in _DEFAULT_HUB_CANDIDATES:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return [str(candidate), "connect"]
    return None


def _extract_mcp_text(result: dict[str, Any]) -> str:
    """Extract readable text from an MCP tools/call result payload."""
    if not isinstance(result, dict):
        return str(result)
    content = result.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, dict):
                parts.append(json.dumps(item, ensure_ascii=False))
        if parts:
            return "\n".join(parts)
    return json.dumps(result, ensure_ascii=False)


def load_local_mcp_servers() -> dict[str, dict[str, Any]]:
    """Load standalone non-disabled stdio MCP server entries from ~/.config/isycode/mcp.json."""
    real_home = Path("/home/danny") if Path("/home/danny/.config/isycode/mcp.json").is_file() else Path.home()
    cfg_path = real_home / ".config" / "isycode" / "mcp.json"
    if not cfg_path.is_file():
        return {}
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        raw = data.get("mcpServers") or data.get("servers") or {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, dict[str, Any]] = {}
        for name, spec in raw.items():
            if not isinstance(spec, dict) or spec.get("disabled") or name == "isymcp-hub":
                continue
            cmd = spec.get("command")
            if isinstance(cmd, list) and cmd:
                argv = [str(x) for x in cmd]
            elif isinstance(cmd, str) and cmd:
                argv = [cmd, *[str(a) for a in (spec.get("args") or [])]]
            else:
                continue
            env = spec.get("env") if isinstance(spec.get("env"), dict) else {}
            out[name] = {"command": argv, "env": {str(k): str(v) for k, v in env.items()}}
        return out
    except Exception:
        return {}


class ISyMCPHubClient:
    """One-shot or short-lived async JSON-RPC client over `isymcp-hub connect` or local stdio MCPs."""

    def __init__(self, command: list[str] | None = None):
        self.command = command or resolve_hub_command()

    @property
    def available(self) -> bool:
        return bool(self.command) or bool(load_local_mcp_servers())

    async def _call_stdio_mcp(
        self,
        command: list[str],
        method: str,
        params: dict[str, Any] | None = None,
        *,
        env_extra: dict[str, str] | None = None,
        timeout: float = 25.0,
    ) -> dict[str, Any]:
        env = os.environ.copy()
        if env_extra:
            env.update(env_extra)
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        assert proc.stdin is not None and proc.stdout is not None

        async def _send(payload: dict[str, Any]) -> None:
            raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
            proc.stdin.write(raw)
            await proc.stdin.drain()

        async def _read_response(expected_id: int) -> dict[str, Any]:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    err_txt = ""
                    if proc.stderr is not None:
                        try:
                            err_b = await asyncio.wait_for(proc.stderr.read(), timeout=0.5)
                            err_txt = err_b.decode("utf-8", "replace").strip()
                        except Exception:
                            pass
                    raise RuntimeError(f"MCP cerró stdout inesperadamente. {err_txt}".strip())
                text = line.decode("utf-8", "replace").strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, dict) and msg.get("id") == expected_id:
                    return msg

        async def _session() -> dict[str, Any]:
            await _send({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "isycode-ide", "version": "0.4.0"},
                },
            })
            init_resp = await _read_response(1)
            if "error" in init_resp:
                return {"ok": False, "error": f"MCP init error: {init_resp['error']}"}
            await _send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
            await _send({"jsonrpc": "2.0", "id": 2, "method": method, "params": params or {}})
            call_resp = await _read_response(2)
            if "error" in call_resp:
                return {"ok": False, "error": json.dumps(call_resp["error"], ensure_ascii=False)}
            res = call_resp.get("result") or {}
            is_err = bool(res.get("isError", False)) if isinstance(res, dict) else False
            text = _extract_mcp_text(res) if method == "tools/call" else json.dumps(res, ensure_ascii=False)
            return {"ok": not is_err, "text": text, "raw": res}

        try:
            return await asyncio.wait_for(_session(), timeout=timeout)
        except asyncio.TimeoutError:
            return {"ok": False, "error": f"ISYMCP_HUB_TIMEOUT: {method} excedió {timeout:.0f}s."}
        except Exception as exc:
            return {"ok": False, "error": f"ISYMCP_HUB_ERROR: {type(exc).__name__}: {exc}"}
        finally:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    async def call_hub_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float = 25.0,
    ) -> dict[str, Any]:
        """Call one of ISyMCP Hub's meta-tools (`hub_discover`, `hub_describe`, `hub_execute`)."""
        if not self.command:
            return {
                "ok": False,
                "error": "ISYMCP_HUB_UNAVAILABLE: no se encontró el binario isymcp-hub en esta máquina.",
            }
        return await self._call_stdio_mcp(
            self.command,
            "tools/call",
            {"name": tool_name, "arguments": arguments or {}},
            timeout=timeout,
        )

    async def discover(
        self,
        *,
        server: str | None = None,
        query: str | None = None,
        include_idle: bool = False,
        limit: int = 30,
    ) -> dict[str, Any]:
        local_servers = load_local_mcp_servers()
        if server and server in local_servers and server != "isymcp":
            spec = local_servers[server]
            res = await self._call_stdio_mcp(spec["command"], "tools/list", {}, env_extra=spec["env"], timeout=20.0)
            if res.get("ok"):
                tools = (res.get("raw") or {}).get("tools") or []
                compact = [{"name": t.get("name", ""), "description": (t.get("description") or "")[:180]} for t in tools[:limit] if isinstance(t, dict)]
                return {"ok": True, "text": json.dumps({"server": server, "source": "mcp.json", "tools": compact}, ensure_ascii=False)}
            return res
        args: dict[str, Any] = {"limit": max(1, min(100, int(limit)))}
        if server:
            args["server"] = server
        if query:
            args["query"] = query
        if include_idle:
            args["include_idle"] = True
        return await self.call_hub_tool("hub_discover", args, timeout=20.0)

    async def describe(self, server: str, tool: str) -> dict[str, Any]:
        local_servers = load_local_mcp_servers()
        if server in local_servers and server != "isymcp":
            spec = local_servers[server]
            res = await self._call_stdio_mcp(spec["command"], "tools/list", {}, env_extra=spec["env"], timeout=20.0)
            if not res.get("ok"):
                return res
            for item in (res.get("raw") or {}).get("tools") or []:
                if isinstance(item, dict) and item.get("name") == tool:
                    return {"ok": True, "text": json.dumps(item, ensure_ascii=False)}
            return {"ok": False, "error": f"Tool '{tool}' no encontrada en servidor local '{server}'."}
        return await self.call_hub_tool("hub_describe", {"server": server, "tool": tool}, timeout=15.0)

    async def execute(self, server: str, tool: str, arguments: dict[str, Any] | None = None, *, timeout: float = 60.0) -> dict[str, Any]:
        local_servers = load_local_mcp_servers()
        if server in local_servers and server != "isymcp":
            spec = local_servers[server]
            return await self._call_stdio_mcp(
                spec["command"],
                "tools/call",
                {"name": tool, "arguments": arguments or {}},
                env_extra=spec["env"],
                timeout=timeout,
            )
        return await self.call_hub_tool(
            "hub_execute",
            {"server": server, "tool": tool, "arguments": arguments or {}},
            timeout=timeout,
        )


async def get_hub_summary_cached() -> dict[str, Any]:
    """Return a compact cached summary of ISyMCP Hub servers for prompt context."""
    global _SUMMARY_CACHE
    now = time.monotonic()
    if _SUMMARY_CACHE is not None and (now - _SUMMARY_CACHE[0]) < _SUMMARY_TTL_SECONDS:
        return _SUMMARY_CACHE[1]
    client = ISyMCPHubClient()
    if not client.available:
        summary = {"available": False, "servers": []}
        _SUMMARY_CACHE = (now, summary)
        return summary
    resp = await client.discover(limit=30)
    if not resp.get("ok"):
        summary = {"available": True, "servers": [], "note": resp.get("error", "")[:160]}
        _SUMMARY_CACHE = (now, summary)
        return summary
    servers: list[dict[str, Any]] = []
    try:
        parsed = json.loads(resp.get("text", "{}"))
        for item in parsed.get("servers", [])[:20]:
            if isinstance(item, dict):
                servers.append({
                    "name": item.get("name", ""),
                    "state": item.get("state", ""),
                    "tools": item.get("tools", 0),
                })
    except Exception:
        pass
    seen_names = {s.get("name") for s in servers}
    for local_name in sorted(load_local_mcp_servers()):
        if local_name not in seen_names:
            servers.append({"name": local_name, "state": "local_mcp_json", "tools": "stdio"})
    summary = {"available": True, "servers": servers}
    _SUMMARY_CACHE = (now, summary)
    return summary
