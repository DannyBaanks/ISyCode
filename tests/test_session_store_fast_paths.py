"""Fast paths in transcript redaction/validation must not change any result."""
import json

from isycode.chat_sessions import ChatSessionStore
from isycode.tool_history import sanitize_historical_text


def test_escaped_secret_inside_json_is_still_redacted():
    # The raw text has no trigger word: "sk-" only becomes "sk-" once parsed.
    raw = '{"a": "\\u0073k-abcdefghijklmnop"}'
    assert "sk-" not in raw
    assert json.loads(sanitize_historical_text(raw)) == {"a": "[redacted]"}


def test_unicode_case_folding_reaches_redaction():
    # (?i) matches U+017F with "s"; the prefilter must not skip what the full pattern catches.
    note = "ſecret=topsecretvalue"
    assert sanitize_historical_text(note) == "[redacted]"


def test_nan_under_secret_key_keeps_structural_redaction():
    # NaN only serializes after redaction replaces it; it must not fall to whole-note removal.
    assert json.loads(sanitize_historical_text('{"api_key": NaN, "x": "y"}')) == {
        "api_key": "[redacted]", "x": "y"}


def test_text_without_trigger_is_returned_canonical():
    assert sanitize_historical_text('{"b": 1, "a": "plain"}') == '{"a":"plain","b":1}'
    assert ChatSessionStore._sanitize_text("plain text") == "plain text"


def _history(arguments):
    return {"tool_history": [{"name": "read_file", "arguments": arguments, "result": "ok"}]}


def test_cached_state_is_independent_and_tampered_file_still_redacted(tmp_path):
    store = ChatSessionStore(tmp_path / "sessions")
    session = store.create("hello")
    session.state = _history('{"path": "a.txt"}')
    store.save(session)
    first = store.load(session.session_id)
    first.state["tool_history"].append("mutated")
    assert store.load(session.session_id).state == _history('{"path":"a.txt"}')

    path = store._path(session.session_id)
    payload = json.loads(path.read_text())
    payload["state"] = _history('{"token": "x", "api_key": "sk-abcdefghijklmnop"}')
    path.write_text(json.dumps(payload))
    loaded = store.load(session.session_id).state["tool_history"][0]["arguments"]
    assert json.loads(loaded) == {"api_key": "[redacted]", "token": "x"}
