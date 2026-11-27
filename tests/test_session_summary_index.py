"""The conversation list reads a stat-keyed summary cache, never stale rows."""
import json
import os

import pytest

from isycode.chat_sessions import ChatSessionStore, SessionSummary


def _expected(store):
    return [SessionSummary.of(session) for session in store.list_sessions()]


def _store(tmp_path):
    store = ChatSessionStore(tmp_path / "sessions")
    first = store.create("first question")
    store.append(first.session_id, "user", "hola")
    store.append(first.session_id, "assistant", "respuesta " * 10)
    second = store.create("second")
    second.state = {"provider": "openai", "model": "gpt-test"}
    store.save(second)
    return store, first, second


def test_summaries_match_full_listing_cold_and_warm(tmp_path):
    store, first, second = _store(tmp_path)
    assert store.list_summaries() == _expected(store)
    index = store.root / ".summary-index"
    assert index.is_file()
    if os.name == "posix":
        assert index.stat().st_mode & 0o777 == 0o600
    assert store.list_summaries() == _expected(store)
    row = next(item for item in store.list_summaries() if item.session_id == first.session_id)
    assert (row.message_count, row.last_role, row.context_chars) == (2, "assistant", 4 + 100)
    other = next(item for item in store.list_summaries() if item.session_id == second.session_id)
    assert (other.model, other.provider, other.last_role) == ("gpt-test", "openai", "")


def test_a_changed_transcript_is_parsed_again(tmp_path):
    store, first, _ = _store(tmp_path)
    store.list_summaries()
    store.append(first.session_id, "user", "nuevo")
    row = next(item for item in store.list_summaries() if item.session_id == first.session_id)
    assert (row.message_count, row.last_content) == (3, "nuevo")
    store.delete(first.session_id)
    assert first.session_id not in {item.session_id for item in store.list_summaries()}
    assert first.session_id not in json.loads((store.root / ".summary-index").read_text())["entries"]


def test_a_forged_index_row_with_a_wrong_key_is_ignored(tmp_path):
    store, first, _ = _store(tmp_path)
    store.list_summaries()
    path = store.root / ".summary-index"
    payload = json.loads(path.read_text())
    payload["entries"][first.session_id]["summary"]["title"] = "forged"
    payload["entries"][first.session_id]["key"][1] += 1
    path.write_text(json.dumps(payload))
    path.chmod(0o600)
    assert "forged" not in {item.title for item in store.list_summaries()}


@pytest.mark.parametrize("content", [b"not json", b'{"version": 1, "entries": []}',
                                     b'{"version": 9, "entries": {}}'])
def test_a_corrupt_index_is_rebuilt(tmp_path, content):
    store, _, _ = _store(tmp_path)
    path = store.root / ".summary-index"
    path.write_bytes(content)
    path.chmod(0o600)
    assert store.list_summaries() == _expected(store)
    assert json.loads(path.read_text())["version"] == 1


def test_a_malformed_cached_row_is_parsed_again(tmp_path):
    store, first, _ = _store(tmp_path)
    store.list_summaries()
    path = store.root / ".summary-index"
    payload = json.loads(path.read_text())
    payload["entries"][first.session_id]["summary"]["message_count"] = True
    path.write_text(json.dumps(payload))
    path.chmod(0o600)
    assert store.list_summaries() == _expected(store)


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlinks")
def test_a_symlinked_index_is_not_followed(tmp_path):
    store, first, _ = _store(tmp_path)
    store.list_summaries()
    path = store.root / ".summary-index"
    payload = json.loads(path.read_text())
    payload["entries"][first.session_id]["summary"]["title"] = "foreign"
    decoy = tmp_path / "decoy"
    decoy.write_text(json.dumps(payload))
    decoy.chmod(0o600)
    path.unlink()
    path.symlink_to(decoy)
    assert "foreign" not in {item.title for item in store.list_summaries()}
    assert not path.is_symlink()


def test_a_long_last_message_is_capped_and_flagged(tmp_path):
    store = ChatSessionStore(tmp_path / "sessions")
    session = store.create("big")
    store.append(session.session_id, "assistant", "x" * (ChatSessionStore.SUMMARY_PREVIEW_CHARS + 5))
    row = store.list_summaries()[0]
    assert row.last_truncated and len(row.last_content) == ChatSessionStore.SUMMARY_PREVIEW_CHARS
