"""Settings values, selector previews and responsive menu navigation."""
import asyncio

import pytest
from rich.console import Console
from textual.widgets import Input, OptionList, Static

from isycode.tui import TUIApp, PromptArea
from test_daily_tui import configure


def rendered(prompt, width):
    console = Console(width=width, color_system=None)
    # Textual supplies an app console width, so render with explicit options.
    lines = console.render_lines(prompt, console.options.update(width=width))
    return "\n".join("".join(segment.text for segment in line) for line in lines)


@pytest.mark.parametrize("size", [(80, 24), (100, 30), (140, 40)])
def test_settings_show_actual_values_and_keep_category_search_back_reachable(tmp_path, monkeypatch, size):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            app._active_role = {"name": "Reviewer", "kind": "agents", "description": "Review only"}
            app._agent_context = {"path": "docs/guide.md", "text": "Read me", "receipt_id": "fixture", "verification": "PASS"}
            app._open_settings_menu()
            await pilot.pause()
            options = app.query_one("#action-list", OptionList)
            rows = {e["kind"]: i for i, e in enumerate(app._menu_filtered)}
            assert {"providers_open", "models_open", "reasoning_open", "roles_open", "context_inject"} <= rows.keys()
            assert "GPT 6 Luna" in rendered(options.get_option_at_index(rows["models_open"]).prompt, 44)
            assert "Reviewer" in rendered(options.get_option_at_index(rows["roles_open"]).prompt, 44)
            assert "docs/guide.md" in rendered(options.get_option_at_index(rows["context_inject"]).prompt, 44)
            assert "Choose the model" in rendered(options.get_option_at_index(rows["models_open"]).prompt, 105)
            for selector in ("#action-search", "#action-hint", "#settings-categories"):
                assert app.screen.region.contains_region(app.query_one(selector).region)
            categories = app.query_one("#settings-categories", OptionList)
            categories.highlighted = 1
            await pilot.pause()
            search = app.query_one("#action-search", Input)
            search.value = "gpt-6-luna"
            await pilot.pause()
            assert any(e["kind"] == "models_open" for e in app._menu_filtered)
            assert all(e.get("category_id") == "Conversation" for e in app._menu_filtered)
            before = app._active_role.copy()
            await pilot.press("escape")
            assert app._active_role == before
            assert app.screen.focused is app.query_one(PromptArea)
    asyncio.run(scenario())


def test_model_setting_opens_current_provider_picker_without_changing_selection(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    opened = []
    monkeypatch.setattr(TUIApp, "_open_scoped_models", lambda self, name: opened.append(name))
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            app._open_settings_menu()
            app._select_menu_entry(next(e for e in app._menu_entries if e["kind"] == "models_open"))
            assert opened == ["openai"]
            from isycode.providers import selected_provider_name, resolved_chat_model
            assert (selected_provider_name(), resolved_chat_model("openai")) == ("openai", "gpt-6-luna")
    asyncio.run(scenario())


@pytest.mark.parametrize("provider, model", [("anthropic", "claude-opus-4-6"),
                                            ("openai", "gpt-6-sol")])
def test_reasoning_setting_matches_provider_default(tmp_path, monkeypatch, provider, model):
    configure(tmp_path, monkeypatch)
    monkeypatch.setenv("ISYCODE_PROVIDER", provider)
    monkeypatch.setenv("ISYCODE_MODEL", model)
    monkeypatch.delenv("ISYCODE_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("ISYMOTRON_REASONING_EFFORT", raising=False)
    for cache in ("_SELECTIONS", "_CATALOG_DEFAULTS"):
        monkeypatch.setattr(f"isycode.reasoning_options.{cache}", {})
    from isycode.providers import Provider

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            app._open_settings_menu()
            await pilot.pause()
            row = next(e for e in app._menu_entries if e["kind"] == "reasoning_open")
            assert Provider(provider, model=model).reasoning_effort == "medium"
            assert row["display_value"].lower() == "medium"
    asyncio.run(scenario())


def test_provider_single_click_previews_and_resizes_without_switching_provider(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(140, 40)) as pilot:
            app._open_provider_menu()
            await pilot.pause()
            options = app.query_one("#action-list", OptionList)
            index = next(i for i, e in enumerate(app._menu_filtered) if e.get("value") == "anthropic")
            options.highlighted = index
            await pilot.pause()
            before = app._menu_filtered[options.highlighted]["value"]
            detail = app.query_one("#action-detail", Static)
            assert detail.region.x > options.region.x
            assert "Anthropic" in str(detail.render())
            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            assert app._menu_filtered[options.highlighted]["value"] == before
            assert detail.region.y >= options.region.bottom
            from isycode.providers import selected_provider_name
            assert selected_provider_name() == "openai"
            await pilot.press("escape")
    asyncio.run(scenario())


def test_model_setting_escape_returns_to_settings_and_keeps_active_model(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            app._account_models_attempted = {"openai"}
            app._open_settings_menu()
            app._select_menu_entry(next(e for e in app._menu_entries if e["kind"] == "models_open"))
            await pilot.pause()
            from isycode.tui_screens_harness import ModelsScreen
            assert isinstance(app.screen, ModelsScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert app._menu_mode == "settings"
            assert app.query_one("#settings-categories", OptionList).display
            from isycode.providers import resolved_chat_model
            assert resolved_chat_model("openai") == "gpt-6-luna"
    asyncio.run(scenario())
