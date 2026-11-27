"""Worker thread that runs the real Agent loop in its own asyncio loop.

The UI (Qt main thread) never touches asyncio. The worker emits Qt
signals with queued connections, so all painting happens in the main
thread. The Agent instance is built exactly like isyvm/agent_cli.py
builds it: same components, same order, same defaults.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
import time

from PySide6.QtCore import QThread, Signal

from core.agent import AgentContext, DEFAULT_SYSTEM_PROMPT
from core.conversations import ConversationService
from core.agent.diagnostics import agent_failure

from .bridge import ObservableAgent


class AgentWorker(QThread):
    text_chunk = Signal(str)
    reasoning_chunk = Signal(str)
    progress = Signal(dict)
    tool_call = Signal(dict)
    tool_result = Signal(dict)
    approval_requested = Signal(str, str, dict, str)  # (approval_id, tool_name, args, diff_summary)
    agent_error = Signal(str)
    session_done = Signal(str)

    def __init__(self, controller, prompt: str, provider: str, model: str,
                 max_turns: int | None = None, parent=None, session_id: str = "",
                 attachments: list[str] | None = None):
        super().__init__(parent)
        self._controller = controller
        self.prompt = prompt
        self.provider = provider
        self.model = model
        self.max_turns = max_turns
        self.attachments = list(attachments or [])
        self._cancelled = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._working_dir = controller.working_dir
        self._mode = controller.mode()
        self._plan_context = controller.plan_context()
        self._runtime = controller.runtime_registry
        self._resident = controller.resident_recorder
        self._provider_config = controller.provider_registry.get_config(provider, model)
        self._conversations = controller.conversations
        self._session_id = session_id
        self._approval_lock = threading.Lock()
        self._pending_approvals: dict[str, asyncio.Future] = {}
        self._last_progress = None
        self._progress_at = 0.0
        self._reasoning_pending = ""
        self._reasoning_size = 0
        self._reasoning_truncated = False
        self._reasoning_handle = None

    def _on_progress(self, event: dict) -> None:
        key = (event.get("phase"), event.get("step"))
        now = time.monotonic()
        if key != self._last_progress or now - self._progress_at >= 0.25:
            self._last_progress, self._progress_at = key, now
            self.progress.emit(event)

    def _flush_reasoning(self) -> None:
        if self._reasoning_handle is not None:
            self._reasoning_handle.cancel()
        self._reasoning_handle = None
        if self._reasoning_pending:
            self.reasoning_chunk.emit(self._reasoning_pending)
            self._reasoning_pending = ""

    def _on_reasoning(self, text: str) -> None:
        remaining = max(0, 32_000 - self._reasoning_size)
        if not remaining or self._reasoning_truncated:
            return
        part = text.encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
        self._reasoning_size += len(part.encode("utf-8"))
        self._reasoning_pending += part
        if len(text.encode("utf-8")) > remaining:
            self._reasoning_truncated = True
            self._reasoning_pending += "\n[Vista de razonamiento limitada a 32 KB.]"
        if self._reasoning_handle is None:
            self._reasoning_handle = self._loop.call_later(0.1, self._flush_reasoning)

    def cancel(self) -> None:
        with self._approval_lock:
            if self._cancelled:
                return
            self._cancelled = True
            loop = self._loop
            task = self._task
            pending = list(self._pending_approvals.values())
            if loop is not None and not loop.is_closed():
                def _cancel_all():
                    for fut in pending:
                        if not fut.done():
                            fut.cancel()
                    if task is not None and not task.done():
                        task.cancel()
                try:
                    loop.call_soon_threadsafe(_cancel_all)
                except RuntimeError:
                    pass

    def resolve_approval(self, approval_id: str, approved: bool | str) -> bool:
        """Called from Qt GUI thread to answer an approval request."""
        with self._approval_lock:
            if self._cancelled:
                return False
            loop = self._loop
            fut = self._pending_approvals.get(approval_id)
            if fut is None or loop is None or loop.is_closed() or fut.done():
                return False

            def answer():
                if not fut.done():
                    fut.set_result(approved)

            try:
                loop.call_soon_threadsafe(answer)
                return True
            except RuntimeError:
                return False

    def _on_agent_event(self, event: dict) -> None:
        if event["type"] == "tool_call":
            self.tool_call.emit(event)
        elif event["type"] == "tool_result":
            self.tool_result.emit(event)

    async def _handle_approval(self, tool_call) -> bool | str:
        """Invoked by ObservableAgent when a modifying tool is proposed."""
        with self._approval_lock:
            if self._cancelled or self._loop is None or self._loop.is_closed():
                return False
            # Approval identity is host-owned; provider tool ids can repeat.
            call_id = uuid.uuid4().hex
            fut = self._loop.create_future()
            self._pending_approvals[call_id] = fut

        tool_name = tool_call.name
        args = dict(tool_call.arguments or {})
        diff = getattr(tool_call, "prepared_diff", "(sin diff preparado)")
        args["proposal_id"] = getattr(tool_call, "proposal_id", "")
        args["before_sha256"] = getattr(tool_call, "before_sha256", None)
        args["approval_kind"] = getattr(tool_call, "approval_kind", "files")
        identity = getattr(tool_call, "command_identity", None)
        if identity is not None:
            args.update(argv=list(identity.argv), cwd=identity.cwd,
                        executable_sha256=identity.executable_sha256, profile_sha256=identity.profile)

        self.approval_requested.emit(call_id, tool_name, args, diff)
        self.progress.emit({"phase": "approval", "tool": tool_name})
        try:
            answer = await fut
            self.progress.emit({"phase": "tool", "tool": tool_name})
            return answer
        finally:
            with self._approval_lock:
                self._pending_approvals.pop(call_id, None)

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        with self._approval_lock:
            self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            task = loop.create_task(self._amain())
            with self._approval_lock:
                self._task = task
                cancelled = self._cancelled
            if cancelled:
                task.cancel()
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        finally:
            with self._approval_lock:
                self._loop = None
                self._task = None
                pending = list(self._pending_approvals.values())
                self._pending_approvals.clear()
            for fut in pending:
                if not fut.done():
                    fut.cancel()
            loop.close()

    async def _amain(self) -> None:
        agent = None
        try:
            if self._cancelled:
                self.session_done.emit("")
                return
            sys_prompt = DEFAULT_SYSTEM_PROMPT
            if self.attachments:
                from core.attachment_router import build_hidden_attachment_prompt
                sys_prompt += build_hidden_attachment_prompt(self.attachments, workspace=self._working_dir)
            context = AgentContext(
                provider_name=self.provider,
                model=self.model,
                system_prompt=sys_prompt,
                working_dir=str(self._working_dir),
                max_turns=self.max_turns,
                mode=self._mode,
                plan_context=self._plan_context,
                session_id=self._session_id,
                provider_config=self._provider_config,
            )
            agent = ObservableAgent(
                context,
                self._controller.provider_registry,
                self._controller.policy_engine,
                self._runtime,
                self._controller.secret_broker,
                self._resident,
                on_event=self._on_agent_event,
                on_approval=self._handle_approval,
            )
            agent.on_progress = self._on_progress
            agent.on_reasoning = self._on_reasoning
            stream = (ConversationService(self._conversations).run_agent(agent, self.prompt)
                      if self._session_id else agent.run(self.prompt))
            try:
                async for chunk in stream:
                    if self._cancelled:
                        break
                    self.text_chunk.emit(chunk)
            finally:
                await stream.aclose()
                self._flush_reasoning()
            self.session_done.emit(agent.session_id)
        except asyncio.CancelledError:
            self._flush_reasoning()
            self.session_done.emit(agent.session_id if agent else "")
        except Exception as exc:
            self._flush_reasoning()
            diagnostic = agent_failure(exc, agent)
            self.agent_error.emit(f"{diagnostic['code']} · {diagnostic['message']} · paso {diagnostic['step']} · {diagnostic['phase']}")


class HostToolWorker(QThread):
    """Explicit host action with the same immutable approval channel as chat."""

    ready = Signal(object)
    progress = Signal(dict)
    failed = Signal(str)
    approval_requested = Signal(str, str, dict, str)
    cancel = AgentWorker.cancel
    resolve_approval = AgentWorker.resolve_approval
    _handle_approval = AgentWorker._handle_approval

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation
        self._cancelled = False
        self._loop = self._task = None
        self._approval_lock = threading.Lock()
        self._pending_approvals = {}

    def run(self):
        loop = asyncio.new_event_loop()
        with self._approval_lock:
            self._loop = loop
        try:
            with self._approval_lock:
                if self._cancelled:
                    return
                task = loop.create_task(self.operation(self._handle_approval))
                self._task = task
            result = loop.run_until_complete(task)
            if not self._cancelled:
                self.ready.emit(result)
        except asyncio.CancelledError:
            pass
        except Exception:
            self.failed.emit("No se pudo completar la acción. Revisa el perfil aislado y el estado del proyecto.")
        finally:
            with self._approval_lock:
                self._loop = None
                self._task = None
                pending = list(self._pending_approvals.values())
                self._pending_approvals.clear()
            for fut in pending:
                if not fut.done():
                    fut.cancel()
            loop.close()
