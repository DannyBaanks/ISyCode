"""Hook server — Unix domain socket server that receives hook events from agents.

Runs in the ISyCode main process (like the Electron main in isyco-worlds).
Handles PreToolUse (write guard), PostToolUse (live status), Stop (inbox drain).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from .manager import HiveManager
from .guard import hive_write_decision, HiveWriteInput
from .types import RegistryAgent


class HookServer:
    """Async Unix domain socket server for hive hooks."""

    def __init__(self, manager: HiveManager) -> None:
        self.manager = manager
        self._server: asyncio.Server | None = None
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the hook server."""
        sock_path = self.manager.sock_path()
        if not sock_path or os.name == "nt":
            # Windows: named pipes not supported in stdlib asyncio yet
            # Fallback: file-based polling or skip
            print("[hive] Hook server not started on Windows (no UDS support)")
            return

        # Remove stale socket
        try:
            os.unlink(sock_path)
        except OSError:
            pass

        self._server = await asyncio.start_unix_server(
            self._handle_client, sock_path
        )
        self._running = True
        self._task = asyncio.create_task(self._serve())
        print(f"[hive] Hook server listening on {sock_path}")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        sock_path = self.manager.sock_path()
        if sock_path:
            try:
                os.unlink(sock_path)
            except OSError:
                pass

    async def _serve(self) -> None:
        if self._server:
            async with self._server:
                await self._server.serve_forever()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while self._running:
                line = await reader.readline()
                if not line:
                    break
                try:
                    payload = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                resp = await self._dispatch(payload)
                if resp is not None:
                    writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                    await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    async def _dispatch(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Dispatch hook event to appropriate handler."""
        evt_type = payload.get("type")
        agent_id = payload.get("agent_id")

        if not agent_id or agent_id not in self.manager.registry.agents:
            return {"decision": "deny", "reason": "Unknown or unregistered agent"}

        agent = self.manager.registry.agents[agent_id]
        if agent.archived:
            return {"decision": "deny", "reason": "Archived Hive agent"}

        if evt_type == "pre_tool_use":
            return await self._handle_pre_tool_use(payload, agent)
        elif evt_type == "post_tool_use":
            await self._handle_post_tool_use(payload, agent)
            return {"decision": "allow"}
        elif evt_type == "stop":
            await self._handle_stop(payload, agent)
            return {"decision": "allow"}
        return None

    async def _handle_pre_tool_use(self, payload: dict[str, Any], agent: RegistryAgent) -> dict[str, Any]:
        """PreToolUse: check write guard, update agent status."""
        tool_name = payload.get("tool_name", "")
        tool_input = payload.get("tool_input", {})
        cwd = payload.get("cwd", agent.cwd or os.getcwd())

        # Write guard check
        if tool_name in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
            inp: HiveWriteInput = {
                "tool": tool_name,
                "toolInput": tool_input,
                "cwd": cwd,
                "agentId": agent.id,
                "isGod": agent.is_god,
                "hiveRoot": str(self.manager.hive_root),
                "caseInsensitive": os.name == "nt",
            }
            decision = hive_write_decision(inp)
            if decision["deny"]:
                self.manager._append_log({
                    "kind": "security_violation",
                    "agentId": agent.id,
                    "tool": tool_name,
                    "reason": decision["reason"],
                    "ts": time.time(),
                })
                print(f"[hive] DENY {agent.id} {tool_name}: {decision['reason']}")
                return {"decision": "deny", "reason": decision["reason"]}

        # Update status to working
        self.manager.set_agent_status(agent.id, "working")
        self.manager._append_log({
            "kind": "tool_start",
            "agentId": agent.id,
            "tool": tool_name,
            "ts": time.time(),
        })
        return {"decision": "allow"}

    async def _handle_post_tool_use(self, payload: dict[str, Any], agent: RegistryAgent) -> None:
        """PostToolUse: update status, log."""
        tool_name = payload.get("tool_name", "")
        self.manager.set_agent_status(agent.id, "idle")
        self.manager._append_log({
            "kind": "tool_end",
            "agentId": agent.id,
            "tool": tool_name,
            "ts": time.time(),
        })

    async def _handle_stop(self, payload: dict[str, Any], agent: RegistryAgent) -> None:
        """Stop: session idle → drain inbox (handled by router, but we can nudge)."""
        self.manager.set_agent_status(agent.id, "idle")
        session_id = payload.get("session_id")
        if session_id:
            self.manager.set_agent_session(agent.id, session_id)
        self.manager._append_log({
            "kind": "session_stop",
            "agentId": agent.id,
            "sessionId": session_id,
            "ts": time.time(),
        })
        # Nudge router to process inbox immediately
        # (router runs on interval anyway)