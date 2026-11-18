import asyncio
import pytest
from isycode.tui import TUIApp
from isycode.user_defaults import UserDefaultsStore
from test_daily_tui import configure


def test_steering_keeps_the_prompt_before_the_steering_message_in_the_saved_session(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace='recurring')
    monkeypatch.setattr("isycode.reasoning_options.steering_support", lambda provider, model: True)
    async def scenario():
        ready = asyncio.Event()
        snapshots = []
        async def complete(provider, messages, **kwargs):
            import copy
            snapshots.append(copy.deepcopy(messages))
            if len(snapshots) == 1:
                kwargs["on_chunk"]("content", "Partial reply")
                ready.set()
                await asyncio.Event().wait()
            kwargs["on_chunk"]("content", "Updated reply")
            return {"text": "Updated reply", "tool_calls": []}
        monkeypatch.setattr("isycode.tui.provider_complete", complete)
        app = TUIApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt-input")
            app._accept_prompt(prompt, "First instruction")
            await asyncio.wait_for(ready.wait(), 5)
            task = app._loop_task
            app._accept_prompt(prompt, "/steer New steering instruction")
            await asyncio.wait_for(task, 5)
            await pilot.pause()
            session = app._chat_session_owner.resume(app._active_chat_session_id)[1]
            pairs = [(m["role"], m["content"]) for m in session.messages]
            assert pairs == [("user", "First instruction"),
                             ("user", "New steering instruction"),
                             ("assistant", "Partial reply\n\nUpdated reply")]
            stamps = [m["sent_at"] for m in session.messages]
            assert stamps[0] <= stamps[1]
            assert session.title == "First instruction"
    asyncio.run(scenario())


def test_steer_cancels_only_provider_request_and_sends_updated_messages(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr("isycode.reasoning_options.steering_support", lambda provider, model: True)
    async def scenario():
        ready = asyncio.Event()
        cancelled = asyncio.Event()
        snapshots = []
        async def complete(provider, messages, **kwargs):
            import copy
            snapshots.append(copy.deepcopy(messages))
            if len(snapshots) == 1:
                kwargs["on_chunk"]("content", "Partial reply")
                ready.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
            kwargs["on_chunk"]("content", "Updated reply")
            return {"text": "Updated reply", "tool_calls": []}
        monkeypatch.setattr("isycode.tui.provider_complete", complete)
        app = TUIApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt-input")
            app._accept_prompt(prompt, "First instruction")
            await asyncio.wait_for(ready.wait(), 5)
            task = app._loop_task
            app._accept_prompt(prompt, "/steer New steering instruction")
            await asyncio.wait_for(task, 5)
            await pilot.pause()
            assert cancelled.is_set()
            assert len(snapshots) == 2
            assert any(m.get("content") == "New steering instruction" for m in snapshots[1])
            assert any(m.get("content") == "Partial reply" for m in snapshots[1])
            assert "Updated reply" in app._history[-1]["content"]
    asyncio.run(scenario())


def test_steering_waits_for_running_tool_and_skips_unstarted_calls(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr("isycode.reasoning_options.steering_support", lambda provider, model: True)
    async def scenario():
        started, finish = asyncio.Event(), asyncio.Event()
        calls, requests = [], []
        async def complete(provider, messages, **kwargs):
            import copy
            requests.append(copy.deepcopy(messages))
            if len(requests) == 1:
                return {"text": "", "tool_calls": [{"id": str(i), "type": "function", "function": {"name": "workspace_read", "arguments": '{"path":"a.py"}'}} for i in range(2)]}
            kwargs["on_chunk"]("content", "Steered after tool")
            return {"text": "Steered after tool", "tool_calls": []}
        async def dispatch(self, call):
            calls.append(call["id"])
            started.set()
            await finish.wait()
            return call["id"], '{"status":"ok"}'
        monkeypatch.setattr("isycode.tui.provider_complete", complete)
        monkeypatch.setattr(TUIApp, "_dispatch_chat_tool", dispatch)
        app = TUIApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt-input")
            app._accept_prompt(prompt, "Read")
            await asyncio.wait_for(started.wait(), 5)
            task = app._loop_task
            app._accept_prompt(prompt, "/steer Change direction")
            await pilot.pause()
            assert not task.done() and not finish.is_set()
            finish.set()
            await asyncio.wait_for(task, 5)
            assert calls == ["0"]
            assert any(m.get("role") == "tool" and "skipped" in str(m.get("content")) for m in requests[1])
            assert any(m.get("content") == "Change direction" for m in requests[1])
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["empty", "unsupported", "auth"])
def test_empty_steer_returns_to_queue_and_resumes_original_request(tmp_path, monkeypatch, failure):
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr("isycode.reasoning_options.steering_support", lambda *args: None)
    async def scenario():
        ready = asyncio.Event()
        snapshots = []
        async def complete(provider, messages, **kwargs):
            import copy
            snapshots.append(copy.deepcopy(messages))
            if len(snapshots) == 1:
                ready.set()
                await asyncio.Event().wait()
            if len(snapshots) == 2:
                from isycode.providers import ProviderError
                if failure == "unsupported":
                    raise ProviderError("unsupported", 400, '{"error":{"code":"unsupported_steering"}}')
                if failure == "auth":
                    raise ProviderError("unauthorized", 401)
                return {"text": "", "tool_calls": []}
            kwargs["on_chunk"]("content", "Original completed")
            return {"text": "Original completed", "tool_calls": []}
        monkeypatch.setattr("isycode.tui.provider_complete", complete)
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            task = asyncio.create_task(app._run_chat("Original"))
            app._loop_task = task
            await asyncio.wait_for(ready.wait(), 5)
            app._accept_prompt(app.query_one("#prompt-input"), "/steer Later idea")
            await asyncio.wait_for(task, 5)
            assert app._queued_messages == ["Later idea"]
            from isycode.capability_observations import observed
            assert observed("openai", "gpt-6-luna", "steer") is (False if failure == "unsupported" else None)
            assert len(snapshots) == (2 if failure == "auth" else 3)
            assert any(m.get("content") == "Later idea" for m in snapshots[1])
            if failure != "auth":
                assert not any(m.get("content") == "Later idea" for m in snapshots[2])
                assert app._history[-1]["content"] == "Original completed"
    asyncio.run(scenario())


def test_cancelled_thinking_turn_does_not_reuse_previous_thought_block(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        thinking_started = asyncio.Event()
        turn = {"n": 0}

        async def complete(provider, messages, **kwargs):
            turn["n"] += 1
            if turn["n"] == 1:
                kwargs["on_chunk"]("reasoning", "first turn thinking")
                thinking_started.set()
                await asyncio.Event().wait()
            kwargs["on_chunk"]("reasoning", "second turn thinking")
            kwargs["on_chunk"]("content", "Second done")
            return {"text": "Second done", "tool_calls": []}

        monkeypatch.setattr("isycode.tui.provider_complete", complete)
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            from isycode.tui_widgets import ChatArea, ThoughtBlock
            t1 = asyncio.create_task(app._run_chat("First"))
            app._loop_task = t1
            await asyncio.wait_for(thinking_started.wait(), 5)
            await pilot.pause()
            blocks_after_1 = list(app.query_one(ChatArea).query(ThoughtBlock))
            assert len(blocks_after_1) == 1
            t1.cancel()
            await asyncio.gather(t1, return_exceptions=True)
            await pilot.pause()

            t2 = asyncio.create_task(app._run_chat("Second"))
            app._loop_task = t2
            await asyncio.wait_for(t2, 5)
            await pilot.pause()
            blocks_after_2 = list(app.query_one(ChatArea).query(ThoughtBlock))
            assert len(blocks_after_2) == 2
            assert blocks_after_2[0] is not blocks_after_2[1]
            assert "second turn thinking" not in str(blocks_after_2[0]._body.render())
            assert "second turn thinking" in str(blocks_after_2[1]._body.render())

    asyncio.run(scenario())


def test_chained_steer_is_accepted_while_previous_steer_is_active(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr("isycode.reasoning_options.steering_support", lambda provider, model: True)

    async def scenario():
        ready1 = asyncio.Event()
        ready2 = asyncio.Event()
        snapshots = []

        async def complete(provider, messages, **kwargs):
            import copy
            snapshots.append(copy.deepcopy(messages))
            if len(snapshots) == 1:
                ready1.set()
                await asyncio.Event().wait()
            if len(snapshots) == 2:
                ready2.set()
                await asyncio.Event().wait()
            kwargs["on_chunk"]("content", "Final steered answer")
            return {"text": "Final steered answer", "tool_calls": []}

        monkeypatch.setattr("isycode.tui.provider_complete", complete)
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            task = asyncio.create_task(app._run_chat("Initial"))
            app._loop_task = task
            await asyncio.wait_for(ready1.wait(), 5)
            prompt = app.query_one("#prompt-input")
            app._accept_prompt(prompt, "/steer First steer")
            await asyncio.wait_for(ready2.wait(), 5)
            app._accept_prompt(prompt, "/steer Second steer")
            await asyncio.wait_for(task, 5)
            assert len(snapshots) == 3
            assert any(m.get("content") == "First steer" for m in snapshots[2])
            assert any(m.get("content") == "Second steer" for m in snapshots[2])

    asyncio.run(scenario())
