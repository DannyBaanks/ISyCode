"""Single canonical on-disk session context file per ISyCode conversation lane.

Keeps one stable Markdown file per conversation under the user's state directory
so user prompts, tool outcomes, partial/interrupted thoughts and replies, and
model switches survive Esc interruptions and provider/model changes, and can be
re-read directly by the active model (including via ``workspace_read`` in Flow).
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import threading
import uuid

from isycode.workspace_setup import ensure_state_root

MAX_FIELD_CHARS = 3500
MAX_REASONING_CHARS = 1200
MAX_TOOL_ARGS_CHARS = 300
MAX_TOOL_RESULT_CHARS = 900
DEFAULT_TAIL_CHARS = 12000
_SAFE_KEY_RE = re.compile(r"[^A-Za-z0-9._-]+")
_HEADER_MARKER = "<!-- isycode-session-turns -->"
_WRITE_LOCK = threading.Lock()


def fresh_session_context_key() -> str:
    """Return a unique, filesystem-safe session key for a fresh conversation."""
    return f"sess-{uuid.uuid4().hex[:12]}"


def sanitize_session_key(key: str | None) -> str:
    """Normalize a session or lane identifier to a safe file stem."""
    cleaned = _SAFE_KEY_RE.sub("-", str(key or "")).strip(".-")
    if not cleaned:
        return fresh_session_context_key()
    return cleaned[:96]


def workspace_context_bucket(workspace_root: Path | str) -> str:
    """Return a stable short hash identifying one workspace on disk."""
    try:
        canonical = str(Path(workspace_root).expanduser().resolve())
    except OSError:
        canonical = os.path.abspath(str(workspace_root))
    return hashlib.sha256(canonical.encode("utf-8", errors="replace")).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _clip(text: str | None, limit: int) -> str:
    raw = str(text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[:limit].rstrip() + "\n…[truncated]"


class SessionContextFile:
    """Manage one established Markdown session context file on disk."""

    def __init__(self, workspace_root: Path | str, session_key: str, *, mode: str = "classic"):
        self.workspace_root = Path(workspace_root)
        self.session_key = sanitize_session_key(session_key)
        self.mode = str(mode or "classic")
        self.directory = ensure_state_root() / "session-context" / workspace_context_bucket(self.workspace_root)
        self.path = self.directory / f"{self.session_key}.md"

    def ensure_initialized(self) -> Path:
        """Create the canonical session file with its header once if missing."""
        with _WRITE_LOCK:
            return self._ensure_initialized_locked()

    def _ensure_initialized_locked(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.directory, 0o700)
        except OSError:
            pass
        header = (
            "# ISyCode Session Context\n"
            f"- session_key: {self.session_key}\n"
            f"- workspace: {self.workspace_root}\n"
            f"- mode: {self.mode}\n"
            f"- created_at: {_now_iso()}\n"
            f"{_HEADER_MARKER}\n\n"
        )
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            return self.path
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(header)
        except OSError:
            pass
        return self.path

    def _append_block(self, block: str) -> bool:
        text = block.rstrip() + "\n\n"
        try:
            with _WRITE_LOCK:
                self._ensure_initialized_locked()
                fd = os.open(self.path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(text)
            return True
        except OSError:
            return False

    def has_entries(self) -> bool:
        """Return True when the file on disk has content beyond its initial header."""
        try:
            raw = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        if _HEADER_MARKER in raw:
            _, _, body = raw.partition(_HEADER_MARKER)
            return bool(body.strip())
        return bool(raw.strip())

    def append_user(self, text: str, *, provider: str = "", model: str = "", mode: str = "") -> bool:
        meta_parts = []
        if provider or model:
            meta_parts.append(f"model: {provider}/{model}".strip("/"))
        if mode or self.mode:
            meta_parts.append(f"mode: {mode or self.mode}")
        meta = f" ({' · '.join(meta_parts)})" if meta_parts else ""
        return self._append_block(
            f"## Turn — {_now_iso()} [user]{meta}\n\n{_clip(text, MAX_FIELD_CHARS)}"
        )

    def append_tool(self, tool_name: str, args_summary: str = "", result_summary: str = "") -> bool:
        lines = [f"### Tool `{tool_name or 'tool'}` ({_now_iso()})"]
        args_clipped = _clip(args_summary, MAX_TOOL_ARGS_CHARS)
        if args_clipped:
            lines.append(f"- args: `{args_clipped}`")
        result_clipped = _clip(result_summary, MAX_TOOL_RESULT_CHARS)
        if result_clipped:
            lines.append(f"- result:\n```text\n{result_clipped}\n```")
        return self._append_block("\n".join(lines))

    def append_assistant(
        self,
        text: str,
        *,
        reasoning: str = "",
        provider: str = "",
        model: str = "",
    ) -> bool:
        tag = f"{provider}/{model}".strip("/")
        suffix = f" [{tag}]" if tag else ""
        parts = [f"### Assistant ({_now_iso()}){suffix}"]
        reason_clipped = _clip(reasoning, MAX_REASONING_CHARS)
        if reason_clipped:
            parts.append(f"Reasoning excerpt:\n{reason_clipped}")
        answer_clipped = _clip(text, MAX_FIELD_CHARS)
        if answer_clipped:
            parts.append(answer_clipped)
        return self._append_block("\n\n".join(parts))

    def append_interrupted(
        self,
        kind: str,
        *,
        provider: str = "",
        model: str = "",
        partial_text: str = "",
        partial_reasoning: str = "",
        error_reason: str = "",
    ) -> bool:
        tag = f"{provider}/{model}".strip("/")
        meta = f" · model: {tag}" if tag else ""
        parts = [f"### Interrupted ({_now_iso()} · {kind}{meta})"]
        if error_reason:
            parts.append(f"- status: {_clip(error_reason, 400)}")
        reason_clipped = _clip(partial_reasoning, MAX_REASONING_CHARS)
        if reason_clipped:
            parts.append(f"Partial reasoning:\n{reason_clipped}")
        partial_clipped = _clip(partial_text, MAX_FIELD_CHARS)
        if partial_clipped:
            parts.append(f"Partial answer:\n{partial_clipped}")
        elif not reason_clipped:
            parts.append("_Turn stopped before any answer text was streamed; user prompt above remains active context._")
        return self._append_block("\n\n".join(parts))

    def append_model_switch(self, provider: str, model: str) -> bool:
        tag = f"{provider}/{model}".strip("/")
        return self._append_block(f"> **[Model switched]** -> `{tag}` ({_now_iso()})")

    def seed_from_messages(self, messages: list[dict]) -> bool:
        """Populate a newly opened session file when resuming a legacy session without one."""
        if self.has_entries():
            return False
        if not messages:
            return False
        chunks = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").strip().lower()
            content = str(msg.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            label = "user" if role == "user" else "assistant"
            chunks.append(f"### History [{label}]\n\n{_clip(content, MAX_FIELD_CHARS)}")
        if not chunks:
            return False
        return self._append_block("\n\n".join(chunks))

    def read_tail(self, max_chars: int = DEFAULT_TAIL_CHARS) -> str:
        """Read the current on-disk session body, bounded cleanly to the latest tail."""
        try:
            raw = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        if _HEADER_MARKER in raw:
            _, _, body = raw.partition(_HEADER_MARKER)
        else:
            body = raw
        body = body.strip()
        if not body:
            return ""
        if len(body) <= max_chars:
            return body
        tail = body[-max_chars:]
        newline = tail.find("\n")
        if 0 <= newline < len(tail) - 1:
            tail = tail[newline + 1 :]
        return f"…[earlier entries omitted; full file: {self.path}]\n\n{tail.lstrip()}"

    def file_digest(self) -> str:
        """Return a short sha256 digest of the session file on disk, or empty if missing."""
        try:
            data = self.path.read_bytes()
        except OSError:
            return ""
        return hashlib.sha256(data).hexdigest()[:16]

    @staticmethod
    def _has_continuity_gap(tail: str) -> bool:
        """True when the file contains interrupted turns or a recent model switch."""
        if not tail:
            return False
        if "### Interrupted (" in tail:
            return True
        last_marker = tail.rfind("> **[Model switched]**")
        last_assistant = tail.rfind("### Assistant (")
        return last_marker > last_assistant

    def should_inject_excerpt(
        self,
        tail: str,
        *,
        history_len: int,
        last_digest: str = "",
    ) -> bool:
        """True when the model needs the on-disk excerpt injected alongside the turn."""
        if not tail:
            return False
        if history_len <= 1:
            return True
        if last_digest and self.file_digest() != last_digest:
            return True
        return self._has_continuity_gap(tail)
