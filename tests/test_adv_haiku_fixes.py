"""Regression tests for the adversarial-run findings fixed on claude/haiku-adv-fixes.

1. PromptArea.load_text left the cursor at (0, 0), so text typed after a restored
   draft was glued in front of the old prompt (ADV:cutADV:malformedADV:error500).
2. ctrl+u deleted nothing from column 0 and only the current line elsewhere, so a
   pasted block survived it.
3. /new, /clear, /settings, /exit and /quit were listed as slash commands but
   never registered, so they fell through to _run_custom_command and went to the
   model as chat text; an unknown /foo went the same way silently.
4. A tool call that Sentinel or the registry blocked produced no line in the
   transcript (the denial only lived inside the collapsed tool card).
"""
from __future__ import annotations

import asyncio
import json

from isycode.tui import TUIApp, PromptArea, ModelsScreen
from isycode.tui_widgets import SelectableText
from test_daily_tui import configure


def _notes(app: TUIApp) -> list[str]:
    return [str(widget.render()) for widget in app.query_one("#chat").query(SelectableText)]


def _user_turns(app: TUIApp) -> list[str]:
    """Only the user cards; notes such as "Chat cleared … keeps the earlier messages" do not count."""
    return [str(widget.render()) for widget in app.query_one("#chat").query(SelectableText)
            if widget.has_class("user-turn")]


# ── 1. load_text leaves the cursor at the end ────────────────────────────────


def test_load_text_puts_the_cursor_at_the_end_so_typed_text_appends(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            prompt = app.query_one(PromptArea)
            prompt.load_text("ADV:cut")
            assert prompt.cursor_location == (0, len("ADV:cut"))
            prompt.focus()
            await pilot.press("A", "D", "V")
            assert prompt.text == "ADV:cutADV"
            prompt.load_text("first\nsecond")
            assert prompt.cursor_location == (1, len("second"))
            await pilot.press("!")
            assert prompt.text == "first\nsecond!"
            prompt.load_text("")
            assert prompt.text == "" and prompt.cursor_location == (0, 0)

    asyncio.run(scenario())


def test_restored_prompt_after_a_failed_turn_is_not_glued_in_front(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    # The failure has to happen inside the real _run_chat: its except/finally is
    # what gives the draft back. Replacing _run_chat itself would only test the
    # double, never the restore path.
    async def complete(provider, messages, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            prompt = app.query_one(PromptArea)
            prompt.load_text("ADV:malformed")
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(0.02)
                if app._loop_task is None or app._loop_task.done():
                    break
            assert prompt.text == "ADV:malformed"
            assert prompt.cursor_location == (0, len("ADV:malformed"))
            prompt.focus()
            await pilot.press("A", "D", "V")
            assert prompt.text == "ADV:malformedADV"

    asyncio.run(scenario())


# ── 2. ctrl+u clears the draft from column 0 ─────────────────────────────────


def test_ctrl_u_from_column_0_clears_a_pasted_block_and_else_cuts_the_line(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            prompt = app.query_one(PromptArea)
            prompt.focus()
            prompt.load_text("0123456789 αβγ — " * 200)
            assert len(prompt.text) > 3000
            prompt.move_cursor((0, 0))
            await pilot.press("ctrl+u")
            assert prompt.text == ""
            prompt.load_text("aaa\nbbb\nccc")
            prompt.move_cursor((1, 2))
            await pilot.press("ctrl+u")
            assert prompt.text == "aaa\nb\nccc"
            prompt.move_cursor((0, 0))
            await pilot.press("ctrl+u")
            assert prompt.text == ""

    asyncio.run(scenario())


# ── 3. slash commands never reach the model as text ──────────────────────────


def test_view_commands_are_registered_and_model_stays_an_alias(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    for name in ("new", "clear", "settings", "exit", "quit"):
        assert app._plugins.route(f"/{name}")[1] is not None, name
    # The registry itself keeps /model unregistered; _accept_prompt resolves it.
    assert app._plugins.route("/model")[1] is None
    assert app._plugins.route("/models")[1] is not None


def test_unknown_slash_command_is_reported_and_never_sent_to_the_model(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    sent: list[str] = []

    async def chat(self, text, **_kwargs):
        sent.append(text)

    monkeypatch.setattr(TUIApp, "_run_chat", chat)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            prompt = app.query_one(PromptArea)
            prompt.load_text("/definitely-not-a-command")
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(0.02)
                if app._loop_task is None or app._loop_task.done():
                    break
            assert sent == []
            assert any("Unknown command /definitely-not-a-command · type /help" in line for line in _notes(app))
            # The mistyped command comes back to the composer, ready to edit.
            assert prompt.text == "/definitely-not-a-command"
            assert prompt.cursor_location == (0, len("/definitely-not-a-command"))

    asyncio.run(scenario())


def test_model_alias_opens_the_models_picker_without_a_chat_turn(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    sent: list[str] = []

    async def chat(self, text, **_kwargs):
        sent.append(text)

    monkeypatch.setattr(TUIApp, "_run_chat", chat)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(110, 36)) as pilot:
            await pilot.pause()
            prompt = app.query_one(PromptArea)
            prompt.load_text("/model")
            await pilot.press("enter")
            screen = None
            for _ in range(30):
                await pilot.pause()
                if isinstance(app.screen, ModelsScreen):
                    screen = app.screen
                    break
            assert isinstance(screen, ModelsScreen)
            assert sent == []
            assert prompt.text == ""

    asyncio.run(scenario())


def test_new_starts_a_conversation_while_a_turn_is_running(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    ready, finish = asyncio.Event(), asyncio.Event()
    started: list[str] = []

    async def chat(self, text, **_kwargs):
        started.append(text)
        self._chat_turn_task = asyncio.current_task()
        ready.set()
        await finish.wait()
        self._chat_turn_task = None

    monkeypatch.setattr(TUIApp, "_run_chat", chat)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            prompt = app.query_one(PromptArea)
            prompt.load_text("first")
            await pilot.press("enter")
            await asyncio.wait_for(ready.wait(), 5)
            running_lane = app._foreground_lane()
            running_task = app._loop_task
            assert running_task is not None and not running_task.done()
            prompt.load_text("/new")
            await pilot.press("enter")
            for _ in range(30):
                await pilot.pause()
                if app._foreground_lane() is not running_lane:
                    break
            assert started == ["first"]
            # The old lane keeps its turn; the new lane is on screen with no chat.
            assert running_lane.loop_task is running_task and not running_task.done()
            assert app._foreground_lane() is not running_lane
            assert not app._foreground_lane().history
            finish.set()
            for _ in range(50):
                await pilot.pause(0.02)

    asyncio.run(scenario())


def test_settings_and_clear_change_the_view_without_a_chat_turn(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    sent: list[str] = []

    async def chat(self, text, **_kwargs):
        sent.append(text)

    monkeypatch.setattr(TUIApp, "_run_chat", chat)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            prompt = app.query_one(PromptArea)
            app._mount_user_turn("earlier message")
            await pilot.pause()
            assert _user_turns(app) == ["earlier message"]
            prompt.load_text("/clear")
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(0.02)
                if app._loop_task is None or app._loop_task.done():
                    break
            assert sent == []
            assert not app._active_lane().history
            assert _user_turns(app) == []
            assert any("Chat cleared" in line for line in _notes(app))
            prompt.load_text("/settings")
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(0.02)
                if app._loop_task is None or app._loop_task.done():
                    break
            assert sent == []
            assert app._menu_mode == "settings"

    asyncio.run(scenario())


# ── 4. a blocked tool call is visible in the transcript ──────────────────────


def test_bogus_tool_call_produces_a_visible_line_in_the_transcript(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            call = {"id": "c1", "type": "function",
                    "function": {"name": "rm_rf_everything", "arguments": json.dumps({"path": "/"})}}
            _, result = await app._dispatch_chat_tool(call)
            assert json.loads(result)["error"] == "tool is not registered by ISyCode"
            await pilot.pause()
            visible = [line for line in _notes(app) if "Tool blocked" in line]
            assert visible and "rm_rf_everything" in visible[0] and "not registered" in visible[0]
            assert any(kind == "note" and "Tool blocked" in text
                       for kind, text, *_ in app._active_lane().lines)

    asyncio.run(scenario())


def test_sentinel_denied_tool_call_produces_a_visible_line_with_the_reason(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            call = {"id": "c2", "type": "function",
                    "function": {"name": "workspace_read", "arguments": json.dumps({"path": "../../etc/passwd"})}}
            _, result = await app._dispatch_chat_tool(call)
            material = json.loads(result)
            assert material.get("error")
            await pilot.pause()
            visible = [line for line in _notes(app) if "Tool blocked" in line and "workspace_read" in line]
            assert visible
            reason = material.get("reason") or material.get("error")
            assert reason[:40] in visible[0]

    asyncio.run(scenario())


def test_turn_that_ends_on_a_blocked_tool_says_why_and_keeps_the_prompt(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    calls: list[list[dict]] = []

    async def complete(provider, messages, **kwargs):
        calls.append(list(messages))
        if len(calls) == 1:
            # ADV:tool_bogus: one bogus call, then the provider ends without text.
            return {"text": "", "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "rm_rf_everything", "arguments": '{"path": "/"}'}}]}
        return {"text": "", "tool_calls": []}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.1)
            prompt = app.query_one(PromptArea)
            prompt.load_text("ADV:tool_bogus")
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(0.02)
                if app._loop_task is None or app._loop_task.done():
                    break
            assert len(calls) == 2
            notes = _notes(app)
            assert any("Tool blocked · rm_rf_everything" in line for line in notes)
            assert any("ended without an answer because a tool call was blocked" in line and "rm_rf_everything" in line
                       for line in notes)
            # Nothing was executed and the prompt is kept for review, cursor at its end.
            assert prompt.text == "ADV:tool_bogus"
            assert prompt.cursor_location == (0, len("ADV:tool_bogus"))

    asyncio.run(scenario())


# ── audit follow-ups ─────────────────────────────────────────────────────────


def test_only_view_commands_run_while_a_turn_is_streaming(tmp_path, monkeypatch):
    """/undo, /commit, /run… act on the workspace; during a turn they wait."""
    configure(tmp_path, monkeypatch)
    ready, finish = asyncio.Event(), asyncio.Event()
    ran: list[str] = []

    async def chat(self, text, **_kwargs):
        self._chat_turn_task = asyncio.current_task()
        ready.set()
        await finish.wait()
        self._chat_turn_task = None

    monkeypatch.setattr(TUIApp, "_run_chat", chat)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            for name in ("undo", "commit", "compact"):
                _plugin, cmd, _arg = app._plugins.route(f"/{name}")
                assert cmd is not None, name
                original = cmd.handler

                async def spy(app_, arg, _name=name):
                    ran.append(_name)

                cmd.handler = spy
                assert original not in app._view_command_handlers()
            prompt = app.query_one(PromptArea)
            prompt.load_text("first")
            await pilot.press("enter")
            await asyncio.wait_for(ready.wait(), 5)
            for name in ("undo", "commit", "compact"):
                prompt.load_text(f"/{name}")
                # Straight to the submit path: Enter would accept the open
                # command menu's completion instead.
                app._accept_prompt(prompt, prompt.text)
                await pilot.pause()
                # The draft is kept and the command never ran under the turn.
                assert prompt.text == f"/{name}"
            assert ran == []
            assert any("Still working" in line for line in _notes(app))
            finish.set()
            for _ in range(50):
                await pilot.pause(0.02)

    asyncio.run(scenario())


def test_tool_blocked_note_is_only_for_calls_refused_before_running():
    deny = TUIApp._is_tool_denial
    assert deny({"error": "tool is not registered by ISyCode"})
    assert deny({"error": "ISyCode denied the action", "reason": "outside workspace"})
    assert deny({"error": "webfetch requires a public HTTPS URL", "decision": "DENY"})
    assert deny({"status": "denied", "error": "one title string is required"})
    # A tool that ran and failed, or an MCP server error, was executed.
    assert not deny({"error": "[Errno 2] No such file or directory: 'x'"})
    assert not deny({"error": "that MCP tool is not available; the server may be stopped"})
    assert not deny({"error": "RuntimeError: upstream 500"})
