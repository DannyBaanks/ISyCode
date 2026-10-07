"""Each open conversation keeps its own turn when the view changes."""
import asyncio

from isycode.tui import TUIApp, plain_text
from isycode.tui_widgets import ChatArea
from isycode.user_defaults import UserDefaultsStore
from test_daily_tui import configure


def _chat_text(app) -> str:
    return "\n".join(plain_text(widget) for widget in app.query_one(ChatArea).query("Static"))


def test_switching_leaves_the_other_conversation_running(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace="recurring")
    gate = asyncio.Event()

    async def chat(self, text):
        self._chat_turn_task = asyncio.current_task()
        self._ensure_lane_session()
        if not self._lane_on_screen():
            self._mount_user_turn(text)
        if text == "keep-going":
            await gate.wait()
        self._append("FROM " + text)
        self._history.append({"role": "assistant", "content": "FROM " + text})

    monkeypatch.setattr(TUIApp, "_run_chat", chat)

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
                if first is not None:
                    break
            assert first is not None and first.session_id
            task = first.loop_task
            app._start_new_conversation()
            await pilot.pause()
            assert "FROM keep-going" not in _chat_text(app)
            assert first.loop_task is task and not task.done() and not task.cancelled()
            await app._show_chat_sessions()
            await pilot.pause()
            row = next(item for item in app._work_rows if item["id"] == first.session_id)
            assert row["status"] == "generating"
            gate.set()
            for _ in range(50):
                await pilot.pause(0.01)
                if task.done():
                    break
            assert task.done() and not task.cancelled()
            assert any(kind == "note" and "FROM keep-going" in text for kind, text, _extra in first.lines)
            app._show_lane(first)
            await pilot.pause()
            assert "FROM keep-going" in _chat_text(app)
            assert app._foreground_lane() is first

    asyncio.run(scenario())


def test_escape_cancels_only_the_visible_conversation(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace="recurring")

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            back = asyncio.create_task(asyncio.Event().wait())
            app._loop_task = back
            app._chat_turn_task = back
            parked = app._foreground_lane()
            app._start_new_conversation()
            await pilot.pause()
            front = asyncio.create_task(asyncio.Event().wait())
            app._loop_task = front
            app._chat_turn_task = front
            app.action_escape_to_chat()
            await asyncio.sleep(0)
            assert front.cancelled() or front.cancelling()
            assert not back.cancelled() and not back.cancelling()
            assert parked.loop_task is back
            back.cancel()
            front.cancel()
            await asyncio.gather(back, front, return_exceptions=True)

    asyncio.run(scenario())
