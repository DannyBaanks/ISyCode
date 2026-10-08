"""ADR 0008: a failed chat step is re-sent automatically, fixed delay, small budget, no repeated effects."""
import asyncio

import pytest

from isycode import continuity_recovery
from isycode.continuity_recovery import POLICIES, plan_recovery
from isycode.providers import ProviderError
from isycode.streaming import StreamError
from isycode.tui import TUIApp
from isycode.user_defaults import UserDefaultsStore
from test_daily_tui import configure


# ── Policy ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("error, kind", [
    (StreamError("provider closed a truncated chunked stream"), "STREAM"),
    (StreamError("provider connection failed"), "NETWORK"),
    (ProviderError("x", status=503), "PROVIDER"),
    (ProviderError("x", status=429), "RATE_LIMIT"),
])
def test_delay_is_fixed_for_every_attempt_and_the_budget_is_bounded(error, kind):
    policy = POLICIES[kind]
    delays = [plan_recovery(error, n).delay_s for n in range(1, policy.max_attempts + 1)]
    assert delays == [policy.delay_s] * policy.max_attempts          # no backoff multiplier
    assert all(plan_recovery(error, n).retry for n in range(1, policy.max_attempts + 1))
    exhausted = plan_recovery(error, policy.max_attempts + 1)
    assert not exhausted.retry and exhausted.reason == "recovery budget exhausted"


def test_retry_after_is_honoured_within_the_cap_and_surfaced_beyond_it():
    error = ProviderError("x", status=429)
    error.retry_after = 11
    assert plan_recovery(error, 1).delay_s == 11
    error.retry_after = 2                                             # never below the class delay
    assert plan_recovery(error, 1).delay_s == POLICIES["RATE_LIMIT"].delay_s
    error.retry_after = 120
    long = plan_recovery(error, 1)
    assert not long.retry and "120" in long.reason


@pytest.mark.parametrize("error", [
    ProviderError("x", status=401), ProviderError("x", status=402), ProviderError("x", status=403),
    ProviderError("x", status=400), ProviderError("x", status=404),
    StreamError("provider URL must be an HTTP(S) URL with a host"),
    StreamError("provider tool arguments exceed 64 KiB"),
    StreamError("provider reported a streaming API error"),          # unknown in-stream error
    PermissionError("authority"),
])
def test_terminal_failures_are_never_retried(error):
    assert not plan_recovery(error, 1).retry


# ── The chat turn ─────────────────────────────────────────────────────
@pytest.fixture
def chat(tmp_path, monkeypatch):
    root = configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace="recurring")
    waits = []

    async def no_wait(delay):
        waits.append(delay)

    monkeypatch.setattr(continuity_recovery, "wait_fixed", no_wait)
    return root, waits


def run_app(scenario):
    async def main():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await scenario(app, pilot)
    asyncio.run(main())


def transcript_text(app):
    from isycode.tui import plain_text
    from isycode.tui_widgets import ChatArea
    parts = []
    for widget in app.query_one(ChatArea).walk_children():
        try:
            parts.append(plain_text(widget))
        except Exception:
            pass
    return "\n".join(parts)


def test_interrupted_stream_recovers_without_manual_retry_and_drops_the_partial(chat, monkeypatch, capsys):
    root, waits = chat
    calls = []

    async def complete(provider, messages, **kwargs):
        calls.append(list(messages))
        if len(calls) == 1:
            kwargs["on_chunk"]("content", "HALF-WRITTEN-PARTIAL")
            raise StreamError("provider closed a truncated chunked stream")
        return {"text": "Complete answer.", "tool_calls": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario(app, pilot):
        await app._run_chat("Explain the parser")
        await pilot.pause()
        assert len(calls) == 2 and waits == [POLICIES["STREAM"].delay_s]
        assert calls[0] == calls[1]                       # the same step, nothing added
        assert app._history[-1] == {"role": "assistant", "content": "Complete answer."}
        shown = transcript_text(app)
        assert "HALF-WRITTEN-PARTIAL" not in shown        # never committed or kept on screen
        assert "Response recovered after 1 automatic retry" in shown
        assert "Prompt kept" not in shown                 # no manual action needed
        stored = app._chat_session_owner.resume(app._active_chat_session_id)[1]
        assert [m["content"] for m in stored.messages] == ["Explain the parser", "Complete answer."]

    with capsys.disabled():
        run_app(scenario)


def test_completed_tool_effects_are_not_dispatched_again(chat, monkeypatch, capsys):
    root, waits = chat
    (root / "notes.txt").write_text("tool-result-marker\n")
    calls = []

    async def complete(provider, messages, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            return {"text": "", "tool_calls": [{"id": "r1", "function": {
                "name": "workspace_read", "arguments": '{"path":"notes.txt"}'}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2}}
        if len(calls) == 2:
            raise ProviderError("overloaded", status=503)
        assert any(m.get("role") == "tool" and "tool-result-marker" in str(m.get("content"))
                   for m in messages)             # the earlier result is reused, not re-run
        return {"text": "Done.", "tool_calls": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario(app, pilot):
        dispatched = []
        original = app._dispatch_chat_tool

        async def counting(call, *args, **kwargs):
            dispatched.append(call["id"])
            return await original(call, *args, **kwargs)

        app._dispatch_chat_tool = counting
        await app._run_chat("Read notes.txt")
        assert dispatched == ["r1"] and len(calls) == 3
        assert waits == [POLICIES["PROVIDER"].delay_s]
        assert app._history[-1]["content"] == "Done."

    with capsys.disabled():
        run_app(scenario)


def test_terminal_failure_is_not_retried_and_keeps_the_prompt(chat, monkeypatch, capsys):
    root, waits = chat
    calls = []

    async def complete(provider, messages, **kwargs):
        calls.append(True)
        raise ProviderError("bad key", status=401)

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario(app, pilot):
        from isycode.tui_composer import PromptArea
        await app._run_chat("Hello")
        assert len(calls) == 1 and waits == []
        assert app.query_one(PromptArea).text == "Hello"

    with capsys.disabled():
        run_app(scenario)


def test_directory_reload_survives_a_screen_without_the_rail(chat, capsys):
    import threading
    from textual.screen import ModalScreen
    from textual.widgets import Static

    class Cover(ModalScreen[None]):
        def compose(self):
            yield Static("cover")

    async def scenario(app, pilot):
        for _ in range(200):
            pending = [worker for worker in app.workers
                       if worker.group == "workspace-startup" and not worker.is_finished]
            if app._workspace is not None and not pending:
                break
            await pilot.pause(0.05)
        else:
            raise AssertionError("startup did not finish")
        started = threading.Event()
        release = threading.Event()
        original_owner = app._workspace_read_owner

        def owner():
            current = original_owner()
            execute = current.execute

            def blocked(action, payload):
                if action == "workspace.files.list":
                    started.set()
                    if not release.wait(5):
                        raise TimeoutError("directory list was not released")
                return execute(action, payload)

            current.execute = blocked
            return current

        app._workspace_read_owner = owner
        load = asyncio.create_task(app._load_directory(str(app._workspace_root)))
        assert await asyncio.to_thread(started.wait, 5)
        app.push_screen(Cover())
        await pilot.pause()
        release.set()
        await asyncio.wait_for(load, 5)
        app.pop_screen()

    with capsys.disabled():
        run_app(scenario)


def test_escape_while_waiting_cancels_recovery(chat, monkeypatch, capsys):
    root, _ = chat
    calls = []
    waiting = asyncio.Event()

    async def complete(provider, messages, **kwargs):
        calls.append(True)
        raise ProviderError("overloaded", status=503)

    async def long_wait(delay):
        waiting.set()
        await asyncio.sleep(60)

    monkeypatch.setattr("isycode.tui.provider_complete", complete)
    monkeypatch.setattr(continuity_recovery, "wait_fixed", long_wait)

    async def scenario(app, pilot):
        turn = asyncio.create_task(app._run_chat("Hello"))
        await asyncio.wait_for(waiting.wait(), 10)
        app.action_escape_to_chat()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(turn, 10)
        await pilot.pause()
        assert len(calls) == 1                    # no attempt after the user stopped it

    with capsys.disabled():
        run_app(scenario)


def test_steering_queued_during_recovery_is_applied_at_the_retried_step(chat, monkeypatch, capsys):
    root, _ = chat
    calls = []

    async def complete(provider, messages, **kwargs):
        calls.append([m.get("content") for m in messages if m.get("role") == "user"])
        if len(calls) == 1:
            raise ProviderError("overloaded", status=503)
        return {"text": "ok", "tool_calls": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario(app, pilot):
        async def steer_then_continue(delay):
            app._pending_steering.append("also check the tests")

        monkeypatch.setattr(continuity_recovery, "wait_fixed", steer_then_continue)
        await app._run_chat("Fix the parser")
        assert len(calls) == 2
        assert "also check the tests" in calls[1][-1] and "also check the tests" not in str(calls[0])
        assert app._pending_steering == []

    with capsys.disabled():
        run_app(scenario)


def test_each_turn_starts_with_a_fresh_budget(chat, monkeypatch, capsys):
    root, waits = chat
    calls = []
    budget = POLICIES["PROVIDER"].max_attempts

    async def complete(provider, messages, **kwargs):
        calls.append(True)
        if len(calls) <= 1 + budget + 1:          # turn 1 exhausts; turn 2 fails once
            raise ProviderError("overloaded", status=503)
        return {"text": "ok", "tool_calls": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario(app, pilot):
        await app._run_chat("first")
        assert len(calls) == 1 + budget
        assert "Recovery stopped after 3 automatic attempts" in transcript_text(app)
        await app._run_chat("second")
        assert app._history[-1]["content"] == "ok"
        assert len(calls) == 1 + budget + 2

    with capsys.disabled():
        run_app(scenario)
