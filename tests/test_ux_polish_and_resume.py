"""Test suite for Pre-1.0 UX Polish + Interrupted Turn Resume (Areas A through F)."""
import asyncio
import pytest

from isycode.file_preview import FilePreviewScreen, guess_syntax_language
from isycode.providers import ProviderError
from isycode.turn_resume import InterruptedTurn
from isycode.tui import PromptArea, SidePanel, TUIApp, plain_text
from isycode.tui_copy import CopyTextArea
from isycode.tui_screens_help import QuickHelpScreen
from isycode.tui_theme import set_ascii_only
from isycode.tui_widgets import CommandOutputCard, ToolActivityGroup, SPINNER_FRAMES
from test_daily_tui import configure


# ── Area A: Quick Help Overlay ───────────────────────────────────────────────

def test_area_a_quick_help_overlay_open_close(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # Initial state: QuickHelpScreen is not mounted
            assert not any(isinstance(s, QuickHelpScreen) for s in app.screen_stack)

            # F1 opens the help overlay
            app.action_quick_help()
            await pilot.pause()
            assert isinstance(app.screen, QuickHelpScreen)

            # Escape closes it
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, QuickHelpScreen)

            # ? opens help when focus is NOT in a text input
            side_button = app.query_one("#sidebar-button")
            side_button.focus()
            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, QuickHelpScreen)

            # Close again
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, QuickHelpScreen)

            # When focus IS in PromptArea, ? does NOT open the modal
            prompt = app.query_one("#prompt-input", PromptArea)
            prompt.focus()
            await pilot.press("question_mark")
            await pilot.pause()
            assert not isinstance(app.screen, QuickHelpScreen)

            # Check footer / composer-hint mentions F1
            hint = plain_text(app.query_one("#composer-hint"))
            assert "F1 help" in hint

    asyncio.run(scenario())


# ── Area B: FilePreviewScreen Syntax Highlighting ────────────────────────────

def test_area_b_guess_syntax_language():
    assert guess_syntax_language("main.py") == "python"
    assert guess_syntax_language("test.pyi") == "python"
    assert guess_syntax_language("data.json") == "json"
    assert guess_syntax_language("README.md") == "markdown"
    assert guess_syntax_language("script.sh") == "bash"
    assert guess_syntax_language("run.bash") == "bash"
    assert guess_syntax_language("config.yaml") == "yaml"
    assert guess_syntax_language("config.yml") == "yaml"
    assert guess_syntax_language("Cargo.toml") == "toml"
    assert guess_syntax_language("app.js") == "javascript"
    assert guess_syntax_language("app.ts") == "javascript"
    assert guess_syntax_language("index.html") == "html"
    assert guess_syntax_language("style.css") == "css"
    assert guess_syntax_language("main.rs") == "rust"
    assert guess_syntax_language("server.go") == "go"
    assert guess_syntax_language("unknown.xyz") is None
    assert guess_syntax_language("Makefile") is None
    assert guess_syntax_language("") is None
    assert guess_syntax_language(None) is None


def test_area_b_file_preview_screen_highlighting(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            # Python file preview
            app.push_screen(FilePreviewScreen("script.py", "def hello():\n    return 42\n"))
            await pilot.pause()
            ta_py = app.screen.query_one(CopyTextArea)
            assert ta_py.language == "python"
            assert ta_py.theme == "monokai"
            assert ta_py.show_line_numbers is True
            app.pop_screen()
            await pilot.pause()

            # Plain text preview
            app.push_screen(FilePreviewScreen("notes.txt", "Plain text note"))
            await pilot.pause()
            ta_txt = app.screen.query_one(CopyTextArea)
            assert ta_txt.language is None
            app.pop_screen()
            await pilot.pause()

            # Empty python preview
            app.push_screen(FilePreviewScreen("empty.py", ""))
            await pilot.pause()
            ta_empty = app.screen.query_one(CopyTextArea)
            assert ta_empty.language == "python"
            app.pop_screen()

    asyncio.run(scenario())


# ── Area C: Tool Running Feedback ────────────────────────────────────────────

def test_area_c_command_output_card_spinner(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            card = CommandOutputCard("python3 test.py")
            await app.query_one("ChatArea").mount(card)
            await pilot.pause()

            assert card.status == "Running"
            assert any(f in str(card.border_subtitle) for f in SPINNER_FRAMES)
            assert any(f in plain_text(card._body) for f in SPINNER_FRAMES)

            # Spinner ticks change frame without crashing
            f0 = card._spinner_idx
            card._tick_spinner()
            assert card._spinner_idx != f0

            # Finish stops timer and removes spinner frame
            card.finish("exit 0", output="All tests passed.")
            assert card.status == "exit 0"
            assert card._spinner_timer is None
            assert not any(f in str(card.border_subtitle) for f in SPINNER_FRAMES)
            assert "All tests passed." in plain_text(card._body)

    asyncio.run(scenario())


def test_area_c_tool_activity_group_spinner(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            leaf = CommandOutputCard("tool_1")
            group = ToolActivityGroup("workspace_read", leaf, "workspace_read(notes.txt)")
            await app.query_one("ChatArea").mount(group)
            await pilot.pause()

            # Ticking updates spinner in title
            group._tick_spinner()
            assert any(f in group.title for f in SPINNER_FRAMES)

            # Finishing leaf clears running state
            group.finish_leaf(leaf, "workspace_read(notes.txt) · Completed · 0.1s")
            assert not any(f in group.title for f in SPINNER_FRAMES)
            assert group._spinner_timer is None

    asyncio.run(scenario())


# ── Area D: Responsive Narrow Mode & Hysteresis ──────────────────────────────

def test_area_d_narrow_mode_hysteresis_and_user_override(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            rail = app.query_one(SidePanel)

            # Explicitly open rail at 120 width (clean baseline)
            app.action_toggle_sidebar()
            await pilot.pause()
            assert app._rail_visible is True
            assert rail.display is True
            # Clear manual override to simulate natural wide state
            app._rail_visibility_override = None

            # Resize 120 -> 80: auto-hides
            await pilot.resize_terminal(80, 40)
            await pilot.pause()
            assert app._rail_visible is False
            assert rail.display is False
            assert app._rail_auto_hidden is True

            # Resize 80 -> 120: auto-restores
            await pilot.resize_terminal(120, 40)
            await pilot.pause()
            assert app._rail_visible is True
            assert rail.display is True
            assert app._rail_auto_hidden is False

            # User manually closes with Ctrl+B at 120
            app.action_toggle_sidebar()
            await pilot.pause()
            assert app._rail_visible is False
            assert rail.display is False
            assert app._rail_visibility_override is False

            # Resize 120 -> 80: remains closed
            await pilot.resize_terminal(80, 40)
            await pilot.pause()
            assert app._rail_visible is False
            assert rail.display is False

            # Resize 80 -> 120: MUST REMAIN CLOSED because user manually chose closed
            await pilot.resize_terminal(120, 40)
            await pilot.pause()
            assert app._rail_visible is False
            assert rail.display is False
            assert app._rail_auto_hidden is False

            # Hysteresis test:
            # Reopen rail
            app.action_toggle_sidebar()
            await pilot.pause()
            assert app._rail_visible is True
            app._rail_visibility_override = None

            # At 89 cols (in hysteresis band 88..90), rail does NOT auto-hide
            await pilot.resize_terminal(89, 40)
            await pilot.pause()
            assert app._rail_visible is True
            assert rail.display is True

            # Drop to 87 cols (< 88): auto-hides
            await pilot.resize_terminal(87, 40)
            await pilot.pause()
            assert app._rail_visible is False
            assert app._rail_auto_hidden is True

            # Up to 89 cols (in hysteresis band 88..90): does NOT auto-restore
            await pilot.resize_terminal(89, 40)
            await pilot.pause()
            assert app._rail_visible is False
            assert app._rail_auto_hidden is True

            # Up to 92 cols (> 90): auto-restores
            await pilot.resize_terminal(92, 40)
            await pilot.pause()
            assert app._rail_visible is True
            assert rail.display is True

    asyncio.run(scenario())


# ── Area E: Semantic Toasts ──────────────────────────────────────────────────

def test_area_e_semantic_toasts(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    notifications = []

    def fake_notify(self, message, **kwargs):
        notifications.append((message, kwargs))

    monkeypatch.setattr(TUIApp, "notify", fake_notify)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            # Unicode notifications
            app.notify_semantic("Operation success", kind="success")
            assert notifications[-1][0].startswith("✓ ")
            assert notifications[-1][1]["severity"] == "information"
            assert notifications[-1][1]["timeout"] == 3.0

            app.notify_semantic("Action permitted", kind="authorized")
            assert notifications[-1][0].startswith("⚡ ")
            assert notifications[-1][1]["severity"] == "information"

            app.notify_semantic("Sentinel denied", kind="denied")
            assert notifications[-1][0].startswith("× ")
            assert notifications[-1][1]["severity"] == "security-denied"
            assert notifications[-1][1]["timeout"] == 5.5

            app.notify_semantic("Review warning", kind="warning")
            assert notifications[-1][0].startswith("! ")
            assert notifications[-1][1]["severity"] == "warning"

            app.notify_semantic("Info note", kind="info")
            assert notifications[-1][0].startswith("ℹ ")

            # ASCII-only notifications
            set_ascii_only(True)
            try:
                app.notify_semantic("Operation success", kind="success")
                assert notifications[-1][0].startswith("[OK] ")

                app.notify_semantic("Action permitted", kind="authorized")
                assert notifications[-1][0].startswith("[AUTH] ")

                app.notify_semantic("Sentinel denied", kind="denied")
                assert notifications[-1][0].startswith("[DENY] ")

                app.notify_semantic("Review warning", kind="warning")
                assert notifications[-1][0].startswith("[WARN] ")
            finally:
                set_ascii_only(False)

    asyncio.run(scenario())


# ── Area F: Interrupted Turn Resume ──────────────────────────────────────────

def test_area_f_interrupted_turn_capture_and_resume(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            # F-01: startup keeps the app busy; wait for it before the resume.
            await app.wait_for_ready()
            await pilot.pause()

            # Simulated interrupted turn
            turn = InterruptedTurn(
                prompt="List workspace files",
                messages=[
                    {"role": "user", "content": "List workspace files"},
                    {"role": "assistant", "content": "", "tool_calls": [
                        {"id": "call_1", "function": {"name": "workspace_list", "arguments": "{}"}}
                    ]},
                    {"role": "tool", "tool_call_id": "call_1", "content": '["README.md", "src/"]'},
                ],
                executed_tools={"call_1": '["README.md", "src/"]'},
                denied_tools={"call_denied"},
            )
            app._interrupted_turn = turn
            app._history = [{"role": "user", "content": "List workspace files"}]

            # Mock provider response on resume
            tool_dispatched = []

            async def mock_complete(provider, messages, **kwargs):
                return {
                    "text": "Found README.md and src/.",
                    "tool_calls": [
                        # Model proposes call_1 (already executed) and call_denied (already denied)
                        {"id": "call_1", "function": {"name": "workspace_list", "arguments": "{}"}},
                        {"id": "call_denied", "function": {"name": "workspace_delete", "arguments": "{}"}},
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                }

            async def fake_dispatch(call):
                tool_dispatched.append(call["id"])
                return call["id"], "ok"

            monkeypatch.setattr("isycode.tui.provider_complete", mock_complete)
            monkeypatch.setattr(app, "_dispatch_chat_tool", fake_dispatch)

            # Trigger resume
            app.action_resume_interrupted_turn()
            await pilot.pause()

            # Verify:
            # 1. tool_1 was NOT re-dispatched to execution owner
            assert "call_1" not in tool_dispatched
            assert "call_denied" not in tool_dispatched

            # 2. History did NOT duplicate the user prompt
            user_turns = [m for m in app._history if m.get("role") == "user"]
            assert len(user_turns) == 1
            assert user_turns[0]["content"] == "List workspace files"

            # 3. Interrupted turn is consumed
            assert app._interrupted_turn is None

    asyncio.run(scenario())


def test_area_f_resume_when_provider_rejects(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            turn = InterruptedTurn(
                prompt="Generate code",
                messages=[{"role": "user", "content": "Generate code"}],
            )
            app._interrupted_turn = turn
            app._history = [{"role": "user", "content": "Generate code"}]

            async def mock_failing_complete(provider, messages, **kwargs):
                raise ProviderError("Endpoint does not support continuation", status=400)

            monkeypatch.setattr("isycode.tui.provider_complete", mock_failing_complete)

            app.action_resume_interrupted_turn()
            await pilot.pause()

            # Ensure safe fallback message is shown and app didn't crash
            transcript = "\n".join(plain_text(w) for w in app.query_one("ChatArea").walk_children())
            assert "rejected turn continuation" in transcript

    asyncio.run(scenario())
