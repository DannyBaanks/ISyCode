"""Qt observation callbacks around the common host execution service."""

from __future__ import annotations

import asyncio
import json

from core.agent import Agent
from .tool_presentation import present_tool


class ObservableAgent(Agent):
    """Agent subclass that emits events and enforces interactive human approval."""

    def __init__(self, context, provider_registry, policy_engine,
                 runtime_registry, secret_broker, resident_recorder=None,
                 on_event=None, on_approval=None):
        super().__init__(context, provider_registry, policy_engine,
                         runtime_registry, secret_broker, resident_recorder, on_approval=on_approval)
        self._on_event = on_event
        # Native tool cards already present status/evidence. Keep machine tool
        # summaries out of the assistant's streamed prose.
        self.emit_tool_text = False

    def _emit(self, event: dict) -> None:
        if self._on_event is not None:
            self._on_event(event)

    async def _execute_tool(self, tool_call):
        """Observe the call and result; the core owns all authorization."""
        self._emit({
            "type": "tool_call",
            "id": str(getattr(tool_call, "id", "")),
            "tool": tool_call.name,
            "arguments": dict(tool_call.arguments or {}),
        })

        try:
            result = await super()._execute_tool(tool_call)
        except asyncio.CancelledError:
            self._emit({"type": "tool_result", "id": str(getattr(tool_call, "id", "")),
                        "tool": tool_call.name, "success": False,
                        "stdout": "", "stderr": "Herramienta detenida por el usuario.",
                        "returncode": None, "error_code": "CANCELLED", "evidence": {}})
            raise
        discovery = None
        if result.success and tool_call.name in {"glob", "project_tree"}:
            try:
                view = json.loads(result.stdout)
                if isinstance(view, dict) and isinstance(view.get("entries"), list):
                    discovery = {"entries": len(view["entries"]), "truncated": view.get("truncated", False),
                                 "path": view.get("path", "."), "version": view.get("version", "")}
            except (ValueError, TypeError):
                pass
        self._emit({
            "type": "tool_result",
            "id": str(getattr(tool_call, "id", "")),
            "tool": tool_call.name,
            "arguments": dict(tool_call.arguments or {}),
            "success": bool(result.success),
            "stdout": (result.stdout or "")[:4000],
            "stderr": (result.stderr or "")[:2000],
            "stdout_truncated": len(result.stdout or "") > 4000,
            "stderr_truncated": len(result.stderr or "") > 2000,
            "returncode": result.returncode,
            "error_code": result.error_code,
            "evidence": result.evidence or {},
            "project_view": discovery,
            "presentation": present_tool(tool_call.name, tool_call.arguments, {
                "success": result.success, "stdout": result.stdout, "stderr": result.stderr,
                "returncode": result.returncode, "error_code": result.error_code}),
        })
        return result
