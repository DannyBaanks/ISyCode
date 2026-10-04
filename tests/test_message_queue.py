import asyncio
from isycode.tui import TUIApp, QueuedMessagesScreen
from test_daily_tui import configure


def test_enter_queues_fifo_without_cancelling_and_preserves_new_draft(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    async def scenario():
        ready, finish = asyncio.Event(), asyncio.Event()
        sent = []
        async def chat(self, text):
            sent.append(text)
            self._chat_turn_task = asyncio.current_task()
            if text == "first":
                ready.set()
                await finish.wait()
            self._chat_turn_task = None
        monkeypatch.setattr(TUIApp, "_run_chat", chat)
        app = TUIApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt-input")
            prompt.load_text("first")
            await pilot.press("enter")
            await ready.wait()
            prompt.load_text("second")
            await pilot.press("enter")
            prompt.load_text("third")
            await pilot.press("enter")
            assert sent == ["first"]
            assert app._queued_messages == ["second", "third"]
            assert not app._loop_task.done()
            prompt.load_text("still drafting")
            finish.set()
            for _ in range(100):
                await pilot.pause(.01)
                if len(sent) == 3:
                    break
            assert sent == ["first", "second", "third"]
            assert prompt.text == "still drafting"
    asyncio.run(scenario())


def test_ctrl_enter_routes_active_text_to_steering(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            active = asyncio.create_task(asyncio.Event().wait())
            app._chat_turn_task = active
            app._loop_task = active
            prompt = app.query_one("#prompt-input")
            prompt.load_text("updated instruction")
            await pilot.press("ctrl+enter")
            assert app._pending_steering == ["updated instruction"]
            assert app._queued_messages == []
            assert not active.cancelled()
            active.cancel()
            try:
                await active
            except asyncio.CancelledError:
                pass
            app._chat_turn_task = app._loop_task = None
    asyncio.run(scenario())
