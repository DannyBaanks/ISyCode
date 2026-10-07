import asyncio
import pytest
from isycode.tui import TUIApp
from test_daily_tui import configure


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
