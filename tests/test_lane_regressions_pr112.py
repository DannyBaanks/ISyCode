"""Regressions for lane ownership, repaint structure, clocks and shutdown."""
import asyncio
from datetime import datetime as RealDateTime, timezone
from types import SimpleNamespace

from isycode.conversation_lane import open_lane
from isycode.turn_resume import InterruptedTurn
from isycode.tui import TUIApp, plain_text
from isycode.tui_widgets import ChatArea, ToolActivityGroup
from test_daily_tui import configure


def _chat_text(app) -> str:
    return "\n".join(
        str(getattr(widget, "selection_text", None) or plain_text(widget))
        for widget in app.query_one(ChatArea).query("Static")
    )


def _tool_call(call_id="call-1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "workspace_read", "arguments": '{"path":"notes.txt"}'},
    }


def test_resume_stays_in_owning_lane_and_uses_lane_lifecycle(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            owner = app._foreground_lane()
            owner.history = [{"role": "user", "content": "question from A"}]
            app._interrupted_turn = InterruptedTurn(
                prompt="question from A",
                messages=[{"role": "user", "content": "question from A"}],
            )
            other = open_lane(app, None)
            other.history = [{"role": "user", "content": "question from B"}]
            app._show_lane(other)
            seen = {}

            async def complete(provider, messages, **kwargs):
                seen["lane"] = app._active_lane().key
                seen["tracked"] = owner.loop_task is not None and not owner.loop_task.done()
                kwargs["on_chunk"]("content", "answer for A")
                return {"text": "answer for A", "tool_calls": []}

            monkeypatch.setattr("isycode.tui.provider_complete", complete)
            app.action_resume_interrupted_turn()
            assert owner.loop_task is None and not seen
            app._show_lane(owner)
            app.action_resume_interrupted_turn()
            task = owner.loop_task
            assert task is not None
            await asyncio.gather(task)
            assert task.exception() is None
            assert seen["lane"] == owner.key
            assert seen["tracked"] is True
            assert owner.loop_task is None
            assert other.history == [{"role": "user", "content": "question from B"}]
            assert owner.history[-1] == {"role": "assistant", "content": "answer for A"}

    with capsys.disabled():
        asyncio.run(scenario())


def test_unmount_cancels_lane_turns_without_touching_removed_widgets(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        started = asyncio.Event()

        async def blocked(self, text):
            self._chat_turn_task = asyncio.current_task()
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(TUIApp, "_run_chat", blocked)
        app = TUIApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            app._accept_prompt(app.query_one("#prompt-input"), "block")
            await asyncio.wait_for(started.wait(), 5)
            turn = app._loop_task
        survived = not turn.done()
        if not turn.done():
            turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        assert not survived, "manually pinned lane turn remained alive after app unmount"

    with capsys.disabled():
        asyncio.run(scenario())


def test_switching_back_restores_tool_structure_in_place(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        calls = 0

        async def complete(provider, messages, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"text": "before tools", "tool_calls": [_tool_call()]}
            return {"text": "after tools", "tool_calls": []}

        async def dispatch(call):
            return call["id"], '{"status":"ok"}'

        monkeypatch.setattr("isycode.tui.provider_complete", complete)
        app = TUIApp()
        async with app.run_test(size=(110, 40)) as pilot:
            await pilot.pause()
            monkeypatch.setattr(app, "_dispatch_chat_tool_impl", dispatch)
            await app._run_chat("structured")
            first = app._foreground_lane()
            assert len(app.query_one(ChatArea).query(ToolActivityGroup)) == 1, (
                first.lines, _chat_text(app))
            app._start_new_conversation()
            await pilot.pause()
            app._show_lane(first)
            await pilot.pause()
            assert len(app.query_one(ChatArea).query(ToolActivityGroup)) == 1
            text = _chat_text(app)
            assert "before tools" in text and "after tools" in text
            assert not app.query_one(ChatArea).query(".tool-history")

    with capsys.disabled():
        asyncio.run(scenario())


def test_background_tool_finishes_only_in_its_own_lane(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def complete(provider, messages, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"text": "before A tool", "tool_calls": [_tool_call()]}
            return {"text": "after A tool", "tool_calls": []}

        async def dispatch(call):
            started.set()
            await release.wait()
            return call["id"], '{"status":"ok"}'

        monkeypatch.setattr("isycode.tui.provider_complete", complete)
        app = TUIApp()
        async with app.run_test(size=(110, 40)) as pilot:
            await pilot.pause()
            monkeypatch.setattr(app, "_dispatch_chat_tool_impl", dispatch)
            owner = app._foreground_lane()
            app._start_background_turn(owner, "A")
            await asyncio.wait_for(started.wait(), 5)
            app._start_new_conversation()
            other = app._foreground_lane()
            await pilot.pause()
            assert "workspace_read" not in _chat_text(app)
            assert not app.query_one(ChatArea).query(ToolActivityGroup)
            release.set()
            task = owner.loop_task
            await asyncio.gather(task)
            assert task.exception() is None
            assert app._foreground_lane() is other
            assert "after A tool" not in _chat_text(app)
            assert not app.query_one(ChatArea).query(ToolActivityGroup)
            app._show_lane(owner)
            await pilot.pause()
            assert len(app.query_one(ChatArea).query(ToolActivityGroup)) == 1
            assert "before A tool" in _chat_text(app)
            assert "after A tool" in _chat_text(app)

    with capsys.disabled():
        asyncio.run(scenario())


def test_idea_box_separates_current_operation_from_total_turn(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    clock = {"value": 0.0}
    monkeypatch.setattr(
        "isycode.tui_app_sessions._time",
        SimpleNamespace(monotonic=lambda: clock["value"]),
    )

    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        snapshots = []
        calls = 0

        async def complete(provider, messages, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                clock["value"] = 100.0
                return {"text": "before tool", "tool_calls": [_tool_call()]}
            kwargs["on_chunk"]("content", "streaming now")
            clock["value"] = 1760.0
            app._paint_idea_box()
            snapshots.append(app.query_one("#idea-box").render().plain)
            return {"text": "streaming now", "tool_calls": []}

        async def dispatch(call):
            clock["value"] = 1755.0
            app._paint_idea_box()
            snapshots.append(app.query_one("#idea-box").render().plain)
            started.set()
            await release.wait()
            return call["id"], '{"status":"ok"}'

        monkeypatch.setattr("isycode.tui.provider_complete", complete)
        app = TUIApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            monkeypatch.setattr(app, "_dispatch_chat_tool_impl", dispatch)
            app._start_background_turn(app._foreground_lane(), "timed work")
            await asyncio.wait_for(started.wait(), 5)
            release.set()
            task = app._foreground_lane().loop_task
            await asyncio.gather(task)
            assert task.exception() is None
            tool_view, stream_view = snapshots
            assert "workspace_read" in tool_view
            assert "1655s" in tool_view and "total 1755s" in tool_view
            assert "Thinking…" not in tool_view
            assert "Generating response" in stream_view
            assert "5s" in stream_view and "total 1760s" in stream_view

    with capsys.disabled():
        asyncio.run(scenario())


def test_empty_final_step_does_not_duplicate_previous_answer(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        calls = 0

        async def complete(provider, messages, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"text": "shown once", "tool_calls": [_tool_call()]}
            return {"text": "", "tool_calls": []}

        async def dispatch(call):
            return call["id"], '{"status":"ok"}'

        monkeypatch.setattr("isycode.tui.provider_complete", complete)
        app = TUIApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            monkeypatch.setattr(app, "_dispatch_chat_tool_impl", dispatch)
            await app._run_chat("no duplicate")
            answers = [item[1] for item in app._foreground_lane().lines if item[0] == "assistant"]
            assert answers == ["shown once"]

    with capsys.disabled():
        asyncio.run(scenario())


def test_each_assistant_step_gets_its_own_timestamp(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    first_stamp = RealDateTime(2026, 1, 1, 14, 12, tzinfo=timezone.utc)
    second_stamp = RealDateTime(2026, 1, 1, 14, 13, tzinfo=timezone.utc)
    stamps = iter([first_stamp, second_stamp])

    class Clock(RealDateTime):
        @classmethod
        def now(cls, tz=None):
            return next(stamps)

    async def scenario():
        calls = 0

        async def complete(provider, messages, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"text": "first step", "tool_calls": [_tool_call()]}
            return {"text": "second step", "tool_calls": []}

        async def dispatch(call):
            return call["id"], '{"status":"ok"}'

        monkeypatch.setattr("isycode.tui.provider_complete", complete)
        monkeypatch.setattr("isycode.tui_app_chat.datetime", Clock)
        app = TUIApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            monkeypatch.setattr(app, "_dispatch_chat_tool_impl", dispatch)
            await app._run_chat("timestamps")
            answers = [item for item in app._foreground_lane().lines if item[0] == "assistant"]
            assert [item[1] for item in answers] == ["first step", "second step"]
            assert [item[2] for item in answers] == [
                first_stamp.astimezone().isoformat(timespec="seconds"),
                second_stamp.astimezone().isoformat(timespec="seconds"),
            ]

    with capsys.disabled():
        asyncio.run(scenario())
