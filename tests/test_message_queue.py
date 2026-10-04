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



import pytest
from isycode.tui import QueuedBox, QueuedTitle, SessionMessageScreen, plain_text
from isycode import reasoning_options


@pytest.mark.parametrize('supported', [True, False, None])
def test_selected_queue_empty_send_respects_model_capability(tmp_path, monkeypatch, supported):
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr(reasoning_options, '_STEERING', {})
    monkeypatch.setattr(reasoning_options, '_STEERING_OBSERVED', {})
    if supported is not None:
        reasoning_options.record_catalog('openai', 'gpt-6-luna', {'supportsSteering': supported})
    reasoning_options.record_catalog('nvidia', 'fixture-supported', {'supportsSteering': True})
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            active = asyncio.create_task(asyncio.Event().wait())
            request = asyncio.create_task(asyncio.Event().wait())
            app._chat_turn_task = app._loop_task = active
            app._chat_request_task = request
            prompt = app.query_one('#prompt-input')
            try:
                prompt.load_text('updated instruction')
                prompt.focus()
                await pilot.press('ctrl+enter')
                assert not app._pending_steering and not app._queued_messages
                assert prompt.text == 'updated instruction'
                await pilot.press('enter')
                await pilot.pause()
                assert app._queued_messages == ['updated instruction']
                assert not prompt.text and not request.cancelled()
                queue = app.query_one('#queued-box', QueuedBox)
                idea = app.query_one('#idea-box')
                assert queue.region.bottom <= idea.region.y
                assert queue.region.x == idea.region.x
                await pilot.click(queue.query_one(QueuedTitle))
                await pilot.pause()
                assert app._selected_queued_message == 'updated instruction'
                prompt.focus()
                await pilot.press('enter')
                await pilot.pause()
                if supported is not False:
                    assert app._pending_steering == ['updated instruction']
                    assert not app._queued_messages and request.cancelled()
                else:
                    assert not app._pending_steering
                    assert app._queued_messages == ['updated instruction']
                    assert not request.cancelled()
                    assert app.query_one('#queue-notice').display
                    await pilot.click('#queue-steer-help')
                    await pilot.pause()
                    assert isinstance(app.screen, SessionMessageScreen)
                    assert 'Fixture Supported' in app.screen.message
            finally:
                active.cancel(); request.cancel()
                await asyncio.gather(active, request, return_exceptions=True)
                app._chat_turn_task = app._loop_task = app._chat_request_task = None
    asyncio.run(scenario())


def test_selected_queue_escape_restores_text_and_never_overwrites_draft(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._queued_messages = ['first', 'second']
            app._paint_queued_messages()
            await pilot.pause()
            queue = app.query_one('#queued-box', QueuedBox)
            await pilot.click(queue.query_one(QueuedTitle))
            await pilot.pause()
            await pilot.press('escape')
            await pilot.pause()
            prompt = app.query_one('#prompt-input')
            assert prompt.text == 'first'
            assert app._queued_messages == ['second']
            await pilot.click(queue.query_one(QueuedTitle))
            await pilot.press('escape')
            assert prompt.text == 'first'
            assert app._queued_messages == ['second']
    asyncio.run(scenario())


def test_missing_steering_metadata_revokes_prior_confirmation(monkeypatch):
    monkeypatch.setattr(reasoning_options, '_STEERING', {})
    monkeypatch.setattr(reasoning_options, '_STEERING_OBSERVED', {})
    reasoning_options.record_catalog('fixture', 'model', {'supportsSteering': True})
    assert reasoning_options.steering_support('fixture', 'model') is True
    reasoning_options.record_catalog('fixture', 'model', {})
    assert reasoning_options.steering_support('fixture', 'model') is None
    assert ('fixture', 'model') not in reasoning_options.steering_models()
