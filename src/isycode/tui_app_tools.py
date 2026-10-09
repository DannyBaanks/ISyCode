"""Chat tool dispatch, subagents, local MCP, and the iteration window.

Moved verbatim from tui.py. TUIApp inherits this mixin.
"""
from __future__ import annotations

from contextvars import ContextVar

_tool_display_context = ContextVar("tool_display_context", default=None)

import os
import asyncio
import json
import shlex
import uuid
from pathlib import Path
from isycode.config import ConfigurationError
from isycode.tool_history import record_tool_result, sanitize_historical_text, tool_history_context
from isycode.workspace_authority import WorkspaceAuthority, WorkspaceAuthorityError
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
from isycode.tui_theme import TEXT, MUTED, GREEN, YELLOW, RED, CYAN, _elapsed_label
from isycode.tui_widgets import ToolActivityGroup, ChatArea, SelectableText
from isycode.tui_composer import PromptArea
from isycode.tui_screens_approval import (
    TailscaleConfirmScreen, LocalMCPConfirmScreen, WorkspacePackConfirmScreen,
)
from isycode.tui_screens_sessions import AgentQuestionScreen


from isycode.providers import provider_supports_tools


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
        if (name not in TOOL_ACTIONS and name not in GIT_TOOL_NAMES
                and name not in {WRITE_TOOL_NAME, EDIT_TOOL_NAME, COMMAND_TOOL_NAME,
                                 DELETE_TOOL_NAME, MOVE_TOOL_NAME,
                                 TASK_TOOL_NAME, CONTEXT_ACCESS_TOOL_NAME,
                                 ASK_USER_TOOL_NAME, IDEA_BOX_TOOL_NAME, "update_session_title"}):
            outcome = {"error": "tool is not registered by ISyCode"}
            self._append("  Tool denied · unregistered tool name", YELLOW)
            return tool_call_id, json.dumps(outcome)
        if not isinstance(raw_arguments, str) or len(raw_arguments) > 64 * 1024:
            outcome = {"error": "tool arguments are malformed or too large"}
            self._append(f"  Tool denied · {name} · invalid arguments", YELLOW)
            return tool_call_id, json.dumps(outcome)
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            arguments = None
        if not isinstance(arguments, dict):
            outcome = {"error": "tool arguments must be a JSON object"}
            self._append(f"  Tool denied · {name} · invalid arguments", YELLOW)
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
            self._append(f"  Tool denied · {action_id} · authority/owner unavailable", YELLOW)
            return tool_call_id, json.dumps({"error": "ISyCode authorization or read owner unavailable"})
        if result.decision != "ALLOW" or result.receipt is None:
            reason = result.reason or result.decision
            self._append(f"  ✗ {summary} · {result.decision} · {reason[:180]}", YELLOW)
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
            self._set_activity("Chat ready", MUTED)
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
                f"{env_keys}.", shlex.join(preview.config.argv), "Start server")):
            self._append(f"  MCP {name} not started.", MUTED)
            return
        approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
        outcome = await mcp_owner.start(preview, approval)
        if outcome.decision == "ALLOW":
            tools = json.loads(outcome.text)["tools"]
            self._append(f"  MCP {name} started · {len(tools)} tools · receipt "
                         f"{outcome.receipt.receipt_id}", GREEN)
        else:
            self._append(f"  MCP {name} {outcome.decision} · {outcome.reason[:180]}", YELLOW)

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
                json.dumps(preview.arguments, ensure_ascii=False, indent=2), "Call once")):
            self._append("  MCP call rejected · nothing was sent", MUTED)
            return json.dumps({"status": "rejected_by_user"})
        outcome = await mcp_owner.call(preview, self._action_approvals.issue(preview.request, ttl_seconds=60))
        if outcome.decision != "ALLOW" or outcome.receipt is None:
            self._append(f"  MCP {outcome.decision} · {outcome.reason[:180]}", YELLOW)
            return json.dumps({"error": "MCP call did not run", "reason": outcome.reason[:300]})
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
