"""Owned persistence of chat transcripts for recurring workspaces.

Saving and resuming conversations are product actions: `session.create`
covers creating a transcript and appending one message to it, and
`session.resume` covers listing and loading transcripts. Each operation is
bound to a request (session id, role, content digest), decided by Workspace
Authority and IsySentinel, and journaled with a receipt. Transcripts live in
the private per-workspace state directory, never inside the checkout, and
common secret shapes are redacted before anything is written.

Continuities. Two ISyCode instances may open the same transcript; each is a
valid continuity, but neither may silently overwrite or merge into the other.
The owner remembers, in memory, the revision (sha256 of the persisted bytes)
it loaded or last wrote for each transcript. Every write compares that with
the bytes on disk under the store's directory lock and writes only if they
match. Otherwise nothing is written, the transcript is marked diverged for
this instance, and further writes to it are refused until the user chooses:
save this continuity as a new conversation, reload the saved one, or keep
working without saving. Each step is journaled (ids and revisions only).
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from datetime import datetime
from pathlib import Path

from isycode.action_runtime import ActionOutcome, ActionReceipt, ProductActionGate
from isycode.chat_sessions import (
    UNCHECKED, ChatSession, ChatSessionError, ChatSessionStore, SessionDiverged, revision_of,
)
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority

MAX_MESSAGE_BYTES = 1_000_000
LIST_TARGET = "sessions"
DIVERGENCE_EVENTS = frozenset({"divergence_detected", "divergence_forked",
                               "divergence_reloaded", "divergence_unsaved"})
DIVERGED_REASON = "session_divergence_detected"


class _TitleWindowClosed(Exception):
    """An automatic title arrived after the user renamed or the window passed."""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _owned_sent_at(value: str | None) -> str:
    """Keep a caller stamp only when it is already a real offset timestamp."""
    if isinstance(value, str):
        try:
            ChatSessionStore._validate_sent_at({"sent_at": value})
            return value
        except ChatSessionError:
            pass
    return datetime.now().astimezone().isoformat(timespec="seconds")


class ChatSessionOwner:
    """Persist, list and load transcripts only after Authority and Sentinel allow it."""

    def __init__(self, root: Path, authority: WorkspaceAuthority, sessions_root: Path):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.store = ChatSessionStore(sessions_root)
        self.gate = ProductActionGate(self.root, authority, owner_id="chat_sessions")
        # session id -> revision this instance believes is on disk (loaded or written by it).
        self._base: dict[str, str] = {}
        # session id -> (expected, current) once another continuity changed it.
        self._diverged: dict[str, tuple[str | None, str | None]] = {}

    # ── Continuity tracking ─────────────────────────────────────────────
    def base_revision(self, session_id: str) -> str | None:
        return self._base.get(session_id)

    def is_diverged(self, session_id: str | None) -> bool:
        return session_id in self._diverged

    def _guarded_write(self, session_id: str, build, *, new: bool = False) -> ChatSession:
        """Read, compare and write one transcript as a single step for other instances.

        ``build`` receives the transcript currently on disk (None when ``new``) and
        returns the transcript to write. Raises SessionDiverged without writing when
        the bytes on disk are not the revision this instance last saw.
        """
        if session_id in self._diverged:
            expected, current = self._diverged[session_id]
            error = SessionDiverged(session_id, expected, current)
            error.already_reported = True  # refused again; the event is journaled once
            raise error
        with self.store.write_lock():
            raw = self.store._read_bytes(session_id)
            current = revision_of(raw)
            if new:
                if raw is not None:
                    raise SessionDiverged(session_id, None, current)
                existing = None
            else:
                if raw is None:
                    raise FileNotFoundError(session_id)
                expected = self._base.get(session_id)
                # A transcript this instance never loaded has no base to defend; the
                # lock still keeps the read-modify-write from losing anyone's write.
                if expected is not None and expected != current:
                    self._diverged[session_id] = (expected, current)
                    raise SessionDiverged(session_id, expected, current)
                existing = self.store._parse(session_id, raw)
            session = build(existing)
            _, revision = self.store._write(session)
            self._base[session.session_id] = revision
            return session

    def _note(self, session_id: str, event: str, expected: str | None, current: str | None,
              fork_id: str = "") -> bool:
        """Journal one divergence event: ids and revisions only, never content."""
        if event not in DIVERGENCE_EVENTS:
            raise ValueError("unknown divergence event")
        try:
            parameters = {"operation": event, "session_id": session_id,
                          "expected_revision": expected or "", "current_revision": current or ""}
            if event == "divergence_forked":
                parameters["fork_id"] = fork_id
            request = ActionRequest("session.resume", self.root, session_id, parameters,
                                    execution_owner="chat_sessions")
        except (TypeError, ValueError):
            return False
        if self._authorize(request) is not None:
            return False
        return self._receipt(request, f"{event}:{session_id}:{expected}:{current}:{fork_id}") is not None

    def _diverged_outcome(self, what: str, error: SessionDiverged) -> ActionOutcome:
        if not getattr(error, "already_reported", False):
            self._note(error.session_id, "divergence_detected", error.expected, error.current)
        return ActionOutcome(f"{what} Nothing was written.", "DENY", None,
                             f"{DIVERGED_REASON}: the conversation changed in another ISyCode "
                             "window or process since this one loaded it")

    def save_continuity_as_new(self, session_id: str, messages: list[dict],
                               state: dict | None, title: str) -> tuple[ActionOutcome, str | None]:
        """Divergence → keep the original untouched and store this continuity apart."""
        expected, current = self._diverged.get(session_id, (self._base.get(session_id), None))
        serialized = json.dumps({"version": 2, "title": f"Fork: {title}"[:80],
                                 "messages": [dict(message) for message in messages],
                                 "state": state or {}}, ensure_ascii=False)
        outcome, fork_id = self.manage("import", None, serialized)
        if outcome.decision != "ALLOW" or fork_id is None:
            return outcome, None
        self._note(session_id, "divergence_forked", expected, current, fork_id)
        self._diverged.pop(session_id, None)
        return outcome, fork_id

    def reload_saved(self, session_id: str) -> tuple[ActionOutcome, ChatSession | None]:
        """Divergence → adopt exactly what is persisted as this instance's base."""
        expected, current = self._diverged.get(session_id, (self._base.get(session_id), None))
        self._diverged.pop(session_id, None)
        outcome, session = self.resume(session_id)
        if session is not None:
            self._note(session_id, "divergence_reloaded", expected, self._base.get(session_id))
        else:
            self._diverged[session_id] = (expected, current)
        return outcome, session

    def keep_unsaved(self, session_id: str) -> None:
        """Divergence → keep working in memory; writes to this transcript stay refused."""
        expected, current = self._diverged.setdefault(
            session_id, (self._base.get(session_id), self.store.revision(session_id)))
        self._note(session_id, "divergence_unsaved", expected, current)

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
               content: str, *, state: dict | None = None,
               sent_at: str | None = None) -> tuple[ActionOutcome, str | None]:
        """Append one message, creating the transcript when session_id is None."""
        if role not in {"user", "assistant"} or not isinstance(content, str):
            return ActionOutcome("Message not saved.", "DENY", None, "message is malformed"), None
        clean = ChatSessionStore._sanitize_text(content)
        if len(clean.encode("utf-8")) > MAX_MESSAGE_BYTES:
            return ActionOutcome("Message not saved.", "DENY", None, "message is too large"), None
        creating = session_id is None
        target = uuid.uuid4().hex if creating else session_id
        try:
            clean_state = ChatSessionStore.validate_state(state) if state is not None else None
            extra = ({"state_sha256": _sha(json.dumps(clean_state, sort_keys=True))}
                     if clean_state is not None else {})
            request = ActionRequest("session.create", self.root, target, {
                "operation": "create" if creating else "append",
                "session_id": target, "role": role,
                "content_sha256": _sha(clean), "size": len(clean.encode("utf-8")),
                **extra,
            }, execution_owner="chat_sessions")
        except (TypeError, ValueError):
            return ActionOutcome("Message not saved.", "DENY", None, "invalid session request"), None
        denied = self._authorize(request)
        if denied is not None:
            return ActionOutcome("Message not saved.", "DENY", None, denied), None
        stamp = _owned_sent_at(sent_at)

        def build(existing: ChatSession | None) -> ChatSession:
            if existing is None:
                now = time.time()
                session = ChatSession(target, self.store._auto_title(clean) if role == "user"
                                      else "New session", [{"role": role, "content": clean,
                                          "sent_at": stamp}],
                                      now, now)
            else:
                session = existing
                session.messages.append({"role": role, "content": clean, "sent_at": stamp})
                if session.title in {"New session", "Draft conversation"} and role == "user":
                    session.title = self.store._auto_title(clean)
            if clean_state is not None:
                session.state = clean_state
            return session

        try:
            self._guarded_write(target, build, new=creating)
        except SessionDiverged as exc:
            return self._diverged_outcome("Message not saved.", exc), target
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

    def review(self, session_id: str) -> tuple[ActionOutcome, ChatSession | None, str | None]:
        """Load a transcript to show it (never re-bases), with the revision shown."""
        return self._load(session_id, track=False)

    def resume(self, session_id: str, *, track: bool = True) -> tuple[ActionOutcome, ChatSession | None]:
        outcome, session, _ = self._load(session_id, track=track)
        return outcome, session

    def _load(self, session_id: str, *, track: bool) -> tuple[ActionOutcome, ChatSession | None, str | None]:
        """Load a transcript. ``track`` makes it this instance's base for later writes.

        Looking at a transcript (export, delete review, fork source) uses
        track=False so it never refreshes the base of a continuity in progress.
        A transcript this instance marked diverged is only re-based through
        reload_saved, never by an incidental resume.
        """
        try:
            request = ActionRequest("session.resume", self.root, session_id, {
                "operation": "load", "session_id": session_id,
            }, execution_owner="chat_sessions")
        except (TypeError, ValueError):
            return ActionOutcome("Conversation unavailable.", "DENY", None,
                                 "invalid session request"), None, None
        denied = self._authorize(request)
        if denied is not None:
            return ActionOutcome("Conversation unavailable.", "DENY", None, denied), None, None
        try:
            session, revision = self.store.snapshot(session_id)
        except (OSError, ChatSessionError, ValueError) as exc:
            return ActionOutcome("Conversation unavailable.", "ERROR", None,
                                 f"transcript could not be read ({type(exc).__name__})"), None, None
        if track and session_id not in self._diverged:
            self._base[session_id] = revision
        receipt = self._receipt(request, f"load:{session_id}:{len(session.messages)}")
        if receipt is None:
            return ActionOutcome("Conversation unavailable.", "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable"), None, None
        return ActionOutcome("Conversation loaded.", "ALLOW", receipt, "transcript loaded"), session, revision

    def export(self, session_id: str) -> tuple[ActionOutcome, str | None]:
        outcome, session = self.resume(session_id, track=False)
        return outcome, self.store.serialize(session) if session is not None else None

    def manage(self, operation: str, session_id: str | None,
               data: str = "") -> tuple[ActionOutcome, str | None]:
        """Bounded, journaled lifecycle changes; imported data never grants authority."""
        if operation not in {"rename", "auto_title", "fork", "import", "state"} or not isinstance(data, str):
            return ActionOutcome("Session unchanged.", "DENY", None, "unsupported session operation"), None
        parent = None
        if operation != "import" and not (operation == "state" and session_id is None):
            outcome, parent = self.resume(session_id, track=False)
            if parent is None:
                return outcome, None
        clean = data if operation in {"state", "import"} else self.store._sanitize_text(data)
        if operation == "state":
            try:
                state = self.store.validate_state(json.loads(clean))
                clean = json.dumps(state, sort_keys=True)
            except (ValueError, TypeError):
                return ActionOutcome("Session unchanged.", "ERROR", None, "invalid session state"), None
        target = session_id if operation in {"rename", "auto_title", "state"} and session_id else uuid.uuid4().hex
        if operation == "import":
            try:
                imported = self.store.parse_import(data, session_id=target)
                clean = self.store.serialize(imported)
            except (ValueError, TypeError):
                return ActionOutcome("Session unchanged.", "ERROR", None, "invalid session import"), None
        if operation == "auto_title":
            count = sum(message.get("role") == "user" for message in parent.messages)
            if parent.title_manual or not 1 <= count <= 5:
                return ActionOutcome("Title unchanged.", "DENY", None,
                                     "automatic titles require the first five user messages and no manual title"), None
            clean = " ".join(clean.split())
            if not clean or len(clean) > 80 or not clean.isprintable():
                return ActionOutcome("Title unchanged.", "DENY", None, "title must contain 1–80 characters"), None
        request = ActionRequest("session.create", self.root, target, {
            "operation": operation, "session_id": target,
            "content_sha256": _sha(clean), "size": len(clean.encode("utf-8")),
            "source_id": session_id or "" if operation != "import" else "",
        }, execution_owner="chat_sessions")
        denied = self._authorize(request)
        if denied is not None:
            return ActionOutcome("Session unchanged.", "DENY", None, denied), None
        if operation in {"rename", "auto_title", "state"} and session_id:
            def build(existing: ChatSession) -> ChatSession:
                if operation == "auto_title":
                    # Recheck live state immediately before applying a proposed title.
                    if existing.title_manual or not 1 <= sum(
                            m.get("role") == "user" for m in existing.messages) <= 5:
                        raise _TitleWindowClosed()
                    existing.title = clean
                elif operation == "rename":
                    existing.title = self.store._clean_title(clean)
                    existing.title_manual = True
                else:
                    existing.state = state
                return existing
        else:
            def build(existing: None) -> ChatSession:
                now = time.time()
                if operation == "fork":
                    return ChatSession(target, self.store._auto_title(f"Fork: {parent.title}"),
                                       [dict(m) for m in parent.messages], now, now,
                                       self.store.validate_state(parent.state))
                if operation == "state":
                    session = ChatSession(target, "Draft conversation", [], now, now)
                    session.state = state
                    return session
                return imported
        try:
            session = self._guarded_write(target, build, new=target != session_id)
        except _TitleWindowClosed:
            return ActionOutcome("Title unchanged.", "DENY", None, "title window closed"), None
        except SessionDiverged as exc:
            return self._diverged_outcome("Session unchanged.", exc), None
        except (OSError, ValueError, TypeError) as exc:
            return ActionOutcome("Session unchanged.", "ERROR", None,
                                 f"session data rejected ({type(exc).__name__})"), None
        receipt = self._receipt(request, f"{operation}:{session.session_id}")
        if receipt is None:
            return ActionOutcome("Session changed without a durable receipt.", "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable"), None
        return ActionOutcome("Session updated.", "ALLOW", receipt, operation), session.session_id


__all__ = ["ChatSessionOwner", "LIST_TARGET", "MAX_MESSAGE_BYTES"]
