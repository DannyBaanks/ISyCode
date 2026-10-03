"""Bounded transcript text reader for explicitly reviewed harness sources."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from isycode.chat_sessions import ChatSessionStore
from isycode.harness_readers._shared import safe_file


MAX_MESSAGES = 200
MAX_MESSAGE_CHARS = 8_000
MAX_TOTAL_CHARS = 200_000
MAX_FILE_BYTES = 1_048_576
TRUNCATED = "…[truncated]"
SKIPPED_ROLE = "Tool or system text was not imported."


@dataclass(frozen=True)
class TranscriptCopy:
    messages: tuple[dict[str, str], ...]
    source_messages: int
    truncated_chars: int


def _reviewed_relative_path(relative_path: str) -> tuple[str, ...]:
    path = Path(relative_path)
    if path.is_absolute():
        raise ValueError("transcript path is outside the reviewed allowlist")
    parts = path.parts
    if (len(parts) != 4 or parts[0] != "sessions"
            or parts[3] != "chat_history.jsonl"
            or any(part in {"", ".", ".."} for part in parts)):
        raise ValueError("transcript path is outside the reviewed allowlist")
    return parts


def transcript_candidates(harness_id: str, root: Path) -> list[str]:
    """Return only concrete transcript files whose body schema is reviewed in v1."""
    if harness_id != "grok":
        return []
    root = Path(root)
    candidates: list[tuple[float, str]] = []
    try:
        paths = root.glob("sessions/*/*/chat_history.jsonl")
        for path in paths:
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            safe = safe_file(root, *relative.parts)
            if safe is None:
                continue
            try:
                stamp = safe.stat().st_mtime
            except OSError:
                continue
            candidates.append((stamp, relative.as_posix()))
    except OSError:
        return []
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [relative for _, relative in candidates]


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= len(TRUNCATED):
        return text[:limit]
    return text[: limit - len(TRUNCATED)] + TRUNCATED


def read_transcript(root: Path, relative_path: str) -> TranscriptCopy:
    """Read inert role/content JSONL under strict size and message caps."""
    parts = _reviewed_relative_path(relative_path)
    path = safe_file(Path(root), *parts)
    if path is None:
        raise ValueError("transcript file is unavailable")
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError("transcript file is unavailable") from exc
    if info.st_size > MAX_FILE_BYTES:
        raise ValueError("transcript file is too large")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("transcript file is unavailable") from exc

    messages: list[dict[str, str]] = []
    source_messages = 0
    truncated_chars = 0
    total_chars = 0
    skipped_role_added = False
    for line in text.splitlines():
        if len(messages) >= MAX_MESSAGES or total_chars >= MAX_TOTAL_CHARS:
            break
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            continue
        source_messages += 1
        if role not in {"user", "assistant"}:
            if skipped_role_added:
                continue
            role = "user"
            clean = SKIPPED_ROLE
            skipped_role_added = True
        else:
            clean = ChatSessionStore._sanitize_text(content)

        per_message = _truncate(clean, MAX_MESSAGE_CHARS)
        remaining = MAX_TOTAL_CHARS - total_chars
        final = _truncate(per_message, remaining)
        truncated_chars += max(0, len(clean) - len(final))
        if not final:
            break
        messages.append({"role": role, "content": final})
        total_chars += len(final)

    return TranscriptCopy(tuple(messages), source_messages, truncated_chars)


__all__ = [
    "MAX_FILE_BYTES", "MAX_MESSAGE_CHARS", "MAX_MESSAGES", "MAX_TOTAL_CHARS",
    "TranscriptCopy", "read_transcript", "transcript_candidates",
]
