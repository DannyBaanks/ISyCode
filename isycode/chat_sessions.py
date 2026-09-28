"""Private, resumable chat transcripts separate from IsyMotron plan receipts."""
from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ChatSessionError(ValueError):
    """A chat transcript is malformed or cannot be stored safely."""


@dataclass
class ChatSession:
    session_id: str
    title: str
    messages: list[dict[str, str]]
    created_at: float
    updated_at: float


class ChatSessionStore:
    """Atomically store chat history under a private, external state directory."""

    _SESSION_ID = re.compile(r"^[a-f0-9]{32}$")
    MAX_BYTES = 4_000_000
    MAX_MESSAGES = 20_000
    _SECRET_VALUE = re.compile(
        r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|authorization)"
        r"(\s*[:=]\s*)([^\s,;]+)"
    )
    _BEARER_VALUE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}={0,2}")
    _API_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("chat session store root must be a real directory, not a symlink")
        self.root = self.root.resolve(strict=True)
        if os.name == "posix":
            self.root.chmod(0o700)

    def _path(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not self._SESSION_ID.fullmatch(session_id):
            raise ValueError("invalid chat session id")
        return self.root / f"{session_id}.json"

    @staticmethod
    def _auto_title(prompt: str) -> str:
        clean = " ".join("".join(
            char if char.isprintable() else " " for char in prompt).split())
        clean = clean.lstrip("/ ").strip()
        clean = re.split(r"(?<=[.!?])\s", clean, maxsplit=1)[0]
        if not clean:
            return "New session"
        if len(clean) > 64:
            return clean[:61].rstrip() + "…"
        return clean

    def create(self, first_prompt: str = "") -> ChatSession:
        now = time.time()
        session = ChatSession(uuid.uuid4().hex, self._auto_title(first_prompt), [], now, now)
        self.save(session)
        return session

    def save(self, session: ChatSession) -> Path:
        if len(session.messages) > self.MAX_MESSAGES:
            raise ChatSessionError("chat session exceeds the message limit")
        for message in session.messages:
            if (not isinstance(message, dict)
                    or message.get("role") not in {"user", "assistant"}
                    or not isinstance(message.get("content"), str)):
                raise ChatSessionError("chat message is malformed")
        session.updated_at = time.time()
        target = self._path(session.session_id)
        payload = json.dumps({
            "version": 1,
            "session_id": session.session_id,
            "title": session.title,
            "messages": session.messages,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }, ensure_ascii=False, allow_nan=False)
        if len(payload.encode("utf-8")) > self.MAX_BYTES:
            raise ChatSessionError("chat session exceeds the 4 MB storage limit")
        fd, temporary = tempfile.mkstemp(prefix=f".{session.session_id}-", dir=self.root)
        try:
            if os.name == "posix":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target

    def append(self, session_id: str, role: str, content: str) -> ChatSession:
        if role not in {"user", "assistant"} or not isinstance(content, str):
            raise ChatSessionError("chat message is malformed")
        session = self.load(session_id)
        session.messages.append({"role": role, "content": content})
        if session.title == "New session" and role == "user":
            session.title = self._auto_title(content)
        self.save(session)
        return session

    def load(self, session_id: str) -> ChatSession:
        path = self._path(session_id)
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > self.MAX_BYTES:
                raise ChatSessionError("chat session is not a bounded regular file")
            try:
                payload = json.load(stream)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ChatSessionError("chat session is not valid UTF-8 JSON") from exc
        if (not isinstance(payload, dict) or payload.get("version") != 1
                or payload.get("session_id") != session_id
                or not isinstance(payload.get("title"), str)
                or not isinstance(payload.get("messages"), list)
                or not isinstance(payload.get("created_at"), (int, float))
                or not isinstance(payload.get("updated_at"), (int, float))):
            raise ChatSessionError("chat session has an invalid structure")
        messages = payload["messages"]
        if any(not isinstance(message, dict)
               or message.get("role") not in {"user", "assistant"}
               or not isinstance(message.get("content"), str) for message in messages):
            raise ChatSessionError("chat session contains malformed messages")
        return ChatSession(session_id, payload["title"], messages,
                           float(payload["created_at"]), float(payload["updated_at"]))

    def list_sessions(self) -> list[ChatSession]:
        sessions = []
        for path in self.root.glob("*.json"):
            if not self._SESSION_ID.fullmatch(path.stem):
                continue
            try:
                sessions.append(self.load(path.stem))
            except (OSError, ChatSessionError, ValueError):
                continue
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    def delete(self, session_id: str) -> None:
        path = self._path(session_id)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ChatSessionError("refusing to delete a non-regular chat session")
        path.unlink()

    def rename(self, session_id: str, title: str) -> ChatSession:
        if not isinstance(title, str):
            raise ChatSessionError("session title must be text")
        cleaned = " ".join("".join(char if char.isprintable() else " " for char in title).split())
        if not cleaned or len(cleaned) > 80:
            raise ChatSessionError("session title must contain 1–80 printable characters")
        session = self.load(session_id)
        session.title = cleaned
        self.save(session)
        return session

    def fork(self, session_id: str, *, through_message: int | None = None) -> ChatSession:
        parent = self.load(session_id)
        if through_message is None:
            messages = list(parent.messages)
        elif not isinstance(through_message, int) or not -1 <= through_message < len(parent.messages):
            raise ChatSessionError("fork message index is outside the transcript")
        else:
            messages = list(parent.messages[:through_message + 1])
        child = self.create(f"Fork: {parent.title}")
        child.messages = messages
        self.save(child)
        return child

    def search(self, query: str) -> list[ChatSession]:
        terms = [part.casefold() for part in query.split()]
        if not terms:
            return []
        matches = []
        for session in self.list_sessions():
            transcript = " ".join(
                [session.title] + [message["content"] for message in session.messages]
            ).casefold()
            if all(term in transcript for term in terms):
                matches.append(session)
        return matches

    @classmethod
    def _sanitize_text(cls, value: str) -> str:
        value = cls._SECRET_VALUE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", value)
        value = cls._BEARER_VALUE.sub("Bearer [redacted]", value)
        return cls._API_TOKEN.sub("[redacted]", value)

    def export_json(self, session_id: str, *, sanitize: bool = True) -> str:
        session = self.load(session_id)
        messages = [dict(item) for item in session.messages]
        title = session.title
        if sanitize:
            title = self._sanitize_text(title)
            messages = [{"role": item["role"],
                         "content": self._sanitize_text(item["content"])}
                        for item in messages]
        payload = {
            "version": 1,
            "session_id": session.session_id,
            "title": title,
            "messages": messages,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }
        return json.dumps(payload, ensure_ascii=False, allow_nan=False)

    def import_json(self, serialized: str) -> ChatSession:
        if not isinstance(serialized, str) or len(serialized.encode("utf-8")) > self.MAX_BYTES:
            raise ChatSessionError("session import exceeds the storage limit")
        try:
            payload = json.loads(serialized)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ChatSessionError("session import is not valid JSON") from exc
        if (not isinstance(payload, dict) or payload.get("version") != 1
                or not isinstance(payload.get("title"), str)
                or not isinstance(payload.get("messages"), list)):
            raise ChatSessionError("session import has an unsupported structure")
        messages = payload["messages"]
        if any(not isinstance(message, dict)
               or message.get("role") not in {"user", "assistant"}
               or not isinstance(message.get("content"), str) for message in messages):
            raise ChatSessionError("session import contains malformed messages")
        if len(messages) > self.MAX_MESSAGES:
            raise ChatSessionError("session import exceeds the message limit")
        clean_title = " ".join(payload["title"].split())[:80] or "Imported session"
        imported = self.create(clean_title)
        imported.messages = [dict(message) for message in messages]
        self.save(imported)
        return imported
