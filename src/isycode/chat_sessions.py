"""Private, resumable chat transcripts separate from IsyMotron plan receipts."""
from __future__ import annotations

import hashlib
import json
import html
import os
import re
import stat
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ChatSessionError(ValueError):
    """A chat transcript is malformed or cannot be stored safely."""


class SessionDiverged(ChatSessionError):
    """The transcript on disk is no longer the one this instance loaded or last wrote.

    Another continuity (another ISyCode window or process) changed it. Nothing was
    written; the caller must let the user choose instead of overwriting or merging.
    """

    def __init__(self, session_id: str, expected: str | None, current: str | None):
        super().__init__("chat session changed elsewhere since it was loaded")
        self.session_id = session_id
        self.expected = expected
        self.current = current


# Anything other than this means "write only if the file still has exactly this
# revision"; None as an expectation means "only if the file does not exist yet".
UNCHECKED = object()


def revision_of(payload: bytes | None) -> str | None:
    """Fingerprint of the persisted bytes: the whole transcript, state included."""
    return None if payload is None else hashlib.sha256(payload).hexdigest()


class _DirectoryLock:
    """One exclusive lock per session directory, held across check and write.

    Threads in this process serialize on the RLock (and may re-enter it); other
    processes block on the OS lock of ``.write.lock``. The kernel drops the OS
    lock if the holder dies, so a crash cannot leave the directory locked.
    Linux/macOS use flock; Windows uses msvcrt.locking (not demonstrated there).
    """

    _registry: dict[str, "_DirectoryLock"] = {}
    _registry_guard = threading.Lock()

    def __init__(self, path: Path):
        self.path = path
        self.rlock = threading.RLock()
        self.depth = 0
        self.descriptor: int | None = None

    @classmethod
    def for_directory(cls, root: Path) -> "_DirectoryLock":
        path = root / ".write.lock"
        with cls._registry_guard:
            return cls._registry.setdefault(str(path), cls(path))

    def _acquire_os(self) -> None:
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ChatSessionError("session write lock is not a regular file")
            try:
                import fcntl
            except ImportError:  # Windows
                import msvcrt
                while True:
                    try:
                        msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
                        break
                    except OSError:  # LK_LOCK gives up after ~10 s; keep waiting
                        continue
            else:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
        except BaseException:
            os.close(descriptor)
            raise
        self.descriptor = descriptor

    def _release_os(self) -> None:
        descriptor, self.descriptor = self.descriptor, None
        if descriptor is None:
            return
        try:
            try:
                import fcntl
            except ImportError:  # Windows
                import msvcrt
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    @contextmanager
    def held(self):
        with self.rlock:
            if self.depth == 0:
                self._acquire_os()
            self.depth += 1
            try:
                yield
            finally:
                self.depth -= 1
                if self.depth == 0:
                    self._release_os()


@dataclass
class ChatSession:
    session_id: str
    title: str
    messages: list[dict[str, str]]
    created_at: float
    updated_at: float
    state: dict[str, Any] = field(default_factory=dict)
    title_manual: bool = False


class ChatSessionStore:
    """Atomically store chat history under a private, external state directory."""

    _SESSION_ID = re.compile(r"^[a-f0-9]{32}$")
    _SECRET_VALUE = re.compile(
        r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|authorization)"
        r"([\"']?\s*[:=]\s*)(\"(?:[^\"\\]|\\.)*\"|'[^']*'|[^\s,;]+)"
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
        self._lock = _DirectoryLock.for_directory(self.root)

    def write_lock(self):
        """Hold the directory's write lock; every mutation of a transcript runs inside it."""
        return self._lock.held()

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
        self.save(session, expected_revision=None)
        return session

    def save(self, session: ChatSession, *, expected_revision: object = UNCHECKED) -> Path:
        """Atomically write a transcript under the directory lock.

        With ``expected_revision`` the write happens only if the file on disk still
        has exactly that revision (None: only if it does not exist); otherwise
        SessionDiverged is raised and nothing is written.
        """
        with self.write_lock():
            if expected_revision is not UNCHECKED:
                current = self.revision(session.session_id)
                if current != expected_revision:
                    raise SessionDiverged(session.session_id, expected_revision, current)
            path, self.last_revision = self._write(session)
            return path

    def _write(self, session: ChatSession) -> tuple[Path, str]:
        state = self.validate_state(session.state)
        for message in session.messages:
            if (not isinstance(message, dict)
                    or message.get("role") not in {"user", "assistant"}
                    or not isinstance(message.get("content"), str)):
                raise ChatSessionError("chat message is malformed")
            self._validate_sent_at(message)
        session.updated_at = time.time()
        target = self._path(session.session_id)
        payload = json.dumps({
            "version": 2,
            "session_id": session.session_id,
            "title": session.title,
            "messages": session.messages,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "state": state,
            "title_manual": session.title_manual,
        }, ensure_ascii=False, allow_nan=False)
        data = payload.encode("utf-8")
        fd, temporary = tempfile.mkstemp(prefix=f".{session.session_id}-", dir=self.root)
        try:
            if os.name == "posix":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target, revision_of(data)

    def append(self, session_id: str, role: str, content: str) -> ChatSession:
        if role not in {"user", "assistant"} or not isinstance(content, str):
            raise ChatSessionError("chat message is malformed")
        with self.write_lock():
            session = self.load(session_id)
            session.messages.append({"role": role, "content": content})
            if session.title in {"New session", "Draft conversation"} and role == "user":
                session.title = self._auto_title(content)
            self.save(session)
        return session

    def _read_bytes(self, session_id: str) -> bytes | None:
        """The exact persisted bytes, or None if the transcript does not exist."""
        path = self._path(session_id)
        # Opening a FIFO must not block before fstat can reject it. O_NONBLOCK
        # does not change regular-file reads and also closes the lstat/open race.
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ChatSessionError("chat session is not a bounded regular file")
            return stream.read()

    def revision(self, session_id: str) -> str | None:
        """Fingerprint of the transcript as it is on disk right now (None if absent)."""
        return revision_of(self._read_bytes(session_id))

    def snapshot(self, session_id: str) -> tuple[ChatSession, str]:
        """Load a transcript together with the revision of exactly those bytes."""
        with self.write_lock():
            payload = self._read_bytes(session_id)
            if payload is None:
                raise FileNotFoundError(session_id)
            return self._parse(session_id, payload), revision_of(payload)

    def load(self, session_id: str) -> ChatSession:
        raw = self._read_bytes(session_id)
        if raw is None:
            raise FileNotFoundError(str(self._path(session_id)))
        return self._parse(session_id, raw)

    def _parse(self, session_id: str, raw: bytes) -> ChatSession:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ChatSessionError("chat session is not valid UTF-8 JSON") from exc
        if (not isinstance(payload, dict) or type(payload.get("version")) is not int or payload.get("version") not in {1, 2}
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
        for message in messages:
            self._validate_sent_at(message)
        return ChatSession(session_id, payload["title"], messages,
                           float(payload["created_at"]), float(payload["updated_at"]),
                           self.validate_state(payload.get("state", {})),
                           payload.get("title_manual") is True)

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

    def delete(self, session_id: str, *, expected_revision: object = UNCHECKED) -> None:
        path = self._path(session_id)
        with self.write_lock():
            if expected_revision is not UNCHECKED:
                current = self.revision(session_id)
                if current != expected_revision:
                    raise SessionDiverged(session_id, expected_revision, current)
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ChatSessionError("refusing to delete a non-regular chat session")
            path.unlink()

    @staticmethod
    def _clean_title(title: str) -> str:
        if not isinstance(title, str):
            raise ChatSessionError("session title must be text")
        cleaned = " ".join("".join(char if char.isprintable() else " " for char in title).split())
        if not cleaned or len(cleaned) > 80:
            raise ChatSessionError("session title must contain 1–80 printable characters")
        return cleaned

    def rename(self, session_id: str, title: str) -> ChatSession:
        cleaned = self._clean_title(title)
        with self.write_lock():
            session = self.load(session_id)
            session.title = cleaned
            session.title_manual = True
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
        child.state = self.validate_state(parent.state)
        if through_message is not None and through_message < len(parent.messages) - 1:
            # Later notes have no message boundary and may reveal excluded turns.
            child.state.pop("tool_history", None)
            child.state.pop("conversation_summary", None)
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
        # Redact bearer values before key/value matching consumes "Bearer" and
        # leaves the actual credential orphaned after Authorization:.
        value = cls._BEARER_VALUE.sub("Bearer [redacted]", value)
        value = cls._SECRET_VALUE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", value)
        return cls._API_TOKEN.sub("[redacted]", value)

    def export_json(self, session_id: str, *, sanitize: bool = True) -> str:
        session = self.load(session_id)
        return self.serialize(session, sanitize=sanitize)

    def export_html(self, session_id: str, *, sanitize: bool = True) -> str:
        """Return a self-contained local review document; never uploads it."""
        session = self.load(session_id)
        title = self._sanitize_text(session.title) if sanitize else session.title
        parts = [
            "<!doctype html>",
            '<html lang="en"><head><meta charset="utf-8">',
            f"<title>{html.escape(title)}</title>",
            "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;"
            "padding:0 1rem;background:#17171b;color:#eceaf1}article{border:1px solid #45424e;"
            "border-radius:10px;padding:1rem;margin:1rem 0}pre{white-space:pre-wrap;word-break:break-word}"
            ".role{opacity:.72;font-size:.85rem;text-transform:uppercase}</style></head><body>",
            f"<h1>{html.escape(title)}</h1>",
        ]
        for message in session.messages:
            content = message["content"]
            if sanitize:
                content = self._sanitize_text(content)
            role = html.escape(message["role"])
            parts.append(
                f'<article><div class="role">{role}</div><pre>{html.escape(content)}</pre></article>')
        parts.append("</body></html>")
        return "\n".join(parts)

    @classmethod
    def serialize(cls, session: ChatSession, *, sanitize: bool = True) -> str:
        messages = [dict(item) for item in session.messages]
        title = session.title
        if sanitize:
            title = cls._sanitize_text(title)
            messages = [{**({"sent_at": item["sent_at"]} if "sent_at" in item else {}),
                         "role": item["role"],
                         "content": cls._sanitize_text(item["content"])}
                        for item in messages]
        payload = {
            "version": 2,
            "session_id": session.session_id,
            "title": title,
            "messages": messages,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "state": cls.validate_state(session.state),
        }
        return json.dumps(payload, ensure_ascii=False, allow_nan=False)

    def import_json(self, serialized: str, *, session_id: str | None = None) -> ChatSession:
        imported = self.parse_import(serialized, session_id=session_id)
        self.save(imported, expected_revision=None)
        return imported

    def parse_import(self, serialized: str, *, session_id: str | None = None) -> ChatSession:
        if not isinstance(serialized, str):
            raise ChatSessionError("session import is malformed")
        try:
            payload = json.loads(serialized)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ChatSessionError("session import is not valid JSON") from exc
        if (not isinstance(payload, dict) or type(payload.get("version")) is not int or payload.get("version") not in {1, 2}
                or not isinstance(payload.get("title"), str)
                or not isinstance(payload.get("messages"), list)):
            raise ChatSessionError("session import has an unsupported structure")
        messages = payload["messages"]
        if any(not isinstance(message, dict)
               or message.get("role") not in {"user", "assistant"}
               or not isinstance(message.get("content"), str) for message in messages):
            raise ChatSessionError("session import contains malformed messages")
        state = self.validate_state(payload.get("state", {}))
        clean_title = self._sanitize_text(" ".join(payload["title"].split())[:80]) or "Imported session"
        now = time.time()
        imported = ChatSession(session_id or uuid.uuid4().hex, clean_title, [], now, now)
        for message in messages:
            self._validate_sent_at(message)
        imported.messages = [{**({"sent_at": message["sent_at"]} if "sent_at" in message else {}),
                              "role": message["role"], "content": self._sanitize_text(message["content"])}
                             for message in messages]
        imported.state = state
        return imported

    @staticmethod
    def _validate_sent_at(message: dict) -> None:
        if "sent_at" not in message:
            return
        value = message["sent_at"]
        try:
            if not isinstance(value, str) or len(value) > 40 or datetime.fromisoformat(value).tzinfo is None:
                raise ValueError("invalid local timestamp")
        except ValueError as exc:
            raise ChatSessionError("message sent_at is not an offset timestamp") from exc

    @classmethod
    def validate_state(cls, state: Any) -> dict[str, Any]:
        """Portable preferences and untrusted notes; never import authority or calls."""
        from isycode.providers import PRESETS
        if not isinstance(state, dict) or set(state) - {"provider", "model", "role", "context_path", "draft",
                                                       "tool_history", "conversation_summary", "usage", "idea_box"}:
            raise ChatSessionError("session state has unsupported fields")
        provider = state.get("provider")
        if provider is not None and (not isinstance(provider, str) or provider not in PRESETS):
            raise ChatSessionError("session provider is invalid")
        model = state.get("model")
        if model is not None and (not isinstance(model, str) or not 1 <= len(model) <= 256
                                  or not re.fullmatch(r"[A-Za-z0-9._:/-]+", model)
                                  or cls._sanitize_text(model) != model):
            raise ChatSessionError("session model is invalid")
        role = state.get("role")
        if role is not None and (not isinstance(role, dict) or set(role) != {"kind", "name"}
                                 or not isinstance(role.get("kind"), str)
                                 or role.get("kind") not in {"agents", "subagents", "motors"}
                                 or not isinstance(role.get("name"), str)
                                 or not 1 <= len(role["name"]) <= 120
                                 or not role["name"].isprintable()
                                 or cls._sanitize_text(role["name"]) != role["name"]):
            raise ChatSessionError("session role is invalid")
        if state.get("context_path") is not None and state.get("context_path") != "AGENTS.md":
            raise ChatSessionError("session context must reference workspace AGENTS.md")
        clean = json.loads(json.dumps(state))
        if "usage" in clean:
            from isycode.usage import UsageLedger
            try:
                clean["usage"] = UsageLedger.from_state(clean["usage"]).to_state()
            except ValueError as exc:
                raise ChatSessionError("session usage is invalid") from exc
        if "draft" in clean:
            if not isinstance(clean["draft"], str):
                raise ChatSessionError("session draft is malformed")
            clean["draft"] = cls._sanitize_text(clean["draft"])
        if "tool_history" in clean:
            from isycode.tool_history import normalize_tool_history
            clean["tool_history"] = normalize_tool_history(clean["tool_history"])
        if "conversation_summary" in clean:
            summary = clean["conversation_summary"]
            if not isinstance(summary, str):
                raise ChatSessionError("session conversation summary is malformed")
            from isycode.tool_history import sanitize_historical_text
            clean["conversation_summary"] = sanitize_historical_text(summary)
        if "idea_box" in clean:
            idea = clean["idea_box"]
            if not isinstance(idea, str) or len(idea) > 2000:
                raise ChatSessionError("session idea box is malformed")
            from isycode.tool_history import sanitize_historical_text
            clean["idea_box"] = sanitize_historical_text(idea)
        return clean
