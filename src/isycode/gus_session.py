"""GUS conversations (ADR 0011, MK4): explicit per-workspace enablement, own transcript.

GUS is offered only in the ISyCode repository (D3), but the two marker files
that detect it only decide whether the entry is shown. GUS answers only after
the person enables it for this exact workspace (GK4-00); the record is bound
to the resolved workspace path in ISyCode's private state, never to files in
the repository.

A GUS turn sends the role, the fixed context pack and GUS's own transcript to
the GUS model slot through the provider network owner, which authorizes the
request with IsySentinel and receipts it. The request is budgeted against the
model's known window, or 32k tokens when it is unknown. This milestone gives
GUS no tools: it reads its fixed context and talks. Edits arrive in MK5 with
the gus/* branch and protected paths.
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from isycode.gus_context_pack import ContextPackError, ContextPackReader, plan_gus_request, window_chars
from isycode.gus_role import GusRoleError, is_isycode_checkout, load_gus_role
from isycode.gus_slot import GusSlotError, check_gus_model, gus_provider, planning_window
from isycode.state_index import get_state_index

RECORD_VERSION = 1
MAX_RECORD_BYTES = 4 * 1024 * 1024
MAX_TRANSCRIPT_ENTRIES = 80
MAX_ENTRY_CHARS = 32_000
# Share of the planning window a request may fill; the rest is left for the answer.
REQUEST_WINDOW_SHARE = 0.75


class GusUnavailable(RuntimeError):
    """GUS cannot answer here; ``reason`` says why in words the TUI shows."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class GusState:
    """GUS's private per-workspace records under the state root."""

    def __init__(self, workspace_root: Path, *, root: Path | None = None) -> None:
        self.workspace = Path(workspace_root).resolve(strict=True)
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

    # Transcript ----------------------------------------------------------
    def transcript(self) -> list[dict[str, str]]:
        record = self._read("transcript.json") or {}
        entries = record.get("entries")
        if not isinstance(entries, list):
            return []
        return [entry for entry in entries
                if isinstance(entry, dict) and entry.get("role") in {"user", "assistant"}
                and isinstance(entry.get("text"), str) and isinstance(entry.get("at"), str)]

    def append(self, role: str, text: str) -> list[dict[str, str]]:
        entries = self.transcript() + [{"role": role, "text": text[:MAX_ENTRY_CHARS], "at": _now()}]
        entries = entries[-MAX_TRANSCRIPT_ENTRIES:]
        self._write("transcript.json", {"entries": entries})
        return entries

    def clear(self) -> None:
        self._write("transcript.json", {"entries": []})


@dataclass(frozen=True)
class GusReply:
    text: str
    model: str
    window_known: bool
    receipt_id: str


Complete = Callable[..., Awaitable[dict]]


async def gus_reply(workspace_root: Path, authority, text: str, *,
                    complete: Complete | None = None, state: GusState | None = None) -> GusReply:
    """Answer one message as GUS, or raise GusUnavailable with the reason."""
    from isycode.action_runtime import LocalWorkspaceReadOwner, ProviderNetworkOwner
    root = Path(workspace_root).resolve(strict=True)
    state = state or GusState(root)
    if not is_isycode_checkout(root):
        raise GusUnavailable("GUS works only in the ISyCode repository.")
    if not state.enabled():
        raise GusUnavailable("GUS is not enabled for this workspace.")
    try:
        role = load_gus_role()
        provider = gus_provider()
        pack = ContextPackReader(root, LocalWorkspaceReadOwner(root, authority)).build()
    except (GusRoleError, GusSlotError, ContextPackError) as exc:
        raise GusUnavailable(str(exc)) from exc
    check = check_gus_model(provider.name, provider.model)
    history = [{"role": entry["role"], "content": entry["text"]} for entry in state.transcript()]
    history.append({"role": "user", "content": text})
    try:
        messages = plan_gus_request(pack=pack, role_instructions=role.instructions,
                                    history=history, tool_history=[],
                                    window_tokens=planning_window(check))
    except ContextPackError as exc:
        raise GusUnavailable(str(exc)) from exc
    # The planner keeps the newest message whole (ADR 0009); one larger than the
    # window must be refused here rather than sent to a model that cannot hold it.
    if sum(len(str(message["content"])) for message in messages) \
            > window_chars(planning_window(check)) * REQUEST_WINDOW_SHARE:
        raise GusUnavailable("This message is too large for GUS's model window.")
    if complete is None:
        from isycode.chat_transport import provider_complete as complete

    async def send():
        return await complete(provider, messages, max_tokens=None, tools=None)

    response, outcome = await ProviderNetworkOwner(root, authority).execute(provider, {
        "operation": "gus.reply", "messages": messages, "max_tokens": None,
        "token_limit_field": provider.token_limit_field,
        "reasoning_effort": provider.reasoning_effort,
        "temperature_supported": provider.temperature_supported, "tools": None,
    }, send)
    if outcome.decision != "ALLOW" or not isinstance(response, dict) or outcome.receipt is None:
        raise GusUnavailable(f"The request to GUS's model was not allowed: {outcome.reason[:160]}")
    answer = str(response.get("text") or "").strip()
    if not answer:
        raise GusUnavailable("GUS's model returned no answer.")
    state.append("user", text)
    state.append("assistant", answer)
    return GusReply(answer, provider.model, check.window is not None, outcome.receipt.receipt_id)


__all__ = ["GusReply", "GusState", "GusUnavailable", "gus_reply"]
