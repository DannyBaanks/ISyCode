"""Chat tool dispatch, subagents, local MCP, and the iteration window.

Moved verbatim from tui.py. TUIApp inherits this mixin.
"""
from __future__ import annotations

from contextvars import ContextVar

_tool_display_context = ContextVar("tool_display_context", default=None)

import os
import asyncio
import json
import math
import shlex
import uuid
from pathlib import Path
from isycode.config import ConfigurationError
from isycode.localization import tr
from isycode.tool_history import record_tool_result, sanitize_historical_text, tool_history_context
from isycode.workspace_authority import (
    OneShotActionAuthority, WorkspaceAuthority, WorkspaceAuthorityError,
)
from isycode.actions import ACTION_BY_ID
from isycode.file_picker import ContextFilePickerOwner, FilePickerUnavailable
from isycode.action_runtime import (
    CHAT_WORKSPACE_TOOLS,
    CONTEXT_ACCESS_TOOL_NAME,
    LocalWorkspaceReadOwner,
    ProviderNetworkOwner,
    TOOL_ACTIONS,
)
from isycode.mcp_local import LocalMCPOwner, config_path as mcp_config_path, load_config as load_mcp_config
from isycode.agent_tasks import TASK_TOOL_NAME, render_tasks, validate_tasks
from isycode.agent_questions import ASK_USER_TOOL_NAME, validate_question
from isycode.idea_box import IDEA_BOX_TOOL_NAME, validate_idea_box
from isycode.git_owner import GIT_TOOL_NAMES
from isycode.command_runner import COMMAND_TOOL_NAME
from isycode.workspace_write import DELETE_TOOL_NAME, EDIT_TOOL, EDIT_TOOL_NAME, MOVE_TOOL_NAME, WRITE_TOOL, WRITE_TOOL_NAME
from textual.widgets import Static, Collapsible
from rich.text import Text
from rich.markdown import Markdown as RichMarkdown
from isycode.providers import PRESETS, Provider, ProviderError, load_provider_key, selected_provider_name
from isycode.streaming import StreamError
import time as _time
from isycode.bridge_tools import BRIDGE_TOOL_NAMES, BridgeSendScreen
from isycode.tui_screens_sessions import BridgePresenceScreen
from isycode.tui_theme import TEXT, MUTED, GREEN, YELLOW, RED, CYAN, SECURITY, _elapsed_label
from isycode.tui_widgets import ToolActivityGroup, ChatArea, SelectableText
from isycode.tui_composer import PromptArea
from isycode.tui_screens_approval import (
    TailscaleConfirmScreen, LocalMCPConfirmScreen, WorkspacePackConfirmScreen,
    MemoryConfirmScreen, BrowserReadPreviewScreen,
)
from isycode.workspace_memory import MEMORY_TOOL_OPERATIONS, WorkspaceMemoryOwner
from isycode.tui_screens_sessions import AgentQuestionScreen


from isycode.providers import provider_supports_tools
from isycode.contracts import AgentRuntime
from isycode.runtime import AuthorityContextChanged
from textual.widgets import Button
import hashlib

try:
    from agents.planner import PlanRejected  # type: ignore[reportMissingImports]
except ModuleNotFoundError:
    class PlanRejected(RuntimeError):
        """A planner rejection raised only when an optional runtime is present."""


class ToolMixin:
    async def _dispatch_chat_tool(self, call: dict) -> tuple[str, str]:
        """Dispatch one tool and report its full duration, including approval time."""
        function = call.get("function") if isinstance(call, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if name == IDEA_BOX_TOOL_NAME:
            return await self._dispatch_chat_tool_impl(call)
        label = name if isinstance(name, str) and name else "unknown tool"
        from isycode.operation_style import operation_icon
        from isycode.tui_theme import ascii_only
        label = f"{operation_icon(label, ascii_only=ascii_only())} {label}"
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except (ValueError, TypeError):
            arguments = {}
        if isinstance(arguments, dict):
            detail = " · ".join(sanitize_historical_text(str(arguments[key]))[:80] for key in ("path", "query", "pattern", "url") if isinstance(arguments.get(key), str))
            if detail:
                label += " · " + detail
        started_at = _time.monotonic()
        notes = Text()
        body = SelectableText(Text(""), selection_text="", classes="tool-activity-body")
        card = Collapsible(body, title=f"{label} · Running", collapsed=True,
                           collapsed_symbol="", expanded_symbol="", classes="tool-activity-leaf")
        group = None
        chat = None
        token = None
        if self._lane_on_screen():
            self._dismiss_idle()
            chat = self.query_one(ChatArea)
            preceding = [child for child in chat.children if child is not chat._tail
                         and not child.has_class("tool-receipt")]
            previous = preceding[-1] if preceding else None
            if isinstance(previous, ToolActivityGroup) and previous.operation == name:
                group = previous
                await group.add_leaf(card, label + " · Running")
            else:
                group = ToolActivityGroup(name, card, label)
                await chat.mount(group)
            chat.follow_tail()
            token = _tool_display_context.set((self, body, notes))
        state = "Failed"
        try:
            result = await self._dispatch_chat_tool_impl(call)
            try:
                material = json.loads(result[1])
            except (ValueError, TypeError):
                material = {}
            state = "Completed"
            if isinstance(material, dict):
                if material.get("status") == "rejected_by_user":
                    state = "Rejected"
                elif material.get("error"):
                    state = str(material.get("decision") or "Error")
                elif material.get("timed_out"):
                    state = "Timed out"
                elif material.get("exit_code") is not None:
                    state = f"Exit {material['exit_code']}"
            return result
        except asyncio.CancelledError:
            state = "Cancelled"
            raise
        finally:
            elapsed = _elapsed_label(_time.monotonic() - started_at)
            self._append(f"Tool duration · {label} · {elapsed}", MUTED)
            if token is not None:
                _tool_display_context.reset(token)
            if group is not None and card.is_mounted and self._lane_on_screen():
                group.finish_leaf(card, f"{label} · {state} · {elapsed}")
                self.query_one(ChatArea).follow_tail()

    def _bridge_tools_enabled(self) -> bool:
        """Offer the Bridge tools only when the workspace granted them."""
        try:
            grants = WorkspaceAuthority(self._workspace_root).effective_policy().get("grants", {})
        except Exception:  # noqa: BLE001 - a missing policy only hides the tools
            return False
        required = ("bridge.connect", "bridge.peek", "bridge.send", "bridge.wake")
        return all(isinstance(grants.get(action), dict)
                   and grants[action].get("enabled") is True
                   for action in required)

    def _bridge_owner(self):
        """One coordination owner per session: the identity stays stable."""
        from isycode.bridge_coordination import BridgeCoordinationOwner
        owner = getattr(self, "_bridge_coordination_owner", None)
        if owner is None:
            owner = BridgeCoordinationOwner(
                self._workspace_root, WorkspaceAuthority(self._workspace_root),
                self._action_approvals)
            self._bridge_coordination_owner = owner
        return owner

    async def _call_bridge_tool(self, name: str, raw_arguments: str) -> str:
        """Run one Bridge proposal: review first, then the owner's gate."""
        from isycode.bridge_tools import BRIDGE_SEND_TOOL, BRIDGE_WAKE_TOOL
        try:
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else None
        except json.JSONDecodeError:
            arguments = None
        if not isinstance(arguments, dict):
            return json.dumps({"error": "bridge tool arguments must be a JSON object"})
        if name == "bridge_peers":
            return json.dumps(await self._bridge_peers(), ensure_ascii=False)
        try:
            if name == "bridge_send":
                to = str(arguments.get("to") or "")
                topic = str(arguments.get("topic") or "")
                message = str(arguments.get("message") or "")
                kind = str(arguments.get("kind") or "message")
                if set(arguments) - {"to", "topic", "message", "kind"}:
                    raise ValueError("bridge_send accepts to, topic, message and kind")
                owner = self._bridge_owner()
                request = owner.prepare("send", to=to, topic=topic, kind=kind,
                                        payload=message)
                confirmed = await self._await_screen(BridgeSendScreen(
                    action="send", to=to, topic=topic, message=message))
                if not confirmed:
                    return json.dumps({"status": "declined"})
                outcome = await asyncio.to_thread(
                    owner.execute, request, self._action_approvals.issue(request))
                return json.dumps({"status": outcome.decision.lower(),
                                   "detail": outcome.reason[:200],
                                   "receipt": outcome.receipt.receipt_id if outcome.receipt else None},
                                  ensure_ascii=False)
            if name == "bridge_wake":
                to = str(arguments.get("to") or "")
                message = str(arguments.get("message") or "")
                if set(arguments) - {"to", "message"}:
                    raise ValueError("bridge_wake accepts to and message")
                owner = self._bridge_owner()
                request = owner.prepare("wake", to=to, message=message)
                confirmed = await self._await_screen(BridgeSendScreen(
                    action="wake", to=to, topic="", message=message))
                if not confirmed:
                    return json.dumps({"status": "declined"})
                outcome = await asyncio.to_thread(
                    owner.execute, request, self._action_approvals.issue(request))
                return json.dumps({"status": outcome.decision.lower(),
                                   "detail": outcome.reason[:200],
                                   "receipt": outcome.receipt.receipt_id if outcome.receipt else None},
                                  ensure_ascii=False)
        except (OSError, ValueError, RuntimeError) as exc:
            return json.dumps({"error": f"bridge action unavailable: {type(exc).__name__}"})
        return json.dumps({"error": "unknown bridge tool"})

    async def _register_bridge_peer(self) -> bool:
        """Register this window as a Bridge peer, with the user's approval."""
        owner = self._bridge_owner()
        try:
            request = owner.prepare("connect")
        except (OSError, ValueError, RuntimeError) as exc:
            self._append(f"  Bridge is not available here ({type(exc).__name__}).", YELLOW)
            return False
        approval = self._action_approvals.issue(request)
        outcome = await asyncio.to_thread(owner.execute, request, approval)
        if outcome.decision != "ALLOW":
            self._append("  Bridge registration was denied.", YELLOW)
            return False
        self._bridge_identity = owner.identity
        self._append(f"  Registered on the Bridge as {owner.identity}.", GREEN)
        return True

    async def _bridge_peers(self) -> dict:
        """Read the registered peers through the presence owner."""
        from isycode.bridge_presence import BridgePresenceOwner
        confirmed = await self._await_screen(BridgePresenceScreen())
        if not confirmed:
            return {"status": "declined"}
        root = self._workspace_root
        approvals = self._action_approvals
        base = WorkspaceAuthority(root)
        try:
            request = BridgePresenceOwner(root, base, approvals).prepare()
            owner = BridgePresenceOwner(
                root, OneShotActionAuthority(base, request), approvals)
            outcome, rows = await asyncio.to_thread(
                owner.read, request, approvals.issue(request))
        except (OSError, RuntimeError, ValueError):
            return {"status": "unavailable", "reason": "bridge handshake unavailable"}
        if outcome.decision != "ALLOW":
            return {"status": "unavailable", "reason": outcome.reason[:200]}
        return {"status": "ok",
                "peers": [{"name": str(row.get("name")), "state": str(row.get("status"))}
                          for row in rows]}

    async def _dispatch_chat_tool_impl(self, call: dict) -> tuple[str, str]:
        """Route one provider function call through the canonical local read owner."""
        function = call.get("function") if isinstance(call, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        raw_arguments = function.get("arguments", "{}") if isinstance(function, dict) else "{}"
        tool_call_id = call.get("id") if isinstance(call, dict) else ""
        if not isinstance(tool_call_id, str) or not tool_call_id:
            tool_call_id = "call_" + uuid.uuid4().hex[:16]
        if name == "webfetch":
            from isycode.web_fetch import WebFetchOwner, validate_url
            try:
                arguments = json.loads(raw_arguments)
                if not isinstance(arguments, dict) or set(arguments) != {"url"}:
                    raise ValueError("webfetch requires one URL")
                url, host = validate_url(arguments["url"])
                authority = WorkspaceAuthority(self._workspace_root)
                grant = authority.policy().get("grants", {}).get("web.fetch", {})
                if not grant.get("enabled") or host not in grant.get("network_hosts", []):
                    await self._change_network_action_grant(json.dumps({"action_id": "web.fetch", "label": "Read public web pages", "url": url}), True)
                result = await asyncio.to_thread(WebFetchOwner(self._workspace_root, authority).execute, url)
            except (ValueError, TypeError):
                result = {"error": "webfetch requires a public HTTPS URL without credentials, query or fragment", "decision": "DENY"}
            return tool_call_id, json.dumps(result, ensure_ascii=False)
        if name == "delegate_task":
            try:
                arguments = json.loads(raw_arguments)
                if not isinstance(arguments, dict) or set(arguments) != {"task"}:
                    raise ValueError("Invalid delegation arguments")
                result = await self._run_subagent(arguments["task"])
            except (TypeError, ValueError):
                result = {"status": "denied", "error": "Delegation requires one bounded task"}
            return tool_call_id, json.dumps(result, ensure_ascii=False)
        if isinstance(name, str) and name in BRIDGE_TOOL_NAMES:
            return tool_call_id, await self._call_bridge_tool(name, raw_arguments)
        if isinstance(name, str) and name.startswith("mcp__"):
            try:
                mcp_arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else None
            except json.JSONDecodeError:
                mcp_arguments = None
            return tool_call_id, await self._call_local_mcp(name, mcp_arguments)
        if name == "workspace_pack":
            try:
                pack_arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else None
            except json.JSONDecodeError:
                pack_arguments = None
            return tool_call_id, await self._call_workspace_pack(pack_arguments)
        if isinstance(name, str) and name in MEMORY_TOOL_OPERATIONS:
            try:
                memory_arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else None
            except json.JSONDecodeError:
                memory_arguments = None
            return tool_call_id, await self._call_workspace_memory(name, memory_arguments)
        if (name not in TOOL_ACTIONS and name not in GIT_TOOL_NAMES
                and name not in {WRITE_TOOL_NAME, EDIT_TOOL_NAME, COMMAND_TOOL_NAME,
                                 DELETE_TOOL_NAME, MOVE_TOOL_NAME,
                                 TASK_TOOL_NAME, CONTEXT_ACCESS_TOOL_NAME,
                                 ASK_USER_TOOL_NAME, IDEA_BOX_TOOL_NAME, "update_session_title"}):
            outcome = {"error": "tool is not registered by ISyCode"}
            self._append("  Tool denied · unregistered tool name", SECURITY)
            return tool_call_id, json.dumps(outcome)
        if not isinstance(raw_arguments, str) or len(raw_arguments) > 64 * 1024:
            outcome = {"error": "tool arguments are malformed or too large"}
            self._append(f"  Tool denied · {name} · invalid arguments", SECURITY)
            return tool_call_id, json.dumps(outcome)
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            arguments = None
        if not isinstance(arguments, dict):
            outcome = {"error": "tool arguments must be a JSON object"}
            self._append(f"  Tool denied · {name} · invalid arguments", SECURITY)
            return tool_call_id, json.dumps(outcome)
        if name == CONTEXT_ACCESS_TOOL_NAME:
            if (set(arguments) != {"path"} or not isinstance(arguments.get("path"), str)
                    or len(arguments["path"]) > 4096 or not Path(arguments["path"]).is_absolute()):
                return tool_call_id, json.dumps({
                    "error": "request_context_access requires one absolute document path"})
            try:
                picker = ContextFilePickerOwner(self._workspace_root)
                selected = picker.validate(Path(arguments["path"]))
                source_root = picker.project_root_for(selected)
                if source_root == self._workspace_root.resolve(strict=True):
                    raise ValueError("use the normal workspace read tools for files in the active project")
            except (FilePickerUnavailable, OSError, RuntimeError, ValueError) as exc:
                return tool_call_id, json.dumps({"error": str(exc)[:240]})
            content = await self._confirm_and_load_external_context(
                selected, source_root, requested_by_agent=True)
            if content is None:
                return tool_call_id, json.dumps({"status": "declined_or_unavailable"})
            return tool_call_id, json.dumps({"status": "approved", "path": str(selected),
                                              "context": content}, ensure_ascii=False)
        if name == ASK_USER_TOOL_NAME:
            try:
                question = validate_question(arguments)
            except ValueError as exc:
                return tool_call_id, json.dumps({"error": str(exc)[:180]})
            answer = await self._await_screen(AgentQuestionScreen(
                question["question"], question["choices"]))
            if not isinstance(answer, dict) or answer.get("status") not in {"answered", "cancelled"}:
                answer = {"status": "cancelled"}
            if answer.get("status") == "answered":
                answer = {key: answer[key] for key in ("status", "choice", "text") if key in answer}
            else:
                answer = {"status": "cancelled"}
            return tool_call_id, json.dumps(answer, ensure_ascii=False)
        if name == "update_session_title":
            if not isinstance(arguments, dict) or set(arguments) != {"title"} or not isinstance(arguments["title"], str):
                return tool_call_id, json.dumps({"status": "denied", "error": "one title string is required"})
            if self._chat_session_owner is None or not self._active_chat_session_id or not self._sessions_enabled():
                return tool_call_id, json.dumps({"status": "unavailable"})
            outcome, _ = self._chat_session_owner.manage("auto_title", self._active_chat_session_id, arguments["title"])
            self._paint_work_status()
            return tool_call_id, json.dumps({"status": outcome.decision, "reason": outcome.reason})
        if name == IDEA_BOX_TOOL_NAME:
            try:
                self._idea_box = validate_idea_box(arguments)
            except ValueError as exc:
                return tool_call_id, json.dumps({"error": str(exc)[:180]})
            self._paint_idea_box()
            self._save_draft()
            return tool_call_id, json.dumps({"status": "shown"})
        if 'folder' in arguments and name not in TOOL_ACTIONS and name not in {WRITE_TOOL_NAME, EDIT_TOOL_NAME}:
            return tool_call_id, json.dumps({'error': 'This tool does not support folder selection'})
        alias = arguments.pop('folder', 'main')
        if not isinstance(alias, str) or (alias != 'main' and name not in TOOL_ACTIONS and name not in {WRITE_TOOL_NAME, EDIT_TOOL_NAME}):
            return tool_call_id, json.dumps({'error': 'Additional folders support file reads/searches/creation/edits only'})
        try:
            root = self._folder_store().resolve(alias, write=name in {WRITE_TOOL_NAME, EDIT_TOOL_NAME})
        except (OSError, ValueError) as exc:
            return tool_call_id, json.dumps({'error': str(exc)[:180]})
        if name in {WRITE_TOOL_NAME, EDIT_TOOL_NAME}:
            batch_decision = self._batch_decisions.pop(tool_call_id, None)
            if batch_decision == "reject":
                self._append("  ✗ Batch rejected · nothing was written", MUTED)
                return tool_call_id, json.dumps({"status": "rejected_by_user",
                                                 "approved_by_user": False,
                                                 "path": arguments.get("path")})
            if batch_decision:
                self._set_activity(f"Applying batch-approved write · {arguments.get('path')}")
            return tool_call_id, await self._dispatch_write_tool(
                arguments, edit=name == EDIT_TOOL_NAME, root=root, folder_alias=alias,
                batch_digest=batch_decision or None)
        if name in {DELETE_TOOL_NAME, MOVE_TOOL_NAME}:
            return tool_call_id, await self._dispatch_file_change(name, arguments)
        if name == COMMAND_TOOL_NAME:
            return tool_call_id, await self._run_workspace_command(arguments)
        if name in GIT_TOOL_NAMES:
            return tool_call_id, await self._git_tool(name, arguments)
        if name == TASK_TOOL_NAME:
            try:
                tasks = validate_tasks(arguments)
            except ValueError as exc:
                return tool_call_id, json.dumps({"error": str(exc)})
            self._show_agent_tasks(tasks)
            return tool_call_id, json.dumps({"status": "shown", "tasks": len(tasks)})
        action_id = TOOL_ACTIONS[name]
        target = arguments.get("path", ".")
        query = arguments.get("query")
        summary = {"workspace_list": f"list {target}", "workspace_read": f"read {target}",
                   "workspace_search": f"find names “{query}” in {target}",
                   "workspace_grep": f"grep “{query}” in {target}"}.get(name, f"{name} {target}")
        try:
            owner = LocalWorkspaceReadOwner(
                root, WorkspaceAuthority(root))
            result = await asyncio.to_thread(owner.execute, action_id, arguments)
        except Exception:
            self._append(f"  Tool denied · {action_id} · authority/owner unavailable", SECURITY)
            return tool_call_id, json.dumps({"error": "ISyCode authorization or read owner unavailable"})
        if result.decision != "ALLOW" or result.receipt is None:
            reason = result.reason or result.decision
            self._append(f"  ✗ {summary} · {result.decision} · {reason[:180]}", SECURITY)
            return tool_call_id, json.dumps({"error": "ISyCode denied the action", "reason": reason[:300]})
        # The outcome and its receipt live inside the tool's own card; no
        # separate box per call.
        self._append(f"  ✓ {alias} · {summary[:160]} · completed", TEXT)
        self._append(self._receipt_text(result, summary), MUTED)
        return tool_call_id, result.text

    def _receipt_text(self, result, summary: str) -> str:
        """Compact receipt: decision, safe path, budget and recovery, never content."""
        from isycode.chat_sessions import ChatSessionStore
        budget = "unavailable"
        try:
            from isycode.effect_ledger import EffectLedger, MAX_CHURN_BYTES
            status = EffectLedger(self._workspace_root).status()
            remaining = max(0, MAX_CHURN_BYTES - status["churn_bytes"])
            budget = (f"churn {status['churn_bytes']} B used · {remaining} B remaining · "
                      f"{status['unique_paths']} paths · {status['delete_ops']} deletes")
        except Exception:
            pass
        lines = [
            f"Decision · {result.decision}",
            f"Receipt · {result.receipt.receipt_id}",
            f"Scope · {ChatSessionStore._sanitize_text(summary[:160])}",
            f"Budget · {budget}",
            "Recovery · /undo restores the last applied change; journal verification in Settings",
        ]
        return "\n".join(lines)

    def _child_model_choices(self):
        from isycode.providers import child_model_choices
        choices = child_model_choices()
        for rows in getattr(self, "_account_model_catalogs", {}).values():
            for row in rows:
                provider, model = row["value"].split("|", 1)
                item = {"provider": provider, "model": model}
                if item not in choices:
                    choices.append(item)
        return choices

    def _iteration_owner(self):
        from isycode.iteration import IterationOwner
        return IterationOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root))

    def _show_iteration_state(self, state):
        self._append("Iteration · " + state["title"] + " · " + state["status"], CYAN)
        participants = {p["participant_id"]: p for p in state["participants"]}
        for turn in state["turns"]:
            p = participants.get(turn["actor_id"])
            label = self._model_display_label(p["provider"], p["model"]) if p else "Human"
            self._append(str(turn["seq"]) + " · " + label + " · " + turn["kind"], CYAN)
            self.query_one(ChatArea).mount(SelectableText(RichMarkdown(turn["content"], code_theme="monokai"), selection_text=turn["content"]))
        self.query_one(ChatArea).follow_tail()
        if state["status"] == "PARTICIPANT_ERROR":
            self._append("Iteration paused · " + str(state["receipts"][-1].get("error_kind")) + " · /iteration retry " + state["iteration_session_id"], YELLOW)

    async def _run_iteration_window(self, objective):
        from isycode.iteration import run_iteration
        from isycode.providers import child_model_choices
        from isycode.subagent_screen import SubagentModelScreen
        if self._subagent_running or (self._loop_task and self._loop_task is not asyncio.current_task() and not self._loop_task.done()):
            self._append("Finish the active task before starting an iteration.", YELLOW)
            return
        if not objective:
            self._append("Usage: /iteration <objective> · choose three participants. Esc cancels.", MUTED)
            return
        self._subagent_running = True
        self._subagent_task = asyncio.current_task()
        try:
            owner = self._iteration_owner()
            if objective.startswith("retry "):
                sid = objective.removeprefix("retry ").strip()
            else:
                participants = []
                choices = self._child_model_choices()
                for role in ("PROPOSER", "REVIEWER", "FINAL HUMAN_HANDOFF"):
                    selected = await self._await_screen(SubagentModelScreen("Iteration · " + role + " · " + objective, choices))
                    if selected is None:
                        return
                    if selected not in choices:
                        raise ValueError("unregistered participant")
                    participants.append(dict(selected, role=role))
                sid = owner.create_iteration(objective[:100], participants)
                owner.human(sid, objective)
            self._show_chat_again()
            self._append("Iteration order · " + " → ".join(self._model_display_label(p["provider"], p["model"]) for p in owner.inspect(sid)["participants"]), CYAN)
            def factory(p):
                return Provider(name=p["provider"], model=p["model"],
                    base_url=PRESETS[p["provider"]]["base_url"], api_key=load_provider_key(p["provider"]) or None)
            state = await run_iteration(owner, sid, factory,
                on_status=lambda status: self._set_activity("Iteration · " + status, CYAN))
            self._show_iteration_state(state)
        except asyncio.CancelledError:
            self._append("Iteration aborted; durable contributions preserved.", YELLOW)
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            self._append("Iteration unavailable · " + type(exc).__name__, YELLOW)
        finally:
            self._subagent_running = False
            self._subagent_task = None
            self._set_activity(tr("Chat ready"), MUTED)
            self.query_one("#prompt-input", PromptArea).focus()
            await self._refresh_work_list()

    async def _run_subagent(self, task: str) -> dict:
        previous_error = None
        while True:
            result = await self._run_subagent_attempt(task, previous_error)
            if result.get("status") != "error" or result.get("error_kind") == "AUTHORITY":
                if previous_error and result.get("status") == "cancelled":
                    result["previous_error"] = previous_error
                return result
            previous_error = result

    async def _run_subagent_attempt(self, task: str, previous_error=None) -> dict:
        from isycode.providers import child_model_choices
        from isycode.subagents import run_child
        from isycode.subagent_screen import SubagentModelScreen
        if not isinstance(task, str) or not task.strip() or len(task) > 8000:
            return {"status": "denied", "error": "Use /subagent <task>, up to 8000 characters"}
        if self._subagent_running:
            return {"status": "denied", "error": "A child is already running; nested delegation is disabled"}
        models = self._child_model_choices()
        if not models:
            return {"status": "denied", "error": "No configured provider model is available"}
        self._subagent_running = True
        self._child_task = task.strip()[:160]
        self._subagent_task = asyncio.current_task()
        card = None
        identity = {}
        try:
            selected = await self._await_screen(SubagentModelScreen(task, models, error=previous_error))
            if selected is None:
                return {"status": "cancelled"}
            if selected not in models or selected not in self._child_model_choices():
                return {"status": "denied", "error": "Selected model is no longer registered"}
            identity = {"provider": selected["provider"], "model": selected["model"]}
            self._child_title = self._model_display_label(selected['provider'], selected['model'])
            # A main provider endpoint override must never receive another provider's key.
            endpoint = (os.environ.get("ISYCODE_BASE_URL") or os.environ.get("ISYMOTRON_BASE_URL")
                        if selected["provider"] == selected_provider_name() else None)
            provider = Provider(name=selected["provider"], model=selected["model"],
                                base_url=endpoint or PRESETS[selected["provider"]]["base_url"],
                                api_key=load_provider_key(selected["provider"]) or None)
            if not provider.configured():
                return {**identity, "status": "error", "error_kind": "APIKEY", "phase": "configuration", "provider_hint": "Selected provider credentials are not configured", "error": "Selected provider is not configured"}
            tools = []
            read_enabled = self._workspace_chat_tools_enabled() or self._additional_folder_access()
            if read_enabled and provider_supports_tools(provider.name):
                tools = json.loads(json.dumps(CHAT_WORKSPACE_TOOLS))
                if self._workspace_write_tool_enabled() or self._additional_folder_access(write=True):
                    tools += json.loads(json.dumps([EDIT_TOOL, WRITE_TOOL]))
            if provider_supports_tools(provider.name):
                from isycode.web_fetch import WEB_FETCH_TOOL
                tools.append(WEB_FETCH_TOOL)
            context = [{"role": "system", "content": (
                f"You are an ISyCode child agent. Work only on the assigned task. Main workspace: {self._workspace_root}. "
                "Use only the tools supplied here. File tools accept registered folder aliases; never ../ across roots. "
                "Workspace Authority, IsySentinel and per-folder approvals remain mandatory; no new authority is granted. "
                "Tools execute through the same owners as the main agent. Do not claim changes without verified results. "
                "Recursive delegation, commands, deletion, moves, Git and MCP are unavailable to children. "
                "Report completed work, errors and remaining work truthfully.") }]
            folders = [{"alias": "main", "path": str(self._workspace_root)}] + self._folder_store().list()
            context[0]["content"] += " Registered folder metadata: " + json.dumps(folders)
            # ADR 0009: the child starts with the parent's continuity capsule, not
            # an empty conversation. It is bounded, redacted and carries no grants.
            from isycode.continuity_capsule import SUBAGENT_CAPSULE_CHARS, build_capsule
            capsule = build_capsule(
                budget_chars=SUBAGENT_CAPSULE_CHARS, tool_history=self._tool_history,
                older_messages=self._history, summary=self._conversation_summary,
                tasks=self._agent_tasks, idea_box=self._idea_box)
            if capsule:
                context.append({"role": "system", "content": capsule})
            if previous_error and self._tool_history:
                context.append({"role": "system", "content": tool_history_context(self._tool_history)})
            if self._active_skills:
                from isycode.skill_catalog import guidance
                context.append({"role": "system", "content": guidance(self._active_skills)})
            card = Static(Text(f"Subagent · {self._model_display_label(provider.name, provider.model)} · starting", style=CYAN))
            chat = self.query_one(ChatArea)
            chat.mount(card); chat.follow_tail()
            def status(value):
                card.update(Text(f"Subagent · {self._model_display_label(provider.name, provider.model)} · {value}", style=CYAN))
                chat.follow_tail()
            owner = ProviderNetworkOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root))
            async def complete(messages):
                material = {"operation": "chat.completions", "messages": messages,
                            "max_tokens": None, "tools": tools or None,
                            "token_limit_field": provider.token_limit_field,
                            "reasoning_effort": provider.reasoning_effort,
                            "temperature_supported": provider.temperature_supported}
                async def send():
                    return await self._complete_accounted_chat(provider, messages, max_tokens=None, tools=tools or None)
                response, outcome = await owner.execute(provider, material, send)
                if outcome.decision != "ALLOW" or outcome.receipt is None or response is None:
                    raise PermissionError("Child provider request denied or unverifiable")
                return response
            async def dispatch(call):
                self._append(f"  Subagent tool · {call['function']['name']}", CYAN)
                self._tool_history = record_tool_result(self._tool_history, call,
                    "Child tool attempt started; completion unverified. Cancellation does not prove no effect.")
                self._save_draft()
                call_id, output = await self._dispatch_chat_tool(call)
                self._tool_history = record_tool_result(self._tool_history[:-1], call, output)
                self._save_draft()
                return call_id, output
            result = await run_child(provider, task, context,
                [tool["function"]["name"] for tool in tools], complete, dispatch,
                on_status=status)
            status(result["status"])
            reply = result.get("text") if isinstance(result, dict) else ""
            if isinstance(reply, str) and reply.strip():
                shown = reply.strip()[:4000]
                chat = self.query_one(ChatArea)
                chat.mount(SelectableText(Text(
                    f"Subagent · {self._model_display_label(identity.get('provider', ''), identity.get('model', ''))}\n{shown}"),
                    selection_text=shown))
                chat.follow_tail()
            return result
        except asyncio.CancelledError:
            if card is not None:
                card.update(Text("Subagent · cancelled; completed effects remain in the action journal", style=YELLOW))
            raise
        except (OSError, ValueError, ProviderError, ConfigurationError, StreamError) as exc:
            from isycode.provider_errors import classify_provider_error
            detail = classify_provider_error(exc)
            if card is not None:
                card.update(Text("Subagent · " + detail["provider_hint"], style=YELLOW))
            self._play_notification_sound("error")
            return {**identity, **detail, "status": "blocked" if isinstance(exc, PermissionError) else "error",
                    "error": detail["provider_hint"]}
        finally:
            self._subagent_running = False
            self._child_task = ""
            self._child_title = ""
            self._subagent_task = None

    def _select_skill(self, name: str) -> None:
        from isycode.skill_catalog import guidance
        try:
            proposed = [item for item in self._active_skills if item != name]
            if name not in self._active_skills:
                proposed.append(name)
            guidance(proposed)
            self._active_skills = proposed
            self._append("  Selected skills · " + (", ".join(proposed) or "none"), CYAN)
        except (OSError, ValueError):
            self._append("  Skill unavailable or selection too large; existing guidance preserved.", YELLOW)

    def _show_agent_tasks(self, tasks: list[dict[str, str]]) -> None:
        """Replace the on-screen task list; an empty or all-done list collapses after a turn."""
        self._agent_tasks = list(tasks)
        if not self._lane_on_screen() or not self.is_mounted:
            return
        panel = self.query_one("#agent-tasks", Static)
        panel.display = bool(tasks)
        panel.update(render_tasks(tasks, collapsed=self._tasks_collapsed) if tasks else "")

    def action_toggle_tasks(self) -> None:
        """Fold the Tasks panel to one line, or open it back to full size."""
        if not self._agent_tasks:
            return
        self._tasks_collapsed = not self._tasks_collapsed
        self._show_agent_tasks(self._agent_tasks)

    def _local_mcp_owner(self) -> LocalMCPOwner:
        if self._mcp_local is None or self._mcp_local.root != self._workspace_root.resolve():
            self._mcp_local = LocalMCPOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root),
                                            self._action_approvals)
        return self._mcp_local

    def _add_mcp_preset(self, name: str) -> None:
        from isycode.mcp_presets import add_preset
        try:
            add_preset(name)
            self._append(f"  MCP {name} configured. /mcp start {name} reviews the npm download/process before starting.", GREEN)
        except (OSError, ValueError):
            self._append("  MCP preset could not be added; inspect the private config, existing name and available presets.", YELLOW)

    async def _list_local_mcp(self) -> None:
        try:
            configs = load_mcp_config()
        except (OSError, ValueError) as exc:
            self._append(f"  MCP config problem · {str(exc)[:200]}", YELLOW)
            return
        if not configs:
            self._append(f"  No local MCP servers configured. Add them to {mcp_config_path()} as "
                         '{"servers": {"name": {"command": ["program", "arg"]}}}.', MUTED)
            return
        running = self._local_mcp_owner().sessions
        for name, config in configs.items():
            state = (f"running · {len(running[name].tools)} tools" if name in running
                     and running[name].process.returncode is None else "stopped")
            self._append(f"  {name} · {state} · {shlex.join(config.argv)[:120]}", MUTED)
        self._append("  /mcp start <name> asks before starting; each tool call asks again.", MUTED)

    async def _start_local_mcp(self, name: str) -> None:
        mcp_owner = self._local_mcp_owner()
        try:
            preview = await asyncio.to_thread(mcp_owner.prepare_start, name)
        except (OSError, ValueError) as exc:
            self._append(f"  MCP {name} cannot start · {str(exc)[:200]}", YELLOW)
            return
        executable = preview.request.parameters["executable"]
        authority = WorkspaceAuthority(self._workspace_root)
        grants = authority.policy().get("grants", {})
        start_grant = grants.get("mcp.local.start", {})
        invoke_grant = grants.get("mcp.local.invoke", {})
        if (executable not in start_grant.get("executables", [])
                or name not in invoke_grant.get("targets", [])):
            if not await self._await_screen(TailscaleConfirmScreen(
                    f"Allow MCP server {name} in this workspace?",
                    f"Saves a grant for {executable} and for calls to {name}. Starting it and every "
                    "tool call still ask first. The server runs with your user's permissions.",
                    "Allow this server")):
                self._append(f"  MCP {name} not allowed; nothing started.", MUTED)
                return
            try:
                authority.set_grant("mcp.local.start", enabled=True, executables=sorted(
                    set(start_grant.get("executables", [])) | {executable}))
                authority.set_grant("mcp.local.invoke", enabled=True, targets=sorted(
                    set(invoke_grant.get("targets", [])) | {name}))
            except (WorkspaceAuthorityError, OSError, ValueError) as exc:
                self._append(f"  MCP grant could not be saved ({type(exc).__name__}).", RED)
                return
        env_keys = ", ".join(preview.request.parameters["env_keys"]) or "none"
        if not await self._await_screen(LocalMCPConfirmScreen(
                f"Start MCP server · {name}",
                f"Runs this program from your MCP config in {self._workspace_root} with your "
                f"user's permissions (network included) until ISyCode exits. Extra environment: "
                f"{env_keys}.", shlex.join(preview.config.argv), "Start server",
                owner="local MCP server",
                scope=name,
                duration="until ISyCode exits",
                not_granted="no other MCP servers; runs with user permissions (no filesystem isolation)")):
            self._append(f"  MCP {name} not started.", MUTED)
            return
        approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
        outcome = await mcp_owner.start(preview, approval)
        if outcome.decision == "ALLOW":
            tools = json.loads(outcome.text)["tools"]
            self._append(f"  MCP {name} started · {len(tools)} tools · receipt "
                         f"{outcome.receipt.receipt_id}", GREEN)
        else:
            self._append(f"  MCP {name} {outcome.decision} · {outcome.reason[:180]}", SECURITY)

    async def _call_local_mcp(self, function: str, arguments) -> str:
        mcp_owner = self._local_mcp_owner()
        resolved = mcp_owner.resolve_function(function)
        if resolved is None:
            return json.dumps({"error": "that MCP tool is not available; the server may be stopped"})
        server, tool = resolved
        try:
            preview = mcp_owner.prepare_call(server, tool, arguments)
        except ValueError as exc:
            return json.dumps({"error": str(exc)[:200]})
        self._append(f"  MCP call requested · {server}.{tool} · review it", CYAN)
        if not await self._await_screen(LocalMCPConfirmScreen(
                f"Call MCP tool · {server}.{tool}",
                "Sends exactly these arguments to the local server. Its answer is untrusted data.",
                json.dumps(preview.arguments, ensure_ascii=False, indent=2), "Call once",
                owner="local MCP tool",
                scope=f"{server}.{tool}",
                duration="one-use tool call",
                not_granted="no other tool calls, no automatic retries")):
            self._append("  MCP call rejected · nothing was sent", MUTED)
            return json.dumps({"status": "rejected_by_user"})
        outcome = await mcp_owner.call(preview, self._action_approvals.issue(preview.request, ttl_seconds=60))
        if outcome.decision != "ALLOW" or outcome.receipt is None:
            self._append(f"  MCP {outcome.decision} · {outcome.reason[:180]}", SECURITY)
            return json.dumps({"error": "MCP call did not run", "reason": outcome.reason[:300]})
        try:
            payload = json.loads(outcome.text)
        except (TypeError, json.JSONDecodeError):
            payload = {}
        if payload.get("browser_read") is True:
            content = payload.get("content")
            if not isinstance(content, str) or not content.strip():
                self._append("  Browser snapshot contained no readable page text; raw output withheld.", YELLOW)
                return json.dumps({"status": "no_readable_page_text", "content_shared": False})
            title = content.splitlines()[0][:180]
            raw_processing_ms = payload.get("processing_ms")
            processing_ms = (
                raw_processing_ms
                if isinstance(raw_processing_ms, (int, float))
                and not isinstance(raw_processing_ms, bool)
                and math.isfinite(raw_processing_ms)
                and raw_processing_ms >= 0
                else None
            )
            if not await self._await_screen(BrowserReadPreviewScreen(
                    title, content, int(payload.get("input_chars", 0)),
                    int(payload.get("filtered_chars", len(content))),
                    bool(payload.get("truncated")), processing_ms)):
                self._append("  Browser text discarded · it was not shared with the model.", MUTED)
                return json.dumps({"status": "rejected_by_user", "content_shared": False})
        self._append(f"  MCP ALLOW · {server}.{tool} · receipt {outcome.receipt.receipt_id}", GREEN)
        return outcome.text

    async def _call_workspace_pack(self, arguments) -> str:
        """Review a bounded file inventory before packing any file contents."""
        from isycode.workspace_pack import WorkspacePackOwner

        try:
            owner = WorkspacePackOwner(
                self._workspace_root, WorkspaceAuthority(self._workspace_root))
            preview = await asyncio.to_thread(owner.prepare, arguments)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return json.dumps({
                "error": f"workspace pack unavailable ({type(exc).__name__}): {str(exc)[:240]}"})

        rows = [
            f"{json.dumps(item.path, ensure_ascii=False)} · {item.size:,} bytes · "
            f"~{(item.size + len(item.path.encode('utf-8')) + 49) // 2:,} tokens"
            for item in preview.files
        ]
        details = (
            f"Files: {len(preview.files)} / 200\n"
            f"Total size: {preview.total_bytes:,} bytes\n"
            f"Estimated tokens: ~{preview.estimated_tokens:,}\n"
            f"Approved budget: {preview.arguments['token_budget']:,}\n\n"
            + "\n".join(rows)
        )
        if not await self._await_screen(WorkspacePackConfirmScreen(details)):
            self._append("  Workspace pack cancelled · no file contents were read", MUTED)
            return json.dumps({"status": "cancelled", "files_read": 0})
        try:
            result = await asyncio.to_thread(owner.execute, preview)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._append(f"  Workspace pack failed · {str(exc)[:180]}", YELLOW)
            return json.dumps({"error": f"workspace pack failed: {str(exc)[:240]}"})
        self._append(
            f"  Workspace pack · {len(preview.files)} files · ~{result['estimated_tokens']:,} tokens",
            GREEN,
        )
        return result["content"]
    async def _call_workspace_memory(self, tool_name: str, arguments) -> str:
        """Run an explicit memory operation after reviewing it with the user."""
        operation = MEMORY_TOOL_OPERATIONS.get(tool_name)
        if operation is None:
            return json.dumps({"error": "memory tool is not registered"})
        authority = WorkspaceAuthority(self._workspace_root)
        try:
            owner = WorkspaceMemoryOwner(self._workspace_root, authority,
                                         self._action_approvals)
            preview = owner.prepare(operation, arguments)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return json.dumps({"error": f"memory request invalid or unavailable ({type(exc).__name__})"})
        action = ACTION_BY_ID[preview.request.action_id]
        try:
            configured = authority.policy().get("grants", {}).get(action.id, {})
        except (OSError, RuntimeError, ValueError):
            return json.dumps({"error": "workspace memory authority is unavailable"})
        if configured.get("enabled") is False:
            self._append("  Memory action denied · explicitly revoked in workspace authority", SECURITY)
            return json.dumps({"error": "workspace memory action was explicitly revoked",
                               "decision": "DENY"})
        sends_to_model = operation in {
            "recall", "list_topics", "list_memoirs", "show_memoir", "search_memoir",
        }
        if not await self._await_screen(MemoryConfirmScreen(
                operation, json.dumps(preview.arguments, ensure_ascii=False, indent=2),
                sends_to_model=sends_to_model)):
            self._append(f"  Memory {operation} rejected · nothing was read or changed", MUTED)
            return json.dumps({"status": "rejected_by_user"})
        one_shot = OneShotActionAuthority(authority, preview.request)
        owner = WorkspaceMemoryOwner(self._workspace_root, one_shot, self._action_approvals)
        outcome = await asyncio.to_thread(owner.execute, preview)
        if outcome.decision != "ALLOW" or outcome.receipt is None:
            self._append(f"  Memory {outcome.decision} · {outcome.reason[:180]}", YELLOW)
            return json.dumps({"error": "workspace memory action did not complete",
                               "decision": outcome.decision, "reason": outcome.reason[:240]})
        self._append(f"  Memory {operation} · receipt {outcome.receipt.receipt_id}", GREEN)
        return outcome.text

    def _menu_skill_use(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        self._select_skill(value)
        self._render_menu("branch", "Skills", self._branch_entries("skills"))
        return

    def _menu_skill_clear(self, entry: dict[str, str | bool]) -> None:
        self._active_skills.clear()
        self._render_menu("branch", "Skills", self._branch_entries("skills"))
        return

    def _menu_mcp_preset(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        self._add_mcp_preset(value)
        self._render_menu("branch", "MCP", self._branch_entries("mcp"))
        return

    async def _run_plan(self, intent: str) -> None:
        """Delegate planning to IsyMotron runtime and render its proposal."""
        self._clear_pending_plan()
        block = None
        if self._lane_on_screen():
            block, _chat = self._mount_thought()
        reason_buf: list[str] = []
        t0 = _time.monotonic()
        try:
            def on_chunk(kind: str, chunk: str) -> None:
                if kind == "reasoning":
                    reason_buf.append(chunk)
                    if block is not None and block.is_mounted and self._lane_on_screen():
                        self.call_from_thread(block.set_text, "".join(reason_buf))

            runtime = self._runtime_factory(self._workspace_root)
            outcome = await runtime.plan(intent, on_chunk=on_chunk)
            plan = outcome.plan
            from isycode.model_presentation import model_display_name
            self._append(f"  Model: {model_display_name(outcome.model)} · {outcome.provider_label}", MUTED)
            self._append(f"  Host: {outcome.host_name}", MUTED)

            if plan.verdict() == "PLANNED":
                self._append(f"\n  Understood: {plan.understood}", TEXT)
                self._append(f"  Plan ({len(plan.steps)} steps):", YELLOW)
                for i, step in enumerate(plan.steps, 1):
                    params_str = ", ".join(f"{k}={v}" for k, v in step.params.items())
                    self._append(f"    {i}. [{step.host}] {step.capability}({params_str})", TEXT)
                    self._append(f"       ↳ {step.why}", MUTED)
                self._append("\n  Proposal only · it carries no authority.", MUTED)
                self._append(
                    "  Execution is disabled in Secure until each step has an ISyCode owner, "
                    "grant, Sentinel decision and required approval.", MUTED)
                if plan.completion and plan.completion.prompt_tokens is not None and plan.completion.completion_tokens is not None:
                    self._append(f"  Tokens: {plan.completion.prompt_tokens + plan.completion.completion_tokens}", MUTED)
                self._clear_pending_plan()
                if self._lane_on_screen():
                    review = self.query_one("#review-plan", Button)
                    review.disabled = True
                    review.label = "Execution unavailable in Secure"
                self._append(
                    f"\n  {outcome.origin} proposal is ready for inspection; it cannot be run through IsyMotron.",
                    YELLOW)
            else:
                self._append(f"\n  Refused: {plan.refused or 'no plan possible'}", RED)
                self._append("  This is correct behavior, not a failure.", MUTED)

        except PlanRejected as e:
            reason = getattr(e, "reason", str(e))
            self._append(f"\n  Plan rejected: {reason}. No executable plan was retained.", RED)
        except ProviderError as e:
            self._append(f"\n  {self._provider_failure(e, 'Planning')}", RED)
        except Exception as e:
            self._append(
                f"\n  Planning failed ({type(e).__name__}). No executable plan was retained.", RED)
        finally:
            if block is not None and block.is_mounted and self._lane_on_screen():
                block.collapse_to(_time.monotonic() - t0)

    def action_run_plan(self) -> None:
        """Review and confirm a demo plan through its contextual button."""
        if self._last_plan is None or self._last_runtime is None:
            self._append("  No plan to run. Use /plan <intent> first.", MUTED)
            return
        if self._loop_task and not self._loop_task.done():
            self._append("  Wait for the current task to finish before running a plan.", YELLOW)
            return
        try:
            current_context = self._last_runtime.approval_context()
        except Exception as e:
            self._clear_pending_plan()
            self._set_activity("Plan cleared · authority could not be revalidated", RED)
            self._append(
                f"  Authority could not be revalidated ({type(e).__name__}); plan cleared.", RED)
            return
        if current_context != self._last_plan_context:
            self._clear_pending_plan()
            self._set_activity("Plan cleared · authority changed", RED)
            self._append(
                "  Host identity, grants, capabilities, or scopes changed after planning. "
                "Create a new plan before execution.", RED)
            return
        now = _time.time()
        plan_digest = self._plan_digest(self._last_plan)
        if (now - self._armed_at > 10.0
                or self._armed_plan_id != self._last_plan.plan_id
                or self._armed_plan_digest != plan_digest
                or self._armed_context != current_context):
            try:
                authority = self._last_runtime.approval_summary()
            except Exception as e:
                self._clear_pending_plan()
                self._set_activity("Plan cleared · authority details unavailable", RED)
                self._append(
                    f"  Authority details could not be loaded ({type(e).__name__}); plan cleared.",
                    RED)
                return
            self._armed_at = now
            self._armed_plan_id = self._last_plan.plan_id
            self._armed_plan_digest = plan_digest
            self._armed_context = current_context
            review = self.query_one("#review-plan", Button)
            is_local_read = self._last_plan_origin == "local-read-only"
            review.label = "Confirm local read-only plan" if is_local_read else "Confirm demo plan"
            n = len(self._last_plan.steps)
            effect = ("local filesystem.read only" if is_local_read
                      else "simulated host; no real workspace effects")
            self._append(
                f"\n  Review {self._last_plan_origin} plan ({n} steps; {effect}):",
                YELLOW)
            self._append(f"  Host: {self._last_plan_host}", MUTED)
            identity = authority.get("identity", {})
            if isinstance(identity, dict):
                self._append(
                    f"  Host identity: {identity.get('host_id', 'unknown')} · "
                    f"{identity.get('engine', 'unknown')} · {identity.get('os_family', 'unknown')}",
                    MUTED)
            capabilities = authority.get("granted", [])
            if isinstance(capabilities, list):
                self._append(
                    "  Granted capabilities: " + (", ".join(map(str, capabilities)) or "none"),
                    MUTED)
            bounds = authority.get("bounds", {})
            if isinstance(bounds, dict):
                for capability, scope in sorted(bounds.items()):
                    scope_text = json.dumps(scope, sort_keys=True, ensure_ascii=False, default=str)
                    self._append(f"  Scope {capability}: {scope_text}", MUTED)
            for i, s in enumerate(self._last_plan.steps, 1):
                params = ", ".join(f"{key}={value}" for key, value in s.params.items())
                self._append(f"    {i}. [{s.host}] {s.capability}({params})", TEXT)
            self._append(
                f"  Select {review.label} in Overview within 10s to execute it.", YELLOW)
            self._set_activity("Awaiting confirmation · expires in 10s", YELLOW)
            return
        plan, runtime = self._last_plan, self._last_runtime
        origin, host_name = self._last_plan_origin, self._last_plan_host
        self._clear_pending_plan()
        self._start_operation(
            self._execute_stored_plan(
                plan, runtime, origin, host_name, expected_context=current_context),
            f"Executing · {host_name}")

    def _clear_pending_plan(self) -> None:
        """Forget an executable plan and any approval bound to it."""
        self._last_plan = None
        self._last_runtime = None
        self._last_plan_origin = ""
        self._last_plan_host = ""
        self._last_plan_context = None
        self._armed_at = 0.0
        self._armed_plan_id = None
        self._armed_plan_digest = None
        self._armed_context = None
        review = self.query_one("#review-plan", Button)
        review.disabled = True
        review.label = "No plan pending"

    @staticmethod
    def _plan_digest(plan) -> str:
        payload = json.dumps(plan.to_dict(), sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _receipt_audit_lines(receipt, verification) -> list[str]:
        """Render the receipt seal and every field from IsyMotron's verifier."""
        def label(value) -> str:
            if value is None:
                return "none"
            return str(getattr(value, "value", getattr(value, "name", value)))

        if receipt is None:
            lines = ["Receipt: unavailable"]
        else:
            decision = getattr(receipt, "decision", None)
            policy_decision = getattr(decision, "decision", None)
            policy_reason = getattr(decision, "reason", None)
            lines = [
                f"Receipt ID: {receipt.receipt_id}",
                f"Seal: kind={getattr(receipt, 'seal_kind', 'unknown')} · "
                f"status={getattr(verification, 'seal_status', 'NOT_REPORTED')} · "
                f"value={getattr(receipt, 'seal', '') or 'missing'}",
                f"Receipt decision: {label(policy_decision)} · reason={label(policy_reason)}",
            ]

        if verification is None:
            lines.append("Verification: NOT_VERIFIABLE · verifier returned no result")
            lines.extend(("Claim match: not checked", "Request match: not checked",
                          "Decision match: not checked", "Re-derived decision: unavailable"))
            return lines

        status = label(getattr(verification, "status", "NOT_VERIFIABLE"))
        lines.append(
            f"Verification: {status} · {getattr(verification, 'reason', 'no verifier reason')}")
        rederived = getattr(verification, "rederived", None)
        was_rederived = rederived is not None
        for title, field in (("Claim match", "claim_matched"),
                             ("Request match", "request_matched"),
                             ("Decision match", "decision_matched")):
            value = getattr(verification, field, None)
            rendered = ("not checked" if not was_rederived else
                        "yes" if value is True else "no" if value is False else "unknown")
            lines.append(f"{title}: {rendered}")
        if rederived is None:
            lines.append("Re-derived decision: unavailable")
        else:
            derived_decision = getattr(rederived, "decision", None)
            lines.append(
                f"Re-derived decision: {label(getattr(derived_decision, 'decision', None))} · "
                f"reason={label(getattr(derived_decision, 'reason', None))}")
        return lines

    async def _execute_stored_plan(
        self, plan, runtime: AgentRuntime, origin: str, host_name: str,
        *, expected_context: str,
    ) -> None:
        """Execute only the plan explicitly reviewed against this host."""
        self._append(f"\n  Executing on {host_name}...", CYAN)
        try:
            execution = await runtime.execute(plan, expected_context=expected_context)
        except AuthorityContextChanged as e:
            self._append(
                f"  DENY before execution: {e} No step was submitted to the host; plan cleared.",
                RED)
            return
        except Exception as e:
            self._append(
                f"  Execution returned no status ({type(e).__name__}); the host outcome is unknown. "
                "Do not retry until host state or receipts are checked.", RED)
            return
        try:
            verifications = await asyncio.to_thread(runtime.verify_execution, execution)
        except Exception as e:
            verifications = {}
            self._append(
                f"  Receipt verification unavailable ({type(e).__name__}); allowed steps remain untrusted.",
                YELLOW)
        ok_count = deny_count = unknown_count = 0
        for step in execution.steps:
            receipt = step.receipt
            verification = verifications.get(step.index)
            verify_status = verification.status if verification else "NOT_VERIFIABLE"
            for line in self._receipt_audit_lines(receipt, verification):
                self._append(f"    {step.index}. {line}", MUTED)
            if step.allowed:
                result = receipt.result or {}
                evidence = getattr(receipt.evidence, "value", str(receipt.evidence))
                if evidence != "DEMONSTRATED" or (isinstance(result, dict) and result.get("error")):
                    unknown_count += 1
                    detail = result.get("error", "engine outcome is not demonstrated") if isinstance(result, dict) else "engine outcome is unknown"
                    self._append(
                        f"    {step.index}. ALLOW decision · UNKNOWN execution ({detail}) · receipt {receipt.receipt_id[:12]} · verify {verify_status}",
                        YELLOW)
                    continue
                if verify_status != "PASS":
                    unknown_count += 1
                    self._append(
                        f"    {step.index}. ALLOW decision · execution evidence not trusted · receipt {receipt.receipt_id[:12]} · verify {verify_status}",
                        RED if verify_status == "REJECT" else YELLOW)
                    continue
                ok_count += 1
                self._append(
                    f"    {step.index}. ALLOW — receipt {receipt.receipt_id[:12]} · verify PASS", GREEN)
                result = receipt.result or {}
                if origin == "local-read-only":
                    if isinstance(result, dict) and isinstance(result.get("text"), str):
                        preview = result["text"][:4000]
                        if len(result["text"]) > 4000:
                            preview += "\n… output truncated at 4,000 characters …"
                        self._append(f"       Read result:\n{preview}", TEXT)
                    elif isinstance(result, dict) and result.get("kind") == "directory":
                        self._append(
                            "       Directory listed. Use Files for the filtered browser view.", MUTED)
            else:
                deny_count += 1
                self._append(
                    f"    {step.index}. DENY — {receipt.decision.reason} · receipt {receipt.receipt_id[:12]} · verify {verify_status}",
                    YELLOW if verify_status == "PASS" else RED)
        if execution.stopped_at is not None:
            self._append(f"    Stopped at step {execution.stopped_at}: {execution.stop_reason}", YELLOW)
        self._append(
            f"\n  Done: {ok_count} demonstrated, {deny_count} denied, {unknown_count} unknown.", CYAN)
        if origin == "local-read-only":
            self._append("  Local read-only execution; write capabilities were removed from this runtime.", MUTED)
        else:
            self._append("  Demo execution only; real workspace writes are not enabled here.", MUTED)
