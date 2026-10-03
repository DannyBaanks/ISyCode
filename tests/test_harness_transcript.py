import json
from pathlib import Path

import pytest

from isycode.harness_readers.transcript import (
    MAX_FILE_BYTES,
    MAX_MESSAGE_CHARS,
    MAX_MESSAGES,
    MAX_TOTAL_CHARS,
    read_transcript,
    transcript_candidates,
)
from tests.harness_reader_helpers import FIXTURES


def _write_jsonl(root: Path, messages: list[dict]) -> str:
    relative = "sessions/project/session/chat_history.jsonl"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(item) + "\n" for item in messages), encoding="utf-8")
    return relative


def test_grok_transcript_candidate_is_explicit_and_other_index_bodies_stay_locked():
    assert transcript_candidates("grok", FIXTURES / "grok") == [
        "sessions/project/session/chat_history.jsonl"
    ]
    for harness_id in ("claude", "codex", "hermes", "fx", "pi", "kimi", "openclaw"):
        assert transcript_candidates(harness_id, FIXTURES / harness_id) == []


def test_transcript_reader_keeps_only_user_assistant_and_one_skipped_role_line():
    copy = read_transcript(
        FIXTURES / "grok", "sessions/project/session/chat_history.jsonl")
    assert copy.messages == (
        {"role": "user", "content": "body must not enter graph"},
        {"role": "assistant", "content": "fixture assistant reply"},
        {"role": "user", "content": "Tool or system text was not imported."},
    )
    assert copy.source_messages == 3


def test_transcript_reader_caps_message_count_and_each_message(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    messages = [
        {"role": "user", "content": "x" * (MAX_MESSAGE_CHARS + 500)}
    ] + [
        {"role": "assistant", "content": f"message-{index}"}
        for index in range(MAX_MESSAGES + 20)
    ]
    relative = _write_jsonl(root, messages)
    copy = read_transcript(root, relative)
    assert len(copy.messages) == MAX_MESSAGES
    assert len(copy.messages[0]["content"]) <= MAX_MESSAGE_CHARS
    assert copy.messages[0]["content"].endswith("…[truncated]")
    assert copy.truncated_chars > 0


def test_transcript_reader_caps_total_characters(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    relative = _write_jsonl(root, [
        {"role": "user", "content": "z" * 3000}
        for _ in range(100)
    ])
    copy = read_transcript(root, relative)
    assert sum(len(item["content"]) for item in copy.messages) <= MAX_TOTAL_CHARS
    assert copy.truncated_chars > 0


def test_transcript_reader_sanitizes_before_return(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    relative = _write_jsonl(root, [{"role": "user", "content": "api_key=very-secret-value"}])
    copy = read_transcript(root, relative)
    assert "very-secret-value" not in copy.messages[0]["content"]
    assert "[redacted]" in copy.messages[0]["content"]


def test_transcript_reader_refuses_oversize_or_symlink_file(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    relative = "sessions/project/session/chat_history.jsonl"
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(ValueError, match="too large"):
        read_transcript(root, relative)

    path.unlink()
    target = tmp_path / "outside.jsonl"
    target.write_text('{"role":"user","content":"outside"}\n', encoding="utf-8")
    path.symlink_to(target)
    with pytest.raises(ValueError, match="unavailable"):
        read_transcript(root, relative)
