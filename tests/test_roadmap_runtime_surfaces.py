"""Executable witnesses for the M17/M18 runtime surfaces adopted by ISyCode."""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

from isycode.chat_sessions import ChatSessionStore
from isycode.headless import EXIT_FAILED, EXIT_OK, main, run_headless
from isycode.turn_events import TurnEventStream
from isycode.workspace_authority import WorkspaceAuthority


def _workspace(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "note.txt").write_text("hello\n", encoding="utf-8")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("ISYCODE_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setattr("isycode.egress.review_destination", lambda _url: None)
    return root.resolve()


def test_html_export_is_local_escaped_and_redacted(tmp_path: Path):
    store = ChatSessionStore(tmp_path / "sessions")
    session = store.create("Review <script>alert(1)</script>")
    store.append(session.session_id, "user", "api_key=sk-secret-value <b>hello</b>")

    exported = store.export_html(session.session_id)

    assert exported.startswith("<!doctype html>")
    assert "&lt;script&gt;" in exported and "<script>" not in exported
    assert "&lt;b&gt;hello&lt;/b&gt;" in exported
    assert "sk-secret-value" not in exported and "[redacted]" in exported


def test_offline_headless_fails_visibly_without_constructing_provider(monkeypatch, capsys):
    monkeypatch.setattr("isycode.headless.Provider", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("offline mode must not construct a provider")))

    code = main(["--offline", "-p", "hello"])

    assert code == EXIT_FAILED
    assert "offline" in capsys.readouterr().err.casefold()


def test_no_tools_profile_can_only_remove_tools(tmp_path: Path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    WorkspaceAuthority(root).set_mode("classic")
    seen = []

    async def transport(messages, tools, on_chunk):
        seen.append(tools)
        return {"text": "ok", "tool_calls": []}

    out = io.StringIO()
    code = asyncio.run(run_headless(
        "hello", root=root, out=out, log=io.StringIO(), transport=transport,
        tool_profile="none",
    ))

    assert code == EXIT_OK
    assert seen == [None]


def test_turn_event_stream_is_monotonic_bounded_and_serializable():
    stream = TurnEventStream()
    first = stream.emit("turn.start", {"source": "headless"})
    second = stream.emit("agent.end", {"status": "complete"})

    assert first.sequence == 1 and second.sequence == 2
    records = [json.loads(line) for line in stream.to_ndjson().splitlines()]
    assert [record["type"] for record in records] == ["turn.start", "agent.end"]
    assert records[1]["payload"] == {"status": "complete"}
    assert all(set(record) == {"version", "sequence", "type", "payload"} for record in records)


def test_headless_json_includes_same_event_contract(tmp_path: Path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    WorkspaceAuthority(root).set_mode("classic")

    async def transport(messages, tools, on_chunk):
        return {"text": "ok", "tool_calls": [], "usage": {
            "prompt_tokens": 3, "completion_tokens": 1,
        }}

    out = io.StringIO()
    code = asyncio.run(run_headless(
        "hello", root=root, out=out, log=io.StringIO(), json_output=True,
        transport=transport,
    ))
    payload = json.loads(out.getvalue())

    assert code == EXIT_OK
    assert [event["type"] for event in payload["events"]] == [
        "turn.start", "provider.request", "provider.result", "agent.end",
    ]
    assert payload["usage"] == {
        "requests": 1, "input_tokens": 3, "output_tokens": 1, "unknown_requests": 0,
    }
    assert payload["context"]["status"] == "estimated"
    assert payload["context"]["estimated_tokens"] > 0
    assert payload["cost"] == {"status": "unknown"}
