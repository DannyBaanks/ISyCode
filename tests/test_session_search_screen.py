"""M-UX3.2: dedicated cross-session search screen on Ctrl+Shift+F.

The screen only filters authority-provided sessions and reports a choice;
resuming goes through the existing session owner path.
"""
import pytest

from isycode.chat_sessions import ChatSession
from isycode.tui import TUIApp, SessionSearchScreen


def _session(session_id, title, contents):
    return ChatSession(session_id, title,
                       [{"role": "user", "content": content} for content in contents],
                       1700000000.0, 1700000000.0)


SESSIONS = [
    _session("a" * 32, "Fix the parser", ["the tokenizer drops accents"]),
    _session("b" * 32, "Deploy notes", ["remember the parser migration"]),
    _session("c" * 32, "Shopping list", ["coffee and tea"]),
]


@pytest.mark.asyncio
async def test_screen_filters_across_titles_and_transcripts():
    app = TUIApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await app.push_screen(SessionSearchScreen(SESSIONS))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SessionSearchScreen)
        screen._refilter("parser")
        assert {item.session_id for item in screen.visible_sessions} == {"a" * 32, "b" * 32}
        screen._refilter("tokenizer")
        assert [item.session_id for item in screen.visible_sessions] == ["a" * 32]
        screen._refilter("")
        assert len(screen.visible_sessions) == 3


@pytest.mark.asyncio
async def test_screen_dismisses_with_selected_session():
    app = TUIApp()
    result = []
    async with app.run_test(size=(100, 30)) as pilot:
        await app.push_screen(SessionSearchScreen(SESSIONS), result.append)
        await pilot.pause()
        screen = app.screen
        screen._refilter("tokenizer")
        await pilot.pause()
        screen.query_one("#session-search-input").value = "tokenizer"
        await pilot.pause()
        screen.dismiss("a" * 32)
        await pilot.pause()
    assert result == ["a" * 32]


@pytest.mark.asyncio
async def test_escape_dismisses_without_choice():
    app = TUIApp()
    result = []
    async with app.run_test(size=(100, 30)) as pilot:
        await app.push_screen(SessionSearchScreen(SESSIONS), result.append)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert result == [None]


@pytest.mark.asyncio
async def test_shortcut_registered_without_collisions():
    from isycode.shortcuts import APP_SHORTCUTS
    keys = [key for item in APP_SHORTCUTS for key in item.key.split(",")]
    assert keys.count("ctrl+shift+f") == 1
    entry = next(item for item in APP_SHORTCUTS if "ctrl+shift+f" in item.key)
    assert entry.action == "open_session_search"
    assert hasattr(TUIApp, "action_open_session_search")


@pytest.mark.asyncio
async def test_action_notifies_when_sessions_disabled(tmp_path, monkeypatch):
    from test_daily_tui import configure
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    async with app.run_test(size=(100, 30)) as pilot:
        app.action_open_session_search()
        await pilot.pause()
        assert not isinstance(app.screen, SessionSearchScreen)


@pytest.mark.asyncio
async def test_action_opens_screen_in_classic_recurring(tmp_path, monkeypatch):
    from test_daily_tui import configure
    from isycode.user_defaults import UserDefaultsStore
    configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace='recurring')
    app = TUIApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.action_open_session_search()
        await pilot.pause()
        assert isinstance(app.screen, SessionSearchScreen)
        await pilot.press("escape")


def test_earlier_tools_preview_is_bounded():
    from isycode.tui_app_sessions import _bounded_note
    big = "x" * 5000
    preview = _bounded_note(big, 600)
    assert len(preview) < 700
    assert "more chars in history" in preview
    assert _bounded_note("short", 600) == "short"


def test_tool_note_line_renders_semantic_summaries():
    from isycode.tui_app_sessions import _tool_note_line
    assert _tool_note_line(1, {"name": "workspace_list",
                               "arguments": '{"path":"."}',
                               "result": '{"entries":[1,2,3]}'}) == "1. workspace_list · . · 3 entries"
    assert _tool_note_line(2, {"name": "workspace_grep",
                               "arguments": '{"path":"AGENTS.md","query":"ISyCo"}',
                               "result": '{"files_scanned":1,"matches":[1,2]}'}) == \
        "2. workspace_grep · AGENTS.md · ISyCo · 2 matches in 1 files"
    assert _tool_note_line(6, {"name": "git_status", "arguments": "{}",
                               "result": '{"branch":"master","changes":[1,2,3]}'}) == \
        "6. git_status · 3 changes on master"
    assert _tool_note_line(7, {"name": "update_session_title",
                               "arguments": '{"title":"x"}',
                                   "result": '{"status":"ALLOW"}'}) == "7. update_session_title · allow"
    line = _tool_note_line(1, {"name": "workspace_read",
                               "arguments": '{"path":"big.json"}',
                               "result": '{"text":"' + "x" * 9000 + '"}'})
    assert line == "1. workspace_read · big.json · 9000 chars"
    assert "{" not in line
