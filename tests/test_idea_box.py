import asyncio
import json
from types import SimpleNamespace

import pytest

from isycode.chat_sessions import ChatSessionError, ChatSessionStore


def test_idea_box_validation_is_bounded_and_redacts_secret_assignments():
    from isycode.idea_box import validate_idea_box

    assert validate_idea_box({"text": "  reading   parser\nnext: tests  "}) == "reading parser next: tests"
    assert validate_idea_box({"text": "api_key=super-secret"}) == "[redacted]"
    with pytest.raises(ValueError):
        validate_idea_box({"text": ""})
    with pytest.raises(ValueError):
        validate_idea_box({"text": "ok", "extra": True})
    with pytest.raises(ValueError):
        validate_idea_box({"text": 7})
    with pytest.raises(ValueError):
        validate_idea_box({"text": "x" * 2001})


def test_session_state_accepts_only_bounded_string_idea_box():
    assert ChatSessionStore.validate_state({"idea_box": "next: tests"})["idea_box"] == "next: tests"
    for value in (None, 7, {}, "x" * 2001):
        with pytest.raises(ChatSessionError):
            ChatSessionStore.validate_state({"idea_box": value})


def test_idea_nudge_changes_request_messages_without_polluting_history():
    from isycode.idea_box import IDEA_BOX_TOOL, IDEA_NUDGE_PREFIX
    from isycode.tui import TUIApp

    app = TUIApp()
    app._history = [{"role": "user", "content": "Do the work"}]
    app._idea_box = "working on parser"
    app._idea_nudge_due = True
    messages = [{"role": "system", "content": "base"}, *[dict(x) for x in app._history]]

    app._apply_idea_nudge(messages, [IDEA_BOX_TOOL])

    assert messages[1]["role"] == "system"
    assert messages[1]["content"].startswith(IDEA_NUDGE_PREFIX)
    assert "working on parser" in messages[1]["content"]
    assert app._idea_nudge_due is False
    assert app._history == [{"role": "user", "content": "Do the work"}]
    assert "sent_at" not in json.dumps(app._history)


def test_idea_box_tool_updates_overlay_without_duration_or_tool_history(monkeypatch):
    from isycode.idea_box import IDEA_BOX_TOOL_NAME
    from isycode.tui import TUIApp

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            before = len(app._tool_history)
            call_id, result = await app._dispatch_chat_tool({
                "id": "idea-1",
                "function": {"name": IDEA_BOX_TOOL_NAME,
                             "arguments": json.dumps({"text": "api_key=secret"})},
            })
            await pilot.pause()
            box = app.query_one("#idea-box")
            chat_text = "\n".join(str(child.render()) for child in app.query_one("#chat").children)
            return call_id, json.loads(result), box.render().plain, chat_text, before, len(app._tool_history)

    call_id, result, box_text, chat_text, before, after = asyncio.run(scenario())
    assert call_id == "idea-1"
    assert result == {"status": "shown"}
    assert "Idea box" in box_text and "[redacted]" in box_text
    assert "Tool duration" not in chat_text
    assert after == before


def test_resume_shows_idea_box_and_new_conversation_clears_it():
    from isycode.idea_box import IDEA_BOX_TOOL_NAME
    from isycode.action_runtime import CHAT_WORKSPACE_TOOLS
    from isycode.tui import TUIApp

    class Owner:
        def resume(self, session_id):
            return (SimpleNamespace(decision="ALLOW", reason=""),
                    SimpleNamespace(session_id=session_id, title="Saved", messages=[],
                                    state={"idea_box": "resume next step"}))

        def list_conversations(self):
            return SimpleNamespace(decision="ALLOW", reason=""), []

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            app._chat_session_owner = Owner()
            app._sessions_enabled = lambda: True
            await app._resume_chat_session("saved")
            await pilot.pause()
            resumed = app.query_one("#idea-box").render().plain
            app._clear_open_conversation()
            await pilot.pause()
            cleared = app.query_one("#idea-box").render().plain
            return resumed, cleared

    resumed, cleared = asyncio.run(scenario())
    assert "resume next step" in resumed
    assert "Ctrl+Shift+Enter" in cleared
    child_names = {tool["function"]["name"] for tool in CHAT_WORKSPACE_TOOLS}
    assert IDEA_BOX_TOOL_NAME not in child_names
