"""Selector interactions and bounded actions at the accepted terminal sizes."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Static
from textual.geometry import Region

from isycode.chat_sessions import ChatSession
from isycode.tui_screens_harness import ModelChoice, ModelsScreen, MultiHarnessScreen
from isycode.tui_screens_sessions import (
    AgentQuestionScreen, ChatSessionsScreen, SessionSearchScreen, ShellProcessesScreen,
)


class SelectorProbe(App):
    CSS_PATH = Path(__file__).parents[1] / "src/isycode/design.tcss"

    def compose(self) -> ComposeResult:
        yield Button("Open selector", id="opener")


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    for key in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "ISYCODE_STATE_HOME"):
        monkeypatch.setenv(key, str(tmp_path / key.lower()))
    monkeypatch.setenv("ISYCODE_PROVIDER", "openai")
    monkeypatch.setenv("ISYCODE_MODEL", "gpt-6-luna")
    monkeypatch.setattr("isycode.tui_screens_harness.selected_provider_name", lambda: "openai")


SIZES = [(80, 24), (100, 30), (140, 40)]
MODELS = [{"kind": "model", "value": f"openai|{model}", "label": model}
          for model in ("gpt-6-luna", "gpt-6-sol", "gpt-6-astra")]


@pytest.mark.asyncio
@pytest.mark.parametrize("size", SIZES)
async def test_model_row_text_stays_visible_when_focused_or_hovered(size):
    app = SelectorProbe()
    async with app.run_test(size=size) as pilot:
        screen = ModelsScreen(MODELS, provider_scope="openai")
        await app.push_screen(screen)
        await pilot.pause()
        current = screen.query_one("#model-choice-0", ModelChoice)
        other = screen.query_one("#model-choice-1", ModelChoice)
        for row, name in ((current, "GPT 6 Luna"), (other, "GPT 6 Sol")):
            row.focus()
            await pilot.hover(row)
            await pilot.pause()
            # Check compositor output, not the stored label or CSS declaration:
            # a top/bottom button border can consume the only content row.
            strips = row.render_lines(Region(0, 0, row.size.width, row.size.height))
            assert name in "\n".join(strip.text for strip in strips)


@pytest.mark.asyncio
async def test_unscoped_picker_reveals_the_current_model_without_requiring_expansion():
    app = SelectorProbe()
    app._account_models_attempted = {"openai"}
    async with app.run_test(size=(100, 30)) as pilot:
        screen = ModelsScreen(MODELS)
        await app.push_screen(screen)
        await pilot.pause()
        current = next(row for row in screen.query(ModelChoice)
                       if screen.choices[row.id]["value"] == "openai|gpt-6-luna")
        assert current.region.width > 0
        assert screen.query_one("#models-scroll").region.contains_region(current.region)
        assert screen.focused is current


def session(session_id, title, text):
    return ChatSession(session_id, title, [{"role": "user", "content": text}],
                       1700000000.0, 1700000000.0)


SESSIONS = [session("a" * 32, "Repair parser", "fix the tokenizer"),
            session("b" * 32, "Write guide", "document setup")]


def visible_inside(screen, card_id, widget_id):
    card, widget = screen.query_one(card_id), screen.query_one(widget_id)
    assert widget.region.height > 0
    assert card.region.contains_region(widget.region), (card.region, widget.region)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", SIZES)
async def test_model_preview_keeps_list_and_explicit_choice_reachable(size):
    app, chosen = SelectorProbe(), []
    async with app.run_test(size=size) as pilot:
        screen = ModelsScreen(MODELS, provider_scope="openai")
        await app.push_screen(screen, chosen.append)
        await pilot.pause()
        assert screen.query_one("#models-scroll").region.height >= 4
        visible_inside(screen, "#models-card", "#models-close")
        visible_inside(screen, "#models-card", "#models-use")
        target = next(row for row in screen.query(ModelChoice)
                      if screen.choices[row.id]["value"] == "openai|gpt-6-astra")
        await pilot.click(f"#{target.id}")
        await pilot.pause()
        assert chosen == []
        assert "gpt-6-astra" in str(screen.query_one("#model-detail").render())
        current = next(row for row in screen.query(ModelChoice)
                       if screen.choices[row.id]["value"] == "openai|gpt-6-luna")
        assert "current" in str(current.label)
        assert "current" not in str(target.label)
        await pilot.click("#models-use")
        await pilot.pause()
    assert chosen == [MODELS[-1]]


@pytest.mark.asyncio
async def test_model_filter_empty_state_never_applies_hidden_selection():
    app, chosen = SelectorProbe(), []
    async with app.run_test(size=(80, 24)) as pilot:
        screen = ModelsScreen(MODELS, provider_scope="openai")
        await app.push_screen(screen, chosen.append)
        await pilot.pause()
        field = screen.query_one("#models-search", Input)
        field.focus()
        await pilot.press(*"not found")
        await pilot.pause()
        assert field.value == "not found"
        assert screen.query_one("#models-use", Button).disabled
        assert "No matching" in str(screen.query_one("#models-status").render())
        await pilot.press("enter")
        assert chosen == []
        await pilot.press("escape")
        await pilot.pause()
        assert app.focused.id == "opener"
    assert chosen == [None]


@pytest.mark.asyncio
@pytest.mark.parametrize("remove_preview", [False, True])
async def test_catalog_refresh_keeps_model_identity_or_disables_removed_preview(remove_preview):
    app, chosen = SelectorProbe(), []
    entries = [{"kind": "model", "value": f"anthropic|{model}", "label": model}
               for model in ("claude-sonnet-4-6", "claude-opus-4-6")]
    async with app.run_test(size=(80, 24)) as pilot:
        screen = ModelsScreen(entries, provider_scope="anthropic")
        await app.push_screen(screen, chosen.append)
        await pilot.pause()
        preview = screen.query_one("#model-choice-1", ModelChoice)
        await pilot.click(f"#{preview.id}")
        await pilot.pause()
        assert "claude-opus-4-6" in str(screen.query_one("#model-detail").render())
        screen.query_one("#models-search", Input).focus()
        # Mirror the live catalog update: rows are remounted with new positions.
        screen.entries = [{"kind": "model", "value": "anthropic|claude-haiku-4-5",
                           "label": "Haiku"}] + entries[:1 if remove_preview else 2]
        screen.choices = {}
        screen.refresh(recompose=True)
        screen.call_after_refresh(screen._reveal_current)
        await pilot.pause()
        field = screen.query_one("#models-search", Input)
        field.focus()
        await pilot.press(*"claude")
        await pilot.pause()
        use = screen.query_one("#models-use", Button)
        if remove_preview:
            assert use.disabled
            await pilot.click("#models-use")
            assert chosen == []
            await pilot.press("escape")
        else:
            assert not use.disabled
            assert "claude-opus-4-6" in str(screen.query_one("#model-detail").render())
            await pilot.click("#models-use")
        await pilot.pause()
    assert chosen == ([None] if remove_preview else [entries[1]])


@pytest.mark.asyncio
async def test_picker_marks_resolved_default_when_no_model_was_saved(monkeypatch):
    monkeypatch.setattr("isycode.providers.selected_model_name", lambda: "")
    app = SelectorProbe()
    async with app.run_test(size=(100, 30)) as pilot:
        screen = ModelsScreen(MODELS, provider_scope="openai")
        await app.push_screen(screen)
        await pilot.pause()
        current = next(row for row in screen.query(ModelChoice)
                       if screen.choices[row.id]["value"] == "openai|gpt-6-luna")
        assert "current" in str(current.label)
        assert screen.focused is current


@pytest.mark.asyncio
@pytest.mark.parametrize("size", SIZES)
async def test_session_search_preview_and_open_use_supplied_session(size):
    app, chosen = SelectorProbe(), []
    async with app.run_test(size=size) as pilot:
        screen = SessionSearchScreen(SESSIONS)
        await app.push_screen(screen, chosen.append)
        await pilot.pause()
        visible_inside(screen, "#session-search-card", "#session-search-close")
        visible_inside(screen, "#session-search-card", "#session-search-open")
        await pilot.press(*"tokenizer")
        await pilot.pause()
        assert [item.session_id for item in screen.visible_sessions] == ["a" * 32]
        assert "Repair parser" in str(screen.query_one("#session-search-detail").render())
        assert chosen == []
        await pilot.click("#session-search-open")
        await pilot.pause()
    assert chosen == ["a" * 32]


@pytest.mark.asyncio
@pytest.mark.parametrize("size", SIZES)
async def test_saved_session_actions_fit_and_new_keeps_callback(size):
    owner = SimpleNamespace(list_conversations=lambda: (SimpleNamespace(decision="ALLOW"), SESSIONS))
    app, chosen = SelectorProbe(), []
    async with app.run_test(size=size) as pilot:
        screen = ChatSessionsScreen(owner)
        await app.push_screen(screen, chosen.append)
        await pilot.pause()
        for widget_id in ("#sessions-new", "#sessions-rename", "#sessions-fork",
                          "#sessions-delete", "#sessions-close"):
            visible_inside(screen, "#sessions-card", widget_id)
        await pilot.click("#sessions-new")
        await pilot.pause()
    assert chosen == ["__new__"]


@pytest.mark.asyncio
@pytest.mark.parametrize("size", SIZES)
async def test_question_choices_scroll_without_hiding_cancel(size):
    app, chosen = SelectorProbe(), []
    async with app.run_test(size=size) as pilot:
        screen = AgentQuestionScreen("Choose the next step. " * 15,
                                     [f"Option {index}" for index in range(12)])
        await app.push_screen(screen, chosen.append)
        await pilot.pause()
        visible_inside(screen, "#agent-question-card", "#ask-cancel")
        last = screen.query_one("#ask-choice-11", Button)
        last.focus()
        await pilot.pause(0.35)
        visible_inside(screen, "#agent-question-card", "#ask-choice-11")
        await pilot.press("enter")
        await pilot.pause()
    assert chosen == [{"status": "answered", "choice": "Option 11"}]


@pytest.mark.asyncio
async def test_empty_process_inspection_disables_stop_and_keeps_close():
    app = SelectorProbe()
    app._shell_jobs = {}
    async with app.run_test(size=(80, 24)) as pilot:
        screen = ShellProcessesScreen()
        await app.push_screen(screen)
        await pilot.pause()
        assert screen.query_one("#shell-stop", Button).disabled
        assert "No" in str(screen.query_one("#shell-text", Static).render())
        assert screen.query_one("#shell-output").region.height >= 4
        visible_inside(screen, "#shell-card", "#shell-close")
        await pilot.click("#shell-close")
        await pilot.pause()
        assert app.screen is not screen


@pytest.mark.asyncio
async def test_long_text_question_keeps_answer_and_cancel_reachable():
    app, chosen = SelectorProbe(), []
    async with app.run_test(size=(80, 24)) as pilot:
        screen = AgentQuestionScreen("Explain this decision. " * 180, [])
        await app.push_screen(screen, chosen.append)
        await pilot.pause(0.35)
        # The question is content to read, so it must survive in the scrollable
        # body rather than being clipped to a short title above the answer.
        assert screen.query_one("#ask-question").region.height >= 40
        visible_inside(screen, "#agent-question-card", "#ask-cancel")
        visible_inside(screen, "#agent-question-card", "#ask-submit")
        visible_inside(screen, "#agent-question-card", "#ask-text")
        await pilot.press(*"keep the current option", "enter")
        await pilot.pause()
    assert chosen == [{"status": "answered", "text": "keep the current option"}]


@pytest.mark.asyncio
async def test_harness_preview_preserves_read_only_folder_callback():
    app, chosen = SelectorProbe(), []
    async with app.run_test(size=(80, 24)) as pilot:
        screen = MultiHarnessScreen()
        await app.push_screen(screen, chosen.append)
        await pilot.pause()
        first = screen.query_one(".harness-section")
        first.collapsed = False
        await pilot.pause()
        button = first.query_one(Button)
        button.focus()
        await pilot.pause()
        visible_inside(screen, "#harness-card", "#harness-close")
        await pilot.press("enter")
        await pilot.pause()
    assert chosen == [first.id.removeprefix("harness-fold-")]
