"""A conversation can receive this user's words without stopping the one on screen."""
import asyncio

from isycode.tui import TUIApp, plain_text
from isycode.tui_widgets import ChatArea
from isycode.user_defaults import UserDefaultsStore
from test_daily_tui import configure


def _chat_text(app) -> str:
    return "\n".join(plain_text(widget) for widget in app.query_one(ChatArea).query("Static"))


def _install_chat(monkeypatch, gate):
    seen = []

    async def chat(self, text):
        self._chat_turn_task = asyncio.current_task()
        self._ensure_lane_session()
        if not self._lane_on_screen():
            self._mount_user_turn(text)
        seen.append(text)
        if text == "keep-going":
            await gate.wait()
        self._append("FROM " + text)
        self._history.append({"role": "assistant", "content": "FROM " + text})

    monkeypatch.setattr(TUIApp, "_run_chat", chat)
    return seen


def test_message_reaches_another_conversation_as_the_user(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace="recurring")
    seen = _install_chat(monkeypatch, asyncio.Event())

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt-input")
            prompt.load_text("hello-a")
            await pilot.press("enter")
            first = None
            for _ in range(50):
                await pilot.pause(0.01)
                if seen:
                    first = app._foreground_lane()
                    break
            assert first is not None and first.session_id
            sid = first.session_id
            app._start_new_conversation()
            await pilot.pause()
            home = app._foreground_key
            prompt.load_text(f"/msg {sid} ping-from-danny")
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(0.01)
                if "ping-from-danny" in seen:
                    break
            assert seen[-1] == "ping-from-danny"
            target = app._lanes[sid]
            assert any(kind == "user" and text == "ping-from-danny"
                       for kind, text, _extra in target.lines)
            assert app._foreground_key == home
            assert "ping-from-danny" not in _chat_text(app)
            assert "Sent to" in _chat_text(app)
            app._show_lane(target)
            await pilot.pause()
            assert "ping-from-danny" in _chat_text(app)

    asyncio.run(scenario())


def test_message_waits_when_the_other_conversation_is_working(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace="recurring")
    gate = asyncio.Event()
    seen = _install_chat(monkeypatch, gate)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt-input")
            prompt.load_text("keep-going")
            await pilot.press("enter")
            first = None
            for _ in range(50):
                await pilot.pause(0.01)
                for item in app._lanes.values():
                    if item.loop_task is not None and not item.loop_task.done():
                        first = item
                        break
                if first is not None and first.session_id:
                    break
            assert first is not None and first.session_id
            task = first.loop_task
            app._start_new_conversation()
            await pilot.pause()
            prompt.load_text(f"/msg {first.session_id} ping-from-danny")
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(0.01)
                if "ping-from-danny" in first.queued_messages:
                    break
            assert first.queued_messages == ["ping-from-danny"]
            assert task is first.loop_task and not task.done() and not task.cancelled()
            assert "ping-from-danny" not in _chat_text(app)
            gate.set()
            for _ in range(50):
                await pilot.pause(0.01)
                if "ping-from-danny" in seen and task.done():
                    break
            assert task.done() and not task.cancelled()
            assert seen[-1] == "ping-from-danny"
            assert any(kind == "user" and text == "ping-from-danny"
                       for kind, text, _extra in first.lines)

    asyncio.run(scenario())


def test_same_title_does_not_guess_and_the_open_chat_is_refused(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace="recurring")
    seen = _install_chat(monkeypatch, asyncio.Event())

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt-input")
            prompt.load_text("hello-a")
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(0.01)
                if seen:
                    break
            app._start_new_conversation()
            await pilot.pause()
            here = app._active_chat_session_id
            prompt.load_text("/msg Draft conversation hello-there")
            await pilot.press("enter")
            for _ in range(40):
                await pilot.pause(0.01)
                if "Several conversations match" in _chat_text(app):
                    break
            assert "Several conversations match" in _chat_text(app)
            assert "hello-there" not in seen
            assert prompt.text.startswith("/msg Draft conversation")
            prompt.load_text(f"/msg {here} not-this-one")
            await pilot.press("enter")
            for _ in range(40):
                await pilot.pause(0.01)
                if "on screen" in _chat_text(app):
                    break
            assert "That conversation is on screen" in _chat_text(app)
            assert "not-this-one" not in seen

    asyncio.run(scenario())
