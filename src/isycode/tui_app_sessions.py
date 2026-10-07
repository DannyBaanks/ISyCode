"""Session, idea, queue, and harness methods for the ISyCode TUI.

Moved verbatim from tui.py. TUIApp inherits SessionMixin.
"""
from __future__ import annotations

import os
import asyncio
import json
from pathlib import Path
from typing import Any
from rich.cells import cell_len
from isycode.config import ConfigurationError
from isycode.chat_sessions import ChatSessionStore
from isycode.session_owner import MAX_MESSAGE_BYTES
from isycode.work_list import (
    WorkList,
    age_label,
    clock_label,
    fit_heading,
    preview_line,
)
from isycode.harness_graph import (
    CATALOG_IDS,
    copyable_default_model,
    present_by_semantic,
)
from isycode.harness_probe import (
    probe_catalog,
    unlock_dotfolder,
)
from isycode.harness_readers import read_harness_root
from isycode.harness_readers.transcript import (
    read_transcript,
    transcript_candidates,
)
from isycode.harness_copy import copy_default_model_selection
from isycode.throughput import ThroughputMeter
from isycode.usage import UsageLedger
from isycode.catalog import (
    ISYCODE_AGENTS,
    ISYCODE_SUBAGENTS,
    ISYCO_MOTORS,
)
from isycode.workspace_authority import (
    OneShotActionAuthority,
    WorkspaceAuthority,
    WorkspaceAuthorityError,
)
from isycode.file_picker import (
    FilePickerUnavailable,
    choose_harness_folder,
)
from isycode.harness_store import HarnessStore
from isycode.harness_probe import validate_picked_root
from isycode.action_runtime import SessionDeleteOwner
from isycode.idea_box import (
    IDEA_BOX_TOOL_NAME,
    IDEA_NUDGE_PREFIX,
    idea_nudge,
)
from isycode.authority_view import displayed_on
from isycode.security import ActionRequest
from textual.css.query import NoMatches
from textual.dom import NoScreen
from textual.widgets import (
    Static,
    Button,
    OptionList,
)
from textual.widgets.option_list import Option
from rich.text import Text
from rich.markdown import Markdown as RichMarkdown
from isycode.providers import (
    PRESETS,
    ProviderError,
    resolved_chat_model,
    selected_provider_name,
)
import time as _time
from isycode.tui_theme import (
    TEXT,
    MUTED,
    GREEN,
    YELLOW,
    CYAN,
    _fit_cells,
)
from isycode.conversation_lane import (
    ConversationLane,
    conversation_lane_context,
    lane_property,
    LANE_FIELDS,
    open_lane,
    rekey_lane,
)
from isycode.tui_widgets import (
    Collapsible,
    ChatArea,
    SelectableText,
    ThoughtBlock,
)
from isycode.tui_composer import (
    QueuedBox,
    PromptArea,
)
from isycode.tui_screens_approval import (
    ApprovalScreen,
    ContextAccessScreen,
    DeleteSessionScreen,
)
from isycode.tui_screens_harness import (
    HarnessFolderConfirmScreen,
    HarnessModelConfirmScreen,
    HarnessTranscriptConfirmScreen,
    HarnessComposeScreen,
    MultiHarnessScreen,
)
from isycode.tui_screens_sessions import (
    IdeaNoteScreen,
    AgentQuestionScreen,
)


class SessionMixin:
    """Chat sessions, the queue, the idea box, and harness import."""

    def _paint_queued_messages(self) -> None:
        if not self._lane_on_screen() or not self.is_mounted:
            return
        if self._selected_queued_message not in self._queued_messages:
            self._selected_queued_message = None
        base = self.screen_stack[0]
        base.query_one("#queued-row").display = bool(self._queued_messages)
        box = base.query_one("#queued-box", QueuedBox)
        selected = self._selected_queued_message
        preview = selected or (self._queued_messages[0] if self._queued_messages else "")
        box.title = f"Queued · {len(self._queued_messages)}" + (" · selected" if selected else "") + "     " + _fit_cells(" ".join(preview.split()), max(8, box.content_size.width - 25))
        listing = base.query_one("#queued-options", OptionList)
        listing.clear_options()
        listing.add_options([Option(_fit_cells(" ".join(text.split()), 80), id=str(index)) for index, text in enumerate(self._queued_messages)])

    def _select_queued_message(self, index: int) -> None:
        if 0 <= index < len(self._queued_messages):
            self._selected_queued_message = self._queued_messages[index]
            self._paint_queued_messages()

    def _steering_target(self) -> tuple[str, str]:
        if self._active_chat_provider is not None:
            return self._active_chat_provider
        provider = selected_provider_name()
        return provider, resolved_chat_model(provider)

    def _queue_steer_warning(self) -> None:
        from isycode.reasoning_options import steering_support
        provider, model = self._steering_target()
        support = steering_support(provider, model)
        label = self._model_display_label(provider, model)
        message = label + (" no permite steer" if support is False else " · soporte steer sin confirmar")
        self.screen_stack[0].query_one("#queue-warning", Static).update(Text(message, style=YELLOW))
        self.screen_stack[0].query_one("#queue-notice").display = True

    def _promote_queued_message(self) -> None:
        from isycode.reasoning_options import steering_support
        selected = self._selected_queued_message
        if selected is None or selected not in self._queued_messages:
            return
        prompt = self.screen_stack[0].query_one("#prompt-input", PromptArea)
        if prompt.text.strip():
            self.notify("Keep the draft; Send must be empty to steer a selected queued message", severity="warning")
            return
        if self._chat_turn_task is None or self._chat_turn_task.done():
            self._undo_queued_message()
            return
        provider, model = self._steering_target()
        if steering_support(provider, model) is False:
            self._queue_steer_warning()
            return
        if self._steering_try_active:
            self.notify("A steer attempt is still pending; this message stays queued")
            return
        previous = len(self._pending_steering)
        position = self._queued_messages.index(selected)
        self._accept_prompt(prompt, "/steer " + selected)
        if len(self._pending_steering) > previous:
            self._steering_restore_positions.setdefault(selected, []).append(position)
            self._queued_messages.remove(selected)
            self._selected_queued_message = None
            self.screen_stack[0].query_one("#queue-notice").display = False
            self._paint_queued_messages()

    def _return_steering_to_queue(self, instructions: list[str], *, unsupported: bool = False) -> None:
        from isycode.reasoning_options import record_steering_result
        for instruction in instructions:
            positions = self._steering_restore_positions.get(instruction, [])
            position = positions.pop(0) if positions else len(self._queued_messages)
            self._queued_messages.insert(min(position, len(self._queued_messages)), instruction)
        self._steering_try_active = False
        if unsupported:
            record_steering_result(*self._steering_target(), False)
        self._paint_queued_messages()
        if self._lane_on_screen():
            self._queue_steer_warning()
            if not unsupported:
                self.screen_stack[0].query_one("#queue-warning", Static).update(Text("Steer sin respuesta confirmada · mensaje devuelto a queued", style=YELLOW))
        self._append("Steer no soportado por provider · mensaje devuelto a queued; continuando el turno original." if unsupported else "Steer no confirmado · devuelto a queued.", YELLOW)

    def _undo_queued_message(self) -> None:
        selected = self._selected_queued_message
        if selected is None or selected not in self._queued_messages:
            return
        prompt = self.screen_stack[0].query_one("#prompt-input", PromptArea)
        if prompt.text:
            self.notify("Draft kept; queued message stays pending", severity="warning")
            return
        self._queued_messages.remove(selected)
        self._selected_queued_message = None
        prompt.load_text(selected)
        self._paint_queued_messages()
        prompt.focus()

    def on_session_option_list_delete_requested(self, event) -> None:
        event.stop()
        session_id = str(event.session_id)
        if session_id.startswith("iteration:"):
            self.run_worker(self._delete_iteration_session(session_id.removeprefix("iteration:")),
                            group="session-delete", exclusive=True)
            return
        self.run_worker(self._delete_chat_session(session_id, allow_once=True), group="session-delete", exclusive=True)

    def _session_state(self) -> dict:
        return {"provider": selected_provider_name(), "model": resolved_chat_model(),
                "role": ({"kind": self._active_role["kind"], "name": self._active_role["name"]}
                         if self._active_role else None),
                "context_path": "AGENTS.md" if self._agent_context and self._agent_context["path"] == "AGENTS.md" else None,
                "draft": self._draft_text,
                "tool_history": self._tool_history,
                "conversation_summary": self._conversation_summary,
                "idea_box": self._idea_box,
                "usage": self._usage.to_state()}

    def _open_idea_note(self) -> None:
        self.push_screen(IdeaNoteScreen(self._idea_box or "Capture an idea · Ctrl+Shift+Enter"))

    def _paint_idea_box(self) -> None:
        if not self._lane_on_screen() or not self.is_mounted:
            return
        for screen in self.screen_stack:
            if isinstance(screen, IdeaNoteScreen) and screen.is_mounted:
                screen.query_one("#idea-note-content", Static).update(
                    Text(self._idea_box or "Capture an idea · Ctrl+Shift+Enter"))
        try:
            box = self.screen_stack[0].query_one("#idea-box", Static)
        except NoMatches:
            return
        body = self._idea_box or "Capture an idea · Ctrl+Shift+Enter"
        busy = self._loop_task is not None and not self._loop_task.done()
        label = "Idea box · ● Thinking…" if busy else "Idea box"
        heading = Text(label, style="bold #c7b8d4")
        try:
            name = selected_provider_name()
            model = resolved_chat_model(name)
            from isycode.model_presentation import model_display_name
            from isycode.reasoning_options import reasoning_label
            preset = PRESETS.get(name, {})
            suffix = f" / {reasoning_label(name, model, preset.get('reasoning_effort')).capitalize()} · {preset.get('label', name)}"
            available = box.content_size.width - cell_len(label) - 5
            model_name = model_display_name(model)
            if box.content_size.width and available > cell_len(suffix):
                model_name = _fit_cells(model_name, available - cell_len(suffix))
            heading.append("     " + model_name + suffix, style=CYAN)
        except (ConfigurationError, ProviderError):
            pass
        if box.content_size.width:
            heading.truncate(box.content_size.width, overflow="ellipsis")
        heading.append("\n")
        heading.append(body, style=TEXT)
        box.update(heading)

    def _mark_idea_nudge_due(self) -> None:
        self._idea_nudge_due = True

    def _apply_idea_nudge(self, messages: list[dict], chat_tools: list[dict] | None) -> None:
        if not self._idea_nudge_due or not chat_tools:
            return
        names = {
            tool.get("function", {}).get("name")
            for tool in chat_tools if isinstance(tool, dict)
        }
        if IDEA_BOX_TOOL_NAME not in names:
            return
        messages[:] = [
            message for message in messages
            if not (message.get("role") == "system"
                    and isinstance(message.get("content"), str)
                    and message["content"].startswith(IDEA_NUDGE_PREFIX))
        ]
        messages.insert(1, {"role": "system", "content": idea_nudge(self._idea_box)})
        self._idea_nudge_due = False

    def _send_next_queued_message(self) -> None:
        if self._loop_task is not None or not self._queued_messages:
            return
        if len(self.screen_stack) > 1:
            self.set_timer(0.25, self._send_next_queued_message)
            return
        text = self._queued_messages[0]
        try:
            self._image_attachments.prepare([{"role": "user", "content": text}], selected_provider_name(), resolved_chat_model(selected_provider_name()))
        except ValueError as exc:
            self.notify("Queue paused · " + str(exc), severity="warning")
            return
        self._queued_messages.pop(0)
        self._paint_queued_messages()
        prompt = self.query_one("#prompt-input", PromptArea)
        current_draft = prompt.text
        self._accept_prompt(prompt, text)
        if current_draft and not prompt.text:
            prompt.load_text(current_draft)

    def _sessions_enabled(self) -> bool:
        """Saving needs a recurring workspace owner plus both session grants."""
        if self._chat_session_owner is None:
            return False
        try:
            grants = WorkspaceAuthority(self._workspace_root).effective_policy().get("grants", {})
        except (WorkspaceAuthorityError, OSError, ValueError):
            return False
        return all(displayed_on(action, grants.get(action, {}))
                   for action in ("session.create", "session.resume"))

    def _show_chat_again(self) -> None:
        self.query_one("#work-list").display = False
        self.query_one("#chat").display = True

    def _conversation_row(self, session) -> dict[str, str]:
        last = session.messages[-1] if session.messages else {}
        sent = last.get("sent_at") if isinstance(last, dict) else None
        return {
            "id": session.session_id,
            "workspace": self._workspace_root.name,
            "title": session.title,
            "preview": preview_line(last.get("content") if isinstance(last, dict) else ""),
            "detail": str(last.get("content", "")) if isinstance(last, dict) else "",
            "model": str(session.state.get("model") or ""),
            "provider": str(session.state.get("provider") or ""),
            "age": age_label(sent or session.updated_at),
            "status": "idle",
        }

    async def _show_chat_sessions(self) -> None:
        self.query_one("#chat").display = False
        self.query_one("#work-list", WorkList).display = True
        await self._refresh_work_list()
        self.query_one("#work-conversations", OptionList).focus()

    def _harness_store(self) -> HarnessStore:
        return HarnessStore()

    async def _choose_harness_root(self, harness_id: str) -> bool:
        if harness_id not in CATALOG_IDS:
            return False
        label = harness_id.title()
        try:
            candidate = await choose_harness_folder(
                Path.home(), title=f"Choose the folder for {label}")
            if candidate is None:
                return False
            safe_root = validate_picked_root(candidate)
        except (FilePickerUnavailable, OSError, ValueError) as exc:
            self._set_activity(f"Folder selection for {label} failed · {str(exc)[:120]}", YELLOW)
            return False
        if not await self._await_screen(HarnessFolderConfirmScreen(harness_id, safe_root)):
            return False
        try:
            await asyncio.to_thread(self._harness_store().set_root, harness_id, safe_root)
        except (OSError, ValueError) as exc:
            self._set_activity(f"Multi Harness folder not saved · {str(exc)[:120]}", YELLOW)
            return False
        self._set_activity(f"Multi Harness · {label} folder saved", GREEN)
        return True

    async def _copy_harness_default_model(self, provider_id: str, model_id: str) -> bool:
        if not copyable_default_model(provider_id, model_id, preset_ids=set(PRESETS)):
            return False
        if not await self._await_screen(HarnessModelConfirmScreen(provider_id, model_id)):
            return False
        try:
            provider, model = await asyncio.to_thread(
                copy_default_model_selection, provider_id, model_id)
        except (OSError, ValueError):
            self._set_activity("Multi Harness model selection was not saved", YELLOW)
            return False
        self._provider_env_override = True
        self._model_env_override = True
        if self.screen_stack:
            self._paint_idea_box()
        self._set_activity("Model selection saved · " + self._model_display_label(provider, model), GREEN)
        return True

    async def _import_harness_transcript(
            self, harness_id: str, root: Path, relative_path: str) -> bool:
        if self._loop_task is not None and not self._loop_task.done():
            self._set_activity("Still working · finish or cancel the current reply first.", YELLOW)
            return False
        if harness_id not in CATALOG_IDS:
            return False
        if not await self._await_screen(HarnessTranscriptConfirmScreen(harness_id, relative_path)):
            return False
        try:
            transcript = await asyncio.to_thread(read_transcript, root, relative_path)
        except (OSError, ValueError) as exc:
            self._set_activity(f"Transcript copy failed · {str(exc)[:160]}", YELLOW)
            return False
        return await self._apply_harness_transcript(harness_id, transcript)

    async def _apply_harness_transcript(
            self, harness_id: str, transcript: TranscriptCopy) -> bool:
        label = harness_id.title()
        copied_label = (
            f"Copied transcript from {label}. This is a copy of text, not the same process "
            "and not the same agent."
        )
        messages = ({"role": "user", "content": copied_label}, *transcript.messages)
        saving = self._sessions_enabled()
        owner = self._chat_session_owner if saving else None
        if saving and owner is None:
            self._set_activity("Transcript copy could not access the conversation owner.", YELLOW)
            return False

        for item in messages:
            role = item.get("role")
            content = item.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                continue
            content = ChatSessionStore._sanitize_text(content)
            self._history.append({"role": role, "content": content})
            if role == "user":
                self._mount_user_turn(content)
            else:
                chat = self.query_one(ChatArea)
                chat.mount(SelectableText(
                    RichMarkdown(content, code_theme="monokai"),
                    selection_text=content,
                ))
                chat.follow_tail()

            if not saving:
                continue
            outcome, session_id = owner.record(
                self._active_chat_session_id, role, content, state=None)
            if outcome.decision != "ALLOW":
                self._set_activity(f"Transcript copy stopped · {outcome.reason[:160]}", YELLOW)
                return False
            if session_id is None:
                self._set_activity("Transcript copy stopped · session id was not returned.", YELLOW)
                return False
            self._active_chat_session_id = session_id

        self._set_activity(
            f"Copied transcript from {label} · {len(transcript.messages)} messages", GREEN)
        return True

    async def _multi_harness_snapshot(self) -> tuple[list[dict[str, Any]], int]:
        probes = await probe_catalog()
        roots: dict[str, Path] = {}
        automatic_roots: dict[str, bool] = {}
        try:
            picked_roots = self._harness_store().roots()
        except (OSError, ValueError):
            picked_roots = {}
        for harness_id in CATALOG_IDS:
            result = probes[harness_id]
            root = None
            automatic = True
            picked = picked_roots.get(harness_id)
            if picked is not None:
                try:
                    root = validate_picked_root(picked)
                    automatic = False
                except ValueError:
                    root = None
            if root is None:
                root = unlock_dotfolder(result)
                automatic = True
            if root is None:
                continue
            roots[harness_id] = root
            automatic_roots[harness_id] = automatic

        read_results: dict[str, tuple[list[Any], list[Any]]] = {}
        transcript_results: dict[str, list[str]] = {}
        if roots:
            harness_ids = list(roots)
            values = await asyncio.gather(*(
                asyncio.to_thread(
                    read_harness_root, harness_id, roots[harness_id],
                    automatic=automatic_roots[harness_id])
                for harness_id in harness_ids
            ), return_exceptions=True)
            for harness_id, value in zip(harness_ids, values):
                if not isinstance(value, Exception):
                    read_results[harness_id] = value
            transcript_values = await asyncio.gather(*(
                asyncio.to_thread(transcript_candidates, harness_id, roots[harness_id])
                for harness_id in harness_ids
            ), return_exceptions=True)
            for harness_id, value in zip(harness_ids, transcript_values):
                if not isinstance(value, Exception):
                    transcript_results[harness_id] = value

        all_settings = [
            setting
            for settings, _ in read_results.values()
            for setting in settings
        ]
        present = present_by_semantic(all_settings)
        sections: list[dict[str, Any]] = []
        for harness_id in CATALOG_IDS:
            probe = probes[harness_id]
            settings, skipped = read_results.get(harness_id, ([], []))
            rendered = []
            for setting in settings:
                rendered.append({
                    "semantic_id": setting.semantic_id,
                    "pointer": setting.pointer,
                    "edge": setting.edge,
                    "display_value": setting.display_value,
                    "n": len(present.get(setting.semantic_id, set())) if setting.semantic_id else 0,
                    "counts_toward_n": setting.counts_toward_n,
                    "provider_id": setting.provider_id,
                    "model_id": setting.model_id,
                    "copyable": (
                        not automatic_roots.get(harness_id, True)
                        and
                        setting.semantic_id == "default_model"
                        and setting.edge == "same"
                        and copyable_default_model(
                            setting.provider_id, setting.model_id, preset_ids=set(PRESETS))
                    ),
                })
            sections.append({
                "harness_id": harness_id,
                "checking": False,
                "unlocked": harness_id in roots and harness_id in read_results,
                "automatic": automatic_roots.get(harness_id, True),
                "root": str(roots[harness_id]) if harness_id in roots else "",
                "version_line": probe.version_line,
                "settings": rendered,
                "skipped_count": len(skipped),
                "transcript_sources": transcript_results.get(harness_id, []),
            })

        transcript_count = 0
        owner = self._chat_session_owner
        if owner is not None and self._sessions_enabled():
            outcome, sessions = await asyncio.to_thread(owner.list_conversations)
            if outcome.decision == "ALLOW":
                transcript_count = len(sessions)
        return sections, transcript_count

    async def _show_multi_harness(self) -> None:
        while True:
            screen = MultiHarnessScreen()

            async def load() -> None:
                try:
                    sections, transcript_count = await self._multi_harness_snapshot()
                except (OSError, RuntimeError, ValueError):
                    sections = [
                        {"harness_id": harness_id, "checking": False,
                         "unlocked": False, "settings": []}
                        for harness_id in CATALOG_IDS
                    ]
                    transcript_count = 0
                screen.update_snapshot(sections, transcript_count)

            loader = asyncio.create_task(load())
            try:
                selected = await self._await_screen(screen)
            finally:
                if not loader.done():
                    loader.cancel()
                await asyncio.gather(loader, return_exceptions=True)
            if selected is None:
                return
            if selected.startswith("compose:"):
                from isycode.harness_graph import repair_compose
                semantic_id = selected.removeprefix("compose:")
                row = next(item for item in screen._gap_rows() if item["semantic_id"] == semantic_id)
                brief = repair_compose(semantic_id, row["harnesses"])
                if await self._await_screen(HarnessComposeScreen(brief)):
                    await self._request_clipboard_copy(brief, "selection")
                continue
            if selected.startswith("copy:"):
                harness_id = selected.removeprefix("copy:")
                identity = screen.copyable_models.get(harness_id)
                if identity is not None:
                    await self._copy_harness_default_model(*identity)
                continue
            if selected.startswith("transcript:"):
                harness_id = selected.removeprefix("transcript:")
                source = screen.transcript_sources.get(harness_id)
                if source is not None:
                    root, relative_path = source
                    await self._import_harness_transcript(harness_id, Path(root), relative_path)
                continue
            await self._choose_harness_root(selected)

    def _conversation_status(self) -> str:
        if isinstance(self.screen, (ApprovalScreen, ContextAccessScreen, AgentQuestionScreen)):
            return "waiting"
        return "generating" if self._loop_task and not self._loop_task.done() else "idle"

    def _paint_work_status(self) -> None:
        try:
            panel = self.screen_stack[0].query_one("#work-list", WorkList)
            if not panel.display:
                return
            for row in self._work_rows:
                row["current"] = row["id"] == (self._active_chat_session_id or "memory")
                if row.get("session_kind") != "iterative":
                    if row["current"]:
                        row["status"] = self._conversation_status()
                    else:
                        other = self._lanes.get(row["id"])
                        live = other is not None and other.loop_task is not None and not other.loop_task.done()
                        row["status"] = "generating" if live else "idle"
            rows = list(self._work_rows)
            if self._subagent_running:
                rows.append({"id": "child", "workspace": self._workspace_root.name,
                             "title": self._child_title or "Child", "preview": preview_line(self._child_task),
                             "age": "now", "status": "generating", "current": False})
            idle = sum(row["status"] == "idle" for row in rows)
            working = sum(row["status"] == "generating" for row in rows)
            tail = f"{idle} idle" + (f" · {working} working" if working else "")
            panel.show_rows(rows, heading=fit_heading(str(self._workspace_root), tail,
                                                      self._idle_content_width()))
        except (NoMatches, NoScreen):
            return

    async def _refresh_work_list(self) -> None:
        if self._work_refresh_busy:
            return
        self._work_refresh_busy = True
        try:
            sessions = []
            owner = self._chat_session_owner
            if owner is not None and self._sessions_enabled():
                outcome, sessions = await asyncio.to_thread(owner.list_conversations)
                if outcome.decision != "ALLOW":
                    self._set_activity("Conversations unavailable · " + outcome.reason[:100], YELLOW)
            self._work_rows = [self._conversation_row(session) for session in sessions]
            if self._sessions_enabled():
                from isycode.iteration import IterationOwner
                try:
                    iterations = await asyncio.to_thread(self._iteration_owner().list_sessions)
                    for item in iterations:
                        self._work_rows.append({"id": "iteration:" + item["iteration_session_id"],
                            "title": item["title"], "session_kind": "iterative",
                            "model": item["participants"][0]["model"] if item["participants"] else "",
                            "provider": item["participants"][0]["provider"] if item["participants"] else "",
                            "workspace": self._workspace_root.name,
                            "status": "generating" if item["status"] == "RUNNING" else "waiting" if item["status"] == "WAITING_FOR_HUMAN" else "idle",
                            "age": age_label(item["created_at"]),
                            "detail": " → ".join(self._model_display_label(p["provider"], p["model"]) for p in item["participants"]) + "\n" + item["status"] + "\n\n" + (item["turns"][-1]["content"] if item["turns"] else "")})
                except (OSError, RuntimeError, ValueError):
                    self._set_activity("Iteration sessions unavailable; ordinary sessions preserved.", YELLOW)
            if not self._active_chat_session_id:
                self._work_rows.insert(0, {"id": "memory", "workspace": self._workspace_root.name,
                                          "title": "Current conversation", "preview": "",
                                          "age": "", "status": "idle"})
            self._paint_work_status()
        finally:
            self._work_refresh_busy = False

    async def _legacy_chat_sessions_menu(self) -> None:
        owner = self._chat_session_owner
        if owner is None:
            self._append("  Only recurring workspaces keep conversations; this run stays in memory.",
                         MUTED)
            return
        if not self._sessions_enabled():
            self._append("  Saving conversations is off · turn it on in Settings → Authority.", MUTED)
            return
        outcome, sessions = await asyncio.to_thread(owner.list_conversations)
        if outcome.decision != "ALLOW":
            self._append(f"  Conversations unavailable · {outcome.reason[:180]}", YELLOW)
            return
        entries = [self._entry("Start a new conversation", "chat_session_new", "")]
        for session in sessions[:50]:
            when = _time.strftime("%Y-%m-%d %H:%M", _time.localtime(session.updated_at))
            current = " · current" if session.session_id == self._active_chat_session_id else ""
            entries.append(self._entry(
                f"{session.title} · {len(session.messages)} messages · {when}{current}",
                "chat_session_resume", session.session_id))
        if not sessions:
            entries.append(self._entry("No saved conversations yet", "info"))
        entries.append(self._entry("Back", "settings_back", ""))
        self._menu_stack = []
        self._render_menu("chat_sessions", "Conversations", entries)

    def _clear_open_conversation(self) -> None:
        """Drop the open chat. Does not create or delete a saved session."""
        lane = self._foreground_lane()
        self.query_one("#prompt-input", PromptArea).load_text("")
        self._draft_text = ""
        self._retry_prompt = None
        self._history = []
        self._tool_history = []
        self._idea_box = ""
        self._idea_nudge_due = False
        self._paint_idea_box()
        self._usage = UsageLedger()
        self._throughput = ThroughputMeter()
        self._refresh_usage()
        self._conversation_summary = ""
        self._show_agent_tasks([])
        self._active_chat_session_id = None
        self._session_save_warned = False
        lane.lines.clear()
        lane.partial = ""
        lane.partial_reason = ""
        lane.stream_widget = None
        lane.stream_block = None
        self.query_one(ChatArea).remove_children()
        self._show_chat_again()
        self._mount_idle_board()

    def _start_new_conversation(self) -> None:
        current = self._foreground_lane()
        busy = current.loop_task is not None and current.loop_task is not asyncio.current_task() and not current.loop_task.done()
        if not busy and not current.history and not current.lines and not current.session_id:
            self._show_chat_again()
            self._append("  New conversation.", MUTED)
            if self._sessions_enabled() and self._chat_session_owner is not None:
                outcome, sid = self._chat_session_owner.manage(
                    "state", None, json.dumps(self._session_state()))
                if outcome.decision == "ALLOW":
                    self._active_chat_session_id = sid
            self.run_worker(self._refresh_work_list(), group="work-list")
            return
        self._capture_running_session()
        self._show_lane(open_lane(self, None))
        self._append("  New conversation.", MUTED)
        if self._sessions_enabled() and self._chat_session_owner is not None:
            outcome, sid = self._chat_session_owner.manage("state", None, json.dumps(self._session_state()))
            if outcome.decision == "ALLOW":
                self._active_chat_session_id = sid
        self.run_worker(self._refresh_work_list(), group="work-list")

    async def _resume_chat_session(self, session_id: str) -> None:
        if session_id.startswith("iteration:"):
            try:
                state = await asyncio.to_thread(self._iteration_owner().inspect, session_id.removeprefix("iteration:"))
                self._show_chat_again()
                self._show_iteration_state(state)
            except (OSError, RuntimeError, ValueError):
                self._append("Iteration unavailable or denied.", YELLOW)
            return
        owner = self._chat_session_owner
        if owner is None or not self._sessions_enabled():
            self._append("  Saving conversations is off; nothing was resumed.", MUTED)
            return
        current_id = self._active_chat_session_id or self._foreground_key
        if session_id == current_id:
            self._show_chat_again()
            return
        existing = self._lanes.get(session_id)
        if existing is not None and (
            (existing.loop_task is not None and not existing.loop_task.done())
            or existing.lines or existing.history
        ):
            self._capture_running_session()
            self._show_lane(existing)
            await self._refresh_work_list()
            return
        self._capture_running_session()
        outcome, session = await asyncio.to_thread(owner.resume, session_id)
        if outcome.decision != "ALLOW" or session is None:
            self._append(f"  Conversation not resumed · {outcome.reason[:180]}", YELLOW)
            return
        lane = open_lane(self, session.session_id)
        lane.history = [{"role": message["role"], "content": message["content"]}
                        for message in session.messages]
        lane.session_save_warned = False
        state = session.state if isinstance(session.state, dict) else {}
        lane.tool_history = list(state.get("tool_history", []))
        lane.conversation_summary = state.get("conversation_summary", "")
        lane.idea_box = state.get("idea_box", "")
        lane.usage = UsageLedger.from_state(state["usage"]) if "usage" in state else UsageLedger()
        lane.throughput = ThroughputMeter()
        if "usage" not in state and session.messages:
            lane.usage.record(None)
        lane.retry_prompt = None
        lane.draft_text = state.get("draft", "")
        lane.partial = ""
        lane.partial_reason = ""
        lane.stream_widget = None
        lane.stream_block = None
        lane.lines = []
        for message in session.messages:
            if message["role"] == "user":
                lane.lines.append(("user", message["content"], message.get("sent_at")))
            elif message["role"] == "assistant":
                lane.lines.append(("assistant", message["content"], message.get("sent_at")))
        self._show_lane(lane)
        if state.get("provider") and not self._provider_env_override:
            os.environ["ISYCODE_PROVIDER"] = state["provider"]
        if state.get("model") and not self._model_env_override and not self._provider_env_override:
            os.environ["ISYCODE_MODEL"] = state["model"]
        self._active_role = None
        role = state.get("role")
        if role:
            catalogs = {"agents": ISYCODE_AGENTS, "subagents": ISYCODE_SUBAGENTS, "motors": ISYCO_MOTORS}
            selected = next((item for item in catalogs.get(role["kind"], ())
                             if item.get("name") == role["name"]), None)
            if selected:
                self._active_role = {**selected, "kind": role["kind"]}
        self.query_one("#role-button", Button).label = self._role_button_label()
        self._agent_context = None
        self.query_one("#context-button", Button).label = "Context"
        if state.get("context_path"):
            await self._load_project_context()
        self._append(f"  Conversation reopened · {session.title} · {len(session.messages)} messages", GREEN)
        await self._refresh_work_list()

    async def _delete_chat_session(self, session_id: str, *, allow_once: bool = False) -> None:
        owner = self._chat_session_owner
        if owner is None:
            return
        outcome, session = owner.resume(session_id)
        if session is None:
            self._append(f"  Conversation unavailable · {outcome.reason[:160]}", YELLOW)
            return
        authority = WorkspaceAuthority(self._workspace_root)
        grant = authority.effective_policy().get("grants", {}).get("session.delete", {})
        if not allow_once and (not grant.get("enabled") or session_id not in grant.get("targets", [])):
            self._append("  Enable Delete current conversation in Settings → Authority first.", YELLOW)
            return
        if not await self._await_screen(DeleteSessionScreen(session.title)):
            self._append("  Conversation kept.", MUTED)
            return
        request = ActionRequest("session.delete", self._workspace_root, session_id,
                                {"session_id": session_id, "title": session.title[:80]},
                                execution_owner="session_delete")
        approval = self._action_approvals.issue(request, ttl_seconds=30)
        if not grant.get("enabled") or session_id not in grant.get("targets", []):
            authority = OneShotActionAuthority(authority, request)
        delete_owner = SessionDeleteOwner(self._workspace_root, authority, owner.store, self._action_approvals)
        result = delete_owner.delete(session_id, session.title, approval)
        self._append(f"  Conversation deletion · {result.decision} · {result.reason[:160]}", MUTED)
        if result.decision == "ALLOW":
            if self._active_chat_session_id == session_id:
                lane = self._foreground_lane()
                task = lane.chat_turn_task if lane.chat_turn_task is not None and not lane.chat_turn_task.done() else lane.loop_task
                lane.loop_task = None
                lane.chat_turn_task = None
                lane.chat_request_task = None
                if task is not None and not task.done():
                    task.cancel()
                self._clear_open_conversation()
            else:
                self._drop_background_lane(session_id)
            self.run_worker(self._refresh_work_list(), group="work-list")

    async def _delete_iteration_session(self, session_id: str) -> None:
        """Remove one iteration ledger after the same one-use session.delete gate."""
        from isycode.iteration import IterationLedger
        row = next((item for item in getattr(self, "_work_rows", [])
                    if item.get("id") == "iteration:" + session_id), None)
        title = str((row or {}).get("title") or "Iteration")
        if not await self._await_screen(DeleteSessionScreen(title, kind="iteration")):
            self._append("  Iteration kept.", MUTED)
            return
        authority = WorkspaceAuthority(self._workspace_root)
        grant = authority.effective_policy().get("grants", {}).get("session.delete", {})
        shown = title[:80]
        request = ActionRequest("session.delete", self._workspace_root, session_id,
                                {"session_id": session_id, "title": shown},
                                execution_owner="session_delete")
        approval = self._action_approvals.issue(request, ttl_seconds=30)
        if not grant.get("enabled") or session_id not in grant.get("targets", []):
            authority = OneShotActionAuthority(authority, request)
        ledger = IterationLedger(self._iteration_owner())
        delete_owner = SessionDeleteOwner(
            self._workspace_root, authority, ledger, self._action_approvals)
        result = delete_owner.delete(session_id, shown, approval)
        reason = ledger.error or result.reason
        self._append(f"  Iteration deletion · {result.decision} · {reason[:160]}",
                     GREEN if result.decision == "ALLOW" else YELLOW)
        if result.decision == "ALLOW":
            self.run_worker(self._refresh_work_list(), group="work-list")

    def _persist_chat_message(self, role: str, content: str, *, sent_at: str | None = None) -> None:
        """Save one message through the owner when this workspace saves conversations."""
        owner = self._chat_session_owner
        if owner is None or not self._sessions_enabled():
            return
        state = self._session_state()
        outcome, session_id = owner.record(
            self._active_chat_session_id, role, content, state=state, sent_at=sent_at)
        if session_id is not None:
            self._active_chat_session_id = session_id
        if outcome.decision != "ALLOW" and not self._session_save_warned:
            self._session_save_warned = True
            self._append(f"  Conversation not saved · {outcome.reason[:160]}", YELLOW)

    async def _manage_sessions(self, argument: str) -> None:
        """Lifecycle UI through typed slash commands; no unowned filesystem export."""
        operation, _, data = argument.strip().partition(" ")
        if not operation or operation == "list":
            await self._show_chat_sessions()
            return
        if operation == "new":
            self._start_new_conversation()
            return
        owner = self._chat_session_owner
        if owner is None or not self._sessions_enabled():
            self._append("  Session management needs a recurring workspace and session permissions.", YELLOW)
            return
        sid = self._active_chat_session_id
        if operation == "resume":
            await self._resume_chat_session(data.strip())
            return
        if operation == "search":
            outcome, sessions = owner.list_conversations()
            if outcome.decision == "ALLOW":
                terms = data.casefold().split()
                for session in sessions:
                    haystack = (session.title + " " + " ".join(m["content"] for m in session.messages)).casefold()
                    if all(term in haystack for term in terms):
                        self._append(f"  {session.session_id} · {session.title}", MUTED)
            else:
                self._append(f"  Search unavailable · {outcome.reason[:160]}", YELLOW)
            return
        if operation == "export" and sid:
            outcome, serialized = owner.export(sid)
            if serialized is not None:
                self._append("  Portable session JSON · common secret patterns redacted; review before sharing:", YELLOW)
                self._append(serialized, MUTED)
            else:
                self._append(f"  Export denied · {outcome.reason[:160]}", YELLOW)
            return
        if operation == "delete" and sid:
            await self._delete_chat_session(sid)
            return
        if operation in {"rename", "fork", "import"} and (sid or operation == "import"):
            outcome, changed = owner.manage(operation, sid if operation != "import" else None, data)
            if changed and outcome.decision == "ALLOW":
                self._append(f"  Session {operation} completed · {changed}", GREEN)
                if operation in {"fork", "import"}:
                    await self._resume_chat_session(changed)
            else:
                self._append(f"  Session unchanged · {outcome.reason[:180]}", YELLOW)
            return
        self._append("  /sessions list|new|resume ID|search TEXT|rename TITLE|fork|export|import JSON|delete", MUTED)

    def _install_conversation_lanes(self) -> None:
        if getattr(self, "_lanes", None):
            return
        self._lanes = {"memory": ConversationLane("memory")}
        self._foreground_key = "memory"

    def _foreground_lane(self) -> ConversationLane:
        lane = self._lanes.get(self._foreground_key)
        if lane is None:
            lane = ConversationLane(self._foreground_key)
            self._lanes[self._foreground_key] = lane
        return lane

    def _active_lane(self) -> ConversationLane:
        pinned = conversation_lane_context.get()
        if pinned is not None:
            return pinned
        return self._foreground_lane()

    def _lane_on_screen(self) -> bool:
        if not getattr(self, "_lanes", None):
            return True
        return self._active_lane().key == self._foreground_key

    @property
    def _active_chat_session_id(self):
        if not getattr(self, "_lanes", None):
            return None
        return self._active_lane().session_id

    @_active_chat_session_id.setter
    def _active_chat_session_id(self, value) -> None:
        if not getattr(self, "_lanes", None):
            return
        rekey_lane(self, self._active_lane(), value)

    def _pin_task(self, coroutine, lane=None):
        lane = lane or self._foreground_lane()
        token = conversation_lane_context.set(lane)
        try:
            return asyncio.create_task(coroutine)
        finally:
            conversation_lane_context.reset(token)

    def _start_background_turn(self, lane, text: str) -> None:
        task = self._pin_task(self._run_chat(text), lane)
        lane.loop_task = task
        lane.activity_message = "Chat · working"
        lane.activity_color = CYAN
        task.add_done_callback(self._operation_finished)

    def _copy_composer_draft(self) -> None:
        try:
            prompt = self.query_one("#prompt-input", PromptArea)
        except (NoMatches, NoScreen):
            return
        text = prompt.text
        pasted = getattr(prompt, "pasted_text", None)
        if pasted is not None:
            text = pasted.expand(text)
        self._foreground_lane().draft_text = text

    def _ensure_lane_session(self) -> None:
        if self._active_chat_session_id or not self._sessions_enabled() or self._chat_session_owner is None:
            return
        try:
            outcome, sid = self._chat_session_owner.manage(
                "state", None, json.dumps(self._session_state()))
        except (OSError, ValueError):
            return
        if getattr(outcome, "decision", None) == "ALLOW" and sid:
            self._active_chat_session_id = sid
            if getattr(self, "is_running", False):
                self.run_worker(self._refresh_work_list(), group="work-list")

    def _capture_running_session(self) -> None:
        self._copy_composer_draft()
        lane = self._foreground_lane()
        if lane.loop_task is not None and not lane.loop_task.done():
            self._ensure_lane_session()
        self._save_draft()

    def _show_lane(self, lane) -> None:
        current = self._foreground_lane()
        if current is not lane:
            self._copy_composer_draft()
            current.stream_widget = None
            current.stream_block = None
            self._foreground_key = lane.key
        self._show_chat_again()
        self._repaint_conversation()
        try:
            prompt = self.query_one("#prompt-input", PromptArea)
            prompt.load_text(lane.draft_text or "")
        except (NoMatches, NoScreen):
            pass
        self._paint_idea_box()
        self._refresh_usage()
        self._paint_queued_messages()
        self._show_agent_tasks(list(lane.agent_tasks))
        self._sync_visible_activity(lane)

    def _sync_visible_activity(self, lane) -> None:
        live = lane.loop_task is not None and not lane.loop_task.done()
        if live:
            self._activity_label = lane.activity_message or "Chat · working"
            self._activity_frame = getattr(self, "_activity_frame", 0)
            if getattr(self, "_activity_timer", None) is None:
                self._activity_timer = self.set_interval(0.12, self._animate_activity)
            self._animate_activity()
            return
        timer = getattr(self, "_activity_timer", None)
        if timer is not None:
            timer.stop()
            self._activity_timer = None
        if getattr(self, "_idea_nudge_timer", None) is not None:
            self._idea_nudge_timer.stop()
            self._idea_nudge_timer = None
        self._set_activity(lane.activity_message or "Chat ready", lane.activity_color or MUTED)

    def _repaint_conversation(self) -> None:
        try:
            chat = self.query_one(ChatArea)
        except (NoMatches, NoScreen):
            return
        chat.remove_children()
        lane = self._foreground_lane()
        if not lane.lines and not lane.partial and not lane.partial_reason and not lane.tool_history:
            self._mount_idle_board()
            return
        for kind, text, extra in list(lane.lines):
            if kind == "user":
                if clock_label(extra):
                    chat.mount(Static(Text(clock_label(extra), style=MUTED), classes="message-clock"))
                chat.mount(SelectableText(Text(text, style=TEXT), selection_text=text, classes="user-turn"))
            elif kind == "assistant":
                if clock_label(extra):
                    chat.mount(Static(Text(clock_label(extra), style=MUTED), classes="message-clock"))
                chat.mount(SelectableText(
                    RichMarkdown(text or "", code_theme="monokai"), selection_text=text or ""))
            elif kind == "note":
                chat.mount(SelectableText(Text(text, style=extra or TEXT), selection_text=text))
        if lane.tool_history:
            history_text = (
                "Earlier tool notes. They may be stale. No tool was run again.\n\n"
                + "\n\n".join(
                    f"{index}. {event.get('name', '')}\n"
                    f"Arguments: {event.get('arguments', '')}\n"
                    f"Result:\n{event.get('result', '')}"
                    for index, event in enumerate(lane.tool_history, start=1)
                )
            )
            chat.mount(Collapsible(
                Static(Text(history_text, style=MUTED)),
                title=f"Earlier tools · {len(lane.tool_history)} · not run again",
                collapsed=True,
                classes="tool-history",
            ))
        if lane.partial_reason:
            block = ThoughtBlock()
            block.set_text(lane.partial_reason)
            chat.mount(block)
            lane.stream_block = block
        else:
            lane.stream_block = None
        if lane.partial:
            widget = SelectableText(
                RichMarkdown(lane.partial, code_theme="monokai"), selection_text=lane.partial)
            chat.mount(widget)
            lane.stream_widget = widget
        else:
            lane.stream_widget = None
        chat.follow_tail()

    def _drop_background_lane(self, session_id: str) -> None:
        lane = self._lanes.get(session_id)
        if lane is None or lane.key == self._foreground_key:
            return
        task = lane.chat_turn_task if lane.chat_turn_task is not None and not lane.chat_turn_task.done() else lane.loop_task
        lane.loop_task = None
        lane.chat_turn_task = None
        lane.chat_request_task = None
        if task is not None and not task.done():
            task.cancel()
        self._lanes.pop(lane.key, None)

    def _session_message_rows(self, sessions) -> list[dict]:
        rows = []
        seen = set()
        for session in sessions:
            rows.append({"id": session.session_id, "title": session.title or session.session_id,
                         "session": session})
            seen.add(session.session_id)
        for key, lane in self._lanes.items():
            ident = lane.session_id or key
            if ident in seen:
                continue
            quiet = (lane.session_id is None and not lane.history and not lane.lines
                     and (lane.loop_task is None or lane.loop_task.done()))
            if quiet:
                continue
            rows.append({"id": ident, "title": ident, "session": None})
            seen.add(ident)
        return rows

    def _match_session_message(self, rows: list[dict], argument: str):
        hits = []
        for row in rows:
            labels = []
            title = " ".join(str(row["title"]).split())
            ident = str(row["id"])
            if title:
                labels.append(title)
            if ident and ident.casefold() != title.casefold():
                labels.append(ident)
            for label in labels:
                head, tail = argument[:len(label)], argument[len(label):]
                if head.casefold() != label.casefold():
                    continue
                if tail and not tail[0].isspace():
                    continue
                hits.append((len(label), row, tail.strip()))
        if not hits:
            return None, "", []
        best = max(item[0] for item in hits)
        chosen = [item for item in hits if item[0] == best]
        ids = {item[1]["id"] for item in chosen}
        if len(ids) != 1:
            return None, "", [item[1] for item in chosen]
        return chosen[0][1], chosen[0][2], []

    def _restore_message_draft(self, text: str) -> None:
        try:
            prompt = self.query_one("#prompt-input", PromptArea)
        except (NoMatches, NoScreen):
            return
        if not prompt.text.strip():
            prompt.load_text(text)

    def _list_message_targets(self, rows: list[dict], heading: str) -> None:
        self._append(heading, YELLOW)
        current = self._active_chat_session_id or self._foreground_key
        if not rows:
            self._append("  No other conversation is open.", MUTED)
            return
        for row in rows:
            mark = " · on screen" if row["id"] == current else ""
            self._append(f"  {row['title']} · {row['id']}{mark}", MUTED)
        self._append("  /msg <name or id> <message>", MUTED)

    def _adopt_saved_conversation(self, session):
        lane = open_lane(self, session.session_id)
        live = lane.loop_task is not None and not lane.loop_task.done()
        if live or lane.history or lane.lines:
            return lane
        lane.history = [{"role": message["role"], "content": message["content"]}
                        for message in session.messages
                        if message.get("role") in {"user", "assistant"}]
        state = session.state if isinstance(session.state, dict) else {}
        lane.tool_history = list(state.get("tool_history", []))
        lane.conversation_summary = state.get("conversation_summary", "") or ""
        lane.idea_box = state.get("idea_box", "") or ""
        lane.usage = UsageLedger.from_state(state["usage"]) if "usage" in state else UsageLedger()
        lane.throughput = ThroughputMeter()
        lane.retry_prompt = None
        lane.draft_text = state.get("draft", "") or ""
        lane.partial = ""
        lane.partial_reason = ""
        lane.stream_widget = None
        lane.stream_block = None
        lane.lines = []
        for message in session.messages:
            if message.get("role") == "user":
                lane.lines.append(("user", message.get("content", ""), message.get("sent_at")))
            elif message.get("role") == "assistant":
                lane.lines.append(("assistant", message.get("content", ""), message.get("sent_at")))
        return lane

    def _post_user_text(self, lane, text: str) -> str:
        live = lane.loop_task is not None and not lane.loop_task.done()
        if live:
            if len(lane.queued_messages) >= 8:
                return "full"
            lane.queued_messages.append(text)
            if lane.key == self._foreground_key:
                self._paint_queued_messages()
            return "queued"
        self._start_background_turn(lane, text)
        return "started"

    async def _deliver_session_message(self, raw: str) -> None:
        """Put the user's words on another conversation and let that one answer."""
        argument = raw.removeprefix("/msg").strip()
        sessions = []
        owner = self._chat_session_owner
        if owner is not None and self._sessions_enabled():
            try:
                outcome, sessions = await asyncio.to_thread(owner.list_conversations)
            except (OSError, ValueError):
                outcome, sessions = None, []
            if outcome is not None and outcome.decision != "ALLOW":
                sessions = []
                if not argument:
                    self._append(f"  Conversations unavailable · {outcome.reason[:160]}", YELLOW)
        rows = self._session_message_rows(sessions)
        if not argument:
            self._list_message_targets(rows, "  Name the conversation, then the message.")
            return
        row, body, ambiguous = self._match_session_message(rows, argument)
        if ambiguous:
            self._restore_message_draft(raw)
            self._list_message_targets(ambiguous, "  Several conversations match. Use the id.")
            return
        if row is None:
            self._restore_message_draft(raw)
            self._list_message_targets(rows, "  No conversation matched that name.")
            return
        current = self._active_chat_session_id or self._foreground_key
        if row["id"] == current or row["id"] == self._foreground_key:
            self._restore_message_draft(raw)
            self._append("  That conversation is on screen. Type the message here.", YELLOW)
            return
        if not body:
            self._restore_message_draft(raw)
            self._append("  Write the message after the name. /msg <name or id> <message>", YELLOW)
            return
        if len(body.encode("utf-8")) > MAX_MESSAGE_BYTES:
            self._restore_message_draft(raw)
            self._append("  That message is too large.", YELLOW)
            return
        session = row.get("session")
        lane = self._lanes.get(row["id"])
        if session is not None:
            lane = self._adopt_saved_conversation(session)
        if lane is None:
            self._restore_message_draft(raw)
            self._append("  That conversation is not open.", YELLOW)
            return
        status = self._post_user_text(lane, body)
        title = row["title"]
        if status == "full":
            self._restore_message_draft(raw)
            self._append(f"  {title} already has 8 messages waiting. Draft kept.", YELLOW)
            return
        if status == "queued":
            self._append(f"  Queued for {title}. It answers after the current reply.", CYAN)
        else:
            self._append(f"  Sent to {title}. It answers there as your message.", GREEN)
        if getattr(self, "is_running", False):
            self.run_worker(self._refresh_work_list(), group="work-list")


for _attr, _field in LANE_FIELDS:
    setattr(SessionMixin, _attr, lane_property(_field))
