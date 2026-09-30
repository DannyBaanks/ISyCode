"""Owned persistence of chat transcripts for recurring workspaces.

Saving and resuming conversations are product actions: `session.create`
covers creating a transcript and appending one message to it, and
`session.resume` covers listing and loading transcripts. Each operation is
bound to a request (session id, role, content digest), decided by Workspace
Authority and IsySentinel, and journaled with a receipt. Transcripts live in
the private per-workspace state directory, never inside the checkout, and
common secret shapes are redacted before anything is written.
"""
from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from pathlib import Path

from isycode.action_runtime import ActionOutcome, ActionReceipt, ProductActionGate
from isycode.chat_sessions import ChatSession, ChatSessionError, ChatSessionStore
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority

MAX_MESSAGE_BYTES = 1_000_000
LIST_TARGET = "sessions"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ChatSessionOwner:
    """Persist, list and load transcripts only after Authority and Sentinel allow it."""

    def __init__(self, root: Path, authority: WorkspaceAuthority, sessions_root: Path):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.store = ChatSessionStore(sessions_root)
        self.gate = ProductActionGate(self.root, authority, owner_id="chat_sessions")

    def _authorize(self, request: ActionRequest) -> str | None:
        """Return None when allowed, otherwise a short denial reason."""
        try:
            authority, decision = self.gate.authorize(request)
        except Exception:
            return "authorization evaluation failed"
        if authority.allowed and decision.allowed:
            return None
        if not authority.allowed:
            return authority.reason[:240]
        return "; ".join(check.reason for check in decision.checks if not check.passed)[:240]

    def _receipt(self, request: ActionRequest, result: str) -> ActionReceipt | None:
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), request.action_id,
                                request.digest, "ALLOW", "SUCCESS", _sha(result))
        return receipt if self.gate.persist_receipt(request, receipt) else None

    def record(self, session_id: str | None, role: str,
               content: str) -> tuple[ActionOutcome, str | None]:
        """Append one message, creating the transcript when session_id is None."""
        if role not in {"user", "assistant"} or not isinstance(content, str):
            return ActionOutcome("Message not saved.", "DENY", None, "message is malformed"), None
        clean = ChatSessionStore._sanitize_text(content)
        if len(clean.encode("utf-8")) > MAX_MESSAGE_BYTES:
            return ActionOutcome("Message not saved.", "DENY", None, "message is too large"), None
        creating = session_id is None
        target = uuid.uuid4().hex if creating else session_id
        try:
            request = ActionRequest("session.create", self.root, target, {
                "operation": "create" if creating else "append",
                "session_id": target, "role": role,
                "content_sha256": _sha(clean), "size": len(clean.encode("utf-8")),
            }, execution_owner="chat_sessions")
        except (TypeError, ValueError):
            return ActionOutcome("Message not saved.", "DENY", None, "invalid session request"), None
        denied = self._authorize(request)
        if denied is not None:
            return ActionOutcome("Message not saved.", "DENY", None, denied), None
        try:
            if creating:
                now = time.time()
                session = ChatSession(target, self.store._auto_title(clean) if role == "user"
                                      else "New session", [{"role": role, "content": clean}],
                                      now, now)
                self.store.save(session)
            else:
                self.store.append(target, role, clean)
        except (OSError, ChatSessionError, ValueError) as exc:
            return ActionOutcome("Message not saved.", "ERROR", None,
                                 f"session store rejected the write ({type(exc).__name__})"), None
        receipt = self._receipt(request, f"{request.parameters['operation']}:{target}:{_sha(clean)}")
        if receipt is None:
            return ActionOutcome("Message saved, but its receipt could not be journaled.",
                                 "NOT_VERIFIABLE", None, "durable action journal is unavailable"), target
        return ActionOutcome("Message saved.", "ALLOW", receipt, "transcript updated"), target

    def list_conversations(self) -> tuple[ActionOutcome, list[ChatSession]]:
        request = ActionRequest("session.resume", self.root, LIST_TARGET, {"operation": "list"},
                                execution_owner="chat_sessions")
        denied = self._authorize(request)
        if denied is not None:
            return ActionOutcome("Conversations unavailable.", "DENY", None, denied), []
        sessions = self.store.list_sessions()
        receipt = self._receipt(request, "list:" + ",".join(s.session_id for s in sessions))
        if receipt is None:
            return ActionOutcome("Conversations unavailable.", "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable"), []
        return ActionOutcome("Conversations listed.", "ALLOW", receipt, "transcripts listed"), sessions

    def resume(self, session_id: str) -> tuple[ActionOutcome, ChatSession | None]:
        try:
            request = ActionRequest("session.resume", self.root, session_id, {
                "operation": "load", "session_id": session_id,
            }, execution_owner="chat_sessions")
        except (TypeError, ValueError):
            return ActionOutcome("Conversation unavailable.", "DENY", None,
                                 "invalid session request"), None
        denied = self._authorize(request)
        if denied is not None:
            return ActionOutcome("Conversation unavailable.", "DENY", None, denied), None
        try:
            session = self.store.load(session_id)
        except (OSError, ChatSessionError, ValueError) as exc:
            return ActionOutcome("Conversation unavailable.", "ERROR", None,
                                 f"transcript could not be read ({type(exc).__name__})"), None
        receipt = self._receipt(request, f"load:{session_id}:{len(session.messages)}")
        if receipt is None:
            return ActionOutcome("Conversation unavailable.", "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable"), None
        return ActionOutcome("Conversation loaded.", "ALLOW", receipt, "transcript loaded"), session


__all__ = ["ChatSessionOwner", "LIST_TARGET", "MAX_MESSAGE_BYTES"]
