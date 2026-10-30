"""GUS conversations (ADR 0011, ADR 0015): user enablement, own transcript, three roots.

GUS answers in any workspace after the person enables it there (GK4-00). The
record is bound to the resolved visible workspace in ISyCode's private state,
never to files in a repository. A GUS turn sends the role, the fixed context
pack of the configured ISyCode target and GUS's own transcript to the GUS model
slot through the provider network owner, which authorizes the request with
IsySentinel and receipts it. The request is budgeted against the model's known
window, or 32k tokens when it is unknown.

``gus_reply`` talks without tools. ``gus_work`` (MK5c) also gives GUS the tools
of its role, only on a ``gus/*`` branch of the target: every tool call runs
inside ``gus_turn``, so IsySentinel refuses L0 and anything outside the role,
and the caller records the turn in a turn journal and checks the L0 fingerprint.
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from isycode.gus_context_pack import (
    PACK_HEADER, ContextPack, ContextPackError, ContextPackReader, plan_gus_request,
    roots_block, window_chars,
)
from isycode.gus_l0 import gus_turn, on_gus_branch
from isycode.gus_role import GusRoleError, load_gus_role
from isycode.gus_slot import GusSlotError, check_gus_model, gus_provider, planning_window
from isycode.state_index import get_state_index

RECORD_VERSION = 1
MAX_RECORD_BYTES = 4 * 1024 * 1024
MAX_GENERATIONS = 50
# Share of the planning window a request may fill; the rest is left for the answer.
REQUEST_WINDOW_SHARE = 0.75
# One GUS turn: model steps and tool calls per step.
MAX_GUS_STEPS = 24
MAX_GUS_CALLS_PER_STEP = 16


class GusUnavailable(RuntimeError):
    """GUS cannot answer here; ``reason`` says why in words the TUI shows."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class GusState:
    """GUS's private per-workspace records under the state root."""

    def __init__(self, workspace_root: Path, *, root: Path | None = None) -> None:
        self.workspace = Path(workspace_root).resolve(strict=True)
        self._root = root
        index = get_state_index()
        self.directory = (index.subsystem("gus", root=root)
                          / index.workspace_digest(self.workspace, length=32))

    def _ensure(self) -> None:
        from isycode.platform_storage import storage
        storage.ensure_directory(self.directory.parent, repair=True)
        storage.ensure_directory(self.directory, repair=True)
        if (self.directory.is_symlink() or not self.directory.is_dir()
                or not storage.private(self.directory)):
            raise OSError("GUS state directory is unsafe")

    def _read(self, name: str) -> dict[str, Any] | None:
        path = self.directory / name
        try:
            info = path.lstat()
        except OSError:
            return None
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_size > MAX_RECORD_BYTES):
            return None
        if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) and data.get("version") == RECORD_VERSION else None

    def _write(self, name: str, record: dict[str, Any]) -> None:
        payload = json.dumps({"version": RECORD_VERSION, **record}, ensure_ascii=False,
                             sort_keys=True).encode("utf-8")
        if len(payload) > MAX_RECORD_BYTES:
            raise ValueError("GUS record exceeds its size limit")
        self._ensure()
        temporary = self.directory / (".gus-" + os.urandom(8).hex() + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            view = memoryview(payload)
            while view:
                view = view[os.write(descriptor, view):]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.replace(temporary, self.directory / name)
        finally:
            if temporary.exists():
                temporary.unlink()

    # Branches and generations (MK5) -------------------------------------
    def record_branch(self, branch: str, base: str, l0_digest: str) -> None:
        """Remember where a gus/* branch started and the L0 fingerprint at that moment."""
        branches = dict((self._read("branches.json") or {}).get("branches") or {})
        branches[branch] = {"base": base, "l0": l0_digest, "at": _now()}
        self._write("branches.json", {"branches": dict(list(branches.items())[-50:])})

    def branch(self, branch: str) -> dict[str, Any] | None:
        record = ((self._read("branches.json") or {}).get("branches") or {}).get(branch)
        return record if isinstance(record, dict) and isinstance(record.get("base"), str) else None

    def save_generation(self, generation: dict[str, Any]) -> None:
        entries = [entry for entry in (self._read("generations.json") or {}).get("entries") or []
                   if isinstance(entry, dict)]
        self._write("generations.json", {"entries": (entries + [generation])[-MAX_GENERATIONS:]})

    def generations(self) -> list[dict[str, Any]]:
        return [entry for entry in (self._read("generations.json") or {}).get("entries") or []
                if isinstance(entry, dict)]

    # Enablement (GK4-00) -------------------------------------------------
    def enabled(self) -> bool:
        record = self._read("enabled.json")
        return bool(record and record.get("workspace") == str(self.workspace))

    def enable(self) -> None:
        self._write("enabled.json", {"workspace": str(self.workspace), "enabled_at": _now()})

    def disable(self) -> None:
        try:
            (self.directory / "enabled.json").unlink()
        except FileNotFoundError:
            pass

    # Conversation (ADR 0015, phase 3): the person's transcript, shared across
    # workspaces and stored outside the checkout. Each entry names the
    # workspace it came from, so the window can show it.
    def transcript(self) -> list[dict[str, str]]:
        from isycode.gus_memory import GusConversation
        return GusConversation(root=self._root).entries()

    def append(self, role: str, text: str) -> list[dict[str, str]]:
        from isycode.gus_memory import GusConversation
        return GusConversation(root=self._root).append(role, text,
                                                       workspace=str(self.workspace))

    def clear(self) -> None:
        from isycode.gus_memory import GusConversation
        GusConversation(root=self._root).clear()


@dataclass(frozen=True)
class GusReply:
    text: str
    model: str
    window_known: bool
    receipt_id: str
    steps: int = 1
    tools_used: tuple[str, ...] = ()
    stopped: str = ""


Complete = Callable[..., Awaitable[dict]]
Dispatch = Callable[[dict], Awaitable[tuple[str, str]]]


MACHINE_TOOL_ACTIONS = {
    "machine_list": "machine.files.list",
    "machine_read": "machine.files.read",
    "machine_search": "machine.files.search",
    "machine_grep": "machine.files.grep",
}
MACHINE_TOOLS = [
    {"type": "function", "function": {
        "name": "machine_list",
        "description": ("List a folder on this computer with absolute paths. Sensitive names, "
                        "credentials and the ISyCode state are never listed."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Absolute folder path."},
        }, "required": ["path"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "machine_read",
        "description": ("Read one UTF-8 text file on this computer with an absolute path, up to "
                        "256 KiB. Credentials, keys, private stores and links are refused."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Absolute file path."},
        }, "required": ["path"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "machine_search",
        "description": "Search file and folder names on this computer; never contents.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Text to find in names."},
            "path": {"type": "string", "description": "Absolute folder path."},
        }, "required": ["query", "path"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "machine_grep",
        "description": ("Find lines containing literal text in UTF-8 files on this computer "
                        "(not a regex). Skips sensitive, binary, oversized and dependency folders."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Literal text; case-insensitive."},
            "path": {"type": "string", "description": "Absolute folder or file path."},
        }, "required": ["query", "path"], "additionalProperties": False},
    }},
]

MEMORY_TOOL_NAME = "memory_remember"
MEMORY_TOOL = {"type": "function", "function": {
    "name": MEMORY_TOOL_NAME,
    "description": ("Remember one durable fact about the person for future conversations: a "
                    "preference, a project, context. Never credentials, keys, tokens or secrets; "
                    "memories are redacted before they are stored."),
    "parameters": {"type": "object", "properties": {
        "text": {"type": "string", "description": "The fact to remember."},
    }, "required": ["text"], "additionalProperties": False},
}}


def gus_tools() -> list[dict]:
    """The tool schemas of GUS's role: machine reads, edits, sandboxed commands, git, memory."""
    from isycode.command_runner import command_tool
    from isycode.git_owner import GIT_COMMIT_TOOL, GIT_TOOLS
    from isycode.workspace_write import DELETE_TOOL, EDIT_TOOL, MOVE_TOOL, WRITE_TOOL
    tools = [*MACHINE_TOOLS, EDIT_TOOL, WRITE_TOOL, DELETE_TOOL, MOVE_TOOL,
             command_tool("flow"), *GIT_TOOLS, GIT_COMMIT_TOOL, MEMORY_TOOL]
    return json.loads(json.dumps(tools))


def _size(messages: list[dict]) -> int:
    return sum(len(json.dumps(message, ensure_ascii=False, default=str)) for message in messages)


def _roots_section(roots) -> str:
    """The three roots stated in the pack: chat, machine reads, target edits."""
    from isycode.gus_roots import scope_text
    target = getattr(roots, "target", None)
    return roots_block(visible=str(roots.visible),
                       target=str(target) if target is not None else "",
                       scope=scope_text(roots.data))


def _minimal_pack(roots) -> ContextPack:
    """The pack when GUS has no readable target: it still knows which roots it has."""
    return ContextPack("\n\n".join([PACK_HEADER, _roots_section(roots)]), ())


def _pack(roots) -> ContextPack:
    """The fixed project context: from the target, or the minimal roots pack.

    Reading the target does not need a clean worktree; only editing does.
    """
    from isycode.action_runtime import LocalWorkspaceReadOwner
    from isycode.gus_role import is_isycode_checkout
    target = getattr(roots, "target", None)
    if target is None or not is_isycode_checkout(target):
        return _minimal_pack(roots)
    try:
        return ContextPackReader(
            target, LocalWorkspaceReadOwner(target, roots.authority())).build(
                roots_section=_roots_section(roots))
    except (ContextPackError, OSError, ValueError):
        return _minimal_pack(roots)


def _prepare(roots, text: str, state: "GusState"):
    if not state.enabled():
        raise GusUnavailable("GUS is not enabled for this workspace.")
    try:
        role = load_gus_role()
        provider = gus_provider()
        pack = _pack(roots)
    except (GusRoleError, GusSlotError, ContextPackError) as exc:
        raise GusUnavailable(str(exc)) from exc
    check = check_gus_model(provider.name, provider.model)
    from isycode.gus_memory import memory_texts
    history = [{"role": entry["role"], "content": entry["text"]} for entry in state.transcript()]
    history.append({"role": "user", "content": text})
    try:
        messages = plan_gus_request(pack=pack, role_instructions=role.instructions,
                                    history=history, tool_history=[],
                                    window_tokens=planning_window(check),
                                    memories=memory_texts(state._root))
    except ContextPackError as exc:
        raise GusUnavailable(str(exc)) from exc
    # The planner keeps the newest message whole (ADR 0009); one larger than the
    # window must be refused here rather than sent to a model that cannot hold it.
    if sum(len(str(message["content"])) for message in messages) \
            > window_chars(planning_window(check)) * REQUEST_WINDOW_SHARE:
        raise GusUnavailable("This message is too large for GUS's model window.")
    return provider, check, messages


async def _send(roots, provider, messages: list[dict], tools, complete: Complete):
    from isycode.action_runtime import ProviderNetworkOwner

    authority = roots.provider_authority()

    async def send():
        return await complete(provider, messages, max_tokens=None, tools=tools)

    response, outcome = await ProviderNetworkOwner(authority.root, authority).execute(
        provider, {
            "operation": "gus.reply", "messages": messages, "max_tokens": None,
            "token_limit_field": provider.token_limit_field,
            "reasoning_effort": provider.reasoning_effort,
            "temperature_supported": provider.temperature_supported, "tools": tools,
        }, send)
    if outcome.decision != "ALLOW" or not isinstance(response, dict) or outcome.receipt is None:
        raise GusUnavailable(f"The request to GUS's model was not allowed: {outcome.reason[:160]}")
    return response, outcome.receipt.receipt_id


Remember = Callable[[Any], Awaitable[str]]


async def gus_reply(roots, text: str, *,
                    complete: Complete | None = None, state: GusState | None = None,
                    remember: Remember | None = None) -> GusReply:
    """Answer one message as GUS, or raise GusUnavailable with the reason.

    Without ``remember`` GUS talks without tools (the original behaviour). With
    it, the model may call ``memory_remember``: the callback reviews one memory
    in the person's chosen mode and returns the tool output. Nothing else is
    offered here; edits stay on a ``gus/*`` branch through ``gus_work``.
    """
    from isycode.chat_transport import assistant_turn
    state = state or roots.visible_state()
    provider, check, messages = _prepare(roots, text, state)
    if complete is None:
        from isycode.chat_transport import provider_complete as complete
    tools = [MEMORY_TOOL] if remember is not None else None
    budget = window_chars(planning_window(check)) * REQUEST_WINDOW_SHARE
    used: list[str] = []
    answer, stopped, receipt_id, step = "", "", "", 0
    # The chat itself is the turn: a memory written while GUS answers is GUS's.
    with gus_turn(state.workspace):
        while True:
            if step >= MAX_GUS_STEPS:
                stopped = "steps"
                break
            if _size(messages) > budget:
                stopped = "window"
                break
            response, receipt_id = await _send(roots, provider, messages, tools, complete)
            step += 1
            answer = str(response.get("text") or "").strip()
            calls = response.get("tool_calls") or []
            if not isinstance(calls, list) or len(calls) > MAX_GUS_CALLS_PER_STEP:
                raise GusUnavailable("GUS's model returned an invalid tool batch.")
            if not calls:
                break
            messages.append(assistant_turn(response))
            for call in calls:
                function = call.get("function") if isinstance(call, dict) else None
                name = function.get("name") if isinstance(function, dict) else None
                call_id = call.get("id") if isinstance(call, dict) else None
                if not isinstance(call_id, str) or not call_id or not isinstance(name, str):
                    raise GusUnavailable("GUS's model returned a tool call without identity.")
                if name != MEMORY_TOOL_NAME or remember is None:
                    output = json.dumps({"error": f"{name} is not one of GUS's tools"})
                else:
                    output = await remember(function.get("arguments"))
                    used.append(name)
                messages.append({"role": "tool", "tool_call_id": call_id, "content": output})
    if not answer:
        answer = {"steps": "GUS stopped after its step limit before answering.",
                  "window": "GUS stopped: this turn filled its model window."}.get(
                      stopped, "GUS finished without a written answer.")
    state.append("user", text)
    state.append("assistant", answer)
    return GusReply(answer, provider.model, check.window is not None, receipt_id,
                    steps=step, tools_used=tuple(used), stopped=stopped)


async def gus_work(roots, text: str, dispatch: Dispatch, *,
                   complete: Complete | None = None, state: GusState | None = None,
                   on_status: Callable[[str], None] | None = None) -> GusReply:
    """One GUS turn with the tools of its role (MK5c); only on a ``gus/*`` target branch.

    Every tool call runs inside ``gus_turn``. The model requests themselves do
    not: they go through the provider network owner like any GUS reply. The
    turn stops after MAX_GUS_STEPS model steps or when the window is full, and
    says so; it never claims work it did not do.
    """
    from isycode.chat_transport import assistant_turn
    target = getattr(roots, "target", None)
    if target is None:
        raise GusUnavailable("GUS has no configured ISyCode checkout to edit.")
    ready, reason = roots.target_ready()
    if not ready:
        raise GusUnavailable(reason)
    if not on_gus_branch(target):
        raise GusUnavailable("GUS edits only on a gus/* branch. Create one with /gus branch <topic>.")
    state = state or roots.visible_state()
    provider, check, messages = _prepare(roots, text, state)
    if complete is None:
        from isycode.chat_transport import provider_complete as complete
    tools = gus_tools()
    allowed = {tool["function"]["name"] for tool in tools}
    budget = window_chars(planning_window(check)) * REQUEST_WINDOW_SHARE
    used: list[str] = []
    answer, stopped, receipt_id, step = "", "", "", 0
    from isycode.machine_view import machine_budget
    with machine_budget():
        while True:
            if step >= MAX_GUS_STEPS:
                stopped = "steps"
                break
            if _size(messages) > budget:
                stopped = "window"
                break
            if on_status:
                on_status(f"step {step + 1}")
            response, receipt_id = await _send(roots, provider, messages, tools, complete)
            step += 1
            answer = str(response.get("text") or "").strip()
            calls = response.get("tool_calls") or []
            if not isinstance(calls, list) or len(calls) > MAX_GUS_CALLS_PER_STEP:
                raise GusUnavailable("GUS's model returned an invalid tool batch.")
            if not calls:
                break
            messages.append(assistant_turn(response))
            for call in calls:
                function = call.get("function") if isinstance(call, dict) else None
                name = function.get("name") if isinstance(function, dict) else None
                call_id = call.get("id") if isinstance(call, dict) else None
                if not isinstance(call_id, str) or not call_id or not isinstance(name, str):
                    raise GusUnavailable("GUS's model returned a tool call without identity.")
                if name not in allowed:
                    output = json.dumps({"error": f"{name} is not one of GUS's tools"})
                else:
                    if on_status:
                        on_status(f"tool · {name}")
                    with gus_turn(target):
                        returned_id, output = await dispatch(call)
                    if returned_id != call_id or not isinstance(output, str):
                        raise GusUnavailable("A tool result did not match its request.")
                    used.append(name)
                messages.append({"role": "tool", "tool_call_id": call_id, "content": output})
    if not answer:
        answer = {"steps": "GUS stopped after its step limit before answering.",
                  "window": "GUS stopped: this turn filled its model window."}.get(
                      stopped, "GUS finished without a written answer.")
    state.append("user", text)
    state.append("assistant", answer)
    return GusReply(answer, provider.model, check.window is not None, receipt_id,
                    steps=step, tools_used=tuple(used), stopped=stopped)


__all__ = ["GusReply", "GusState", "GusUnavailable", "MACHINE_TOOLS", "MACHINE_TOOL_ACTIONS",
           "MEMORY_TOOL", "MEMORY_TOOL_NAME", "Remember", "gus_reply", "gus_tools", "gus_work"]
