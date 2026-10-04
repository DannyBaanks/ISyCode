import asyncio
from isycode.tui import TUIApp
from test_daily_tui import configure


def test_steer_cancels_only_provider_request_and_sends_updated_messages(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
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
