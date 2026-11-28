"""Journaled session writes leave the UI loop but are never orphaned (PASO 1)."""
import asyncio
import threading
import time
from types import SimpleNamespace

from isycode.tui import TUIApp
from isycode.tui_app_sessions import SessionMixin


def test_write_runs_off_the_loop_and_lands_even_when_the_turn_is_cancelled():
    applied: list[tuple[str, int]] = []
    writers: list[int] = []
    started = threading.Event()

    def slow_write(value):
        writers.append(threading.get_ident())
        started.set()
        time.sleep(0.2)  # an fsync under disk pressure
        return value

    async def scenario():
        loop_thread = threading.get_ident()
        turn = asyncio.ensure_future(SessionMixin._journal_off_ui(
            None, lambda result: applied.append((result, threading.get_ident())),
            slow_write, "sid-1"))
        while not started.is_set():
            await asyncio.sleep(0.01)
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        assert turn.cancelled()
        for _ in range(100):
            if applied:
                break
            await asyncio.sleep(0.01)
        return loop_thread

    loop_thread = asyncio.run(scenario())
    assert writers and loop_thread not in writers
    assert applied == [("sid-1", loop_thread)]  # adopted on the loop, after the cancel


def test_tab_title_reviews_a_session_once_until_the_work_list_reloads():
    calls: list[str] = []

    def review(sid):
        calls.append(sid)
        return None, SimpleNamespace(title="Parser refactor"), None

    app = SimpleNamespace(_active_chat_session_id="s1", _work_rows=[],
                          _chat_session_owner=SimpleNamespace(review=review),
                          _sessions_enabled=lambda: True)
    title = TUIApp._current_session_title
    assert title(app) == "Parser refactor"
    assert title(app) == "Parser refactor"
    assert calls == ["s1"]
    app._reviewed_session_title = None  # what _refresh_work_list does
    assert title(app) == "Parser refactor"
    assert calls == ["s1", "s1"]
    app._active_chat_session_id = "s2"
    title(app)
    assert calls == ["s1", "s1", "s2"]
