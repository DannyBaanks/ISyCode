"""GUS's tool dispatch (ADR 0015): every call bound to the target or the machine.

The dispatcher is the only bridge between GUS's model and an execution owner.
It accepts the tool names of ``gus_session.gus_tools()`` and routes each one to
the owner that already exists (``WorkspaceWriteOwner``, ``CommandRunOwner``,
``MachineView``, ``GitOwner``), with the target authority for edits and the
machine authority for reads.

Nothing here grants: the owners still run Authority, IsySentinel, the effect
ledger, the journal and receipts. Reads go through the consented machine view,
whose paths are absolute; edits are relative to the target. Writes and commands
that the target's ``gus/*`` turn covers run quietly; anything else asks the
person through the ``approve`` callback. ``git_commit`` always asks. A rejected
call returns JSON and changes nothing.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from isycode.command_runner import COMMAND_DEFAULT_STAGE_BYTES, COMMAND_TOOL_NAME, CommandRunOwner
from isycode.git_owner import GIT_TOOL_NAMES, GitOwner
from isycode.machine_view import MachineView
from isycode.gus_session import MACHINE_TOOL_ACTIONS
from isycode.workspace_write import (
    DELETE_TOOL_NAME, EDIT_TOOL_NAME, MOVE_TOOL_NAME, WRITE_TOOL_NAME, WorkspaceWriteOwner,
)

Approval = Callable[[str, Any], Awaitable[bool]]
Approve = Approval

MAX_PATH_CHARS = 4096


def _deny(reason: str) -> str:
    return json.dumps({"error": "ISyCode denied the call", "reason": reason[:300]},
                      ensure_ascii=False)


def _target_relative(value: object) -> str:
    """A non-empty relative path inside the target; absolute paths are refused."""
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_PATH_CHARS \
            or "\0" in value:
        raise ValueError("path must be a bounded relative string")
    path = Path(value)
    if path.is_absolute() or (len(value) > 1 and value[1] == ":"):
        raise ValueError("path must be relative to the ISyCode target")
    if any(part == ".." for part in path.parts):
        raise ValueError("path cannot leave the ISyCode target")
    return path.as_posix()


def _quiet(authority, request) -> bool:
    try:
        from isycode.workspace_trust import quiet_request
        return bool(quiet_request(authority, request))
    except Exception:
        return False


class GusToolDispatcher:
    """Run one GUS tool call against the configured target, or refuse it."""

    def __init__(self, roots, approvals, *, approve: Approval | None = None,
                 on_output: Callable[[str], None] | None = None) -> None:
        if getattr(roots, "target", None) is None:
            raise ValueError("GUS has no target to dispatch to")
        self.roots = roots
        self.target = Path(roots.target).resolve(strict=True)
        self.authority = roots.authority()
        self.approvals = approvals
        self.approve = approve
        self.on_output = on_output
        self._machine_view: MachineView | None = None

    async def __call__(self, call: dict) -> tuple[str, str]:
        function = call.get("function") if isinstance(call, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        raw = function.get("arguments", "{}") if isinstance(function, dict) else "{}"
        call_id = call.get("id") if isinstance(call, dict) else None
        if not isinstance(call_id, str) or not call_id:
            return "", json.dumps({"error": "tool call has no identity"})
        if not isinstance(name, str) or not name:
            return call_id, json.dumps({"error": "tool call has no name"})
        if not isinstance(raw, str) or len(raw) > 64 * 1024:
            return call_id, json.dumps({"error": "tool arguments are malformed or too large"})
        try:
            arguments = json.loads(raw)
        except json.JSONDecodeError:
            return call_id, json.dumps({"error": "tool arguments must be JSON"})
        if not isinstance(arguments, dict):
            return call_id, json.dumps({"error": "tool arguments must be an object"})
        try:
            output = await self._dispatch(name, arguments)
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            output = _deny(str(exc) or type(exc).__name__)
        return call_id, output

    async def _dispatch(self, name: str, arguments: dict[str, Any]) -> str:
        if name in MACHINE_TOOL_ACTIONS:
            return await self._machine(MACHINE_TOOL_ACTIONS[name], arguments)
        if name in {WRITE_TOOL_NAME, EDIT_TOOL_NAME}:
            return await self._write(name, arguments)
        if name in {DELETE_TOOL_NAME, MOVE_TOOL_NAME}:
            return await self._change(name, arguments)
        if name == COMMAND_TOOL_NAME:
            return await self._command(arguments)
        if name in GIT_TOOL_NAMES:
            return await self._git(name, arguments)
        return json.dumps({"error": f"{name} is not one of GUS's tools"})

    async def _machine(self, action_id: str, arguments: dict[str, Any]) -> str:
        if self._machine_view is None:
            self._machine_view = MachineView(self.roots)
        view = self._machine_view
        outcome = await asyncio.to_thread(view.execute, action_id, arguments)
        if outcome.decision != "ALLOW" or outcome.receipt is None:
            return _deny(outcome.reason or outcome.decision)
        return outcome.text

    async def _review(self, kind: str, preview) -> bool:
        if self.approve is None:
            return False
        return bool(await self.approve(kind, preview))

    async def _write(self, name: str, arguments: dict[str, Any]) -> str:
        path = _target_relative(arguments.get("path"))
        owner = WorkspaceWriteOwner(self.target, self.authority, self.approvals)
        if name == EDIT_TOOL_NAME:
            old_text, new_text = arguments.get("old_text"), arguments.get("new_text")
            replace_all = arguments.get("replace_all", False)
            if (not isinstance(old_text, str) or not isinstance(new_text, str)
                    or not isinstance(replace_all, bool)):
                return json.dumps({"error": "old_text and new_text must be strings"})
            preview = await asyncio.to_thread(owner.preview_edit, path, old_text, new_text,
                                              replace_all)
        else:
            content = arguments.get("content")
            if not isinstance(content, str):
                return json.dumps({"error": "content must be a string"})
            preview = await asyncio.to_thread(owner.preview, path, content)
        approval = None
        if not _quiet(self.authority, preview.request):
            if not await self._review("write", preview):
                return json.dumps({"status": "rejected_by_user", "path": preview.path})
            approval = self.approvals.issue(preview.request, ttl_seconds=60)
        outcome = await asyncio.to_thread(owner.apply, preview, approval)
        return self._changed(outcome, preview.path)

    async def _change(self, name: str, arguments: dict[str, Any]) -> str:
        path = _target_relative(arguments.get("path"))
        owner = WorkspaceWriteOwner(self.target, self.authority, self.approvals)
        if name == DELETE_TOOL_NAME:
            preview = await asyncio.to_thread(owner.preview_delete, path)
        else:
            destination = _target_relative(arguments.get("to"))
            preview = await asyncio.to_thread(owner.preview_move, path, destination)
        approval = None
        if not _quiet(self.authority, preview.request):
            if not await self._review("write", preview):
                return json.dumps({"status": "rejected_by_user", "path": preview.path})
            approval = self.approvals.issue(preview.request, ttl_seconds=60)
        outcome = await asyncio.to_thread(owner.apply, preview, approval)
        return self._changed(outcome, preview.path)

    @staticmethod
    def _changed(outcome, path: str) -> str:
        if outcome.decision != "ALLOW" or outcome.receipt is None:
            return _deny(outcome.reason or outcome.decision)
        return json.dumps({"status": "done", "path": path, "result": outcome.text,
                           "receipt": outcome.receipt.receipt_id}, ensure_ascii=False)

    async def _command(self, arguments: dict[str, Any]) -> str:
        owner = CommandRunOwner(self.target, self.authority, self.approvals)
        preview = await asyncio.to_thread(
            owner.prepare, arguments.get("argv"), arguments.get("cwd", "."),
            arguments.get("timeout_s", 120), scope=arguments.get("scope", "."),
            max_stage_bytes=arguments.get("max_stage_bytes", COMMAND_DEFAULT_STAGE_BYTES))
        approval = None
        if not _quiet(self.authority, preview.request):
            if not await self._review("command", preview):
                return json.dumps({"status": "rejected_by_user", "argv": list(preview.argv)})
            approval = self.approvals.issue(preview.request, ttl_seconds=60)
        outcome = await owner.run(preview, approval, on_output=self.on_output)
        if outcome.decision != "ALLOW" or outcome.receipt is None:
            return _deny(outcome.reason or outcome.decision)
        return outcome.text

    async def _git(self, name: str, arguments: dict[str, Any]) -> str:
        repository = arguments.get("repository")
        if repository is not None and not isinstance(repository, str):
            return json.dumps({"error": "repository must be a direct child folder name"})
        owner = GitOwner(self.target, self.authority, self.approvals, repository=repository)
        if name == "git_status":
            outcome = await asyncio.to_thread(owner.status)
            if outcome.decision != "ALLOW" or outcome.receipt is None:
                return _deny(outcome.reason or outcome.decision)
            return outcome.text
        if name == "git_diff":
            path, staged = arguments.get("path", "."), arguments.get("staged", False)
            if not isinstance(path, str) or not isinstance(staged, bool):
                return json.dumps({"error": "path must be a string and staged a boolean"})
            outcome = await asyncio.to_thread(owner.diff, path, staged)
            if outcome.decision != "ALLOW" or outcome.receipt is None:
                return _deny(outcome.reason or outcome.decision)
            return outcome.text
        preview = await asyncio.to_thread(owner.preview_commit, arguments.get("message"),
                                          arguments.get("paths"))
        if not await self._review("commit", preview):
            return json.dumps({"status": "rejected_by_user"})
        approval = self.approvals.issue(preview.request, ttl_seconds=60)
        outcome = await asyncio.to_thread(owner.commit, preview, approval)
        if outcome.decision != "ALLOW" or outcome.receipt is None:
            return _deny(outcome.reason or outcome.decision)
        return outcome.text


__all__ = ["GusToolDispatcher"]
