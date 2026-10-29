"""Shift+Tab walks the primary roles and colors the composer and each answer."""
import asyncio

import pytest
from textual.color import Color

from isycode.catalog import ISYCODE_AGENTS, ISYCODE_SUBAGENTS, ISYCO_MOTORS, ROLE_CYCLE, role_color
from isycode.localization import configure_locale as set_locale
from isycode.tui import ChatArea, TUIApp
from isycode.tui_composer import PromptArea
from test_daily_tui import configure


def test_every_role_has_its_own_color():
    roles = ISYCODE_AGENTS + ISYCODE_SUBAGENTS + ISYCO_MOTORS
    colors = [role["color"] for role in roles]
    assert len(set(colors)) == len(colors)
    assert [role["name"] for role in ROLE_CYCLE] == [
        "Build", "Plan", "coder", "researcher", "planner", "librarian",
        "maintainer", "devils-advocate", "historian", "orchestrator"]
    assert role_color(None) is None and role_color("unknown") is None


@pytest.mark.parametrize("locale", ["en", "es", "zh"])
def test_shift_tab_cycles_roles_and_frames_the_composer(tmp_path, monkeypatch, capsys, locale):
    configure(tmp_path, monkeypatch)
    from isycode.user_defaults import UserDefaultsStore
    UserDefaultsStore().update(locale=locale)
    set_locale(locale)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.wait_for_ready()
            prompt = app.query_one("#prompt-input", PromptArea)
            prompt.focus()
            await pilot.pause()
            assert app._active_role is None and prompt.border_title is None
            for role in ROLE_CYCLE:
                await pilot.press("shift+tab")
                await pilot.pause()
                assert app._active_role["name"] == role["name"]
                assert app._active_role["engine"] == role["engine"]
                assert role["name"] in str(prompt.border_title)
                assert prompt.styles.border_top[1] == Color.parse(role["color"])
                assert app.focused is prompt              # the draft keeps the focus
            await pilot.press("shift+tab")                # past the last role: none
            await pilot.pause()
            assert app._active_role is None
            assert prompt.border_title is None
            assert str(app.query_one("#role-button").label) == "Role"

    try:
        with capsys.disabled():
            asyncio.run(scenario())
    finally:
        set_locale("en")


def test_answers_keep_the_color_of_the_role_that_wrote_them(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    sent = []

    async def complete(provider, messages, **kwargs):
        sent.append(messages)
        kwargs["on_chunk"]("content", f"Answer {len(sent)}.")
        return {"text": f"Answer {len(sent)}.", "tool_calls": []}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await app.wait_for_ready()
            app.query_one("#prompt-input", PromptArea).focus()
            await pilot.press("shift+tab", "shift+tab", "shift+tab")    # Build, Plan, coder
            assert app._active_role["name"] == "coder"
            await app._run_chat("Fix it.")
            # The coder engine is the role contract the model receives.
            contract = [m["content"] for m in sent[0] if "role contract for coder" in m["content"]]
            assert contract and ISYCO_MOTORS[0]["engine"] in contract[0]
            await pilot.press("shift+tab")                               # researcher
            await app._run_chat("Measure it.")
            await pilot.pause()

            def painted():
                answers = list(app.query_one(ChatArea).query(".assistant-turn"))
                clocks = [str(clock.render()) for clock in app.query_one(ChatArea).query(".message-clock")]
                return [answer.styles.border_left[1] for answer in answers], clocks

            colors, clocks = painted()
            assert colors == [Color.parse(role_color("coder")), Color.parse(role_color("researcher"))]
            assert any("coder" in clock for clock in clocks)
            assert any("researcher" in clock for clock in clocks)
            # Repainting the conversation (e.g. after switching chats) keeps each color.
            app._repaint_conversation()
            await pilot.pause()
            assert painted()[0] == colors

    with capsys.disabled():
        asyncio.run(scenario())


def test_design_tokens_record_the_runtime_role_colors():
    import json
    from pathlib import Path
    tokens = json.loads((Path(__file__).parents[1] / ".agents/skills/isycode-design/assets/tokens.json")
                        .read_text(encoding="utf-8"))
    roles = ISYCODE_AGENTS + ISYCODE_SUBAGENTS + ISYCO_MOTORS
    assert tokens["role_colors"] == {role["name"]: role["color"] for role in roles}


def test_shift_tab_cycles_roles_wherever_focus_sits_in_the_chat(tmp_path, monkeypatch, capsys):
    """Focus on the command bar or rail must not turn Shift+Tab back into focus-previous."""
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await app.wait_for_ready()
            button = app.query_one("#sidebar-button")
            button.focus()
            await pilot.pause()
            await pilot.press("shift+tab")
            await pilot.pause()
            assert app._active_role["name"] == "Build"
            assert app.focused is button                  # no focus jump
            # The command menu keeps Shift+Tab for its own search field.
            app._open_settings_menu()
            await pilot.pause()
            assert app.query_one("#action-menu").display
            await pilot.press("shift+tab")
            await pilot.pause()
            assert app._active_role["name"] == "Build"

    with capsys.disabled():
        asyncio.run(scenario())
