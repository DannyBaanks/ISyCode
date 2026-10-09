"""Provider → model → reasoning as one flow, with a card of known facts only."""
import asyncio
import time

import pytest

from isycode.model_card import catalog_entry, model_facts
from isycode.providers import Provider, resolved_chat_model, selected_provider_name
from isycode.tui import TUIApp, ModelsScreen
from test_daily_tui import configure


def facts(provider, model):
    return {fact.label: (fact.value, fact.source) for fact in model_facts(provider, model)}


# ── Model card: real facts, named sources, nothing invented ───────────
def test_card_shows_snapshot_context_and_pricing_with_their_source(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    entry = catalog_entry("nvidia", "z-ai/glm-5.3")
    assert entry is not None
    card = facts("nvidia", "z-ai/glm-5.3")
    assert card["Model ID"] == ("z-ai/glm-5.3", "Configured")
    assert card["Context"][1] == "models.dev snapshot"
    assert card["Input"] == (f"${entry['cost_in']:,.2f} / 1M tokens", "models.dev snapshot")
    assert card["Cached input"] == ("Not reported", "Unknown")  # the snapshot has no cache price


def test_unknown_model_gets_unknowns_not_guesses(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    card = facts("nvidia", "z-ai/glm-5.3-not-a-real-model")
    assert card["Context"] == ("Unknown", "Unknown")
    assert card["Pricing"] == ("Unavailable", "Unknown")
    assert "Family" not in card and "Input" not in card


def test_catalog_match_is_exact_never_a_prefix_or_suffix(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    assert catalog_entry("nvidia", "glm-5.3") is None             # id without vendor prefix
    assert catalog_entry("nvidia", "z-ai/glm-5.3-flash")["id"] == "z-ai/glm-5.3-flash"
    assert catalog_entry("nvidia", "Z-AI/GLM-5.3")["id"] == "z-ai/glm-5.3"  # case only


def test_live_account_context_wins_over_the_snapshot(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    from isycode.providers import record_model_metadata
    record_model_metadata("nvidia", "z-ai/glm-5.3", {"context_length": 123_000})
    assert facts("nvidia", "z-ai/glm-5.3")["Context"] == ("123K tokens", "Account catalog")


# ── The TUI flow ───────────────────────────────────────────────────────
NVIDIA_MODELS = ["z-ai/glm-5.3", "z-ai/glm-5.3-flash", "moonshotai/kimi-k3"] + [
    f"vendor/model-{index:02d}" for index in range(77)]


@pytest.fixture
def tui(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "test-not-real")
    monkeypatch.setattr(Provider, "models",
                        lambda provider: NVIDIA_MODELS if provider.name == "nvidia" else [])
    return tmp_path


async def until(pilot, condition, timeout=10.0):
    for _ in range(int(timeout / 0.05)):
        await pilot.pause(0.05)
        try:
            if condition():
                return True
        except Exception:
            pass
    return False


def run(scenario, size=(140, 45)):
    async def main():
        app = TUIApp()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await scenario(app, pilot)
    asyncio.run(main())


def provider_entry(app, name):
    return next(entry for entry in app._menu_entries
                if entry["kind"] == "provider" and entry["value"] == name)


async def open_nvidia(app, pilot):
    await pilot.click("#model-button")
    assert await until(pilot, lambda: app._menu_mode == "providers")
    app._select_menu_entry(provider_entry(app, "nvidia"))
    # The picker is rebuilt when the account catalog arrives; wait until the same
    # set of nvidia models has stayed on screen for a moment.
    last, stable = None, 0
    for _ in range(300):
        await pilot.pause(0.05)
        screen = app.screen
        models = (tuple(sorted(e["value"] for e in screen.choices.values() if e["kind"] == "model"))
                  if isinstance(screen, ModelsScreen) and not getattr(app, "_account_models_loading", False)
                  else ())
        stable = stable + 1 if models and models == last else 0
        last = models
        if stable >= 6:
            return screen
    raise AssertionError("the nvidia model picker never settled")


def choice(screen, model):
    return next(button for button in screen.query(".model-choice")
                if screen.choices.get(button.id, {}).get("value") == f"nvidia|{model}")


def test_provider_opens_only_its_models_and_changes_nothing_yet(tui, capsys):
    async def scenario(app, pilot):
        before = (selected_provider_name(), resolved_chat_model(selected_provider_name()))
        screen = await open_nvidia(app, pilot)
        assert screen.provider_scope == "nvidia"
        providers = {entry["value"].split("|", 1)[0] for entry in screen.choices.values()
                     if entry["kind"] == "model"}
        assert providers == {"nvidia"}
        assert (selected_provider_name(), resolved_chat_model(selected_provider_name())) == before

    with capsys.disabled():
        run(scenario)


def test_highlight_fills_the_card_and_search_matches_ids_and_names(tui, capsys):
    async def scenario(app, pilot):
        screen = await open_nvidia(app, pilot)
        choice(screen, "z-ai/glm-5.3").focus()
        await pilot.pause()
        detail = str(screen.query_one("#model-detail").render())
        assert "z-ai/glm-5.3" in detail and "Context" in detail
        screen.query_one("#models-search").value = "kimi"
        await pilot.pause()
        visible = [button for button in screen.query(".model-choice") if button.display
                   and screen.choices[button.id]["kind"] == "model"]
        assert [screen.choices[b.id]["value"] for b in visible] == ["nvidia|moonshotai/kimi-k3"]

    with capsys.disabled():
        run(scenario)


def test_escape_walks_back_and_keeps_the_previous_model(tui, capsys):
    async def scenario(app, pilot):
        before = (selected_provider_name(), resolved_chat_model(selected_provider_name()))
        await open_nvidia(app, pilot)
        await pilot.press("escape")
        assert await until(pilot, lambda: app._menu_mode == "providers")
        await pilot.press("escape")
        assert await until(pilot, lambda: not app.query_one("#action-menu").display)
        assert (selected_provider_name(), resolved_chat_model(selected_provider_name())) == before

    with capsys.disabled():
        run(scenario)


def test_model_with_levels_is_applied_only_with_its_reasoning(tui, monkeypatch, capsys):
    import isycode.reasoning_options as reasoning
    monkeypatch.setattr(reasoning, "_SELECTIONS", {})
    monkeypatch.setattr(reasoning, "reasoning_levels",
                        lambda provider, model: ("low", "high") if model == "z-ai/glm-5.3" else ())

    async def scenario(app, pilot):
        before = selected_provider_name()
        screen = await open_nvidia(app, pilot)
        target = f"#{choice(screen, 'z-ai/glm-5.3').id}"
        await pilot.click(target)
        assert isinstance(app.screen, ModelsScreen)
        await pilot.click(target)
        assert await until(pilot, lambda: app._menu_mode == "reasoning")
        assert selected_provider_name() == before            # still a draft
        assert [e["value"].rsplit("|", 1)[1] for e in app._menu_entries] == ["default", "low", "high"]
        await pilot.press("escape")                           # back to the models, not applied
        assert await until(pilot, lambda: isinstance(app.screen, ModelsScreen))
        assert selected_provider_name() == before
        screen = app.screen
        target = f"#{choice(screen, 'z-ai/glm-5.3').id}"
        await pilot.click(target)
        await pilot.click(target)
        assert await until(pilot, lambda: app._menu_mode == "reasoning")
        app._select_menu_entry(app._menu_entries[-1])
        assert await until(pilot, lambda: selected_provider_name() == "nvidia")
        assert resolved_chat_model("nvidia") == "z-ai/glm-5.3"
        assert reasoning.effective_reasoning("nvidia", "z-ai/glm-5.3", None) == "high"

    with capsys.disabled():
        run(scenario)


def test_model_without_levels_is_applied_without_a_fake_selector(tui, monkeypatch, capsys):
    import isycode.reasoning_options as reasoning
    monkeypatch.setattr(reasoning, "reasoning_levels", lambda provider, model: ())

    async def scenario(app, pilot):
        screen = await open_nvidia(app, pilot)
        target = f"#{choice(screen, 'moonshotai/kimi-k3').id}"
        await pilot.click(target)
        assert isinstance(app.screen, ModelsScreen)
        detail = str(app.screen.query_one("#model-detail").render())
        assert "kimi-k3" in detail
        await pilot.click(target)
        assert await until(pilot, lambda: selected_provider_name() == "nvidia")
        assert resolved_chat_model("nvidia") == "moonshotai/kimi-k3"
        assert app._menu_mode != "reasoning"

    with capsys.disabled():
        run(scenario)


def test_vanished_current_model_is_reported_not_replaced(tui, monkeypatch, capsys):
    from isycode.providers import save_provider_selection
    save_provider_selection("nvidia", "retired/old-model")
    monkeypatch.setenv("ISYCODE_PROVIDER", "nvidia")
    monkeypatch.setenv("ISYCODE_MODEL", "retired/old-model")

    async def scenario(app, pilot):
        await open_nvidia(app, pilot)
        rows = [entry["label"] for entry in app.screen.entries if entry["kind"] == "info"]
        assert any("retired/old-model is not in the refreshed" in row for row in rows)
        assert resolved_chat_model("nvidia") == "retired/old-model"

    with capsys.disabled():
        run(scenario)


def test_reveal_does_not_crash_when_the_current_row_is_not_mounted(tui, capsys):
    from isycode.tui_screens_harness import ModelChoice

    async def scenario(app, pilot):
        entries = app._branch_entries("models")
        app._models_scope = "openai"
        screen = ModelsScreen(entries, provider_scope="openai")
        await app.push_screen(screen)
        await pilot.pause()
        for button in list(screen.query(ModelChoice)):
            await button.remove()
        screen._reveal_current()
        await pilot.pause()
        assert isinstance(app.screen, ModelsScreen)
        assert "gpt-6-luna" in str(screen.query_one("#model-detail").render())

    with capsys.disabled():
        run(scenario)


def test_narrow_terminal_stacks_the_card_below_the_list(tui, capsys):
    async def scenario(app, pilot):
        screen = await open_nvidia(app, pilot)
        assert screen.has_class("-narrow")

    with capsys.disabled():
        run(scenario, size=(90, 40))


def test_eighty_model_catalog_opens_quickly(tui, capsys):
    async def scenario(app, pilot):
        started = time.monotonic()
        screen = await open_nvidia(app, pilot)
        assert time.monotonic() - started < 8
        assert sum(1 for entry in screen.choices.values() if entry["kind"] == "model") >= 80

    with capsys.disabled():
        run(scenario)


def test_arming_one_model_row_disarms_the_others(tmp_path, monkeypatch):
    """Hermes audit 2026-10-08, finding 9: A, B, A selected A on the third click."""
    import asyncio
    from textual.app import App
    from textual.widgets import Static
    from isycode.tui_screens_harness import ModelsScreen
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    class Probe(App):
        def compose(self):
            yield Static("probe")
    entries = [{"kind": "model", "value": "openai|audit-model-a", "label": "A"},
               {"kind": "model", "value": "openai|audit-model-b", "label": "B"}]

    async def clicks(order):
        app, chosen = Probe(), []
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(ModelsScreen(entries, provider_scope="openai"), chosen.append)
            await pilot.pause()
            for key in order:
                await pilot.click(f"#model-choice-{key}")
                await pilot.pause()
            return chosen, type(app.screen).__name__
    chosen, screen = asyncio.run(clicks([0, 1, 0]))
    assert chosen == [] and screen == "ModelsScreen"
    chosen, screen = asyncio.run(clicks([0, 0]))
    assert len(chosen) == 1 and "audit-model-a" in str(chosen[0])
